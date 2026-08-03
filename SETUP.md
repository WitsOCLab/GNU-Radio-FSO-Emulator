# Setup & Integration Guide

How to install the FSO Turbulence Twin and wire it into your own program. There
are three integration paths — pick the one that matches your setup:

- **[A. Wire protocol](#a-wire-protocol-any-language)** — any language, over ZMQ.
- **[B. Python import](#b-python-import)** — call the physics/server directly.
- **[C. GNU Radio block](#c-gnu-radio-block)** — drop into a flowgraph.

---

## 1. Prerequisites

- **Python 3.6+** (developed on 3.8).
- **numpy < 2** — AOtools 1.0.7 and this code assume the numpy 1.x API. This is
  the single most common install pitfall; keep numpy pinned below 2.
- Linux/macOS recommended (Windows works for the library; the GNU Radio and TUN
  paths are Linux-oriented).

## 2. Installation

```bash
git clone <your-repo-url> fso-turbulence-twin
cd fso-turbulence-twin
python3 -m venv .venv && source .venv/bin/activate     # optional but recommended
pip install -r requirements.txt
```

Core dependencies (`numpy<2`, `scipy`, `aotools==1.0.7`, `pyzmq`) give you the
server, the wire protocol, the physics, and the examples.

**Optional extras:**

```bash
pip install PyQt5 pyqtgraph      # the control/telemetry GUI
pip install matplotlib           # plotting in examples / validation
# GNU Radio 3.8+ is a SYSTEM package, not pip:
sudo apt install gnuradio        # only needed for the embedded channel block
```

**Verify the install** (no server, no network — just the physics):

```bash
python3 examples/offline_trace.py --scheme weak
# -> prints r0, sigma_R^2, and gain statistics for a generated trace
```

## 3. Running the channel server

```bash
./examples/run_server.sh                  # weak scheme, server only
SCHEME=moderate ./examples/run_server.sh  # weak | moderate | strong
GUI=1 ./examples/run_server.sh            # also launch the Qt GUI
```

or directly:

```bash
cd fso_twin && python3 server.py --scheme weak --seed 20240
```

The server binds two ports on localhost:

| Port | Socket | Purpose |
|---|---|---|
| `50003` | ZMQ **PUB** | gain stream (framed binary, see below) |
| `50004` | ZMQ **REP** | control (JSON request/reply) |

It generates the reference trace at start-up (~4 s weak, ~12 s strong), then
streams continuously, publishing ~0.25 s ahead of real time.

---

## A. Wire protocol (any language)

Subscribe to `tcp://127.0.0.1:50003` and parse each message. This is the most
portable path — no Python dependency on this repo at all.

**Message layout** (little-endian, one ZMQ message per publish):

| Field | Type | Meaning |
|---|---|---|
| magic | `4s` | `b"FSOG"` |
| version | `B` | protocol version (1) |
| flags | `B` | bit0 = TRACE_CHANGED, bit1 = LOOPED |
| epoch | `H` | increments on a discrete trace change |
| seq_start | `Q` | absolute sample index of the first gain sample |
| f_update | `d` | update rate [Hz] of the gain samples in this message |
| n | `I` | number of gain samples that follow |
| payload | `n × f4` | `n` float32 gain values (already ≥ 0) |

Reference implementation (pack/unpack + rationale for every field):
[`fso_twin/fso_stream_proto.py`](fso_twin/fso_stream_proto.py). Compare
`seq_start` against the index you expect to detect dropped messages; reset your
interpolation continuity on an `epoch` change; treat a `LOOPED` flag as a
finite-trace wrap, not a real discontinuity.

**To apply the gain**, upsample from `f_update` to your signal rate by **linear
interpolation** (never a zero-order hold), then multiply:

```python
R = signal_sample_rate / f_update            # signal samples per gain sample
pos = cursor + np.arange(n_out) / R
h_fast = np.interp(pos, np.arange(gain_buf.size), gain_buf)
y = x[:h_fast.size] * h_fast                 # y[n] = h(t_n) * x[n]
```

See [`examples/minimal_subscriber.py`](examples/minimal_subscriber.py) for a
complete ~20-line consumer, including sending control commands.

---

## B. Python import

Add `fso_twin/` to your path and import what you need.

```python
import sys; sys.path.insert(0, "path/to/fso-turbulence-twin/fso_twin")
```

**Just a trace (no server):**

```python
from traces import make_reference_trace
ref = make_reference_trace("weak", seed=20240)
h = ref["h"]                 # gain samples at ref["f_update"], sampled at v_max
# metadata: ref["r0"], ref["sigma_R2"], ref["validated"], ref["cn2"], ...
```

**Run the server in-process:**

```python
from server import ChannelServer
srv = ChannelServer(scheme="weak", loop_mode="pingpong")
srv.start()      # binds :50003/:50004 in background threads
# ... your consumer runs ...
srv.stop()
```

**Key modules:** `screens` (phase screens), `propagation` (split-step +
Rytov/Fried helpers), `receiver` (aperture integration), `traces` (frozen-flow
trace + presets), `server` (streaming + wind retiming), `fso_stream_proto`
(protocol). For clean namespacing you can also copy `fso_twin/` into your own
project as a package.

---

## C. GNU Radio block

`gnuradio/epy_fso_channel.py` is an Embedded Python Block. Instantiate it as a
complex-in / complex-out block and point it at the stream:

```python
from epy_fso_channel import blk as FsoChannel
fso = FsoChannel(gain_endpoint="tcp://127.0.0.1:50003", sample_rate=30.72e6)
self.connect(tx_chain, fso, rx_chain)     # y = h * x
```

Start the server before running the graph. A complete minimal flowgraph
(sine → throttle → channel → file sink) is in
[`gnuradio/example_flowgraph.py`](gnuradio/example_flowgraph.py); see
[`gnuradio/README.md`](gnuradio/README.md) for GRC usage. The block never blocks
the scheduler, upsamples by linear interpolation, and prints a summary of any
dropped/looped/starved events when the flowgraph stops.

---

## SNR convention (important if you label data)

The channel multiplies the **complex amplitude** by `h`, and if you add
signal-independent AWGN afterwards (`y = h·x + w`), the received electrical SNR
scales as `h²`:

```
SNR_dB = 20·log10(h) + offset
```

Use **`20·log10(h)`**, not `10·log10(h)`. (`10·log10` would only apply if you
instead scaled the *power* by `h`, e.g. `y = sqrt(h)·x`.) Choose `offset` so that
clear air (`h = 1`) sits at your nominal operating SNR — high enough for your
top MCS to be reachable in clear air.

---

## Control protocol reference

JSON over the REP socket (`tcp://127.0.0.1:50004`). Each request gets one reply.

| Command | Effect |
|---|---|
| `{"cmd":"status"}` | full state: scheme, r0, σ_R², wind, f_update, validation, Greenwood |
| `{"cmd":"set","param":"wind_speed","value":8.0}` | live wind [m/s], (0.5, 20]; pure time-resampling |
| `{"cmd":"set","param":"attenuation","value":0.5}` | weather loss factor (0, 1] |
| `{"cmd":"set","param":"gain_scale","value":2.0}` | overall gain multiplier (> 0) |
| `{"cmd":"fade","depth_db":20,"duration_s":0.5}` | inject a deterministic deep fade (labelled, not turbulence) |
| `{"cmd":"ping"}` | liveness check |

Wind above `v_max` (20 m/s) is clamped with a warning; published gain is always
asserted ≥ 0.

## Recording data

```bash
cd fso_twin && python3 recorder.py --out run.csv --seconds 30
```

Writes `recv_time_s, seq, h, f_update_eff_hz` beneath a metadata header that
carries the scheme's **validation status**, and prints a deep-fade summary on
stop. (Reads the same stream; the CHANNEL gain, not link-side BER.)

## Configuration

Fixed link/grid constants live at the top of
[`fso_twin/traces.py`](fso_twin/traces.py): `L = 800 m`, `WAVELENGTH = 1550 nm`,
`APERTURE_D = 75 mm`, `GRID_N = 512`, `GRID_DELTA = 2 mm`, `V_MAX = 20 m/s`,
`DEFAULT_SEED = 20240`, and the three `PRESETS` (weak/moderate/strong Cn²).

## Troubleshooting

- **`ImportError: numpy.core.multiarray failed` / AOtools errors** — you have
  numpy ≥ 2. `pip install "numpy<2"`.
- **`Address already in use` on 50003/50004** — a previous server is still up:
  `pkill -f server.py`, or wait a few seconds for the socket to free.
- **Consumer prints "no server"** — start the server first; check nothing else
  binds those ports.
- **GUI won't start** — needs `PyQt5` + `pyqtgraph` and a display (`DISPLAY`
  set). The server and consumers run fine headless without it.
- **`[fso-zmq] STARVED` in the GNU Radio block** — the consumer is pulling
  faster than real time (e.g. no throttle/USRP pacing the flowgraph). Add a
  throttle at the signal rate, or run against hardware.
- **Only `weak` gives trustworthy numbers** — by design. See the validity
  envelope note in the README and `validation/`.
