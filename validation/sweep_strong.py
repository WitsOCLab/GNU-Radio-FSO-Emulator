"""
sweep_strong.py -- Stage 7: strong-fluctuation strength sweep + Gamma-Gamma
comparison.

--probe : gate before the sweep. Checks (i) n_screens convergence and (ii) grid
          resolution (delta sensitivity), because in strong turbulence the
          speckle coherence radius rho0 shrinks toward the pixel size and an
          under-resolved grid biases sigma_I^2 low (a fake saturation). Reports
          the per-realization scatter so the sweep's n_real can be sized.
--sweep : dense sweep of the validated split-step propagator (Kolmogorov-limit
          screens, exactly the Stage-2 path) across turbulence strength; POINT-
          detector sigma_I^2 (var/mean^2 over the grid), mean +/- SE per point;
          overlays the plane-wave Gamma-Gamma theory (gamma_gamma.py). Writes
          results to strong_sweep.json for the report.

Note: per-realization sigma_I^2 is a full-grid spatial average over many
speckles, so it is far tighter than the library's single-swath traces; n_real
of a few tens suffices (confirmed by --probe).
"""

import argparse
import json
import os
import time

import numpy as np

from propagation import (propagate_kolmogorov_plane, scintillation_index,
                         cn2_for_rytov)
import gamma_gamma as gg

WAVELENGTH = 1550e-9
L = 800.0
_HERE = os.path.dirname(os.path.abspath(__file__))


def sim_sci(sigmaR2, N, delta, n_screens, n_real, seed0):
    """Simulated point-detector sigma_I^2 at plane-wave Rytov variance sigmaR2.
    Returns (mean, SE, per_real_std, cn2)."""
    cn2 = cn2_for_rytov(sigmaR2, WAVELENGTH, L)
    si = np.empty(n_real)
    for r in range(n_real):
        U = propagate_kolmogorov_plane(cn2, WAVELENGTH, L, N, delta, n_screens,
                                       seed=seed0 + r)
        si[r] = scintillation_index(U)
    return si.mean(), si.std(ddof=1) / np.sqrt(n_real), si.std(ddof=1), cn2


def rho0_over_delta(sigmaR2, delta):
    cn2 = cn2_for_rytov(sigmaR2, WAVELENGTH, L)
    return gg.coherence_radius_plane(cn2, WAVELENGTH, L) / delta


def probe():
    print("=" * 76)
    print("STAGE 7 PROBE: n_screens convergence + grid resolution (gate)")
    print("=" * 76)
    print("lambda=%.0f nm, L=%.0f m" % (WAVELENGTH * 1e9, L))
    n_real = 20

    print("\n(i) n_screens convergence  (N=512, delta=2 mm, %d realizations)"
          % n_real)
    print("   sigma_R^2  n_screens   sigma_I^2 +/- SE      per-real std")
    for sR2 in (4.0, 10.0):
        for nsc in (10, 20, 40):
            m, se, sd, _ = sim_sci(sR2, 512, 2e-3, nsc, n_real, seed0=7000)
            print("   %7.1f   %6d      %.4f +/- %.4f     %.4f"
                  % (sR2, nsc, m, se, sd))

    print("\n(ii) grid resolution  (n_screens=20, %d realizations)" % n_real)
    print("   sigma_R^2   grid            rho0/delta   sigma_I^2 +/- SE")
    for sR2 in (4.0, 10.0):
        for (N, d) in ((512, 2e-3), (1024, 1e-3)):
            m, se, sd, _ = sim_sci(sR2, N, d, 20, n_real, seed0=8000)
            print("   %7.1f   N=%4d d=%.1fmm   %6.2f      %.4f +/- %.4f"
                  % (sR2, N, 1e3 * d, rho0_over_delta(sR2, d), m, se))
    print("\nReading: sigma_I^2 should converge as n_screens grows, and be "
          "delta-independent only where rho0/delta is comfortably > ~2. Trust "
          "the sweep only in that resolved range.")
    print("=" * 76)


def converge():
    """Extended n_screens convergence -- rule out a deceptive 10-40 plateau as
    the cause of any strong-regime overshoot (the classic split-step trap)."""
    print("=" * 76)
    print("STAGE 7 EXTENDED CONVERGENCE (N=512, delta=2 mm, 20 realizations)")
    print("=" * 76)
    print("   sigma_R^2   n_screens   sigma_I^2 +/- SE     (per-screen Rytov sR2/n)")
    for sR2 in (2.0, 4.0):
        for nsc in (10, 20, 40, 80, 160):
            m, se, sd, _ = sim_sci(sR2, 512, 2e-3, nsc, 20, seed0=9000)
            print("   %7.1f    %6d      %.4f +/- %.4f      %.3f"
                  % (sR2, nsc, m, se, sR2 / nsc))
    print("If sigma_I^2 keeps falling toward theory as n_screens grows, 10-40 "
          "was a plateau; if it stays put, the overshoot is real.")
    print("=" * 76)


def sweep(N, delta, n_screens, n_real, strengths):
    print("=" * 84)
    print("STAGE 7 SWEEP: split-step scintillation vs plane-wave Gamma-Gamma")
    print("=" * 84)
    print("grid N=%d, delta=%.1f mm; n_screens=%d; n_real=%d; lambda=%.0f nm, "
          "L=%.0f m" % (N, 1e3 * delta, n_screens, n_real, WAVELENGTH * 1e9, L))
    print("theory: gamma_gamma.sci_plane_andrews (coeffs UNVERIFIED-from-print)")
    print("-" * 84)
    print(" sigma_R^2  sigma_R  beta0   rho0/del   sim sigma_I^2 +/- SE     "
          "theory    sim/theory")
    rows = []
    for sR2 in strengths:
        m, se, sd, cn2 = sim_sci(sR2, N, delta, n_screens, n_real, seed0=12000)
        th = float(gg.sci_plane_andrews(sR2))
        b0 = float(np.sqrt(gg.beta0_squared(cn2, WAVELENGTH, L)))
        rd = rho0_over_delta(sR2, delta)
        ratio = m / th if th > 0 else float("nan")
        flag = "" if rd > 2.0 else "  (rho0/del<2: under-resolved)"
        print("  %7.2f   %5.2f   %5.2f   %6.2f     %.4f +/- %.4f      "
              "%.4f    %.3f%s" % (sR2, sR2 ** 0.5, b0, rd, m, se, th, ratio, flag))
        rows.append(dict(sigmaR2=sR2, sigmaR=sR2 ** 0.5, beta0=b0,
                         rho0_over_delta=rd, sim_sci=m, sim_se=se,
                         theory_sci=th, ratio=ratio, cn2=cn2))
    out = dict(meta=dict(N=N, delta=delta, n_screens=n_screens, n_real=n_real,
                         wavelength=WAVELENGTH, L=L,
                         theory="plane-wave Andrews; coeffs UNVERIFIED-from-print"),
               rows=rows)
    with open(os.path.join(_HERE, "strong_sweep.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("-" * 84)
    print("wrote strong_sweep.json")
    print("=" * 84)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--converge", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--N", type=int, default=1024)
    ap.add_argument("--delta", type=float, default=1e-3)
    ap.add_argument("--n-screens", type=int, default=20)
    ap.add_argument("--n-real", type=int, default=24)
    args = ap.parse_args()
    t0 = time.time()
    if args.probe:
        probe()
    if args.converge:
        converge()
    if args.sweep:
        strengths = [0.2, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0,
                     10.0, 12.0, 15.0, 20.0]
        sweep(args.N, args.delta, args.n_screens, args.n_real, strengths)
    print("[elapsed %.0f s]" % (time.time() - t0))


if __name__ == "__main__":
    main()
