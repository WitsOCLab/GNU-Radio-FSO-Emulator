# PROCESS — simplified single-screen FSO channel (equation ledger)

Slim ledger for the simplified rebuild. Every constant is traced to a primary
reference or **flagged TO-CONFIRM**. No reference numbers invented.
Reference key **[AP]** = Andrews & Phillips, *Laser Beam Propagation through
Random Media*, 2nd ed., SPIE, 2005.

## Fixed configuration
L = 800 m (folded path, single-pass equivalent); λ = 1550 nm; k = 2π/λ;
receive aperture D = 75 mm; grid N = 512, δ = 2 mm; v_max = 20 m/s.

## Three preset schemes (chosen at startup, not live)
| scheme | Cn² | σ_R² | status |
|---|---|---|---|
| weak | 1e-14 | 0.132 | **Rytov-VALIDATED** (single screen sim/Rytov ≈ 1.01) |
| moderate | 5e-14 | 0.661 | PHYSICALLY-PLAUSIBLE-BUT-UNVERIFIED (divergence zone) |
| strong | 3e-13 | 3.967 | PHYSICALLY-PLAUSIBLE-BUT-UNVERIFIED (Gamma-Gamma check FAILED) |

**Validation caveat (carried in code + server status + here):** only the weak
scheme is on validated propagation. Moderate sits in the divergence zone; strong
is where the earlier Gamma-Gamma check FAILED (the split-step overshoots and does
not saturate scintillation). This rebuild does NOT fix strong-regime propagation.

## Constants
| Quantity | Expression | Source | Status |
|---|---|---|---|
| Fried parameter | r0 = (0.42 k² Cn² L)^(−3/5) | [AP] Ch.14 eq.25/95 | **VERIFIED** (project lead) |
| Rytov variance | σ_R² = 1.23 Cn² k^(7/6) L^(11/6) | [AP] weak-fluctuation theory | **FLAG**: chapter/eq TO-CONFIRM; 1.23 not independently traced |
| Coherence (Greenwood) time | τ0 = 0.32 r0 / v | [AP] Ch.14 eq.39 | **FLAG**: 0.32 TO-CONFIRM from print |
| Greenwood frequency | f_G = 1/τ0 (APPROX) | — | **FLAG (approximate)**: the literature relation carries a proportionality coefficient that is NOT exactly 1 (Greenwood/Tyler ≈ 0.31×); exact constant TO-CONFIRM from print. Displayed/labelled as approximate; **pending** confirmation. |
| Kolmogorov phase PSD const | 0.023 (cyclic-freq vK), 6.88 SF | aotools / Schmidt 2010; [AP] Ch.6 (6.88) | **FLAG**: aotools 0.023 & `structure_function_vk` 0.17253 not primary-traced; 6.88 standard |

The screen uses the **Kolmogorov** spectrum (worst case, no outer-scale
truncation): effectively-infinite L0 (`KOLMOGOROV_L0=1e6`) and `l0=1e-6`. l0 is
kept tiny (not 0) only because aotools computes `5.92/l0`; physically it is the
zero-inner-scale Kolmogorov limit. **Note:** on a finite N·δ grid the screen
cannot represent eddies larger than the grid, so its structure function shows a
large-scale deficit (~50%); this is the documented FFT-grid truncation and does
NOT affect scintillation (Fresnel-scale), confirmed by the weak Rytov match.

## Verified on the reused physics (single-screen rebuild)
- **Kolmogorov screen SF**: matches 6.88(r/r0)^(5/3) at small/mid separations;
  large-scale deficit as noted above.
- **Weak-scheme scintillation vs Rytov** (Cn²=1e-14, σ_R²=0.132), point detector,
  N=512, δ=2 mm, 48 realisations:
  - single screen (n=1): σ_I² = 0.1331 ± 0.0004 → **sim/Rytov = 1.01**
  - n=5: 0.1318 (1.00); n=10: 0.1311 (0.99). A single screen reproduces Rytov.
- **Frozen-flow temporal↔spatial equivalence** (single advected screen, weak):
  temporal σ_I² = 0.1288 ± 0.019 vs spatial 0.1330 ± 0.001 → −3.2% (consistent).

## Architecture (simplified)
One Kolmogorov screen at the chosen r0, generated once, advected rigidly
(Fourier shift, single direction) across the fixed 75 mm aperture; propagated to
the receiver as a single screen at the path midpoint (verified split-step with
n_screens=1); aperture-integrated to h = P_turb/P_clear (real ≥ 0). Reference
trace sampled at the v_max displacement step; wind tuned live by time-resampling
(`f_update_eff = f_stored·v/v_max`), consumer linear-interpolates. Greenwood
frequency is a derived readout only. No library, no trace selection, no manifest.
