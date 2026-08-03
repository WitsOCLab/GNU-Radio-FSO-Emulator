#!/usr/bin/env python3
"""
minimal_subscriber.py -- the smallest possible consumer of the FSO gain stream.

This is the integration template for ANY program (SDR, link simulator, notebook)
that wants the live turbulence gain without GNU Radio. It:

  1. subscribes to the gain stream   (ZMQ SUB, tcp://127.0.0.1:50003),
  2. sends a control command         (ZMQ REQ, tcp://127.0.0.1:50004),
  3. decodes each framed message with the shared wire protocol,
  4. shows how to upsample the slow gain to a fast signal by LINEAR interpolation
     and apply it as  y[n] = h(t_n) * x[n].

Start the server first (see examples/run_server.sh), then run this.

    python3 examples/minimal_subscriber.py --seconds 5 --wind 8
"""

import argparse
import json
import os
import sys
import time

import numpy as np
import zmq

# make fso_twin importable regardless of where this is run from
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fso_twin"))
from fso_stream_proto import unpack_message           # noqa: E402

GAIN_SUB = "tcp://127.0.0.1:50003"      # server PUB: gain frames
CONTROL_REQ = "tcp://127.0.0.1:50004"   # server REP: JSON control


def send_control(ctx, req):
    """One JSON command over a short-lived REQ socket; returns the reply dict."""
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.RCVTIMEO, 1000); s.setsockopt(zmq.LINGER, 0)
    s.connect(CONTROL_REQ)
    try:
        s.send_string(json.dumps(req))
        return json.loads(s.recv_string())
    finally:
        s.close(0)


def main():
    ap = argparse.ArgumentParser(description="Minimal FSO gain-stream consumer")
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--wind", type=float, default=None, help="set wind [m/s]")
    ap.add_argument("--sample-rate", type=float, default=1e6,
                    help="pretend signal rate, to demo interpolation")
    args = ap.parse_args()

    ctx = zmq.Context.instance()

    # (2) control: query status, optionally set wind
    st = send_control(ctx, {"cmd": "status"})
    if not st or not st.get("ok"):
        print("ERROR: no server on %s -- start it first." % CONTROL_REQ)
        return
    print("connected: scheme=%s  r0=%.1f cm  sigma_R^2=%.3f  validated=%s"
          % (st["scheme"], st["r0_m"] * 100, st["sigma_R2"], st["validated"]))
    if args.wind is not None:
        r = send_control(ctx, {"cmd": "set", "param": "wind_speed",
                               "value": args.wind})
        print("set wind=%.1f m/s -> f_update_eff=%.1f Hz"
              % (args.wind, r.get("f_update_effective", float("nan"))))

    # (1) subscribe to the gain stream
    sub = ctx.socket(zmq.SUB); sub.connect(GAIN_SUB)
    sub.setsockopt(zmq.SUBSCRIBE, b""); sub.setsockopt(zmq.RCVTIMEO, 1000)

    # (3)+(4) receive, decode, and demonstrate applying the gain
    n_msgs = n_samples = 0
    hmin, hmax, hsum = np.inf, -np.inf, 0.0
    t0 = time.time()
    while time.time() - t0 < args.seconds:
        try:
            raw = sub.recv()
        except zmq.Again:
            continue
        try:
            msg = unpack_message(raw)
        except ValueError:
            continue                                  # skip a malformed frame
        g = msg["gains"]                              # gain samples at f_update
        n_msgs += 1; n_samples += g.size
        hmin = min(hmin, g.min()); hmax = max(hmax, g.max()); hsum += g.sum()

        # --- how you would apply it to a fast signal (illustrative) -----------
        # R = signal samples per gain sample; interpolate, then multiply:
        #   R = args.sample_rate / msg["f_update"]
        #   pos = np.arange(N_out) / R
        #   h_fast = np.interp(pos, np.arange(g.size), g)
        #   y = x[:h_fast.size] * h_fast
        # (epy_fso_channel.py does exactly this, with buffering + integrity
        #  checks, inside GNU Radio.)

    dur = time.time() - t0
    print("received %d messages, %d gain samples in %.1f s (%.0f gain-Hz)"
          % (n_msgs, n_samples, dur, n_samples / dur if dur else 0))
    if n_samples:
        print("gain h: min=%.4f  mean=%.4f  max=%.4f"
              % (hmin, hsum / n_samples, hmax))
    sub.close(0)


if __name__ == "__main__":
    main()
