"""
traces.py -- simplified single-screen frozen-flow channel.

ONE static Kolmogorov phase screen at the chosen turbulence strength, advected
rigidly across a fixed 75 mm receive aperture (Taylor frozen flow), propagated
to the receiver (single screen at the path midpoint -- the verified split-step
with n_screens=1) and aperture-integrated to the real, non-negative scalar gain

    h = P_turb / P_clear.

This is the whole physics for the simplified rebuild: one r0 per run, no library,
no trace selection. The reference trace is sampled at the MAXIMUM-wind (20 m/s)
displacement step dd_ref = v_max/f_update so the server can serve any slower wind
by pure time-resampling (upsampling). Reuses the verified screen generation
(screens.py), propagation and aperture integration (propagation.py, receiver.py)
unchanged.

VALIDATION CAVEAT (carried in code, server metadata and PROCESS.md):
  * weak   (Cn2=1e-14, sigma_R^2~0.13): the single screen matches the plane-wave
    Rytov scintillation to ~1% -> the ONLY validated regime.
  * moderate (Cn2=5e-14, sigma_R^2~0.66): divergence zone -- UNVERIFIED.
  * strong (Cn2=3e-13, sigma_R^2~4): where the earlier Gamma-Gamma check FAILED
    (the split-step overshoots / does not saturate) -- UNVERIFIED.
  moderate and strong are PHYSICALLY-PLAUSIBLE-BUT-UNVERIFIED; not validated.

Equation ledger: PROCESS.md.
"""

import numpy as np

from screens import generate_screen, KOLMOGOROV_L0, KOLMOGOROV_l0
from propagation import (AngularSpectrumPropagator, fried_parameter_plane,
                         rytov_variance_plane, split_step_plane_wave)
from receiver import aperture_mask, turbulence_gain

# ---- fixed link / grid (single configuration, no sweeping) ----------------
L = 800.0                  # m   folded path, single-pass equivalent
WAVELENGTH = 1550e-9       # m
APERTURE_D = 0.075         # m   receive aperture (75 mm)
GRID_N = 512               # px
GRID_DELTA = 2e-3          # m/px  (~8 px per Fresnel scale; verified)
V_MAX = 20.0               # m/s  reference (maximum) wind -- the stored rate
F_UPDATE_FLOOR = 2000.0    # Hz
N_STEPS_CAP = 400          # cap reference-trace length (bounds startup cost;
                           # ~40 decorrelation lengths even for strong)
DEFAULT_SEED = 20240       # fixed screen seed (one r0, one realisation per run)

# Three preset schemes the user picks between AT STARTUP (not live).
PRESETS = {
    "weak":     {"cn2": 1e-14, "validated": True,
                 "status": "Rytov-VALIDATED (single screen sim/Rytov ~1.01)"},
    "moderate": {"cn2": 5e-14, "validated": False,
                 "status": "PHYSICALLY-PLAUSIBLE-BUT-UNVERIFIED (divergence zone)"},
    "strong":   {"cn2": 3e-13, "validated": False,
                 "status": "PHYSICALLY-PLAUSIBLE-BUT-UNVERIFIED "
                           "(Gamma-Gamma check FAILED: overshoots, no saturation)"},
}


def greenwood_time(r0, v):
    """Atmospheric coherence (Greenwood) time tau0 = 0.32 * r0 / v.
    [AP] Ch.14 eq.39. The 0.32 coefficient is FLAGGED -- to confirm from print."""
    return 0.32 * r0 / v


def greenwood_frequency_approx(tau0):
    """APPROXIMATE Greenwood frequency f_G = 1 / tau0.

    FLAG: the literature relation between f_G and tau0 carries a proportionality
    coefficient that is NOT exactly 1 (Greenwood/Tyler give ~0.31x); the exact
    constant is TO-CONFIRM from the print copy. This returns the 1/tau0
    approximation and callers MUST label it as such. Do not treat as exact.
    """
    return 1.0 / tau0


def make_reference_trace(scheme, seed=DEFAULT_SEED):
    """Generate the single-screen frozen-flow reference gain trace for a preset.

    Returns a dict with the trace `h` (at the v_max displacement step) plus all
    metadata the server/GUI need (r0, sigma_R^2, screen seed/grid, aperture,
    wrap margin, validation flag). The GUI regenerates the SAME screen from
    (r0, N, delta, seed) to visualise exactly the patch being measured.
    """
    if scheme not in PRESETS:
        raise ValueError("scheme must be one of %s" % list(PRESETS))
    cn2 = PRESETS[scheme]["cn2"]
    r0 = fried_parameter_plane(cn2, L, WAVELENGTH)
    sigma_R2 = rytov_variance_plane(cn2, WAVELENGTH, L)
    f_update = max(F_UPDATE_FLOOR, 10.0 / greenwood_time(r0, V_MAX))
    dd = V_MAX / f_update                              # displacement step [m]

    # No-wrap span: the centred aperture must never sample wrapped screen.
    wrap_limit = GRID_N * GRID_DELTA / 2.0 - APERTURE_D / 2.0
    n_steps = min(int(0.95 * wrap_limit / dd), N_STEPS_CAP)
    max_disp = (n_steps - 1) * dd
    assert max_disp < wrap_limit, "frozen-flow advection would wrap"

    prop = AngularSpectrumPropagator(GRID_N, GRID_DELTA, WAVELENGTH)
    base = generate_screen(r0, GRID_N, GRID_DELTA, KOLMOGOROV_L0, KOLMOGOROV_l0,
                           seed=seed)
    base_fft = np.fft.fft2(base)
    fx = np.fft.fftfreq(GRID_N)
    KX, _ = np.meshgrid(fx, fx, indexing="ij")         # advect along axis 0
    mask = aperture_mask(GRID_N, GRID_DELTA, APERTURE_D)

    h = np.empty(n_steps, dtype=np.float64)
    for s in range(n_steps):
        sx = s * dd / GRID_DELTA                       # pixels advected
        scr = np.fft.ifft2(base_fft * np.exp(-2j * np.pi * KX * sx)).real
        U = split_step_plane_wave([scr], L, prop)      # 1 screen at midpoint
        h[s] = turbulence_gain(U, mask)

    assert np.isrealobj(h) and np.all(np.isfinite(h)) and np.all(h >= 0.0)
    return {
        "h": h, "f_update": f_update, "dd_ref": dd, "v_max": V_MAX,
        "scheme": scheme, "cn2": cn2, "r0": r0, "sigma_R2": sigma_R2,
        "validated": PRESETS[scheme]["validated"],
        "status": PRESETS[scheme]["status"],
        "N": GRID_N, "delta": GRID_DELTA, "aperture_D": APERTURE_D,
        "screen_seed": seed, "n_steps": n_steps, "max_disp": max_disp,
        "wrap_limit": wrap_limit, "L": L, "wavelength": WAVELENGTH,
        "tau0_at_vmax": greenwood_time(r0, V_MAX),
    }
