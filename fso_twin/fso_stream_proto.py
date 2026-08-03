"""
fso_stream_proto.py
===================
Wire protocol for the FSO gain stream (piece 2 server -> piece 3 GNU Radio
block, and any standalone subscriber).

WHY A FRAMED BINARY MESSAGE AND NOT RAW float32:
  Raw float32 chunks over PUB/SUB carry no identity. If a subscriber lags
  and ZMQ drops a message, the gain trajectory silently misaligns from then
  on with no error -- a subtle, permanent corruption of the channel. So
  every message carries the ABSOLUTE sample index of its first gain sample
  (seq_start). A subscriber compares seq_start against the index it
  expected; any mismatch is a detected gap, handled explicitly, never
  silently absorbed.

  A monotonic EPOCH counter marks legitimate discontinuities: when the
  operator selects a different trace (a different turbulence regime), the
  gain trajectory is SUPPOSED to jump. The subscriber resets its
  interpolation continuity on an epoch change instead of mistaking it for a
  network gap.

  A separate FLAG_LOOPED bit marks the seam where a finite trace wraps. A
  forward loop can step h discontinuously from the record's end back to its
  start -- a real, unphysical periodic glitch. That seam is therefore never
  silent: it is flagged here, counted, and logged by the server, exactly so
  the subscriber (and the operator) know it happened. (The server's
  default loop mode is value-continuous ping-pong, which has no step at
  all; see fso_channel_server.py LOOP MODES.)

MESSAGE LAYOUT (little-endian), one ZMQ message per publish:
    magic     4s   b'FSOG'
    version   B    protocol version (currently 1)
    flags     B    bit0 = TRACE_CHANGED (first message after a discrete
                   trace selection; reset continuity, do not warn)
                   bit1 = LOOPED (this message contains a finite-trace wrap
                   seam; flagged so the wrap is never silent)
    epoch     H    increments on every discrete trace change
    seq_start Q    absolute sample index of the first gain sample here
    f_update  d    update rate [Hz] of the gain samples in this message
    n         I    number of gain samples following
    payload   n*f  n IEEE-754 float32 gain values (already scaled by the
                   cheap params; guaranteed >= 0 by the server)

The gain values are sampled at f_update spacing; seq_start + k is the
absolute index of payload sample k. The subscriber upsamples them to the
signal sample rate by linear interpolation (piece 3).

This module has NO third-party dependencies (struct + numpy only) so it can
be imported by the server, by a plain test subscriber, and -- by copy, see
the MUST-MATCH note in the GNU Radio block -- by the embedded Python block.
"""

import struct

import numpy as np

MAGIC = b"FSOG"
VERSION = 1

# flags bitfield
FLAG_TRACE_CHANGED = 0x01
FLAG_LOOPED = 0x02

# '<' little-endian; 4s B B H Q d I  -> magic,ver,flags,epoch,seq_start,fupd,n
_HEADER = struct.Struct("<4sBBHQdI")
HEADER_SIZE = _HEADER.size


def pack_message(seq_start, f_update, gains, epoch=0, trace_changed=False,
                 looped=False):
    """Pack one gain message. `gains` is a 1-D float array (already scaled
    and verified non-negative by the caller)."""
    g = np.ascontiguousarray(gains, dtype="<f4")
    flags = 0
    if trace_changed:
        flags |= FLAG_TRACE_CHANGED
    if looped:
        flags |= FLAG_LOOPED
    header = _HEADER.pack(MAGIC, VERSION, flags, epoch & 0xFFFF,
                          int(seq_start), float(f_update), g.size)
    return header + g.tobytes()


def unpack_message(buf):
    """Parse one gain message -> dict. Raises ValueError on a bad frame."""
    if len(buf) < HEADER_SIZE:
        raise ValueError("short message (truncated header)")
    magic, version, flags, epoch, seq_start, f_update, n = \
        _HEADER.unpack(buf[:HEADER_SIZE])
    if magic != MAGIC:
        raise ValueError("bad magic %r (not an FSO gain message)" % (magic,))
    if version != VERSION:
        raise ValueError("unsupported protocol version %d" % version)
    expected = HEADER_SIZE + 4 * n
    if len(buf) != expected:
        raise ValueError("payload length mismatch: got %d, expected %d"
                         % (len(buf), expected))
    gains = np.frombuffer(buf[HEADER_SIZE:], dtype="<f4").astype(np.float64)
    return {
        "version": version,
        "trace_changed": bool(flags & FLAG_TRACE_CHANGED),
        "looped": bool(flags & FLAG_LOOPED),
        "epoch": epoch,
        "seq_start": seq_start,
        "f_update": f_update,
        "n": n,
        "gains": gains,
    }
