"""
epy_fso_channel.py
==================
GNU Radio Embedded Python Block that applies the FSO turbulence channel gain to
a complex baseband stream, with the gain streamed LIVE over ZMQ from the
channel server (fso_twin/server.py):

    y[n] = h(t_n) * x[n]            (IM/DD framing: h real, >= 0)

Drop this file into a GNU Radio Companion "Python Block" (or import `blk`
directly in a hand-built flowgraph) and connect any complex stream through it.
It subscribes (ZMQ SUB) to the gain stream on tcp://127.0.0.1:50003 and
upsamples the slow gain updates (hundreds of Hz) to the signal sample rate
(tens of MHz) by LINEAR interpolation -- never a zero-order hold.

Design rules honoured (all hard constraints from the build brief):
  * LINEAR interpolation between received gain samples onto the signal
    sample grid, indexed by the absolute gain-sample index. A naive hold
    would inject non-physical staircase steps; this never holds during
    normal flow.
  * NON-BLOCKING ZMQ receive (zmq.NOBLOCK). work() never waits on the
    network, so it can never stall a downstream block that is waiting on
    all of its inputs.
  * BUFFER STARVATION is a visible, counted, logged anomaly -- never a
    silent hold. When the gain buffer cannot cover the whole work() window
    (the server normally publishes 0.25 s ahead, so this should not happen),
    the block produces ONLY the samples it can interpolate honestly and
    defers the rest to a later call (GR backpressure). Deferring injects no
    artefact at all, unlike a hold.
  * Gain is CLAMPED and checked NON-NEGATIVE on receipt. The server already
    guarantees non-negativity after its cheap-parameter scaling; a negative
    here means corruption, so it is counted, logged, and clamped to 0 rather
    than silently used.
  * Sequence numbers (per message) are checked: an unflagged gap is a real
    network drop (counted, logged, re-anchored); an epoch change is a
    legitimate operator-driven trace switch (continuity reset, not a gap);
    a FLAG_LOOPED seam is a finite-trace wrap (counted, logged).

The decode + interpolation logic lives in GainStreamDecoder (pure
numpy/struct, no zmq, no gnuradio) so it can be unit-tested off-line and reused
outside GNU Radio.

Environment: GNU Radio 3.8+, numpy < 2, pyzmq. The wire protocol is an inline
copy of fso_twin/fso_stream_proto.py (kept identical so a bare GRC paste works).
"""

import struct
import time

import numpy as np


# --------------------------------------------------------------------------
# Wire protocol. Prefer the shared module (when this file is run from the
# repo, fso_stream_proto.py is importable); fall back to an INLINE copy so a
# bare GRC paste still works. The inline copy MUST MATCH fso_stream_proto.py.
# --------------------------------------------------------------------------
try:
    from fso_stream_proto import (unpack_message, MAGIC, VERSION,
                                  FLAG_TRACE_CHANGED, FLAG_LOOPED, HEADER_SIZE)
except ImportError:                                   # inline fallback
    MAGIC = b"FSOG"
    VERSION = 1
    FLAG_TRACE_CHANGED = 0x01
    FLAG_LOOPED = 0x02
    _HEADER = struct.Struct("<4sBBHQdI")
    HEADER_SIZE = _HEADER.size

    def unpack_message(buf):
        if len(buf) < HEADER_SIZE:
            raise ValueError("short message")
        magic, version, flags, epoch, seq_start, f_update, n = \
            _HEADER.unpack(buf[:HEADER_SIZE])
        if magic != MAGIC:
            raise ValueError("bad magic")
        if version != VERSION:
            raise ValueError("bad version")
        if len(buf) != HEADER_SIZE + 4 * n:
            raise ValueError("payload length mismatch")
        gains = np.frombuffer(buf[HEADER_SIZE:], dtype="<f4").astype(np.float64)
        return {"version": version,
                "trace_changed": bool(flags & FLAG_TRACE_CHANGED),
                "looped": bool(flags & FLAG_LOOPED),
                "epoch": epoch, "seq_start": seq_start,
                "f_update": f_update, "n": n, "gains": gains}


class GainStreamDecoder:
    """Pure-numpy gain stream consumer + upsampler. No ZMQ, no GNU Radio.

    Holds a rolling buffer of received gain samples and a fractional cursor
    into it. Each signal sample advances the cursor by 1/R gain-samples,
    where R = sample_rate / f_update; the gain at a fractional position is
    LINEARLY interpolated between the two bracketing gain samples (indexed
    by absolute gain-sample index). The slow gain stream is thereby
    upsampled to the signal rate with no hold and no overshoot.

    Timeline coupling: the gain advances in lockstep with the signal samples
    actually consumed, so the gain f_update and the signal sample_rate are
    physically locked (R signal samples per gain sample). With the source
    running at ~real-time (throttle / USRP) and the server publishing ahead,
    the buffer stays full; a dry buffer is a genuine anomaly.
    """

    def __init__(self, sample_rate, warn_period_s=1.0):
        self.sample_rate = float(sample_rate)
        self.f_update = None
        self.R = None                 # signal samples per gain sample
        self.buf = np.empty(0, dtype=np.float64)
        self.base_index = 0           # absolute gain index of buf[0]
        self.cursor = 0.0             # fractional position within buf
        self.epoch = None
        self.expected_seq = None      # next contiguous seq we expect

        # counters -- the visible record of every non-ideal event
        self.n_messages = 0
        self.n_gaps = 0               # detected network drops
        self.n_lost_samples = 0       # gain samples lost to drops
        self.n_epoch_changes = 0      # legitimate trace switches
        self.n_loops = 0              # finite-trace wrap seams (flagged)
        self.n_starve_events = 0      # work() calls that could not fill
        self.n_starve_samples = 0     # signal samples deferred to starvation
        self.n_negative_clamped = 0   # negative gains clamped on receipt

        self._warn_period_s = warn_period_s
        self._last_warn = {}

    # -- ingest ---------------------------------------------------------
    def _reset_buffer(self, gains, base_index):
        self.buf = np.asarray(gains, dtype=np.float64)
        self.base_index = int(base_index)
        self.cursor = 0.0

    def ingest(self, raw):
        """Decode and incorporate one raw gain message. Returns the parsed
        message dict (for logging by the caller), or None if unparseable."""
        try:
            msg = unpack_message(raw)
        except ValueError:
            self._warn("badmsg", "[fso-zmq] dropped an unparseable gain "
                                 "message")
            return None
        self.n_messages += 1

        # non-negativity on receipt: clamp + count (server guarantees >= 0,
        # so any negative is corruption, never silently used)
        g = msg["gains"]
        if np.any(g < 0):
            nneg = int(np.sum(g < 0))
            self.n_negative_clamped += nneg
            self._warn("neg", "[fso-zmq] %d negative gain value(s) on "
                              "receipt; clamping to 0 (corruption?)" % nneg)
            g = np.maximum(g, 0.0)

        f_update = msg["f_update"]
        if self.f_update != f_update:
            self.f_update = f_update
            self.R = self.sample_rate / f_update

        # discrete trace switch: legitimate discontinuity, reset continuity
        if self.epoch is not None and msg["epoch"] != self.epoch:
            self.n_epoch_changes += 1
            self._reset_buffer(g, msg["seq_start"])
            self.epoch = msg["epoch"]
            self.expected_seq = msg["seq_start"] + msg["n"]
            return msg
        self.epoch = msg["epoch"]

        if msg["looped"]:
            self.n_loops += 1
            self._warn("loop", "[fso-zmq] loop seam flagged by server "
                              "(finite-trace wrap)")

        # sequence continuity within an epoch
        if self.expected_seq is None:
            self._reset_buffer(g, msg["seq_start"])
        elif msg["seq_start"] == self.expected_seq:
            self._append(g)                      # contiguous: normal path
        elif msg["seq_start"] > self.expected_seq:
            lost = msg["seq_start"] - self.expected_seq
            self.n_gaps += 1
            self.n_lost_samples += int(lost)
            self._warn("gap", "[fso-zmq] sequence GAP: lost %d gain "
                             "samples (re-anchoring)" % lost)
            self._reset_buffer(g, msg["seq_start"])
        else:
            # seq_start < expected: duplicate/reorder (TCP should prevent
            # this); ignore the stale overlap region
            self._warn("dup", "[fso-zmq] out-of-order/duplicate message "
                             "ignored")
        self.expected_seq = msg["seq_start"] + msg["n"]
        return msg

    def _append(self, g):
        self.buf = np.concatenate([self.buf, np.asarray(g, np.float64)])

    # -- produce --------------------------------------------------------
    def produce(self, n_out):
        """Return up to n_out interpolated gain values for the next n_out
        signal samples. May return FEWER (starvation): the caller must then
        process only that many input samples this call and defer the rest --
        never hold. Returns (gains[float64], shortfall)."""
        if self.R is None or self.buf.size == 0:
            # nothing received yet, or buffer fully drained -> starved
            if n_out > 0:
                self.n_starve_events += 1
                self.n_starve_samples += n_out
                self._warn("starve", "[fso-zmq] STARVED: no gain data for "
                                    "%d signal samples (deferring)" % n_out)
            return np.empty(0, dtype=np.float64), n_out

        # absolute (within-buffer) fractional positions of the n_out samples
        pos = self.cursor + np.arange(n_out) / self.R
        last = self.buf.size - 1
        # positions is strictly increasing, so the coverable ones are a
        # prefix: the largest k with pos[k-1] <= last (we need a right
        # neighbour for honest linear interpolation, no edge extrapolation)
        k = int(np.searchsorted(pos, last + 1e-9, side="right"))
        if k <= 0:
            # cannot even cover the first sample -> fully starved this call
            self.n_starve_events += 1
            self.n_starve_samples += n_out
            self._warn("starve", "[fso-zmq] STARVED: buffer cannot cover "
                                "%d signal samples (deferring)" % n_out)
            return np.empty(0, dtype=np.float64), n_out

        gains = np.interp(pos[:k], np.arange(self.buf.size), self.buf)

        # advance the cursor and trim fully-consumed gain samples
        self.cursor += k / self.R
        drop = int(np.floor(self.cursor))
        if drop > 0:
            self.buf = self.buf[drop:]
            self.base_index += drop
            self.cursor -= drop

        shortfall = n_out - k
        if shortfall > 0:
            self.n_starve_events += 1
            self.n_starve_samples += shortfall
            self._warn("starve", "[fso-zmq] STARVED: covered %d/%d signal "
                                "samples this call, deferring %d"
                                % (k, n_out, shortfall))
        return gains, shortfall

    # -- logging (rate-limited so it is visible but never floods) -------
    def _warn(self, key, message):
        now = time.monotonic()
        if now - self._last_warn.get(key, 0.0) >= self._warn_period_s:
            print(message)
            self._last_warn[key] = now

    def summary(self):
        return dict(
            messages=self.n_messages, gaps=self.n_gaps,
            lost_samples=self.n_lost_samples,
            epoch_changes=self.n_epoch_changes, loops=self.n_loops,
            starve_events=self.n_starve_events,
            starve_samples=self.n_starve_samples,
            negative_clamped=self.n_negative_clamped)


# --- GNU Radio wrapper (requires gnuradio + pyzmq; not importable in plain
# --- Python, which is intentional and matches epy_fso_channel.py) ----------
try:
    from gnuradio import gr
    import zmq

    class blk(gr.sync_block):
        """FSO turbulent channel gain (Tier B: live ZMQ gain stream)."""

        def __init__(self, gain_endpoint="tcp://127.0.0.1:50003",
                     sample_rate=30.72e6):
            gr.sync_block.__init__(
                self,
                name="FSO Channel Gain ZMQ (OCLab)",
                in_sig=[np.complex64],
                out_sig=[np.complex64],
            )
            self.decoder = GainStreamDecoder(sample_rate)
            self._ctx = zmq.Context.instance()
            self._sock = self._ctx.socket(zmq.SUB)
            self._sock.connect(gain_endpoint)
            self._sock.setsockopt(zmq.SUBSCRIBE, b"")
            self._sock.setsockopt(zmq.LINGER, 0)
            self._endpoint = gain_endpoint

        def _drain(self):
            """Pull every currently-available gain message without blocking.
            zmq.NOBLOCK means work() never waits on the network."""
            while True:
                try:
                    raw = self._sock.recv(zmq.NOBLOCK)
                except zmq.Again:
                    break
                self.decoder.ingest(raw)

        def work(self, input_items, output_items):
            x = input_items[0]
            out = output_items[0]
            n_out = min(len(x), len(out))

            self._drain()
            gains, shortfall = self.decoder.produce(n_out)
            k = gains.size

            if k > 0:
                out[:k] = (x[:k] * gains).astype(np.complex64)

            if k == 0:
                # fully starved this call: produce nothing, do NOT hold. A
                # tiny sleep avoids a busy-spin while the (rare) starvation
                # clears; far shorter than one gain-update interval, so it
                # adds no perceptible latency. Returning 0 is non-blocking
                # and lets the scheduler retry once more data arrives.
                time.sleep(0.0002)
            return k

        def stop(self):
            s = self.decoder.summary()
            print("[fso-zmq] stream summary: %s" % s)
            try:
                self._sock.close(0)
            except Exception:
                pass
            return True

except ImportError:
    pass  # plain-Python import: GainStreamDecoder remains available
