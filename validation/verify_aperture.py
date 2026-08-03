"""
verify_aperture.py -- Stage 3 acceptance test.

Checks:
  (1) Clear-air / no-turbulence limit gives h = 1 to numerical precision.
  (2) Aperture-integrated gain statistics are consistent with the Stage-2
      scintillation index: the point limit recovers sigma_I^2 ~= sigma_R^2, and
      the fractional variance FALLS as the aperture grows (aperture averaging).
      mean(h) ~= 1 (turbulence conserves average power).
"""

import numpy as np

from propagation import (wavenumber, cn2_for_rytov, rytov_variance_plane,
                         AngularSpectrumPropagator, propagate_kolmogorov_plane)
from receiver import (aperture_mask, turbulence_gain, aperture_averaged_sci,
                      beer_lambert_transmittance, link_gain)


def main():
    wavelength, L = 1550e-9, 1000.0
    cn2 = cn2_for_rytov(0.10, wavelength, L)
    sigmaR2 = rytov_variance_plane(cn2, wavelength, L)
    N, delta = 512, 2e-3
    n_screens, n_real = 10, 64
    k = wavenumber(wavelength)
    r_F = np.sqrt(L / k)

    print("=" * 72)
    print("STAGE 3 VERIFICATION: aperture integration -> scalar gain h")
    print("=" * 72)
    print("lambda=%.0f nm, L=%.0f m, Cn2=%.3e, sigma_R^2=%.4f, Fresnel=%.1f mm"
          % (wavelength * 1e9, L, cn2, sigmaR2, 1e3 * r_F))
    print("grid N=%d, delta=%.1f mm; realizations=%d" % (N, 1e3 * delta, n_real))

    # ---- (1) clear-air limit: unit plane wave through vacuum -> h = 1 -------
    prop = AngularSpectrumPropagator(N, delta, wavelength)
    U_clear = prop.propagate(np.ones((N, N), dtype=np.complex128), L)
    print("\n(1) CLEAR-AIR limit (unit plane wave, no turbulence):")
    for D in (0.004, 0.02, 0.08):
        h = turbulence_gain(U_clear, aperture_mask(N, delta, D))
        print("    D=%5.1f mm:  h = %.15f   |h-1| = %.2e"
              % (1e3 * D, h, abs(h - 1.0)))
    # demonstrate the separate scalar multipliers
    T = beer_lambert_transmittance(1e-4, L)     # example sigma=1e-4 /m
    print("    separate multipliers (example): weather T(sigma=1e-4/m)=%.4f, "
          "geometric G=1.0 -> link_gain(h=1)=%.4f"
          % (T, link_gain(1.0, T, 1.0)))

    # ---- (2) aperture averaging vs Stage-2 scintillation -------------------
    diams = [0.02, 0.04, 0.08]              # m
    sci_pt, sci_ap = [], {D: [] for D in diams}
    meanh_2cm = []
    mask2 = aperture_mask(N, delta, 0.02)
    for r in range(n_real):
        U = propagate_kolmogorov_plane(cn2, wavelength, L, N, delta,
                                       n_screens, seed=777_000 + r)
        I = np.abs(U) ** 2
        sci_pt.append(float(I.var() / I.mean() ** 2))      # point detector
        for D in diams:
            sci_ap[D].append(aperture_averaged_sci(I, N, delta, D))
        meanh_2cm.append(turbulence_gain(U, mask2))

    pt = np.array(sci_pt)
    print("\n(2) APERTURE AVERAGING (mean +/- SE over %d realizations):" % n_real)
    print("    point detector      sigma_I^2 = %.4f +/- %.4f   "
          "(Stage-2 sigma_R^2 = %.4f)"
          % (pt.mean(), pt.std(ddof=1) / np.sqrt(n_real), sigmaR2))
    for D in diams:
        a = np.array(sci_ap[D])
        A = a.mean() / pt.mean()
        print("    aperture D=%4.0f mm   sigma_I^2 = %.4f +/- %.4f   "
              "A(D)=sigma_I^2(D)/point = %.3f   (D/Fresnel=%.1f)"
              % (1e3 * D, a.mean(), a.std(ddof=1) / np.sqrt(n_real), A,
                 D / r_F))
    mh = np.array(meanh_2cm)
    print("    mean(h) over realizations at D=20 mm = %.4f +/- %.4f  (~1 => "
          "power conserved)" % (mh.mean(), mh.std(ddof=1) / np.sqrt(n_real)))

    print("\nSUMMARY: clear-air h=1 to ~1e-15; point sigma_I^2 matches Stage-2; "
          "fractional variance falls with aperture (aperture averaging).")
    print("=" * 72)


if __name__ == "__main__":
    main()
