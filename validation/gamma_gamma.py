"""
gamma_gamma.py -- theoretical point-detector scintillation index vs turbulence
strength, for comparing the split-step propagator in the strong-fluctuation
regime (Stage 7).

REFERENCE / FLAGS (read before trusting the numbers):
  The plane-wave scintillation index used here is the Andrews & Phillips
  "effective-parameter" (Gamma-Gamma-consistent) result

      sigma_I^2(plane) = exp[ sigma_lnX^2 + sigma_lnY^2 ] - 1
      sigma_lnX^2 = 0.49 sR2 / (1 + 1.11 sR2^(6/5))^(7/6)     (large-scale)
      sigma_lnY^2 = 0.51 sR2 / (1 + 0.69 sR2^(6/5))^(5/6)     (small-scale)

  with sR2 = sigma_R^2 = 1.23 Cn2 k^(7/6) L^(11/6) the PLANE-WAVE Rytov
  variance (note sigma_R^(12/5) = (sigma_R^2)^(6/5) = sR2^1.2).

  ** UNVERIFIED-FROM-PRINT: ** the coefficients (0.49, 1.11, 0.51, 0.69) and
  exponents (7/6, 5/6, 6/5), and the exact equation number (the project lead
  cited "eq. ~51 / fig. 14.6" of Andrews & Phillips 2nd ed, Ch.14), are taken
  from the established A&P plane-wave scintillation-index literature but have
  NOT been confirmed against the print copy. Flagged for the project lead to
  close; do not treat the coefficients as print-verified.

  WAVE-TYPE NOTE: the project lead's strength parameter beta0^2 = 0.5 Cn2
  k^(7/6) L^(11/6) is the SPHERICAL-wave Rytov variance. The simulation is a
  PLANE wave, so the consistent comparison is the PLANE-wave curve above vs
  sigma_R^2 (1.23). beta0 is provided only for cross-referencing the chapter's
  x-axis; it is sqrt(0.5/1.23) = 0.638 times sigma_R.
"""

import numpy as np


def k_wavenumber(wavelength):
    return 2.0 * np.pi / wavelength


def rytov_variance_plane(cn2, wavelength, L):
    """Plane-wave Rytov variance sigma_R^2 = 1.23 Cn2 k^(7/6) L^(11/6) ([AP])."""
    k = k_wavenumber(wavelength)
    return 1.23 * cn2 * k ** (7.0 / 6.0) * L ** (11.0 / 6.0)


def beta0_squared(cn2, wavelength, L):
    """Project-lead strength parameter beta0^2 = 0.5 Cn2 k^(7/6) L^(11/6)
    (spherical-wave Rytov variance). UNVERIFIED-from-print; cross-reference
    only (the plane-wave sim is compared vs sigma_R^2)."""
    k = k_wavenumber(wavelength)
    return 0.5 * cn2 * k ** (7.0 / 6.0) * L ** (11.0 / 6.0)


def sci_plane_andrews(sigmaR2):
    """Plane-wave point-detector scintillation index vs plane-wave Rytov
    variance sigmaR2. Coefficients UNVERIFIED-from-print (see module header)."""
    sR2 = np.asarray(sigmaR2, dtype=float)
    ln_x = 0.49 * sR2 / (1.0 + 1.11 * sR2 ** (6.0 / 5.0)) ** (7.0 / 6.0)
    ln_y = 0.51 * sR2 / (1.0 + 0.69 * sR2 ** (6.0 / 5.0)) ** (5.0 / 6.0)
    return np.exp(ln_x + ln_y) - 1.0


def coherence_radius_plane(cn2, wavelength, L):
    """Plane-wave spatial coherence radius rho0 = (1.46 Cn2 k^2 L)^(-3/5)
    ([AP]); used to flag grid under-resolution (rho0 must stay > ~2*delta).
    Coefficient 1.46 UNVERIFIED-from-print."""
    k = k_wavenumber(wavelength)
    return (1.46 * cn2 * k ** 2 * L) ** (-3.0 / 5.0)


if __name__ == "__main__":
    # quick shape sanity: peak and saturation of the plane-wave curve
    sR2 = np.logspace(-1, 1.6, 40)
    si = sci_plane_andrews(sR2)
    ipk = int(np.argmax(si))
    print("plane-wave Andrews sigma_I^2: peak %.3f at sigma_R^2=%.2f "
          "(sigma_R=%.2f); sigma_I^2 -> %.3f at sigma_R^2=%.0f (saturation)"
          % (si[ipk], sR2[ipk], np.sqrt(sR2[ipk]), si[-1], sR2[-1]))
