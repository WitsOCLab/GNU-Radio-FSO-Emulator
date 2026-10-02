"""
server.py -- simplified single-r0 FSO gain server with live wind tuning.

ONE turbulence scheme per run (weak | moderate | strong), chosen at startup.
At launch it generates the single-screen frozen-flow reference trace (traces.py)
for that scheme, then streams it over ZMQ with the verified wind-as-time-
resampling: publish the stored samples unchanged and report
    f_update_eff = f_stored * (wind / v_max).
The consumer (GR block) locks R = sample_rate/f_update and linearly interpolates,
so slower wind => slower fades, same fade VALUES.

No library, no trace selection, no manifest. Wind is the only live-tunable
turbulence parameter; attenuation and gain_scale remain as cheap multipliers.
The Greenwood readout (tau0, f_G) is a DERIVED telemetry value, not a control.

VALIDATION CAVEAT (in status + PROCESS.md): only `weak` is on validated
propagation; `moderate`/`strong` are PHYSICALLY-PLAUSIBLE-BUT-UNVERIFIED.

Sockets: PUB gain on tcp://127.0.0.1:50003, REP control on tcp://127.0.0.1:50004.
Wire protocol: fso_stream_proto.py.
"""

import argparse
import json
import os
import threading
import time

import numpy as np
import zmq

from fso_stream_proto import pack_message
from traces import (make_reference_trace, greenwood_time,
                    greenwood_frequency_approx, PRESETS, DEFAULT_SEED)

GAIN_PUB_ENDPOINT = "tcp://127.0.0.1:50003"
CONTROL_REP_ENDPOINT = "tcp://127.0.0.1:50004"
LOOKAHEAD_S = 0.25
PUBLISH_TICK_S = 0.02
LOOP_MODES = ("pingpong", "forward", "once")
WIND_MIN = 0.5

# Greenwood-frequency labelling: 1/tau0 is an APPROXIMATION; the literature
# proportionality coefficient (~0.31x, Greenwood/Tyler) is TO-CONFIRM from print.
F_G_NOTE = "approximate (f_G = 1/tau0); proportionality coefficient TO-CONFIRM from print"

CHEAP_SPEC = {
    "attenuation": dict(default=1.0, lo=0.0, hi=1.0, soft=None,
                        desc="Beer-Lambert weather loss factor in (0,1]"),
    "gain_scale":  dict(default=1.0, lo=0.0, hi=1e6, soft=10.0,
                        desc="overall gain scale multiplier (>0)"),
}


def _exists(path):
    return os.path.exists(path)


def loop_indices(progress, m, n, mode):
    """Map monotonic trace-progress to record indices for `m` samples (verified
    logic, index-based so it is wind/rate independent)."""
    p = progress + np.arange(m)
    if n < 2 or mode == "forward":
        idx = p % n
        return idx.astype(np.int64), int(((p % n == 0) & (p > 0)).sum()), False
    if mode == "pingpong":
        period = 2 * (n - 1)
        q = p % period
        idx = np.where(q < n, q, period - q)
        return idx.astype(np.int64), int(((p % (n - 1) == 0) & (p > 0)).sum()), False
    if mode == "once":
        in_range = p < n
        return p[in_range].astype(np.int64), 0, bool(np.any(p >= n))
    raise ValueError("unknown loop mode %r" % mode)


class CheapParams:
    def __init__(self):
        self.values = {k: s["default"] for k, s in CHEAP_SPEC.items()}

    def set(self, name, value):
        if name not in CHEAP_SPEC:
            raise KeyError("unknown cheap parameter %r" % name)
        spec = CHEAP_SPEC[name]
        v = float(value)
        if not np.isfinite(v):
            raise ValueError("%s must be finite" % name)
        if v <= spec["lo"] or v > spec["hi"]:
            raise ValueError("%s must be in (%g, %g], got %g"
                             % (name, spec["lo"], spec["hi"], v))
        self.values[name] = v
        if spec["soft"] is not None and v > spec["soft"]:
            return "%s=%g exceeds soft limit %g" % (name, v, spec["soft"])
        return None

    def combined_multiplier(self):
        return self.values["attenuation"] * self.values["gain_scale"]


class ChannelServer:
    def __init__(self, scheme="weak", loop_mode="pingpong", verbose=True,
                 seed=DEFAULT_SEED):
        if loop_mode not in LOOP_MODES:
            raise ValueError("loop_mode must be one of %s" % (LOOP_MODES,))
        self.loop_mode = loop_mode
        self.verbose = verbose
        self.lock = threading.Lock()

        if verbose:
            print("[server] generating single-screen reference trace for "
                  "scheme '%s' (screen seed %d) ..." % (scheme, seed))
        self.ref = make_reference_trace(scheme, seed=seed)  # ONE r0, once
        self.h = self.ref["h"]
        self.f_update_stored = self.ref["f_update"]
        self.r0 = self.ref["r0"]
        self.v_max = self.ref["v_max"]
        self.wind_speed = self.v_max                   # default: stored rate

        self.cheap = CheapParams()
        # Injected test-fade state (an EXPLICIT deterministic deep fade, NOT
        # turbulence): published gain is scaled by fade_factor until fade_until.
        self.fade_factor = 1.0
        self.fade_depth_db = 0.0
        self.fade_until = 0.0          # time.monotonic() deadline
        # Ground truth for fade alignment: every injected fade is recorded with
        # the ABSOLUTE gain-sample index range it actually scaled (consumers
        # align by index, never by wall clock).
        self.fade_log_path = None
        self.fade_records = []         # finished records (dicts)
        self._fade_open = None         # record being filled by the publisher
        self.seq = 0
        self.trace_progress = 0
        self.loop_count = 0
        self.exhausted = False
        self.pending_trace_changed = True
        self.running = False
        self._ctx = zmq.Context.instance()
        self._threads = []
        if verbose:
            print("[server] scheme=%s  Cn2=%.1e  r0=%.1f cm  sigma_R^2=%.3f  "
                  "[%s]" % (scheme, self.ref["cn2"], 100 * self.r0,
                            self.ref["sigma_R2"], self.ref["status"]))
            print("[server] reference trace: %d samples, f_update_stored=%.0f Hz"
                  % (len(self.h), self.f_update_stored))

    # ---- controls -----------------------------------------------------
    def set_wind(self, value):
        v = float(value)
        if not np.isfinite(v) or v <= 0.0:
            raise ValueError("wind_speed must be finite and > 0")
        warning = None
        if v > self.v_max:
            warning = ("wind_speed=%g exceeds hard max %g (stored resolution); "
                       "clamped" % (v, self.v_max))
            v = self.v_max
        elif v < WIND_MIN:
            warning = "wind_speed=%g below min %g; clamped" % (v, WIND_MIN)
            v = WIND_MIN
        with self.lock:
            self.wind_speed = v
        return warning

    def effective_f_update(self):
        return self.f_update_stored * (self.wind_speed / self.v_max)

    def inject_fade(self, depth_db, duration_s):
        """Trigger an EXPLICIT test fade: scale the published gain by
        10^(-depth_db/10) (power) for duration_s seconds. This is a deterministic
        injected fade for link stress-testing (BER/FEC/loss-of-lock), NOT a
        turbulence statistic -- it is recorded/labelled as 'injected'."""
        d = float(depth_db); dur = float(duration_s)
        if not (np.isfinite(d) and d > 0.0):
            raise ValueError("fade depth_db must be finite and > 0")
        if not (np.isfinite(dur) and dur > 0.0):
            raise ValueError("fade duration_s must be finite and > 0")
        d = min(d, 60.0)               # cap (10^-6 floor keeps gain > 0)
        with self.lock:
            self._close_fade_record()          # a new fade ends any open one
            self.fade_depth_db = d
            self.fade_factor = 10.0 ** (-d / 10.0)
            self.fade_until = time.monotonic() + dur
            self._fade_open = {"t_cmd_unix": time.time(), "depth_db": d,
                               "duration_s": dur, "seq_first": None,
                               "seq_last": None}
        if self.verbose:
            print("[server] INJECTED test fade: -%.1f dB for %.3f s" % (d, dur))
        return self.cmd_status()

    def _close_fade_record(self):
        """Finish the open fade record (call with self.lock held) and append it
        to the fade log. A fade that scaled no samples is still recorded."""
        rec = self._fade_open
        if rec is None:
            return
        self._fade_open = None
        self.fade_records.append(rec)
        line = "%.6f,%g,%g,%s,%s" % (
            rec["t_cmd_unix"], rec["depth_db"], rec["duration_s"],
            "" if rec["seq_first"] is None else rec["seq_first"],
            "" if rec["seq_last"] is None else rec["seq_last"])
        if self.verbose:
            print("[server] fade record: depth %.1f dB, %.3f s, gain seq %s..%s"
                  % (rec["depth_db"], rec["duration_s"], rec["seq_first"],
                     rec["seq_last"]))
        if self.fade_log_path:
            new = not _exists(self.fade_log_path)
            with open(self.fade_log_path, "a") as f:
                if new:
                    f.write("t_cmd_unix,depth_db,duration_s,seq_first,seq_last\n")
                f.write(line + "\n")

    def cmd_status(self):
        with self.lock:
            tau0 = greenwood_time(self.r0, self.wind_speed)
            return {
                "ok": True,
                "scheme": self.ref["scheme"], "cn2": self.ref["cn2"],
                "r0_m": self.r0, "sigma_R2": self.ref["sigma_R2"],
                "validated": self.ref["validated"],
                "validation_status": self.ref["status"],
                "L": self.ref["L"], "wavelength": self.ref["wavelength"],
                "N": self.ref["N"], "delta": self.ref["delta"],
                "aperture_D": self.ref["aperture_D"],
                "screen_seed": self.ref["screen_seed"],
                "f_update_stored": self.f_update_stored,
                "f_update_effective": self.effective_f_update(),
                "wind_speed": self.wind_speed,
                "wind_max": self.v_max, "wind_min": WIND_MIN,
                "tau0_s": tau0,
                "greenwood_freq_hz": greenwood_frequency_approx(tau0),
                "greenwood_freq_note": F_G_NOTE,
                "loop_mode": self.loop_mode, "loop_count": self.loop_count,
                "n_samples": len(self.h),
                "fade_active": time.monotonic() < self.fade_until,
                "fade_depth_db": self.fade_depth_db,
                "fade_remaining_s": max(0.0, self.fade_until - time.monotonic()),
                "fades_recorded": len(self.fade_records),
                "seq_next": self.seq,
                "cheap": dict(self.cheap.values),
            }

    def cmd_set(self, param, value):
        if param == "wind_speed":
            warning = self.set_wind(value)
        else:
            with self.lock:
                warning = self.cheap.set(param, value)
        if self.verbose:
            print("[server] set %s = %s%s"
                  % (param, value, "  WARNING: " + warning if warning else ""))
        status = self.cmd_status()
        if warning:
            status["warning"] = warning
        return status

    def handle_command(self, req):
        try:
            cmd = req.get("cmd")
            if cmd == "status":
                return self.cmd_status()
            if cmd == "set":
                return self.cmd_set(req["param"], req["value"])
            if cmd == "fade":
                return self.inject_fade(req["depth_db"], req["duration_s"])
            if cmd == "ping":
                return {"ok": True, "pong": True}
            return {"ok": False, "error": "unknown cmd %r" % cmd}
        except KeyError as e:
            return {"ok": False, "error": "missing field: %s" % e}
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": str(e)}

    # ---- service loops ------------------------------------------------
    def _control_loop(self):
        sock = self._ctx.socket(zmq.REP)
        sock.bind(CONTROL_REP_ENDPOINT)
        if self.verbose:
            print("[server] control REP on %s" % CONTROL_REP_ENDPOINT)
        poller = zmq.Poller(); poller.register(sock, zmq.POLLIN)
        while self.running:
            if dict(poller.poll(200)):
                try:
                    req = json.loads(sock.recv().decode("utf-8"))
                except Exception as e:
                    sock.send_string(json.dumps({"ok": False, "error": str(e)}))
                    continue
                sock.send_string(json.dumps(self.handle_command(req)))
        sock.close(0)

    def _publish_loop(self):
        sock = self._ctx.socket(zmq.PUB)
        sock.bind(GAIN_PUB_ENDPOINT)
        if self.verbose:
            print("[server] gain PUB on %s" % GAIN_PUB_ENDPOINT)
        time.sleep(0.3)
        t0 = time.monotonic(); emitted = 0; cur_wind = self.wind_speed
        cur_f = self.f_update_stored * (cur_wind / self.v_max)
        n = len(self.h)
        while self.running:
            now = time.monotonic()
            with self.lock:
                mult = self.cheap.combined_multiplier()
                fading = now < self.fade_until
                if fading:                             # injected deep test fade
                    mult *= self.fade_factor
                elif self._fade_open is not None and \
                        self._fade_open["seq_first"] is not None:
                    self._close_fade_record()          # fade over: log it
                wind = self.wind_speed
                f_eff = self.f_update_stored * (wind / self.v_max)
                progress = self.trace_progress
                seq = self.seq
                trace_changed = self.pending_trace_changed
                if wind != cur_wind:                   # re-baseline on rate change
                    # Carry over the lookahead ALREADY published (seconds ahead
                    # of real time at the old rate) so the new rate only tops
                    # it up to LOOKAHEAD_S. Restarting from emitted=0 re-sent a
                    # full LOOKAHEAD_S on every wind command, and that surplus
                    # accumulated as consumer latency (70k-185k samples over
                    # the 15-min scenario).
                    ahead_s = min(max(emitted / cur_f - (now - t0), 0.0),
                                  LOOKAHEAD_S)
                    cur_wind = wind; cur_f = f_eff; t0 = now
                    emitted = int(round(ahead_s * f_eff))
                due = int((now - t0 + LOOKAHEAD_S) * f_eff)
                m = due - emitted
                msg = None
                if m > 0 and not self.exhausted:
                    idx, n_seams, exhausted = loop_indices(progress, m, n,
                                                           self.loop_mode)
                    if idx.size:
                        gains = self.h[idx] * mult
                        if np.any(gains < 0):
                            raise RuntimeError("negative gain; refusing")
                        msg = pack_message(seq, f_eff, gains, epoch=0,
                                           trace_changed=trace_changed,
                                           looped=(n_seams > 0))
                        sent = idx.size
                        if fading and self._fade_open is not None:
                            if self._fade_open["seq_first"] is None:
                                self._fade_open["seq_first"] = seq
                            self._fade_open["seq_last"] = seq + sent - 1
                        self.seq = seq + sent
                        self.trace_progress = progress + sent
                        self.pending_trace_changed = False
                        emitted += sent
                        self.loop_count += n_seams
                        if exhausted:
                            self.exhausted = True
            if msg is not None:
                sock.send(msg)
            time.sleep(PUBLISH_TICK_S)
        sock.close(0)

    def start(self):
        self.running = True
        self._threads = [threading.Thread(target=self._publish_loop, daemon=True),
                         threading.Thread(target=self._control_loop, daemon=True)]
        for t in self._threads:
            t.start()

    def stop(self):
        self.running = False
        time.sleep(0.3)
        with self.lock:
            self._close_fade_record()

    def run(self):
        self.start()
        if self.verbose:
            print("[server] running (wind %.1f m/s, max %.1f). Ctrl+C to stop."
                  % (self.wind_speed, self.v_max))
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n[server] stopping...")
        finally:
            self.stop()


COMMANDS = """\
Control (JSON over REP tcp://127.0.0.1:50004):
  {"cmd":"status"}                                -> scheme, r0, wind, f_update, Greenwood
  {"cmd":"set","param":"wind_speed","value":8.0}  -> live wind m/s (0.5,20], time-resample
  {"cmd":"set","param":"attenuation","value":0.5} -> weather loss (0,1]
  {"cmd":"set","param":"gain_scale","value":2.0}  -> gain scale (>0)
  {"cmd":"fade","depth_db":20,"duration_s":0.5}   -> INJECT a deep test fade (not turbulence)
  {"cmd":"ping"}
"""


def main():
    ap = argparse.ArgumentParser(description="Simplified single-r0 FSO server")
    ap.add_argument("--scheme", default="weak", choices=list(PRESETS),
                    help="turbulence scheme (chosen at startup, not live)")
    ap.add_argument("--loop-mode", default="pingpong", choices=LOOP_MODES)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help="screen realisation seed (default %d; use a "
                         "HELD-OUT seed when evaluating the GRU predictor -- "
                         "the training library used 20240+1000*regime+k, "
                         "k=0..7)" % DEFAULT_SEED)
    ap.add_argument("--fade-log", default=None,
                    help="CSV file to append one row per injected fade: "
                         "command time, depth, duration and the absolute "
                         "gain-sample index range it scaled")
    args = ap.parse_args()
    server = ChannelServer(scheme=args.scheme, loop_mode=args.loop_mode,
                           seed=args.seed)
    server.fade_log_path = args.fade_log
    print(COMMANDS)
    print("[server] only 'weak' is Rytov-validated; moderate/strong are "
          "PHYSICALLY-PLAUSIBLE-BUT-UNVERIFIED.")
    server.run()


if __name__ == "__main__":
    main()
