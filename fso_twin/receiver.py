"""
receiver.py -- Stage 3: aperture integration -> real, non-negative scalar gain.

The turbulence gain is the power collected through the receiver aperture
divided by the CLEAR-AIR power collected through the SAME aperture:

    h = P_turb / P_clear = (sum_aperture |U|^2) / (sum_aperture |U_clear|^2)

For a unit plane wave the clear-air intensity is 1 everywhere, so
P_clear = (number of aperture pixels) and h reduces to the MEAN intensity over
the aperture. All numerical (delta^2) and geometric factors divide out, and
clear air gives h = 1 exactly. h is real and non-negative by construction
(it is a ratio of sums of |.|^2) and is asserted so.

Weather (Beer-Lambert) and geometric capture are kept as SEPARATE scalar
multipliers applied AFTER the turbulence gain (link_gain), never folded into
the field integration.

Equation ledger: PROCESS.md. Reference keys: [AP], [Schmidt] (see PROCESS.md).
"""

import numpy as np


def aperture_mask(N, delta, diameter):
    """Boolean mask of the circular receiver aperture of given diameter [m],
    centred on the grid."""
    c = (N - 1) / 2.0
    yy, xx = np.mgrid[0:N, 0:N]
    r = np.hypot((xx - c) * delta, (yy - c) * delta)
    mask = r <= (diameter / 2.0)
    if not mask.any():
        raise ValueError("aperture diameter %g m selects no pixels on the grid "
                         "(delta=%g m)" % (diameter, delta))
    return mask


def turbulence_gain(U, mask):
    """Real, non-negative turbulence gain h = mean(|U|^2) over the aperture.

    Equals P_turb / P_clear because clear-air |U_clear|^2 = 1, so
    P_clear = mask.sum(); clear air therefore yields h = 1 exactly.
    """
    I = np.abs(U) ** 2
    h = float(I[mask].sum() / mask.sum())
    assert np.isreal(h) and np.isfinite(h) and h >= 0.0, \
        "turbulence gain must be real, finite, non-negative"
    return h


def beer_lambert_transmittance(extinction_coeff, L):
    """Weather transmittance, Beer-Lambert law:  T = exp(-sigma * L), with
    sigma the extinction coefficient [1/m] and L the path [m]. SEPARATE scalar
    multiplier, not folded into the field integration. The Beer-Lambert form is
    standard ([AP] Ch.1 atmospheric attenuation); the VALUE of sigma (e.g. Kim
    / Kruse fog models) is out of Stage-3 scope and supplied by the caller.
    """
    T = float(np.exp(-extinction_coeff * L))
    assert 0.0 <= T <= 1.0
    return T


def link_gain(h_turb, weather_T=1.0, geometric_G=1.0):
    """Final scalar gain = turbulence * weather * geometric, kept SEPARATE.

    geometric_G defaults to 1.0: for plane-wave illumination there is no
    geometric capture loss (the clear-air normalisation already removes
    geometry). A finite-beam capture factor would enter here, unchanged in
    form. Result is asserted real and non-negative.
    """
    g = float(h_turb * weather_T * geometric_G)
    assert np.isfinite(g) and g >= 0.0
    return g


def aperture_averaged_sci(I, N, delta, diameter):
    """Scintillation index sigma_I^2(D) = var/mean^2 of the APERTURE-AVERAGED
    intensity, over all aperture positions on the grid.

    Computed by circular convolution of I with a normalised uniform disk (the
    grid/field are periodic, so circular convolution is the consistent
    operator). As D shrinks to one pixel this recovers the point scintillation
    var(I)/mean(I)^2. As D grows the fractional variance falls -- aperture
    averaging.
    """
    mask = aperture_mask(N, delta, diameter).astype(np.float64)
    mask /= mask.sum()
    h_field = np.fft.ifft2(np.fft.fft2(I) *
                           np.fft.fft2(np.fft.ifftshift(mask))).real
    return float(h_field.var() / h_field.mean() ** 2)
