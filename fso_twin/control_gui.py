"""
control_gui.py -- control + telemetry GUI for the simplified single-r0 server.

ONE turbulence scheme per run (chosen at server startup, shown here, not
selectable). The only live turbulence control is WIND SPEED (an input box, not a
slider), plus the cheap attenuation / gain_scale multipliers, and the RX AWGN
noise voltage of the modem's noise source (sent to the modem's XML-RPC server
on :50006, NOT to the channel server -- receiver noise is a modem property,
not a channel property). A persistent
validation banner makes the unverified regimes unmistakable. The phase screen is
a colour map with the FIXED 75 mm aperture overlaid; as frozen flow advects, the
screen slides under the fixed aperture circle. Greenwood frequency is a live
DERIVED readout (flagged approximate), not a control.

Robustness:
  * each control request uses a FRESH short-lived REQ socket, so rapid edits can
    never desync a shared REQ/REP socket (the cause of "attenuation/gain stop
    working after changing wind");
  * a _closing guard + timer-stop-before-socket-close means closing this window
    never throws (so closing either UI shuts the app down cleanly).

WIND INVARIANT: wind changes f_update_eff (the rate), not the h(t) VALUES.

Run (after server.py is up):  python3 control_gui.py
Environment: PyQt5 + pyqtgraph + pyzmq + aotools, numpy < 2.
"""

import argparse
import json
import time
import xmlrpc.client

import numpy as np
import zmq

from PyQt5 import QtCore, QtWidgets
import pyqtgraph as pg

from fso_stream_proto import unpack_message
from screens import generate_screen, KOLMOGOROV_L0, KOLMOGOROV_l0

GAIN_SUB_ENDPOINT = "tcp://127.0.0.1:50003"
CONTROL_REQ_ENDPOINT = "tcp://127.0.0.1:50004"
MODEM_XMLRPC_ENDPOINT = "http://127.0.0.1:50006"   # modem_full.py XML-RPC server
NOISE_AMP_DEFAULT = 0.007                          # modem --noise-amp default
GAIN_PLOT_SAMPLES = 3000
VIZ_GAIN = 2.5     # screen-drift visual gain (px per s per m/s of wind)
_VIRIDIS = [(0.0, (68, 1, 84)), (0.25, (59, 82, 139)), (0.5, (33, 145, 140)),
            (0.75, (94, 201, 98)), (1.0, (253, 231, 37))]


class _TimeoutTransport(xmlrpc.client.Transport):
    """xmlrpc transport with a per-connection socket timeout, so a wedged
    modem can never freeze the GUI (mirrors the 1 s ZMQ RCVTIMEO)."""

    def __init__(self, timeout):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class FsoControlGui(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FSO Channel — single-r0 control & telemetry")
        self._ctx = zmq.Context.instance()
        self._closing = False
        self._sub = self._ctx.socket(zmq.SUB)
        self._sub.connect(GAIN_SUB_ENDPOINT)
        self._sub.setsockopt(zmq.SUBSCRIBE, b"")
        self._sub.setsockopt(zmq.LINGER, 0)

        self.gain_buf = np.full(GAIN_PLOT_SAMPLES, np.nan)
        self.f_update_eff = None
        self.cur_wind = 20.0
        self.viz_base = None          # the single screen (regenerated from status)
        self.viz_disp = 0.0           # accumulated drift [px]; integral of wind*dt
        self.viz_last_t = time.monotonic()
        self._scheme_shown = None
        self._noise_synced = False    # spin box adopted the modem's live value

        self._build_ui()
        self.tel_timer = QtCore.QTimer(self); self.tel_timer.timeout.connect(self._update_telemetry); self.tel_timer.start(50)
        self.status_timer = QtCore.QTimer(self); self.status_timer.timeout.connect(self._poll_status); self.status_timer.start(500)
        self.viz_timer = QtCore.QTimer(self); self.viz_timer.timeout.connect(self._update_screen); self.viz_timer.start(50)
        self._poll_status()

    # ---- zmq control: a fresh REQ per request (no shared-socket desync) ----
    def _send(self, req):
        if self._closing:
            return None
        s = self._ctx.socket(zmq.REQ)
        s.setsockopt(zmq.RCVTIMEO, 1000)
        s.setsockopt(zmq.SNDTIMEO, 1000)
        s.setsockopt(zmq.LINGER, 0)
        s.connect(CONTROL_REQ_ENDPOINT)
        try:
            s.send_string(json.dumps(req))
            return json.loads(s.recv_string())
        except Exception:
            return None
        finally:
            s.close(0)

    # ---- modem XML-RPC: a fresh short-timeout proxy per call ------------
    def _modem_call(self, method, *args):
        """Call a modem_full.py XML-RPC method (e.g. set_noise_amp). Returns
        (ok, value); ok=False means the modem is not reachable. A fresh proxy
        per call, same rationale as the fresh REQ sockets above."""
        if self._closing:
            return False, None
        try:
            proxy = xmlrpc.client.ServerProxy(
                MODEM_XMLRPC_ENDPOINT, transport=_TimeoutTransport(1.0),
                allow_none=True)
            return True, getattr(proxy, method)(*args)
        except Exception:
            return False, None

    # ---- UI -----------------------------------------------------------
    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        self.banner = QtWidgets.QLabel("connecting…")
        self.banner.setAlignment(QtCore.Qt.AlignCenter)
        self.banner.setStyleSheet("padding:6px; font-weight:bold;")
        outer.addWidget(self.banner)
        root = QtWidgets.QHBoxLayout(); outer.addLayout(root, 1)
        left = QtWidgets.QVBoxLayout(); root.addLayout(left, 0)

        gb_s = QtWidgets.QGroupBox("Turbulence scheme (fixed at startup)")
        fs = QtWidgets.QVBoxLayout(gb_s)
        self.scheme_label = QtWidgets.QLabel("connecting…"); self.scheme_label.setWordWrap(True)
        self.valid_label = QtWidgets.QLabel("-"); self.valid_label.setWordWrap(True)
        fs.addWidget(self.scheme_label); fs.addWidget(self.valid_label)
        left.addWidget(gb_s)

        gb = QtWidgets.QGroupBox("Live controls")
        g = QtWidgets.QGridLayout(gb)
        # Wind: an input box (spin box) -- precise, not finicky like a slider.
        g.addWidget(QtWidgets.QLabel("Wind speed [m/s]"), 0, 0)
        self.wind_box = QtWidgets.QDoubleSpinBox()
        self.wind_box.setRange(0.5, 20.0); self.wind_box.setSingleStep(0.5)
        self.wind_box.setDecimals(1); self.wind_box.setValue(20.0)
        self.wind_box.setKeyboardTracking(False)   # emit once per committed value
        self.wind_box.valueChanged.connect(self._on_wind)
        g.addWidget(self.wind_box, 0, 1, 1, 2)
        g.addWidget(QtWidgets.QLabel("Attenuation (weather)"), 1, 0)
        self.atten_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.atten_slider.setRange(1, 1000); self.atten_slider.setValue(1000)
        self.atten_slider.valueChanged.connect(self._on_atten)
        g.addWidget(self.atten_slider, 1, 1); self.atten_val = QtWidgets.QLabel("1.000"); g.addWidget(self.atten_val, 1, 2)
        g.addWidget(QtWidgets.QLabel("Gain scale"), 2, 0)
        self.gain_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.gain_slider.setRange(10, 1000); self.gain_slider.setValue(100)
        self.gain_slider.valueChanged.connect(self._on_gain)
        g.addWidget(self.gain_slider, 2, 1); self.gain_val = QtWidgets.QLabel("1.00"); g.addWidget(self.gain_val, 2, 2)
        # RX AWGN noise voltage: amplitude of the modem's Gaussian noise
        # source (receiver-side, applied AFTER the channel gain). Goes to the
        # modem's XML-RPC server, not to the channel server.
        g.addWidget(QtWidgets.QLabel("RX AWGN noise voltage"), 3, 0)
        self.noise_box = QtWidgets.QDoubleSpinBox()
        self.noise_box.setRange(0.0, 1.0); self.noise_box.setDecimals(4)
        self.noise_box.setSingleStep(0.001); self.noise_box.setValue(NOISE_AMP_DEFAULT)
        self.noise_box.setKeyboardTracking(False)  # emit once per committed value
        self.noise_box.valueChanged.connect(self._on_noise)
        g.addWidget(self.noise_box, 3, 1)
        self.noise_state = QtWidgets.QLabel("no modem")
        self.noise_state.setStyleSheet("color: gray;")
        g.addWidget(self.noise_state, 3, 2)
        left.addWidget(gb)

        gbf = QtWidgets.QGroupBox("Deep-fade injection (explicit test fade — NOT turbulence)")
        gf = QtWidgets.QGridLayout(gbf)
        gf.addWidget(QtWidgets.QLabel("Depth [dB]"), 0, 0)
        self.fade_depth = QtWidgets.QDoubleSpinBox()
        self.fade_depth.setRange(1.0, 60.0); self.fade_depth.setSingleStep(1.0); self.fade_depth.setValue(20.0)
        gf.addWidget(self.fade_depth, 0, 1)
        gf.addWidget(QtWidgets.QLabel("Duration [s]"), 1, 0)
        self.fade_dur = QtWidgets.QDoubleSpinBox()
        self.fade_dur.setRange(0.01, 60.0); self.fade_dur.setDecimals(2); self.fade_dur.setSingleStep(0.1); self.fade_dur.setValue(0.5)
        gf.addWidget(self.fade_dur, 1, 1)
        self.fade_btn = QtWidgets.QPushButton("Trigger deep fade")
        self.fade_btn.clicked.connect(self._on_fade)
        gf.addWidget(self.fade_btn, 2, 0, 1, 2)
        left.addWidget(gbf)

        gb_t = QtWidgets.QGroupBox("Telemetry")
        f = QtWidgets.QFormLayout(gb_t)
        self.lbl_conn = QtWidgets.QLabel("connecting…")
        self.lbl_gain = QtWidgets.QLabel("-")
        self.lbl_sigma = QtWidgets.QLabel("-")
        self.lbl_feff = QtWidgets.QLabel("-")
        self.lbl_fstored = QtWidgets.QLabel("-")
        self.lbl_wind = QtWidgets.QLabel("-")
        self.lbl_tau0 = QtWidgets.QLabel("-")
        self.lbl_fg = QtWidgets.QLabel("-")
        self.lbl_fade = QtWidgets.QLabel("idle")
        f.addRow("connection", self.lbl_conn)
        f.addRow("current gain h", self.lbl_gain)
        f.addRow("sigma_I^2 (live)", self.lbl_sigma)
        f.addRow("f_update_eff [Hz]", self.lbl_feff)
        f.addRow("f_update_stored [Hz]", self.lbl_fstored)
        f.addRow("server wind [m/s]", self.lbl_wind)
        f.addRow("tau0 (Greenwood) [ms]", self.lbl_tau0)
        f.addRow("Greenwood freq [Hz]", self.lbl_fg)
        f.addRow("injected fade", self.lbl_fade)
        left.addWidget(gb_t)
        self.fg_note = QtWidgets.QLabel("Greenwood freq = 1/tau0 (APPROX — "
            "proportionality coefficient TO-CONFIRM from print). tau0 uses the "
            "0.32 coefficient (also flagged).")
        self.fg_note.setWordWrap(True); self.fg_note.setStyleSheet("color: gray;")
        left.addWidget(self.fg_note)
        left.addWidget(QtWidgets.QLabel("Wind re-times the stream "
            "(f_update_eff); it does NOT change the h(t) values."))
        left.addStretch(1)

        right = QtWidgets.QVBoxLayout(); root.addLayout(right, 1)
        self.gain_plot = pg.PlotWidget(title="Streamed gain h(t) (as applied)")
        self.gain_plot.setLabel("left", "gain h"); self.gain_plot.setLabel("bottom", "recent samples")
        self.gain_plot.showGrid(x=True, y=True, alpha=0.3)
        self.gain_curve = self.gain_plot.plot(pen=pg.mkPen("y", width=1))
        right.addWidget(self.gain_plot, 1)

        scr = QtWidgets.QGroupBox("Phase screen (live) — fixed 75 mm aperture "
                                  "overlaid at the measured patch")
        sv = QtWidgets.QVBoxLayout(scr)
        self._glw = pg.GraphicsLayoutWidget()
        self._vb = self._glw.addViewBox(lockAspect=True)
        self.screen_img = pg.ImageItem(); self._vb.addItem(self.screen_img)
        self.aperture_curve = pg.PlotDataItem(pen=pg.mkPen("r", width=2))
        self._vb.addItem(self.aperture_curve)
        self._hist = pg.HistogramLUTItem(image=self.screen_img)
        self._hist.gradient.restoreState({"mode": "rgb",
            "ticks": [(p, (r, g, b, 255)) for p, (r, g, b) in _VIRIDIS]})
        self._hist.axis.setLabel("phase [rad]")
        self._glw.addItem(self._hist)
        sv.addWidget(self._glw)
        self.screen_caption = QtWidgets.QLabel("-"); self.screen_caption.setWordWrap(True)
        sv.addWidget(self.screen_caption)
        right.addWidget(scr, 1)
        self.resize(1180, 860)

    # ---- screen (regenerated from server's r0/seed/grid) --------------
    def _ensure_screen(self, st):
        if self.viz_base is not None and st["scheme"] == self._scheme_shown:
            return
        try:
            base = generate_screen(st["r0_m"], st["N"], st["delta"],
                                   KOLMOGOROV_L0, KOLMOGOROV_l0,
                                   seed=st["screen_seed"])
        except Exception as e:
            self.screen_caption.setText("screen view unavailable: %s" % e)
            return
        self.viz_base = base
        self._scheme_shown = st["scheme"]
        self.viz_disp = 0.0; self.viz_last_t = time.monotonic()
        s = 3.0 * float(base.std()); self._hist.setLevels(-s, s)
        N, delta, D = st["N"], st["delta"], st["aperture_D"]
        rad_px = (D / 2.0) / delta
        th = np.linspace(0, 2 * np.pi, 180)
        self.aperture_curve.setData(N / 2.0 + rad_px * np.cos(th),
                                    N / 2.0 + rad_px * np.sin(th))
        self.screen_caption.setText(
            "Kolmogorov screen, r0=%.1f cm, %d×%d @ %.0f mm/px. Red circle = "
            "%.0f mm aperture footprint (fixed); screen advects under it at the "
            "wind speed. This IS the screen behind h(t)."
            % (st["r0_m"] * 100, N, N, delta * 1e3, D * 1e3))

    def _update_screen(self):
        if self._closing or self.viz_base is None:
            return
        # Accumulate drift = integral of wind*dt. A wind change alters only the
        # future rate, never retro-shifts the screen.
        now = time.monotonic()
        self.viz_disp += self.cur_wind * (now - self.viz_last_t) * VIZ_GAIN
        self.viz_last_t = now
        N = self.viz_base.shape[0]
        self.screen_img.setImage(
            np.roll(self.viz_base, int(self.viz_disp) % N, axis=0),
            autoLevels=False)

    # ---- controls -----------------------------------------------------
    def _on_wind(self, v):
        self.cur_wind = float(v)
        self._send({"cmd": "set", "param": "wind_speed", "value": self.cur_wind})

    def _on_atten(self, v):
        val = v / 1000.0; self.atten_val.setText("%.3f" % val)
        self._send({"cmd": "set", "param": "attenuation", "value": val})

    def _on_gain(self, v):
        val = v / 100.0; self.gain_val.setText("%.2f" % val)
        r = self._send({"cmd": "set", "param": "gain_scale", "value": val})
        self.gain_val.setStyleSheet("color: orange;" if r and r.get("warning") else "")

    def _on_noise(self, v):
        ok, _ = self._modem_call("set_noise_amp", float(v))
        if ok:
            self.noise_state.setText("applied")
            self.noise_state.setStyleSheet("color: green;")
        else:
            self.noise_state.setText("no modem")
            self.noise_state.setStyleSheet("color: red;")
            self._noise_synced = False   # re-adopt the modem value on reconnect

    def _on_fade(self):
        d = float(self.fade_depth.value()); dur = float(self.fade_dur.value())
        self._send({"cmd": "fade", "depth_db": d, "duration_s": dur})
        self.lbl_fade.setText("ACTIVE: -%.1f dB (%.2f s)" % (d, dur))  # instant feedback
        self.lbl_fade.setStyleSheet("color: red; font-weight: bold;")

    # ---- telemetry ----------------------------------------------------
    def _update_telemetry(self):
        if self._closing:
            return
        got = False
        while True:
            try:
                raw = self._sub.recv(zmq.NOBLOCK)
            except zmq.Again:
                break
            except zmq.ZMQError:
                return
            try:
                msg = unpack_message(raw)
            except ValueError:
                continue
            got = True
            self.f_update_eff = msg["f_update"]
            g = msg["gains"]; k = min(g.size, GAIN_PLOT_SAMPLES)
            self.gain_buf = np.roll(self.gain_buf, -k); self.gain_buf[-k:] = g[-k:]
        if got:
            self.lbl_conn.setText("streaming"); self.lbl_conn.setStyleSheet("color: green;")
            valid = self.gain_buf[~np.isnan(self.gain_buf)]
            if valid.size:
                self.gain_curve.setData(valid)
                self.lbl_gain.setText("%.4f" % valid[-1])
                if valid.size > 5 and valid.mean() != 0:
                    self.lbl_sigma.setText("%.4f" % (valid.var() / valid.mean() ** 2))
            if self.f_update_eff:
                self.lbl_feff.setText("%.1f" % self.f_update_eff)

    def _poll_status(self):
        if self._closing:
            return
        # Adopt the modem's live noise_amp once (it may have been launched
        # with --noise-amp). Independent of the channel server, so it runs
        # before the server early-return; connection-refused is instant on
        # localhost, so an absent modem does not stall this 500 ms poll.
        if not self._noise_synced:
            ok, v = self._modem_call("get_noise_amp")
            if ok and v is not None:
                self._noise_synced = True
                self.noise_box.blockSignals(True)
                self.noise_box.setValue(float(v))
                self.noise_box.blockSignals(False)
                self.noise_state.setText("linked")
                self.noise_state.setStyleSheet("color: green;")
        st = self._send({"cmd": "status"})
        if not st or not st.get("ok"):
            self.lbl_conn.setText("no server"); self.lbl_conn.setStyleSheet("color: red;")
            return
        self._ensure_screen(st)
        self.scheme_label.setText("scheme: %s   Cn2=%.1e   r0=%.1f cm   "
            "sigma_R^2=%.3f" % (st["scheme"], st["cn2"], st["r0_m"] * 100,
                                st["sigma_R2"]))
        self.valid_label.setText("validation: %s" % st["validation_status"])
        self.valid_label.setStyleSheet(
            "color: green;" if st["validated"] else "color: orange;")
        if st["validated"]:
            self.banner.setText("✓  Rytov-VALIDATED regime (weak) — "
                                "scintillation matches the plane-wave Rytov target")
            self.banner.setStyleSheet("padding:6px; font-weight:bold; "
                                      "background-color:#1b5e20; color:white;")
        else:
            self.banner.setText("⚠  %s  —  PHYSICALLY-PLAUSIBLE-BUT-UNVERIFIED: "
                                "strong-fluctuation propagation NOT validated; "
                                "values are NOT quantitatively trustworthy"
                                % st["scheme"].upper())
            self.banner.setStyleSheet("padding:6px; font-weight:bold; "
                                      "background-color:#b71c1c; color:white;")
        self.lbl_fstored.setText("%.1f" % st["f_update_stored"])
        self.lbl_wind.setText("%.1f" % st["wind_speed"])
        self.lbl_tau0.setText("%.3f" % (st["tau0_s"] * 1e3))
        self.lbl_fg.setText("%.1f  (approx)" % st["greenwood_freq_hz"])
        if st.get("fade_active"):
            self.lbl_fade.setText("ACTIVE: -%.1f dB (%.2f s left)"
                                  % (st["fade_depth_db"], st["fade_remaining_s"]))
            self.lbl_fade.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.lbl_fade.setText("idle"); self.lbl_fade.setStyleSheet("")
        if st.get("f_update_effective"):
            self.lbl_feff.setText("%.1f" % st["f_update_effective"])

    def closeEvent(self, event):
        # Stop timers and guard callbacks BEFORE closing sockets, so no queued
        # timer event touches a closed socket (clean shutdown, no traceback).
        self._closing = True
        for t in (self.tel_timer, self.status_timer, self.viz_timer):
            t.stop()
        self._sub.close(0)
        event.accept()


def main():
    argparse.ArgumentParser(description="Simplified FSO control GUI").parse_args()
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(True)
    gui = FsoControlGui(); gui.show()
    app.exec_()


if __name__ == "__main__":
    main()
