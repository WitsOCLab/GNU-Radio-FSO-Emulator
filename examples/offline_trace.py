#!/usr/bin/env python3
"""
offline_trace.py -- use the physics directly, with no server and no ZMQ.

If all you want is a turbulence gain trace h(t) to drive your own simulator,
import the library and generate one. This is the simplest integration path:
no streaming, no GNU Radio, just numpy arrays.

    python3 examples/offline_trace.py --scheme moderate --csv trace.csv

Schemes: weak (Rytov-validated), moderate, strong (see PROCESS.md for the
validity envelope -- only 'weak' is quantitatively validated).
"""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fso_twin"))
from traces import make_reference_trace, PRESETS      # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Generate one FSO gain trace")
    ap.add_argument("--scheme", default="weak", choices=list(PRESETS))
    ap.add_argument("--seed", type=int, default=20240)
    ap.add_argument("--csv", default=None, help="optional CSV output path")
    args = ap.parse_args()

    ref = make_reference_trace(args.scheme, seed=args.seed)
    h = ref["h"]
    # Reference trace is sampled at the v_max displacement step; served at any
    # slower wind v it plays at f_update * v / v_max (see server.py / PROCESS.md).
    print("scheme=%s  Cn2=%.1e  r0=%.2f cm  sigma_R^2=%.3f  [%s]"
          % (args.scheme, ref["cn2"], ref["r0"] * 100, ref["sigma_R2"],
             ref["status"]))
    print("trace: %d samples at f_update=%.1f Hz (v_max=%.0f m/s)"
          % (h.size, ref["f_update"], ref["v_max"]))
    print("gain h: min=%.4f  mean=%.4f  max=%.4f  (deepest fade %.2f dB)"
          % (h.min(), h.mean(), h.max(), 10 * np.log10(h.min())))

    if args.csv:
        t = np.arange(h.size) / ref["f_update"]        # time axis at v_max [s]
        np.savetxt(args.csv, np.column_stack([t, h]), delimiter=",",
                   header="time_s,gain_h", comments="")
        print("wrote %s" % args.csv)


if __name__ == "__main__":
    main()
