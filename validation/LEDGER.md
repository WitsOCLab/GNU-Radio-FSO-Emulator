# Equation ledger & staged validation record

> **Note on scope.** This is the full development ledger. **Stage 5 (the offline
> `.npz` trace *library* and its manifest)** is historical and is **not shipped**
> in this streaming release — the current server generates a single reference
> trace at start-up instead (see `../PROCESS.md` and `../fso_twin/traces.py`).
> Its physics findings (energy conservation, aperture averaging, ergodicity) are
> still relevant and are retained below. The runnable acceptance tests in this
> folder are Stages 1–3 and 6–7; the Stage-4 result is recorded in §4.5.

---

## PROCESS — FSO turbulence channel simulator, equation ledger

Fresh rebuild. Every constant and equation is traced to a primary reference
with chapter/equation, **or explicitly flagged when it could not be traced**.
No reference numbers are invented. Format follows the retired
`phase_screens.py` ledger: each entry gives the expression, a derivation or
citation, a **status**, and a consistency check where one exists.

Status tags: **VERIFIED** (traced to a specific equation and confirmed),
**TO-CONFIRM** (formula trusted but the exact chapter/eq must be filled from a
print copy), **PROVISIONAL** (derived relation, not independently proven; held
provisional until a downstream test corroborates it), **UNVERIFIED** (constant
taken from an implementation/source whose primary-reference trace I could not
complete — flagged, not guessed), **CHOICE** (a modelling choice inside a cited
literature range, not a universal constant).

## Reference keys
- **[AP]** L. C. Andrews & R. L. Phillips, *Laser Beam Propagation through
  Random Media*, 2nd ed., SPIE Press, 2005.
- **[Schmidt]** J. D. Schmidt, *Numerical Simulation of Optical Wave
  Propagation with Examples in MATLAB*, SPIE Press, 2010.
- **[Goodman]** J. W. Goodman, *Introduction to Fourier Optics*, 3rd ed.,
  Roberts & Co., 2005.
- **[Fried66]** D. L. Fried, "Optical Resolution Through a Randomly
  Inhomogeneous Medium…", J. Opt. Soc. Am. 56(10), 1372, 1966.
- **[Lane92]** R. G. Lane, A. Glindemann, J. C. Dainty, "Simulation of a
  Kolmogorov phase screen", Waves in Random Media 2(3), 209, 1992.
- **[aotools]** M. J. Townson et al., "AOtools: a Python package for adaptive
  optics modelling and analysis", Optics Express 27(22), 31316, 2019.
  Code: aotools 1.0.7 (installed in gnuradio-env alongside numpy 1.17.4).

## Fixed parameters (project-set)
| Symbol | Value | Note |
|---|---|---|
| λ | 1550 nm | optical wavelength (fixed; not a priority to vary) |
| v_max | 20 m/s | max wind; reference traces generated at this advection rate |
| f_update target | 5000 Hz | channel update rate |
| `numpy` | < 2 (1.17.4) | environment constraint, satisfied |

## Modelling choices (cited range, not universal constants)
| Symbol | Value | Basis | Status |
|---|---|---|---|
| L0 (production) | 10 m | terrestrial near-ground outer scale, within the ~1 m–tens-of-m range discussed in [AP] | **CHOICE** |
| l0 (production) | 5 mm | terrestrial inner scale, within the ~mm–cm range in [AP] | **CHOICE** |
| L0, l0 (Rytov verification) | 1e6 m, 1e-6 m | Kolmogorov limit: pushes the vK spectrum into the inertial range so σ_R²=1.23·… is the correct analytic target. l0 must be > 0 (aotools computes 5.92/l0). | **CHOICE** (verification only) |

---

## Stage 1 — phase-screen generation (aotools `ft_phase_screen`)

Screens are finite, static, **strictly periodic** von Kármán screens from
`aotools.turbulence.phasescreen.ft_phase_screen(r0, N, delta, L0, l0, seed)`
(McGlamery/FFT method). **No subharmonics, no oversampling** — both break
periodicity, and Stage 2's angular-spectrum kernel is periodic, so a
non-periodic screen would diffract the wrap-seam (a ~+0.073 scintillation
offset was seen with the retired generator). We do **not** use the aotools
infinite-screen classes (they renew structure and violate frozen flow).

### 1.1 von Kármán phase PSD (aotools, cyclic-frequency convention)
```
Φ_φ(f) = 0.023 · r0^(−5/3) · exp(−(f/f_m)²) / (f² + f0²)^(11/6)
         f_m = 5.92 / (2π l0),   f0 = 1 / L0,   f in cycles/m
```
- Source: [Schmidt] FFT phase-screen listing, as implemented in [aotools]
  `ft_phase_screen`.
- **Status: UNVERIFIED** for the leading constant **0.023** — it is the
  cyclic-frequency phase-PSD constant used by aotools/Schmidt; I have not
  re-derived it to a specific [AP] equation here. Flagged, not guessed. The
  screens are validated *as a whole* by the structure-function test below, so
  the constant is corroborated indirectly.
- Note the convention is **cyclic** frequency f [cycles/m]; the retired ledger
  used **angular** κ = 2πf and a constant 0.49 — different convention, not a
  contradiction.

### 1.2 Kolmogorov phase structure function (acceptance target)
```
D_φ(r) = 6.88 (r/r0)^(5/3)
```
- [Fried66]; [AP] Ch. 6. aotools `structure_function_kolmogorov` uses 6.88.
- **Consistency check (VERIFIED):** 6.88 = 2·(24/5·Γ(6/5))^(5/6) = 6.8839…,
  tied to the definition of r0 itself.

### 1.3 von Kármán structure function (acceptance target, finite L0)
```
D_vk(r) = 0.17253 (L0/r0)^(5/3) · [ 1 − (2 π^(5/6) / Γ(5/6)) (r/L0)^(5/6)
                                       · K_(5/6)(2π r / L0) ]
```
- aotools `structure_function_vk(r, r0, L0)` (K = modified Bessel, 2nd kind).
- **Status: UNVERIFIED** for the constant **0.17253** — taken from the aotools
  implementation; primary-reference trace not completed here. Flagged.
- **Consistency check (VERIFIED numerically):** D_vk/D_k → 1 as L0 → ∞
  (ratios at r∈{1,5,10,30} cm: L0=1e2 → 0.79–0.93; 1e4 → 0.95–0.98;
  1e6 → 0.99–1.0). So `structure_function_vk` and `…_kolmogorov` are mutually
  consistent, and the Kolmogorov limit is the right Stage-2 target.

### 1.4 Verification result (verify_screens.py)
Ensemble of 30 screens, N=512, δ=4 mm (2.048 m), r0=10 cm. Empirical isotropic
structure function (exact circular shifts on the periodic grid) vs theory, over
the inertial window [4δ, Nδ/4] = [16 mm, 512 mm]:

| Case | L0, l0 | target | mean \|rel err\| | max | signed |
|---|---|---|---|---|---|
| von Kármán (resolvable) | 2.0 m, 1 mm | `structure_function_vk` | **1.55 %** | 3.30 % | −1.55 % |
| Kolmogorov limit | 1e6 m, 1e-6 m | `6.88 (r/r0)^(5/3)` | **52.4 %** | 68.7 % | −52.4 % |

**Reading:** with a resolvable outer scale the aotools screens reproduce the
von Kármán structure function to ~1.5 % — they are statistically correct. The
Kolmogorov-limit screen shows a large **low-frequency (large-separation)
deficit**: with L0→∞ the grid (span Nδ) cannot hold the dominant large-scale
power, and with no subharmonics (required for periodicity) it is not restored.
This is the known, documented price of strict periodicity. It is a **large-
scale** deficit; scintillation is **Fresnel-scale** driven (Rytov filter
sin²(κ²L/2k) → 0 as κ→0), so it should not bias σ_I². **Stage 2 tests this
directly and is the real arbiter** for the Kolmogorov-limit screens.

**Stage 1 status: PASS** (von Kármán screens correct to 1.55 %; Kolmogorov-limit
large-scale deficit understood and deferred to the Stage-2 scintillation test).

---

## Stage 2 — split-step angular-spectrum propagation

Unit plane wave through `n_screens` strictly-periodic Kolmogorov-limit screens,
symmetric split-step (dz/2, screen, dz, …, dz/2), Fresnel angular-spectrum
transfer function.

### 2.1 Fried parameter (plane wave)
```
r0 = (0.42 k^2 Cn2 L)^(-3/5),    k = 2 pi / lambda
```
- [AP] Ch. 14 eq. 25/95. **Status: VERIFIED** (project lead).

### 2.2 Per-screen Fried scaling (split-step slabs)
```
r0_i = r0_total * n_screens^(3/5)      (equal slabs dz = L/n)
```
- Derived: r0 ~ (Cn2·dz)^(-3/5); dz = L/n multiplies r0 by n^(3/5).
- **Status: PROVISIONAL → CORROBORATED.** Validated indirectly by 2.5: the
  aggregate σ_I² is independent of n_screens (∈{5,10,20}) and matches σ_R², so
  the slicing is self-consistent. Not a first-principles proof.

### 2.3 Rytov variance (plane wave) — the verification target
```
sigma_R^2 = 1.23 Cn2 k^(7/6) L^(11/6)
```
- [AP] 2nd ed, weak-fluctuation (Rytov) theory. **Status: TO-CONFIRM** — exact
  chapter/equation to be filled from print copy; coefficient **1.23** not
  independently traced here (formula supplied by project lead).

### 2.4 Fresnel angular-spectrum transfer function & sampling
```
H(fx,fy) = exp(-i pi lambda dz (fx^2+fy^2))   ;   require dz <= N delta^2 / lambda
```
- [Goodman] Ch. 4; [Schmidt] Ch. 7 (transfer-function form and sampling
  criterion). **Status: VERIFIED** (standard Fourier optics).
- Weak-scintillation relation σ_I² = exp(σ_R²) − 1 ≈ σ_R² ([AP], Rytov);
  scintillation index σ_I² = var(I)/⟨I⟩² ([AP] Ch. 1).

### 2.5 Verification result (verify_rytov.py) — HARD GATE: PASS
λ=1550 nm, L=1000 m, Cn²=5.02e-15 (σ_R²=0.10000), N=512, δ=2 mm
(~8 px/Fresnel), 64 realizations. exp(σ_R²)−1 = 0.10517.

| n_screens | r0_screen | dz | mean(I) | σ_I² | vs σ_R² |
|---|---|---|---|---|---|
| 5  | 31.3 cm | 200 m | 1.0000 | 0.09941 ± 0.00039 | −0.6 % |
| 10 | 47.4 cm | 100 m | 1.0000 | 0.09904 ± 0.00034 | −1.0 % |
| 20 | 71.9 cm | 50 m  | 1.0000 | 0.09910 ± 0.00031 | −0.9 % |

σ_I² within ~1 % of σ_R² at all layer counts; spread across n_screens = 0.4 %
of σ_R²; mean(I)=1.0000 (energy conserved). **No +0.073 seam offset** (periodic
aotools screens). Corroborates 2.2. **Stage 2 status: PASS.**

---

## Stage 3 — aperture integration → real, non-negative scalar gain h

### 3.1 Definition
```
h = P_turb / P_clear = (Σ_aperture |U|^2) / (Σ_aperture |U_clear|^2)
  = mean_aperture |U|^2        (since clear-air |U_clear|^2 = 1)
```
- Normalisation by clear-air power through the SAME aperture divides out δ² and
  geometric factors and fixes clear air at h = 1. **Status: VERIFIED by 3.3.**
- h is a ratio of sums of |·|² ⇒ real and ≥ 0 (asserted in `turbulence_gain`).

### 3.2 Separate scalar multipliers (NOT folded into the field integration)
```
link_gain = h_turb * T_weather * G_geom
T_weather = exp(-sigma_ext L)      (Beer-Lambert, [AP] Ch. 1; sigma_ext caller-supplied)
G_geom    = 1.0                    (plane-wave illumination; finite-beam factor would enter here)
```
- Beer-Lambert FORM **VERIFIED**; the extinction value σ_ext is out of scope
  (Kim/Kruse models, later). G_geom = 1 for the normalised plane wave.

### 3.3 Verification result (verify_aperture.py) — PASS
λ=1550 nm, L=1000 m, σ_R²=0.10, N=512, δ=2 mm, 64 realizations; Fresnel 15.7 mm.

- **Clear air:** h = 1.000000000000000, |h−1| = 0 at D = 4/20/80 mm (exact).
- **Point detector:** σ_I² = 0.0985 ± 0.0004 → matches Stage-2 σ_R²=0.10.
- **Aperture averaging** (fractional variance falls as D grows):

  | D | σ_I²(D) | A(D)=σ_I²(D)/point | D/Fresnel |
  |---|---|---|---|
  | 20 mm | 0.0599 | 0.609 | 1.3 |
  | 40 mm | 0.0281 | 0.286 | 2.5 |
  | 80 mm | 0.0074 | 0.075 | 5.1 |

- mean(h) at D=20 mm = 1.0306 ± 0.0371 (consistent with 1 → power conserved).

**Stage 3 status: PASS.**

---

## Stage 4 — frozen-flow gain trace generation

### 4.1 Taylor frozen flow (temporal model)
The rigid screen is advected across the aperture: φ(r, t) = φ(r − v t). Implemented
as a sub-pixel circular Fourier shift of the rigid aotools screen; each layer
moves at a COMMON speed in its OWN per-trace-seeded direction (existing wind
model preserved).
- [Taylor1938] G. I. Taylor, "The spectrum of turbulence", Proc. R. Soc. Lond.
  A 164, 476, 1938; [AP] Ch. 8 (temporal statistics). **Status: VERIFIED** (model
  choice, standard); Fourier-shift advection is exact for the periodic screen.

### 4.2 Per-trace update rate
```
tau0 = 0.32 r0 / v           f_update = max(floor, 10 / tau0)
```
- τ0: [AP] Ch. 14 eq. 39 (project-lead). 10/τ0 (≥10 samples/coherence time) is
  the existing design rule. **Status: τ0 coefficient 0.32 as given; rule VERIFIED.**

### 4.3 Wind as time-resampling (the stored-trace contract)
Under frozen flow h depends on wind ONLY through displacement d = v t. The
reference trace is therefore sampled at the **maximum-wind displacement step**
```
dd_ref = v_max / f_update           (v_max = 20 m/s)
```
**The stored quantity is the frozen-flow gain sampled at the 20 m/s displacement
step.** Serving any slower wind v < v_max downstream is a pure TIME-STRETCH
(upsample) of this reference — index by d = v t and interpolate; never a
downsample (which could not synthesise missing fine detail). This is the entire
justification for live wind tuning without regenerating physics. **Status:
VERIFIED by construction** (Taylor hypothesis, 4.1).

### 4.4 No-wrap condition (rigid finite screen)
Centred aperture must never sample wrapped screen content:
```
max_disp = (n_steps-1) * dd_ref  <  N*delta/2 - aperture_D/2
```
Asserted in `generate_trace`; production must enlarge N (screen length in the
wind direction ≥ aperture + advection span) for longer traces.

### 4.5 Verification result (verify_traces.py) — PASS
λ=1550 nm, L=1000 m, Cn²=5.02e-15, aperture D=20 mm, N=512, δ=2 mm,
n_screens=10, Kolmogorov-limit screens (to compare with Stages 2–3),
10 traces × 110 steps.

Sampling: r0=0.119 m, τ0@20 m/s=1.906 ms, **f_update=5245.8 Hz,
dd_ref=3.813 mm**; span 0.416 m at 20 m/s (21 ms; the same trace plays 0.42 s
at 1 m/s).

| check | result |
|---|---|
| h real, finite, ≥ 0 | asserted; min(h)=0.4096 |
| mean(h) per trace | 0.9928 ± 0.0240 (≈1 → power conserved) |
| trace temporal σ_I² | 0.0596 ± 0.0060 |
| Stage-3 spatial target σ_I²(20 mm) | 0.0607 ± 0.0005 |
| difference | **−1.8 %** (consistent within SE → ergodicity OK) |
| no-wrap | max_disp 0.4156 m < limit 0.5020 m, margin 0.0864 m → **NO WRAP** |

**Stage 4 status: PASS.**

---

## Stage 5 — offline gain-trace library generator

Sweeps physical Cn² (→ r0) for the 800 m link, several seeds per r0, writing
self-describing `.npz` traces + `manifest.json` (schema 3). Uses **production**
von Kármán scales L0=10 m, l0=5 mm (not the Kolmogorov-limit verification
scales). Each trace records Cn², L, λ, aperture, r0, τ0, f_update, dd_ref,
displacement span, σ_I², h-stats, wrap margin; manifest carries units, the
deterministic seed rule, sha256 code provenance, and known limitations.

### 5.1 Link / grid / sampling
- L=800 m, λ=1550 nm, aperture D=20 mm; N=512, δ=2 mm; n_screens=10.
- Each trace sampled at the **20 m/s displacement step** dd_ref = v_max/f_update
  (Stage 4) so downstream wind tuning is upsampling. Displacement span 0.40 m.
- f_update = max(2000, 10/τ0); τ0 = 0.32 r0/v at v_max ([AP] Ch.14 eq.39).

### 5.2 Full-grid plan (weak → strong, reported before generating)
| Cn² | r0 | τ0@20 | f_update | dd_ref | n_steps | σ_R² | regime | wrap margin |
|---|---|---|---|---|---|---|---|---|
| 1e-15 | 35.9 cm | 5.74 ms | 2000 Hz | 10.0 mm | 41 | 0.013 | weak | 0.102 m |
| 1e-14 | 9.0 cm | 1.44 ms | 6936 Hz | 2.88 mm | 140 | 0.132 | weak | 0.101 m |
| 3e-14 | 4.7 cm | 0.75 ms | 13408 Hz | 1.49 mm | 269 | 0.397 | moderate | 0.102 m |
| 7e-14 | 2.8 cm | 0.45 ms | 22293 Hz | 0.90 mm | 447 | 0.926 | moderate | 0.102 m |
| 1.5e-13 | 1.8 cm | 0.28 ms | 35217 Hz | 0.57 mm | 705 | 1.984 | strong | 0.102 m |
| 3e-13 | 1.2 cm | 0.19 ms | 53380 Hz | 0.38 mm | 1069 | 3.968 | strong | 0.102 m |

Estimate: 30 traces (5 seeds), ~13 k steps, ~52 min, ~0.1 MB. Exceeds the safety
gate (>120 s / >20 traces) → full run requires `--full --yes`. Strong regimes
push f_update to 35–53 kHz (faster fading, correct per the τ0 rule).

### 5.3 Production von Kármán vs Kolmogorov-limit (measured, weak)
σ_I² production (L0=10 m, l0=5 mm) = 0.0819 vs Kolmogorov-limit 0.0825 →
**−0.8 %** (small reduction, as expected). It is *small* because on the 1.024 m
grid the outer scale L0=10 m lies below the grid fundamental (f0=1/L0=0.1 <
0.98 cycles/m), so L0 does not roll off the on-grid spectrum; only l0=5 mm has
an on-grid effect. **Documented as known-limitation #2** — the recorded L0 is
the intended physical value, not a fully on-grid-resolved one. Scintillation
(the quantity in h) is Fresnel-scale and unaffected.

### 5.4 Per-regime wrap re-check (CRITICAL, enforced)
`generate()` re-derives and asserts the wrap margin for every regime and
**raises rather than writing a corrupted trace** if margin ≤ 0. Small-grid
margins: weak 0.1012 m, moderate 0.1024 m → **NO WRAP**. With fixed N and
displacement span the margin is ~constant across regimes; it MUST be re-checked
if N or the span change (known-limitation #3).

### 5.5 Small-grid verification result (library_gen.py --small) — PASS
2 r0 × 2 seeds; production scales.

| regime | Cn² | σ_R² | trace σ_I² (2 seeds) | mean(h) | min(h) |
|---|---|---|---|---|---|
| weak | 1e-14 | 0.132 | 0.0819 / 0.0411 (mean 0.062) | 1.037 / 0.939 | 0.51 / 0.57 |
| moderate | 5e-14 | 0.661 | 0.4718 / 0.2151 (mean 0.343) | 1.187 / 1.254 | 0.23 / 0.44 |

- **h real, finite, ≥ 0** at all points (min h = 0.227).
- **Large per-seed σ_I² scatter** (≈ ×2) is expected for a single 0.40 m trace
  (~10–36 decorrelation lengths) and is exactly why several seeds per r0 are
  stored; the ensemble converges. Weak ensemble σ_I² ≈ 0.062 is consistent with
  the Stage-3 aperture-averaged expectation A·σ_R² (A≈0.55 at D/r_F≈1.4 ⇒ ≈0.073)
  within the 2-seed scatter.
- **mean(h):** weak ≈ 1.0; moderate ≈ 1.2. **Global energy is conserved EXACTLY**
  (mean|U|² over the full grid = 1.00000000 ± 2e-16 at weak/moderate/strong), so
  the moderate >1 is a finite-sample swath effect (one trace samples a limited
  1-D advection track), not an energy leak. Expected to converge to 1 with the
  full 5-seed run — **to confirm there.**
- **Moderate/strong σ_R² is a regime LABEL, not the expected σ_I²** (Rytov is
  weak-only); those traces' higher-order stats are UNVERIFIED (known-limitation #1).

### 5.6 Recorded limitations (folded into manifest + ledger before the full run)
1. **Effective outer scale = screen size.** The screen is N·δ = 1.024 m,
   smaller than the nominal L0 = 10 m; it cannot contain eddies larger than
   ~1 m. δ = 2 mm is kept small to resolve the Fresnel scale (~1.4 cm) for
   scintillation fidelity — the priority — not enlarged to fit L0. The manifest
   records `L0_effective_m = N·δ` alongside `L0_nominal_m = 10 m`. **Consequence:**
   fade dynamics slower than the screen-crossing time (~ N·δ / v) are NOT
   represented; the slowest temporal-spectrum content is truncated. Fine for the
   scintillation INDEX (Fresnel-scale, well resolved); **to be checked against
   the temporal spectrum once traces exist.**
2. **Strong regimes unverified.** σ_R² = 2.0 and 4.0 (Cn²=1.5e-13, 3e-13) are in
   the strong-fluctuation regime where Rytov is invalid (scintillation saturates,
   statistics → Gamma-Gamma). The split-step CAN in principle represent this but
   was only validated against Rytov in the WEAK regime (Stage 2). These traces
   carry `validation_status = PHYSICALLY-PLAUSIBLE-BUT-UNVERIFIED` and **must be
   checked against the Gamma-Gamma scintillation-index saturation curve before
   use** (A&P Ch.14, σ_I² vs β0; eq. ~51 / fig. 14.6 — TO CONFIRM). Not attempted
   here; the flag travels with the data.

### 5.7 Full-grid generation result (library_gen.py --full --yes) — DONE
Production von Kármán (L0_nominal=10 m, L0_effective=N·δ=1.024 m, l0=5 mm),
6 r0 × 5 seeds = 30 traces, ~47 min. Per-regime ensemble (mean ± std over 5 seeds):

| Cn² | r0 | σ_R² | regime | ensemble σ_I² | mean(h) | min(h) | wrap | status |
|---|---|---|---|---|---|---|---|---|
| 1e-15 | 35.9 cm | 0.013 | weak | 0.0058 ± 0.0014 | 0.996 ± 0.028 | 0.835 | 0.102 | Rytov-verified |
| 1e-14 | 9.0 cm | 0.132 | weak | 0.088 ± 0.029 | 1.060 ± 0.056 | 0.444 | 0.101 | Rytov-verified |
| 3e-14 | 4.7 cm | 0.397 | moderate | 0.198 ± 0.069 | 1.033 ± 0.137 | 0.263 | 0.102 | transitional |
| 7e-14 | 2.8 cm | 0.926 | moderate | 0.368 ± 0.110 | 0.924 ± 0.178 | 0.118 | 0.102 | transitional |
| 1.5e-13 | 1.8 cm | 1.984 | strong | 0.701 ± 0.331 | 0.860 ± 0.211 | 0.076 | 0.102 | UNVERIFIED |
| 3e-13 | 1.2 cm | 3.968 | strong | 0.884 ± 0.404 | 1.135 ± 0.186 | 0.083 | 0.102 | UNVERIFIED |

- **NO REGIME WRAPPED** (all margins ≈ 0.102 m; enforced per regime).
- **mean(h) converges to 1 with 5 seeds:** all regimes ∈ [0.86, 1.13],
  consistent with 1 within ~1–1.5 SE (SE = std/√5). The small-grid moderate
  outlier (5e-14, 2 seeds → 1.22) was 2-seed swath scatter; the 5-seed moderate
  regimes (1.033, 0.924) confirm the swath effect averages out as predicted.
  Energy conservation holds in the ensemble.
- **Weak aperture-averaged σ_I² ≈ A·σ_R²** with A ≈ 0.44–0.67 (D/r_F ≈ 1.4),
  consistent with Stage-3 aperture averaging.
- **Strong σ_I² saturates** (0.70, 0.88 at σ_R² = 2.0, 4.0 — does NOT grow with
  σ_R²): qualitatively the strong-fluctuation saturation behaviour, but
  UNVERIFIED quantitatively (limitation #1; check vs Gamma-Gamma before use).
- **min(h) deepens with strength** (0.84 → 0.08, i.e. down to ~−11 dB fades);
  all h ≥ 0.
- **Large per-seed scatter** (σ_I² std 33–47 %) confirms each trace is a genuine
  random realisation; the 5-seed ensemble is the meaningful statistic (strong
  regimes would need more seeds to tighten — but are UNVERIFIED regardless).

**Stage 5 status: COMPLETE.** 30-trace library in `fso_sim/fso_library/`
(untracked); manifest schema 3 with provenance, units, seed rule, per-trace
`validation_status`, and the recorded limitations (5.6).

---

## Stage 6 — streaming server: live wind-speed tuning (time-resampling)

### 6.1 Physics
Stored trace = frozen-flow gain at dd_ref = v_max/f_stored. Under Taylor, the
gain depends on wind only through displacement d = v·t, so serving wind v is the
SAME spatial sequence at a rate ∝ v. The server publishes the stored samples
UNCHANGED and sets the message rate `f_update_eff = f_stored·(v/v_max)`. Exact
under frozen flow ([Taylor1938]; [AP] Ch. 8). v = v_max plays at the stored
rate; v < v_max is a pure time-stretch (upsampling).

### 6.2 f_update interaction (the place a bug would hide)
The consumer locks `R = sample_rate / f_update`. Wind changes `f_update`, not the
values, so R scales: slower wind → larger R → slower fades, identical values.
The consumer's existing **linear interpolation** (np.interp) does the upsampling;
the server does no resampling itself. On a wind change the server re-baselines
its pacing clock (trace_t0, trace_emitted) **without** bumping the epoch or
resetting trace_progress — values continue, only the rate changes; the consumer
recomputes R and continues its buffer/cursor smoothly. **Loop logic runs on the
sample index**, so a stretched trace still loops cleanly (pingpong/forward/once)
at any wind.

### 6.3 Bounds
wind ∈ (WIND_MIN = 0.5, v_max = 20] m/s. v_max is the HARD maximum (the stored
displacement resolution; faster would require downsampling and lose detail) →
clamped with a logged warning. Below WIND_MIN clamped (very low wind stretches
the trace over a long real-time span; the loop modes handle the wrap).

### 6.4 Linear, never zero-order hold
Resampling is linear interpolation (the consumer's np.interp idiom), never a
sample-repeat / staircase — the failure mode rejected at project start. Verified.

### 6.5 Verification (verify_wind.py, end-to-end ZMQ) — PASS
Weak trace (Cn²=1e-14, stored f_update 6935.9 Hz), forward loop.
- **(a) rate ∝ wind:** f_update(20 m/s)=6935.9 (=stored), f_update(10 m/s)=3467.9
  → ratio 0.500.
- **(b) same data, resampled:** max|gain(20)−gain(10)| = 0 over 300 samples from
  progress 0 (same trace, different rate — not different data).
- **(c) linear not ZOH:** upsample R=50 via np.interp → repeated-value fraction
  0.0000 (linear) vs 0.9803 (ZOH counter-example); within-segment 2nd-difference
  ≈ 1.6e-3 (piecewise-linear).
- **(d) over-max graceful:** wind=25 → clamped to 20 with a logged warning.
- **(e) non-negative:** min published gain 0.487 ≥ 0.

**Stage 6 status: PASS.** Server `fso_sim/server.py` + `fso_stream_proto.py`
(wire contract, matches the GR block's inline copy); wind_speed is a continuous
control over the existing REP channel, on the cheap/continuous side.

---

## Stage 7 — strong-fluctuation validation vs Gamma-Gamma (RESULT: FAILED)

Goal: validate the split-step propagator in moderate→strong turbulence by
comparing the simulated POINT-detector scintillation index against the
plane-wave Gamma-Gamma theory across a dense strength sweep. Same path as the
Stage-2 Rytov check (`propagate_kolmogorov_plane` → `var/mean²` over the grid),
Kolmogorov-limit screens, λ=1550 nm, L=800 m.

### 7.1 Theory (gamma_gamma.py) — UNVERIFIED-FROM-PRINT
```
sigma_I^2(plane) = exp[ 0.49 sR2/(1+1.11 sR2^(6/5))^(7/6)
                      + 0.51 sR2/(1+0.69 sR2^(6/5))^(5/6) ] - 1,
sR2 = sigma_R^2 = 1.23 Cn2 k^(7/6) L^(11/6)   (plane-wave Rytov variance)
```
- Andrews & Phillips 2nd ed plane-wave scintillation index (project lead cited
  "Ch.14, eq. ~51 / fig. 14.6"). **Coefficients (0.49, 1.11, 0.51, 0.69),
  exponents, and the equation number are NOT confirmed against the print copy —
  flagged.** Peak σ_I²≈1.24 at σ_R²≈10; slow saturation.
- **WAVE-TYPE FLAG:** the project lead's β0² = 0.5 Cn² k^(7/6) L^(11/6) is the
  SPHERICAL-wave Rytov variance; the simulation is a PLANE wave, so the
  consistent comparison is the plane-wave curve vs σ_R² (1.23). β0 (=0.638 σ_R)
  is tabulated only for cross-reference.

### 7.2 Methodology gate (passed — the result below is not an artifact)
- **n_screens convergence:** σ_I² flat from n_screens=10 to **160** (σ_R²=2:
  1.555→1.558; σ_R²=4: 1.952→1.961; per-screen Rytov down to 0.013–0.025). NOT a
  deceptive plateau.
- **Grid resolution:** σ_I² δ-independent where ρ0/δ ≳ 2 (σ_R²=4: 1.960 at
  δ=2mm vs 1.973 at δ=1mm; σ_R²=10: 1.741 vs 1.737). N=512/δ=2mm adequate to
  σ_R²≈6; the σ_R²>7 tail (ρ0/δ<2) is under-resolved and flagged.

### 7.3 Sweep result (N=512, δ=2mm, n_screens=20, 32 realizations)
| σ_R² | ρ0/δ | sim σ_I² ± SE | theory | sim/theory |
|---|---|---|---|---|
| 0.20 | 16.6 | 0.199 ± 0.001 | 0.193 | 1.03 |
| 0.50 | 9.6 | 0.491 ± 0.003 | 0.433 | 1.14 |
| 1.00 | 6.3 | 0.939 ± 0.005 | 0.706 | 1.33 |
| 2.00 | 4.2 | 1.585 ± 0.009 | 0.985 | 1.61 |
| 3.00 | 3.3 | 1.890 ± 0.011 | 1.109 | **1.71** |
| 4.00 | 2.8 | **1.979** ± 0.012 | 1.170 | 1.69 |
| 6.00 | 2.2 | 1.936 ± 0.011 | 1.223 | 1.58 |
| 10.0 | 1.6* | 1.747 ± 0.009 | 1.243 | 1.41 |
| 20.0 | 1.1* | 1.507 ± 0.009 | 1.225 | 1.23 |
(*under-resolved tail.) Full data: `strong_sweep.json`.

### 7.4 Reading & conclusion
- **Weak (σ_R² ≲ 0.2–0.3): agree** (ratio 1.03) — consistent with the Stage-2
  Rytov validation.
- **Moderate→strong: systematic, robust overshoot.** Divergence begins at
  σ_R²≈0.5 and reaches **~70 %** near the peak. The sim peaks at **σ_I²≈1.98 at
  σ_R²≈4 (σ_R≈2)**; the theory peaks at **1.24 at σ_R²≈10**. The sim shows the
  qualitative rise-peak-decline of strong fluctuations but at the wrong height
  and location, and does not saturate toward ~1.
- The overshoot is **not** explained by n_screens (flat to 160) or grid
  resolution (δ-independent in the resolved range), and a ~70 % overshoot with a
  ~2.0 peak is too large to be theory-coefficient uncertainty (any standard
  point-scintillation theory peaks ~1.2–1.5 and saturates to 1).
- **CONCLUSION: the propagator is validated ONLY in the weak regime
  (σ_R² ≲ 0.2–0.3). The Gamma-Gamma check FAILED in moderate and strong
  turbulence.** Per the pre-stated criterion, the **strong library regimes stay
  UNVERIFIED — validation_status NOT upgraded.** The moderate library regimes
  (σ_R²=0.40, 0.93) also fall in the divergence zone and must likewise be
  treated as quantitatively unvalidated.
- **Not resolved here (candidate causes / future work):** Kolmogorov-limit
  (L0→∞) screens on a finite grid may produce anomalous large-scale focusing /
  fail to saturate; grid-EXTENT sensitivity (N·δ) was NOT tested (only δ);
  finite outer scale + subharmonics may be required for faithful strong-regime
  statistics. These, plus confirming the theory from the print copy, are the
  path to any future strong-regime validation. **Stage 7 status: FAILED (strong
  regime not validated).**

---

## Open ledger items (for project lead to close from print copy)
- **σ_R² coefficient 1.23** (2.3): chapter/equation TO-CONFIRM; not independently traced.
- **aotools 0.023** (1.1) and **0.17253** (1.3): UNVERIFIED primary-reference trace
  (from aotools/Schmidt implementation); corroborated indirectly by Stage-1/2 tests.
- Production von Kármán **L0=10 m, l0=5 mm** (CHOICE): document the expected small
  scintillation reduction vs the Kolmogorov target when the production library is built (Stage 5).
- **Gamma-Gamma plane-wave σ_I² coefficients** (7.1): 0.49, 1.11, 0.51, 0.69 and
  eq. number ("~51 / fig. 14.6") TO-CONFIRM from print; ρ0 coefficient 1.46
  (coherence radius) and β0² coefficient 0.5 (spherical Rytov) likewise TO-CONFIRM.
