# Validation

Staged acceptance tests, each traced to analytic theory. Every physical constant
is either traced to a primary reference or explicitly flagged — see
[`LEDGER.md`](LEDGER.md) for the full record and the flagged-coefficient list.

All scripts import the physics modules from `../fso_twin`, so run them with that
directory on the path:

```bash
cd validation
PYTHONPATH=../fso_twin python3 verify_screens.py
PYTHONPATH=../fso_twin python3 verify_rytov.py
PYTHONPATH=../fso_twin python3 verify_aperture.py
PYTHONPATH=../fso_twin python3 verify_wind.py
PYTHONPATH=../fso_twin python3 verify_latency.py
PYTHONPATH=../fso_twin python3 sweep_strong.py --probe   # then --sweep
```

| Script | Stage | Checks | Expected result |
|---|---|---|---|
| `verify_screens.py` | 1 | phase-screen structure function vs von Kármán / Kolmogorov theory | 1.55 % mean error (resolvable L₀); documented large-scale deficit in the Kolmogorov limit |
| `verify_rytov.py` | 2 | split-step scintillation vs Rytov variance (the hard gate) | within ~1 % for 5/10/20 screens; mean intensity preserved |
| `verify_aperture.py` | 3 | aperture integration → scalar gain h | clear-air h = 1 exactly; aperture averaging as D grows |
| `verify_wind.py` | 6 | live wind tuning = time-resampling (end-to-end ZMQ) | rate halves exactly; zero value difference; linear ≠ ZOH |
| `verify_latency.py` | 6 | delivery latency under live wind changes (160 commands in 40 s) + injected fades, through the GNU Radio block's decoder | latency bounded (no growth), 0 resyncs / gaps, each fade applied exactly at its server-logged gain-index range |
| `sweep_strong.py` + `gamma_gamma.py` | 7 | strong-regime split-step vs Gamma-Gamma theory | agreement to σ_R² ≈ 0.3, then a bounded departure (the validity envelope) |

**Stage 4** (frozen-flow ergodicity) was verified against the retired multi-trace
API; its result (temporal vs spatial σ_I² within a few per cent) is recorded in
[`LEDGER.md`](LEDGER.md) §4.5.

`strong_sweep.json` is the cached Stage-7 sweep output (the data behind the
validity-envelope figure in the paper).

## The validity envelope in one line

Only the **weak** preset (σ_R² ≈ 0.13) is quantitatively validated (matches Rytov
to ~1 %). **Moderate** and **strong** are physically plausible but **not
quantitatively validated** — the split-step propagator diverges from strong-
fluctuation theory beyond σ_R² ≈ 0.3, exactly where weak-fluctuation theory
itself stops applying. The code carries this status in the server metadata, the
GUI banner, and every recorded file, so an unverified regime is never mistaken
for a validated one.
