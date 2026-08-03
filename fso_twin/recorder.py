"""
recorder.py -- log the streamed gain h(t) to a CSV for offline fade analysis.

Subscribes to the gain stream (:50003), reads scheme metadata once from the
control port (:50004), and writes one row per published sample:
    recv_time_s, seq, h, f_update_eff_hz
plus a commented metadata header (scheme, r0, sigma_R^2, validation status,
aperture, f_update). On stop it prints a deep-fade summary (deepest fade in dB
and the fraction of samples below -3/-6/-10/-20 dB).

h is the gain ACTUALLY applied to the link (already includes attenuation,
gain_scale and any INJECTED test fade). Records any scheme; for moderate/strong
the metadata carries the UNVERIFIED caveat. This records the CHANNEL gain; the
link-side BER/constellation would be recorded in the GNU Radio flowgraph.

Run (server up):  python3 recorder.py --out run.csv [--seconds 30]
"""

import argparse
import json
import time

import numpy as np
import zmq

from fso_stream_proto import unpack_message

GAIN_SUB_ENDPOINT = "tcp://127.0.0.1:50003"
CONTROL_REQ_ENDPOINT = "tcp://127.0.0.1:50004"
THRESHOLDS_DB = (-3.0, -6.0, -10.0, -20.0)


def get_status(ctx):
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.RCVTIMEO, 1500); s.setsockopt(zmq.SNDTIMEO, 1500)
    s.setsockopt(zmq.LINGER, 0); s.connect(CONTROL_REQ_ENDPOINT)
    try:
        s.send_string(json.dumps({"cmd": "status"}))
        return json.loads(s.recv_string())
    except Exception:
        return None
    finally:
        s.close(0)


def main():
    ap = argparse.ArgumentParser(description="Record the FSO gain stream h(t)")
    ap.add_argument("--out", default="fso_record.csv")
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="record duration (0 = until Ctrl+C)")
    args = ap.parse_args()

    ctx = zmq.Context.instance()
    st = get_status(ctx)
    if not st or not st.get("ok"):
        print("ERROR: no server on %s (start server.py first)" % CONTROL_REQ_ENDPOINT)
        return
    sub = ctx.socket(zmq.SUB); sub.connect(GAIN_SUB_ENDPOINT)
    sub.setsockopt(zmq.SUBSCRIBE, b""); sub.setsockopt(zmq.RCVTIMEO, 1000)

    f = open(args.out, "w")
    f.write("# FSO gain recording\n")
    f.write("# scheme=%s  Cn2=%.3e  r0_m=%.4f  sigma_R2=%.4f  aperture_D=%.3f\n"
            % (st["scheme"], st["cn2"], st["r0_m"], st["sigma_R2"], st["aperture_D"]))
    f.write("# f_update_stored_hz=%.1f  validated=%s\n"
            % (st["f_update_stored"], st["validated"]))
    f.write("# validation_status=%s\n" % st["validation_status"])
    f.write("# NOTE: h includes attenuation/gain_scale and any INJECTED test "
            "fade (explicit, not turbulence).\n")
    f.write("recv_time_s,seq,h,f_update_eff_hz\n")

    print("recording scheme=%s (%s) -> %s%s"
          % (st["scheme"], "VALIDATED" if st["validated"] else "UNVERIFIED",
             args.out, "" if args.seconds == 0 else "  for %.0f s" % args.seconds))
    if not st["validated"]:
        print("  ** %s **" % st["validation_status"])
    print("  Ctrl+C to stop. (Trigger deep fades via the GUI or "
          "{'cmd':'fade','depth_db':20,'duration_s':0.5} on :50004.)")

    n = 0; hmin = np.inf; hsum = 0.0
    below = {d: 0 for d in THRESHOLDS_DB}
    t_start = time.time()
    try:
        while True:
            if args.seconds and (time.time() - t_start) >= args.seconds:
                break
            try:
                raw = sub.recv()
            except zmq.Again:
                continue
            try:
                m = unpack_message(raw)
            except ValueError:
                continue
            t = time.time(); fu = m["f_update"]
            for j, h in enumerate(m["gains"]):
                f.write("%.6f,%d,%.6e,%.3f\n" % (t, m["seq_start"] + j, h, fu))
                n += 1; hsum += h; hmin = min(hmin, h)
                if h > 0:
                    db = 10.0 * np.log10(h)
                    for d in THRESHOLDS_DB:
                        if db < d:
                            below[d] += 1
    except KeyboardInterrupt:
        pass
    finally:
        f.close(); sub.close(0)

    dur = time.time() - t_start
    print("\n=== recording summary (%s) ===" % args.out)
    print("  samples=%d  wall=%.1f s  mean h=%.4f  deepest fade: h=%.4e (%.1f dB)"
          % (n, dur, (hsum / n if n else float("nan")), hmin,
             (10 * np.log10(hmin) if hmin > 0 else float("-inf"))))
    for d in THRESHOLDS_DB:
        frac = below[d] / n if n else 0.0
        print("  below %5.0f dB: %8d samples (%.3f%%, ~%.3f s)"
              % (d, below[d], 100 * frac, frac * dur))
    if not st["validated"]:
        print("  reminder: %s scheme is UNVERIFIED -- fade depths from turbulence "
              "are not quantitatively trustworthy (injected fades are exact)."
              % st["scheme"])


if __name__ == "__main__":
    main()
