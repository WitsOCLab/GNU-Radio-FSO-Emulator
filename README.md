# FSO Turbulence Twin

A real-time, physics-based **free-space optical (FSO) turbulence channel**
emulator for software-defined radio and link-simulation research. It produces a
single time-varying power gain `h(t)` that you multiply onto your complex
baseband — `y[n] = h(t_n)·x[n]` — and streams it live over a small, integrity-
checked protocol so you can drop it into your own simulator or a GNU Radio
flowgraph.

A Kolmogorov phase screen is advected across a receive aperture under the Taylor
frozen-flow hypothesis, propagated by a split-step angular-spectrum method, and
aperture-integrated to `h = P_turb / P_clear`. Wind speed is a **live control**
implemented as pure time-axis rescaling (no physics regeneration), and the
quantitative **validity envelope** is carried as machine-readable status so an
unverified regime can never be mistaken for a validated one.

> **New here?** Read [`SETUP.md`](SETUP.md) for installation and the three ways
> to integrate this into your own program.

## Why

Turbulent FSO channels are not repeatable outdoors, and hardware emulators are
expensive and hard to couple to an SDR stack. This gives you a physically
grounded, repeatable-by-construction channel that runs in pure software and sits
inside a live protocol stack — so two link-adaptation controllers can be
compared on *identical* channel realisations.

## Features

- **Wave-optics physics**, not a parametric fading distribution: AOtools FFT
  phase screen → split-step propagation → aperture integration.
- **Live streaming** over ZMQ (PUB gain, REP control) with a framed binary
  protocol that makes every discontinuity (drop, trace change, loop seam)
  detectable instead of silent.
- **Live wind tuning** as a provable time-resampling identity: same fade values,
  different rate.
- **Operator multipliers**: weather attenuation, gain scale, and deterministic
  injected deep fades for stress-testing.
- **Validated stage by stage** against analytic theory (see `validation/`), with
  the validity envelope enforced in code.
- Optional **Qt GUI** (live `h(t)`, phase-screen view with aperture overlay,
  telemetry, validation banner) and a **CSV recorder**.

## Quickstart

```bash
pip install -r requirements.txt

# 1) start the channel server (weak scheme), no GUI, no hardware
./examples/run_server.sh

# 2a) in another terminal: consume the stream with ~20 lines of Python
python3 examples/minimal_subscriber.py --seconds 5 --wind 8

# 2b) or skip the server entirely and just generate a trace offline
python3 examples/offline_trace.py --scheme moderate --csv trace.csv
```

## Three ways to integrate

1. **Wire protocol (any language):** run the server, subscribe to the gain
   stream on `tcp://127.0.0.1:50003`, parse frames per `fso_twin/fso_stream_proto.py`.
2. **Python import:** `from traces import make_reference_trace` or
   `from server import ChannelServer` (add `fso_twin/` to your path).
3. **GNU Radio block:** drop `gnuradio/epy_fso_channel.py` into a Python Block
   and point it at the stream.

Full details and a control-command reference are in [`SETUP.md`](SETUP.md).

## Validity envelope (read before trusting numbers)

Only the **weak** preset (σ_R² ≈ 0.13) is quantitatively validated (matches
Rytov scintillation to ~1 %). **Moderate** and **strong** are physically
plausible but **not quantitatively validated** — the propagator diverges from
strong-fluctuation theory beyond σ_R² ≈ 0.3, which is where weak-fluctuation
theory itself stops applying. This status travels with the server metadata, the
GUI banner, and every recorded file. See [`PROCESS.md`](PROCESS.md) and
[`validation/`](validation/).

## Repository layout

```
fso_twin/      core library: physics + server + protocol + GUI + recorder
gnuradio/      GNU Radio embedded channel block + a minimal example flowgraph
examples/      run the server, a pure-Python subscriber, offline trace generation
validation/    staged acceptance tests + the equation ledger
PROCESS.md     slim equation ledger for the shipped configuration
SETUP.md       installation + integration guide
```

## Configuration (defaults)

L = 800 m, λ = 1550 nm, aperture D = 75 mm, grid N = 512 at δ = 2 mm,
v_max = 20 m/s. These live in `fso_twin/traces.py`.

## Citing

If you use this in academic work, please cite the accompanying paper (details to
be added on publication) and this repository.

## License

MIT (see [`LICENSE`](LICENSE) — fill in the copyright holder/year before
publishing). Dependencies (AOtools, GNU Radio, …) carry their own licenses.
