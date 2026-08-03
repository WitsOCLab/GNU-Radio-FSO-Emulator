"""
propagation.py -- Stage 2: split-step angular-spectrum propagation.

A unit-amplitude plane wave is propagated through n_screens thin, strictly
periodic phase screens separated by vacuum slabs of thickness dz = L/n_screens,
using the Fresnel (paraxial) angular-spectrum transfer function and a SYMMETRIC
split-step (dz/2, screen, dz, screen, ..., dz/2) [Schmidt Ch. 9].

Each screen carries the phase of one slab, generated (Stage 1) with the
PROVISIONAL per-slab Fried parameter r0_i = r0_total * n_screens^(3/5). That
relation is derived, not independently verified; it is confirmed ONLY if the
aggregate scintillation index of the propagated field matches the plane-wave
Rytov variance (see verify_rytov.py and PROCESS.md).

The field is complex during propagation; we verify its intensity statistics
here. The real, non-negative scalar gain h is Stage 3 and is NOT built yet.

Equation ledger: PROCESS.md. Reference keys:
    [Schmidt] J. D. Schmidt, "Numerical Simulation of Optical Wave Propagation
              with Examples in MATLAB", SPIE Press, 2010.
    [Goodman] J. W. Goodman, "Introduction to Fourier Optics", 3rd ed., 2005.
    [AP]      L. C. Andrews & R. L. Phillips, "Laser Beam Propagation through
              Random Media", 2nd ed., SPIE Press, 2005.
"""

import numpy as np

from screens import generate_screen, KOLMOGOROV_L0, KOLMOGOROV_l0


def wavenumber(wavelength):
    """k = 2*pi / lambda  [rad/m]."""
    return 2.0 * np.pi / wavelength


def fried_parameter_plane(cn2, L, wavelength):
    """Plane-wave Fried parameter over a uniform path of length L:

        r0 = (0.42 * k^2 * Cn2 * L)^(-3/5),   k = 2*pi/lambda.

    Coefficient 0.42: [AP] Ch. 14 eq. 25/95 (project-lead VERIFIED). PROCESS.md.
    """
    k = wavenumber(wavelength)
    return (0.42 * k ** 2 * cn2 * L) ** (-3.0 / 5.0)


def per_screen_r0(r0_total, n_screens):
    """PROVISIONAL per-slab Fried parameter for n equal slabs (dz = L/n):

        r0_i = r0_total * n_screens^(3/5).

    Derived by applying the r0 definition to a slab of thickness dz = L/n
    (r0 ~ (Cn2 * dz)^(-3/5), so dz -> L/n multiplies r0 by n^(3/5)). NOT
    independently verified -- it is confirmed only if the Stage-2 aggregate
    sigma_I^2 matches sigma_R^2 across n_screens. PROCESS.md flags it PROVISIONAL.
    """
    return r0_total * n_screens ** (3.0 / 5.0)


def rytov_variance_plane(cn2, wavelength, L):
    """Plane-wave Rytov variance (weak-fluctuation scintillation target):

        sigma_R^2 = 1.23 * Cn2 * k^(7/6) * L^(11/6).

    [AP] 2nd ed, weak-fluctuation (Rytov) theory. CHAPTER/EQUATION TO CONFIRM
    from print copy; formula and coefficient 1.23 provided by the project lead
    and NOT independently traced here (PROCESS.md, flagged).
    """
    k = wavenumber(wavelength)
    return 1.23 * cn2 * k ** (7.0 / 6.0) * L ** (11.0 / 6.0)


def cn2_for_rytov(sigma_R2, wavelength, L):
    """Invert the Rytov formula to find the Cn2 giving a target sigma_R^2."""
    k = wavenumber(wavelength)
    return sigma_R2 / (1.23 * k ** (7.0 / 6.0) * L ** (11.0 / 6.0))


class AngularSpectrumPropagator:
    """Fresnel (paraxial) angular-spectrum free-space propagator on a periodic
    N x N grid of pitch delta.

    Transfer function over a distance dz [Goodman Ch. 4; Schmidt Ch. 7]:

        H(fx, fy) = exp(-i * pi * lambda * dz * (fx^2 + fy^2))

    fx, fy are cyclic spatial frequencies [cycles/m] from np.fft.fftfreq. The
    constant piston exp(i k dz) is omitted: it does not affect |U|^2.

    Sampling guard: the quadratic transfer phase must not alias on the grid,
    which requires dz <= N * delta^2 / lambda [Schmidt Ch. 7, transfer-function
    sampling criterion]. We raise if a caller exceeds it.
    """

    def __init__(self, N, delta, wavelength):
        self.N = int(N)
        self.delta = float(delta)
        self.wavelength = float(wavelength)
        fx = np.fft.fftfreq(self.N, d=self.delta)        # cycles/m
        FX, FY = np.meshgrid(fx, fx, indexing="ij")
        self.fsq = FX ** 2 + FY ** 2
        self.dz_max = self.N * self.delta ** 2 / self.wavelength

    def propagate(self, U, dz):
        if dz > self.dz_max:
            raise ValueError(
                "dz=%g m exceeds the angular-spectrum sampling limit "
                "N*delta^2/lambda=%g m (aliasing risk)" % (dz, self.dz_max))
        H = np.exp(-1j * np.pi * self.wavelength * dz * self.fsq)
        return np.fft.ifft2(np.fft.fft2(U) * H)


def split_step_plane_wave(screens, dz, prop):
    """Symmetric split-step propagation of a unit plane wave through a list of
    phase screens (each applied as exp(i*phi)), with vacuum slabs of thickness
    dz. Returns the complex field at the receiver plane z = n_screens * dz.

    Geometry (screens at slab centres): propagate dz/2 to the first slab
    centre, apply screen, propagate dz to the next centre, ..., apply the last
    screen, propagate dz/2 to z = L. Total path = n*dz = L. [Schmidt Ch. 9]
    """
    n = len(screens)
    U = np.ones((prop.N, prop.N), dtype=np.complex128)   # unit plane wave
    U = prop.propagate(U, dz / 2.0)
    for i, phi in enumerate(screens):
        U = U * np.exp(1j * phi)
        if i < n - 1:
            U = prop.propagate(U, dz)
    U = prop.propagate(U, dz / 2.0)
    return U


def scintillation_index(U):
    """Scintillation index sigma_I^2 = var(I)/mean(I)^2 of the field, I=|U|^2,
    estimated over the grid. (Definition: [AP] Ch. 1.)"""
    I = np.abs(U) ** 2
    return float(I.var() / I.mean() ** 2)


def propagate_kolmogorov_plane(cn2, wavelength, L, N, delta, n_screens, seed):
    """Build n_screens Kolmogorov-limit screens (per-slab r0) and split-step a
    unit plane wave through them. Returns the complex receiver field U.

    Kolmogorov limit (large L0, tiny l0) makes sigma_R^2 = 1.23 Cn2 k^(7/6)
    L^(11/6) the correct analytic target (PROCESS.md). `seed` seeds the whole
    realization; each screen gets a distinct derived seed.
    """
    r0_total = fried_parameter_plane(cn2, L, wavelength)
    r0_i = per_screen_r0(r0_total, n_screens)
    dz = L / float(n_screens)
    prop = AngularSpectrumPropagator(N, delta, wavelength)
    screens = [generate_screen(r0_i, N, delta, KOLMOGOROV_L0, KOLMOGOROV_l0,
                               seed=seed * 1000 + i) for i in range(n_screens)]
    return split_step_plane_wave(screens, dz, prop)
