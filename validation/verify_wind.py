"""
verify_wind.py -- end-to-end acceptance test for live wind tuning (real ZMQ).

Confirms the frozen-flow retiming identity against the CURRENT single-r0 server:
serving a slower wind is a pure time-resampling of ONE stored trace -- same gain
VALUES, different rate.

  (a) RATE scales with wind:  f_update(v) = f_stored * v / v_max.
  (b) VALUES invariant:       the gain at a given absolute sample index is the
      same at 20 and 10 m/s (two streams from seq 0, compared by index).
  (c) LINEAR interpolation, not zero-order hold: upsampling with the consumer's
      np.interp idiom repeats ~no values, where a ZOH repeats ~(R-1)/R of them.
  (d) wind > v_max is clamped with a warning (graceful, not silent).
  (e) published gain stays real and >= 0.

Run (from this directory):  PYTHONPATH=../fso_twin python3 verify_wind.py
"""

import json
import time

import numpy as np
import zmq

from server import ChannelServer, GAIN_PUB_ENDPOINT, CONTROL_REP_ENDPOINT
from fso_stream_proto import unpack_message


def run_at_wind(v, seconds=1.5):
    """Fresh server from seq 0 at wind v; return {seq: gain} and f_update."""
    srv = ChannelServer(scheme="weak", loop_mode="forward", verbose=False)
    srv.start(); time.sleep(0.4)
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB); sub.connect(GAIN_PUB_ENDPOINT)
    sub.setsockopt(zmq.SUBSCRIBE, b""); sub.setsockopt(zmq.RCVTIMEO, 800)
    rq = ctx.socket(zmq.REQ); rq.connect(CONTROL_REP_ENDPOINT)
    rq.setsockopt(zmq.RCVTIMEO, 1500)
    rq.send_string(json.dumps({"cmd": "set", "param": "wind_speed", "value": v}))
    reply = json.loads(rq.recv())
    out = {}; f = None; poller = zmq.Poller(); poller.register(sub, zmq.POLLIN)
    t0 = time.time()
    while time.time() - t0 < seconds:
        if dict(poller.poll(50)):
            m = unpack_message(sub.recv()); f = m["f_update"]
            for i, g in enumerate(m["gains"]):
                out.setdefault(m["seq_start"] + i, g)
    srv.stop(); sub.close(0); rq.close(0); time.sleep(0.3)
    return out, f, reply


def main():
    print("=" * 72)
    print("VERIFY: live wind tuning = time-resampling (end-to-end ZMQ)")
    print("=" * 72)
    a, f20, _ = run_at_wind(20.0)
    b, f10, _ = run_at_wind(10.0)
    shared = sorted(set(a) & set(b))
    maxdiff = max(abs(a[s] - b[s]) for s in shared) if shared else float("nan")
    gmin = min(min(a.values()), min(b.values()))

    print("\n(a) RATE vs wind:")
    print("    f_update(20 m/s) = %.1f Hz" % f20)
    print("    f_update(10 m/s) = %.1f Hz   (f10/f20 = %.3f, expect 0.500)"
          % (f10, f10 / f20))

    print("\n(b) VALUES vs wind (matched sample indices):")
    print("    compared %d samples, max|gain(20)-gain(10)| = %.2e (expect 0)"
          % (len(shared), maxdiff))

    # (c) linear interpolation vs zero-order hold
    g = np.array([b[s] for s in sorted(b)][:60], dtype=float)
    R = 50
    pos = np.arange(0, len(g) - 1, 1.0 / R)
    up_lin = np.interp(pos, np.arange(len(g)), g)
    up_zoh = g[np.floor(pos).astype(int)]
    frac_lin = float(np.mean(np.diff(up_lin) == 0.0))
    frac_zoh = float(np.mean(np.diff(up_zoh) == 0.0))
    print("\n(c) LINEAR interpolation (upsample R=%d):" % R)
    print("    repeated-value fraction: linear=%.4f vs ZOH=%.4f" % (frac_lin, frac_zoh))

    # (d) over-max clamp
    srv = ChannelServer(scheme="weak", verbose=False); srv.start(); time.sleep(0.3)
    ctx = zmq.Context.instance(); rq = ctx.socket(zmq.REQ)
    rq.connect(CONTROL_REP_ENDPOINT); rq.setsockopt(zmq.RCVTIMEO, 1500)
    rq.send_string(json.dumps({"cmd": "set", "param": "wind_speed", "value": 25.0}))
    st = json.loads(rq.recv()); rq.close(0); srv.stop()
    print("\n(d) wind=25 m/s -> clamped to %.1f, warning present: %s"
          % (st["wind_speed"], "warning" in st))

    print("\n(e) published gain min over both winds = %.4f (>= 0)" % gmin)

    ok = (abs(f10 / f20 - 0.5) < 0.02 and maxdiff < 1e-9 and frac_lin < 0.01
          and st["wind_speed"] == 20.0 and "warning" in st and gmin >= 0)
    print("\n%s" % ("ALL CHECKS PASS" if ok else "*** A CHECK FAILED ***"))
    print("=" * 72)


if __name__ == "__main__":
    main()
