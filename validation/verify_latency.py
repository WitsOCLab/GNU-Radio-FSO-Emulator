"""
verify_latency.py -- end-to-end regression test for gain-stream DELIVERY LATENCY
under live wind changes (real ZMQ, real server, real GNU Radio block decoder).

Guards the fix for a bug that verify_wind.py cannot see (it never changes the wind
on a live stream): the server used to re-send its full publish lookahead on every
wind change, so a consumer's buffered gain -- i.e. the delay between the server
publishing a sample and the channel applying it -- grew with every wind command
(minutes over a scripted scenario).

A real-time-paced consumer (the block's GainStreamDecoder, no GNU Radio needed)
reads the live stream while a controller sends a wind change every 0.25 s and
injects deep fades. Checks:
  (a) buffered latency stays bounded (< 0.3 s) throughout -- no growth with the
      number of wind commands;
  (b) zero resyncs and zero gaps (the decoder's latency cap never had to act);
  (c) every injected fade appears in the APPLIED gain exactly at the absolute
      gain-index range the server logged (--fade-log), and nowhere else.

Run (from this directory):  PYTHONPATH=../fso_twin python3 verify_latency.py
Takes ~45 s.
"""

import importlib.util
import json
import os
import tempfile
import threading
import time

import numpy as np
import zmq

TMP = tempfile.mkdtemp(prefix="fso_latency_")
FRAME = 2000                                        # signal samples per log row
FS = 2e6                                            # consumer signal rate
os.environ["FSO_INDEX_LOG"] = os.path.join(TMP, "index.csv")
os.environ["FSO_EVENT_LOG"] = os.path.join(TMP, "events.csv")
os.environ["FSO_FRAME_LEN"] = str(FRAME)

from server import ChannelServer, GAIN_PUB_ENDPOINT, CONTROL_REP_ENDPOINT  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "epy_fso_channel", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "gnuradio", "epy_fso_channel.py"))
epy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(epy)

DURATION = 40.0
WIND_PERIOD = 0.25
FADES = [(12.0, 6.0, 0.4), (25.0, 10.0, 0.5)]      # (t_s, depth_dB, duration_s)


def consumer(stop, out):
    """Real-time-paced consumer: demands FS signal samples per wall-clock second,
    deferring on starvation (like a throttle-paced flowgraph)."""
    dec = epy.GainStreamDecoder(FS)
    sub = zmq.Context.instance().socket(zmq.SUB)
    sub.connect(GAIN_PUB_ENDPOINT); sub.setsockopt(zmq.SUBSCRIBE, b"")
    t0 = time.time(); done = 0; ahead = []; rows = []
    while not stop.is_set():
        while True:
            try:
                dec.ingest(sub.recv(zmq.NOBLOCK))
            except zmq.Again:
                break
        want = int((time.time() - t0) * FS) - done
        while want > 0:
            n0 = dec.n_signal_out
            g, _ = dec.produce(min(want, 200000))
            b = -(-n0 // FRAME) * FRAME
            while b < n0 + g.size:
                rows.append((b // FRAME, g[b - n0])); b += FRAME
            done += g.size; want -= g.size
            if g.size == 0:
                break
        if dec.f_update:
            ahead.append((time.time(), (dec.buf.size - 1 - dec.cursor) / dec.f_update))
        time.sleep(0.005)
    out.update(summary=dec.summary(), ahead=ahead, applied=rows)
    dec.close_logs()
    sub.close(0)


def main():
    fade_log = os.path.join(TMP, "fades.csv")
    srv = ChannelServer(scheme="weak", loop_mode="pingpong", verbose=False)
    srv.fade_log_path = fade_log
    srv.start(); time.sleep(0.4)
    rq = zmq.Context.instance().socket(zmq.REQ)
    rq.connect(CONTROL_REP_ENDPOINT); rq.setsockopt(zmq.RCVTIMEO, 2000)

    def cmd(d):
        rq.send_string(json.dumps(d)); return json.loads(rq.recv())

    cmd({"cmd": "set", "param": "wind_speed", "value": 1.0})
    stop = threading.Event(); out = {}
    th = threading.Thread(target=consumer, args=(stop, out)); th.start()
    time.sleep(1.0)
    t0 = time.time(); n_cmd = 0; pending = list(FADES)
    while time.time() - t0 < DURATION:
        t = time.time() - t0
        wind = 2.5 + 1.5 * np.sin(2 * np.pi * t / 8.0)       # 1..4 m/s
        cmd({"cmd": "set", "param": "wind_speed", "value": round(float(wind), 3)}); n_cmd += 1
        if pending and t >= pending[0][0]:
            _, dep, dur = pending.pop(0)
            cmd({"cmd": "fade", "depth_db": dep, "duration_s": dur})
        time.sleep(WIND_PERIOD)
    time.sleep(1.5)
    stop.set(); th.join(); srv.stop()

    print("=" * 72)
    print("verify_latency: %d live wind commands in %.0f s, %d fades" % (n_cmd, DURATION, len(FADES)))
    s = out["summary"]; ok = True
    lat = np.array([a for _, a in out["ahead"][200:]])          # after start-up
    first, last = lat[:len(lat) // 4], lat[-len(lat) // 4:]
    print("\n(a) buffered latency: max %.3f s, mean %.3f s; first-quarter mean %.3f s, "
          "last-quarter mean %.3f s" % (lat.max(), lat.mean(), first.mean(), last.mean()))
    a_ok = lat.max() < 0.3 and last.mean() < first.mean() + 0.05
    print("    bounded, no growth with wind commands: %s" % ("PASS" if a_ok else "FAIL"))
    ok &= a_ok
    print("\n(b) decoder summary: resyncs %s, gaps %s, latency_max %s s"
          % (s["resync_events"], s["gaps"], s["latency_max_s"]))
    b_ok = s["resync_events"] == 0 and s["gaps"] == 0
    print("    %s" % ("PASS" if b_ok else "FAIL")); ok &= b_ok

    ix = np.genfromtxt(os.environ["FSO_INDEX_LOG"], delimiter=",", names=True)
    gidx = dict(zip(ix["frame"].astype(int), ix["gain_index"]))
    app = [(gidx[k], v) for k, v in out["applied"] if k in gidx]
    G = np.array([a for a, _ in app]); V = np.array([v for _, v in app])
    print("\n(c) fades at the server-logged gain-index ranges:")
    if not os.path.exists(fade_log):
        print("    server wrote no fade log (--fade-log unsupported?) -> FAIL")
        print("\nSOME CHECKS FAILED"); print("=" * 72)
        raise SystemExit(1)
    fl = np.atleast_1d(np.genfromtxt(fade_log, delimiter=",", names=True))
    c_ok = len(fl) == len(FADES)
    for f in fl:
        a, b = f["seq_first"], f["seq_last"]; fac = 10 ** (-f["depth_db"] / 10)
        inside = (G >= a) & (G <= b - 1)
        outside = ((G > a - 300) & (G < a - 1)) | ((G > b + 1) & (G < b + 300))
        good = inside.any() and V[inside].max() < 1.3 * fac and V[outside].min() > 2 * fac
        c_ok &= bool(good)
        print("    %.0f dB, idx %d..%d: applied gain inside max %.3f (fade factor %.3f), "
              "neighbours min %.3f -> %s" % (f["depth_db"], a, b, V[inside].max() if inside.any() else np.nan,
                                              fac, V[outside].min(), "PASS" if good else "FAIL"))
    deep = V < 0.5                                     # weak turbulence never dips this low
    in_any = np.zeros(G.size, bool)
    for f in fl:
        in_any |= (G >= f["seq_first"] - 1) & (G <= f["seq_last"] + 1)
    stray = int((deep & ~in_any).sum())
    print("    deep gain outside any logged fade range: %d samples -> %s" % (stray, "PASS" if stray == 0 else "FAIL"))
    c_ok &= stray == 0
    ok &= c_ok
    print("\n%s" % ("ALL CHECKS PASS" if ok else "SOME CHECKS FAILED"))
    print("=" * 72)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
