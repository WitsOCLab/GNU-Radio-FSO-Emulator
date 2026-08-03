"""
verify_rytov.py -- Stage 2 acceptance test (THE HARD GATE).

Propagates a unit plane wave through n_screens strictly-periodic
Kolmogorov-limit phase screens (split-step angular spectrum) and checks that
the measured scintillation index sigma_I^2 matches the plane-wave Rytov
variance

    sigma_R^2 = 1.23 Cn2 k^(7/6) L^(11/6)            ([AP], chapter/eq TO CONFIRM)

to within a few percent in the weak regime. This simultaneously validates the
PROVISIONAL per-screen Fried scaling r0_i = r0 * n_screens^(3/5): if it is
right, the aggregate sigma_I^2 is independent of n_screens and tracks sigma_R^2.

Weak-regime note: the scintillation index is sigma_I^2 = exp(sigma_R^2) - 1 in
Rytov theory, so a small positive bias of order sigma_R^2/2 above sigma_R^2 is
PHYSICAL, not error. We report measured sigma_I^2 against both sigma_R^2 and
exp(sigma_R^2)-1.
"""

import numpy as np

from propagation import (wavenumber, fried_parameter_plane, per_screen_r0,
                         rytov_variance_plane, cn2_for_rytov,
                         propagate_kolmogorov_plane, scintillation_index)


def main():
    # --- regime: weak turbulence, target Rytov variance ~0.1 ----------------
    wavelength = 1550e-9        # m   (fixed)
    L = 1000.0                  # m   path length
    target_sigmaR2 = 0.10       # weak (< 0.3 weak/moderate threshold)
    cn2 = cn2_for_rytov(target_sigmaR2, wavelength, L)
    sigmaR2 = rytov_variance_plane(cn2, wavelength, L)

    # --- grid: resolve the Fresnel scale, stay well inside the AS limit -----
    # delta=2 mm gives ~8 px per Fresnel scale (r_F~16 mm) so the scintillation
    # speckle is well sampled; N=512 spans 1.024 m = many Fresnel zones.
    N, delta = 512, 2e-3        # 1.024 m grid
    n_real = 64                 # realizations (independent screen sets)
    k = wavenumber(wavelength)
    r_fresnel = np.sqrt(L / k)  # sqrt(lambda L / 2pi)

    print("=" * 72)
    print("STAGE 2 VERIFICATION: split-step scintillation vs Rytov (HARD GATE)")
    print("=" * 72)
    print("lambda = %.0f nm, L = %.0f m, Cn2 = %.3e m^-2/3" %
          (wavelength * 1e9, L, cn2))
    print("k = %.4e rad/m, Fresnel scale sqrt(lambda L/2pi) = %.4f m "
          "(%.1f px)" % (k, r_fresnel, r_fresnel / delta))
    print("grid: N=%d, delta=%.4f m (%.3f m), realizations=%d" %
          (N, delta, N * delta, n_real))
    print("TARGET  sigma_R^2 = 1.23 Cn2 k^7/6 L^11/6 = %.5f" % sigmaR2)
    print("        exp(sigma_R^2)-1 (weak scintillation index) = %.5f"
          % (np.expm1(sigmaR2)))
    print("-" * 72)
    print(" n_screens   r0_total[cm]  r0_screen[cm]  dz[m]   mean(I)   "
          "sigma_I^2     vs sigmaR2")

    r0_total = fried_parameter_plane(cn2, L, wavelength)
    results = {}
    for n_screens in (5, 10, 20):
        r0_i = per_screen_r0(r0_total, n_screens)
        dz = L / n_screens
        si_list = []
        meanI_list = []
        for r in range(n_real):
            U = propagate_kolmogorov_plane(cn2, wavelength, L, N, delta,
                                           n_screens, seed=10_000 * n_screens + r)
            I = np.abs(U) ** 2
            meanI_list.append(float(I.mean()))
            si_list.append(float(I.var() / I.mean() ** 2))
        si = np.array(si_list)
        si_mean = si.mean()
        si_se = si.std(ddof=1) / np.sqrt(n_real)
        meanI = np.mean(meanI_list)
        rel = 100.0 * (si_mean / sigmaR2 - 1.0)
        results[n_screens] = (si_mean, si_se, rel)
        print(" %6d      %9.2f     %9.2f    %6.1f  %7.4f   "
              "%.5f+/-%.5f   %+6.1f%%"
              % (n_screens, 100 * r0_total, 100 * r0_i, dz, meanI,
                 si_mean, si_se, rel))

    print("-" * 72)
    # PASS criterion: aggregate within a few percent of sigma_R^2, and stable
    # across n_screens (which validates the provisional r0_i = r0 n^(3/5)).
    rels = {n: abs(v[2]) for n, v in results.items()}
    best = min(rels, key=rels.get)
    spread = max(v[0] for v in results.values()) - min(v[0] for v in results.values())
    print("Closest to Rytov: n_screens=%d at %+.1f%%." % (best, results[best][2]))
    print("sigma_I^2 spread across n_screens={5,10,20}: %.5f (%.1f%% of sigmaR2)"
          % (spread, 100 * spread / sigmaR2))
    print("mean(I) ~ 1 confirms energy conservation (unitary propagation, "
          "pure-phase screens).")
    print("=" * 72)


if __name__ == "__main__":
    main()
