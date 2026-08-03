"""
verify_screens.py -- Stage 1 acceptance test.

Verifies that the aotools ft_phase_screen output has the correct von Karman
phase structure function, by comparing the ENSEMBLE-AVERAGED empirical
structure function of the generated screens against the theoretical target
aotools.turbulence.structure_function_vk (and structure_function_kolmogorov in
the Kolmogorov limit -- the screen type the Stage-2 propagator actually uses).

Expected, documented limitation: the plain FFT screen (no subharmonics, no
oversampling -- required for strict periodicity) under-represents spatial
frequencies below the grid fundamental 1/(N*delta), so the empirical structure
function sags below theory at LARGE separations. We therefore report agreement
over the reliable inertial window [4*delta, N*delta/4] and show the large-r
deficit explicitly. (PROCESS.md, Stage 1.)
"""

import numpy as np

from aotools.turbulence.slopecovariance import (structure_function_vk,
                                                structure_function_kolmogorov)
from screens import (ensemble_structure_function, KOLMOGOROV_L0,
                     KOLMOGOROV_l0)


def _report(name, sep_m, D_emp, D_theory, delta, N):
    lo, hi = 4.0 * delta, N * delta / 4.0
    win = (sep_m >= lo) & (sep_m <= hi)
    rel = D_emp[win] / D_theory[win] - 1.0
    print("\n--- %s ---" % name)
    print("inertial window: %.3f m .. %.3f m (%d separations)"
          % (lo, hi, win.sum()))
    print("  mean |rel err| in window : %6.2f %%" % (100 * np.mean(np.abs(rel))))
    print("  max  |rel err| in window : %6.2f %%" % (100 * np.max(np.abs(rel))))
    print("  signed mean rel err      : %+6.2f %% (negative = FFT low-freq "
          "deficit)" % (100 * np.mean(rel)))
    # a few sample separations across the whole range
    print("   sep[m]   D_emp     D_theory   rel%")
    for s in np.linspace(sep_m[0], sep_m[-1], 8):
        i = int(np.argmin(np.abs(sep_m - s)))
        print("  %7.3f  %8.4f  %8.4f  %+6.1f"
              % (sep_m[i], D_emp[i], D_theory[i],
                 100 * (D_emp[i] / D_theory[i] - 1.0)))
    return float(np.mean(np.abs(rel)))


def main():
    print("=" * 70)
    print("STAGE 1 VERIFICATION: phase-screen structure function vs theory")
    print("=" * 70)

    # ----- Case A: von Karman with a RESOLVABLE outer scale (L0 < screen) ----
    # so the outer-scale rolloff is visible within the grid and we genuinely
    # test structure_function_vk, not just its Kolmogorov limit.
    N, delta = 512, 4e-3              # 2.048 m screen
    r0, L0, l0 = 0.10, 2.0, 1e-3      # m ; L0 ~ screen size ; l0 << delta range
    n_real = 30
    max_sep = N // 2
    sep_m, D_emp = ensemble_structure_function(r0, N, delta, L0, l0,
                                               n_real, max_sep, base_seed=1000)
    D_vk = structure_function_vk(sep_m, r0, L0)
    print("\nParams: N=%d, delta=%.4f m, r0=%.3f m, L0=%.2f m, l0=%.0e m, "
          "%d screens" % (N, delta, r0, L0, l0, n_real))
    errA = _report("von Karman (L0=%.1f m) vs structure_function_vk" % L0,
                   sep_m, D_emp, D_vk, delta, N)

    # ----- Case B: Kolmogorov limit (the Stage-2 propagator screen type) -----
    sep_m, D_emp = ensemble_structure_function(r0, N, delta, KOLMOGOROV_L0,
                                               KOLMOGOROV_l0, n_real, max_sep,
                                               base_seed=2000)
    D_k = structure_function_kolmogorov(sep_m, r0)
    print("\nParams: N=%d, delta=%.4f m, r0=%.3f m, L0=%.0e m, l0=%.0e m, "
          "%d screens" % (N, delta, r0, KOLMOGOROV_L0, KOLMOGOROV_l0, n_real))
    errB = _report("Kolmogorov limit vs 6.88 (r/r0)^(5/3)",
                   sep_m, D_emp, D_k, delta, N)

    print("\n" + "=" * 70)
    print("STAGE 1 SUMMARY: mean |rel err| in inertial window -- "
          "vK %.2f%% , Kolmogorov %.2f%%" % (100 * errA, 100 * errB))
    print("Large-separation deficit (FFT low-freq truncation, no subharmonics) "
          "is expected and documented; it does not affect Fresnel-scale\n"
          "scintillation, which Stage 2 verifies against the Rytov target.")
    print("=" * 70)


if __name__ == "__main__":
    main()
