"""Lorentzian / pseudo-Voigt / true-Voigt peak shapes for the spectral engine.

Companions to :func:`fermiviewer.calc.spectral_fit.gaussian` — same
:class:`~fermiviewer.calc.spectral_fit.Component` builder style, same
``amp`` = peak HEIGHT at ``center`` convention, so any of these can be
dropped into :func:`~fermiviewer.calc.spectral_fit.fit_spectrum` next to
Gaussians, backgrounds, etc. Each shape has a matching analytic net-area
helper (``<shape>_area``), the integral over the whole real line, used
wherever a fit result needs a net intensity rather than a peak height
(e.g. :mod:`fermiviewer.calc.eds_peakfit`).

Imports :class:`Component` from :mod:`spectral_fit` only — never the
reverse (spectral_fit is the generic engine; this module is one of its
consumers, alongside eds_peakfit/eels_model).

Pure library: numpy + scipy.special only. No fastapi/pydantic/route
imports (enforced by tests/test_repo_integrity.py).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.special import voigt_profile

from fermiviewer.calc.spectral_fit import Component, gaussian_area

__all__ = [
    "lorentzian",
    "lorentzian_area",
    "pseudo_voigt",
    "pseudo_voigt_area",
    "voigt",
    "voigt_area",
]

_EPS = 1e-12
_INF = math.inf
# FWHM_gaussian = 2*sqrt(2*ln2)*sigma; sharing that FWHM, the matching
# Lorentzian HWHM is FWHM/2 = sqrt(2*ln2)*sigma.
_FWHM_TO_GAMMA = math.sqrt(2.0 * math.log(2.0))


def lorentzian(
    name: str,
    *,
    amp: float,
    center: float,
    gamma: float,
    amp_bounds: tuple[float, float] = (0.0, _INF),
    center_bounds: tuple[float, float] | None = None,
    gamma_bounds: tuple[float, float] = (_EPS, _INF),
) -> Component:
    """A Lorentzian peak: amp·γ²/((E−center)²+γ²).

    ``amp`` is the peak HEIGHT at ``center`` (not the net area); ``gamma``
    is the half-width at half-maximum (HWHM). See :func:`lorentzian_area`
    for the integrated net area, amp·π·γ.
    """
    if center_bounds is None:
        center_bounds = (-_INF, _INF)

    def f(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
        a, c, g = p
        g = max(float(g), _EPS)
        return np.asarray(
            a * g * g / ((energy - c) ** 2 + g * g), dtype=np.float64
        )

    return Component(
        name, ("amp", "center", "gamma"), f,
        (amp, center, gamma),
        (amp_bounds[0], center_bounds[0], gamma_bounds[0]),
        (amp_bounds[1], center_bounds[1], gamma_bounds[1]),
    )


def lorentzian_area(amp: float, gamma: float) -> float:
    """Analytic net area of :func:`lorentzian`: amp·π·γ."""
    return float(amp) * math.pi * float(gamma)


def pseudo_voigt(
    name: str,
    *,
    amp: float,
    center: float,
    sigma: float,
    eta: float,
    amp_bounds: tuple[float, float] = (0.0, _INF),
    center_bounds: tuple[float, float] | None = None,
    sigma_bounds: tuple[float, float] = (_EPS, _INF),
    eta_bounds: tuple[float, float] = (0.0, 1.0),
) -> Component:
    """A pseudo-Voigt peak: η·L(E) + (1−η)·G(E).

    G and L share one FWHM derived from the Gaussian ``sigma`` parameter
    (FWHM = 2√(2 ln 2)·sigma); the Lorentzian's matching HWHM is then
    γ = FWHM/2 = √(2 ln 2)·sigma. Both terms are individually normalised
    to height 1 at ``center``, so their η-weighted sum is also height 1
    at center — ``amp`` is therefore the peak HEIGHT at ``center`` for
    the combined curve, same convention as :func:`gaussian` /
    :func:`lorentzian`. ``eta`` is bounded to [0, 1]: η=0 is pure
    Gaussian, η=1 is pure Lorentzian. See :func:`pseudo_voigt_area`.
    """
    if center_bounds is None:
        center_bounds = (-_INF, _INF)

    def f(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
        a, c, s, eta_p = p
        s = max(float(s), _EPS)
        eta_p = float(np.clip(eta_p, 0.0, 1.0))
        g = _FWHM_TO_GAMMA * s
        gauss = np.exp(-0.5 * ((energy - c) / s) ** 2)
        lor = g * g / ((energy - c) ** 2 + g * g)
        return np.asarray(a * (eta_p * lor + (1.0 - eta_p) * gauss), dtype=np.float64)

    return Component(
        name, ("amp", "center", "sigma", "eta"), f,
        (amp, center, sigma, eta),
        (amp_bounds[0], center_bounds[0], sigma_bounds[0], eta_bounds[0]),
        (amp_bounds[1], center_bounds[1], sigma_bounds[1], eta_bounds[1]),
    )


def pseudo_voigt_area(amp: float, sigma: float, eta: float) -> float:
    """Analytic net area of :func:`pseudo_voigt`.

    The η-weighted sum of each term's own area at the shared FWHM:
    (1−η)·amp·sigma·√(2π) + η·amp·π·γ, γ = √(2 ln 2)·sigma.
    """
    gamma = _FWHM_TO_GAMMA * float(sigma)
    eta = float(eta)
    return (1.0 - eta) * gaussian_area(amp, sigma) + eta * lorentzian_area(amp, gamma)


def voigt(
    name: str,
    *,
    amp: float,
    center: float,
    sigma: float,
    gamma: float,
    amp_bounds: tuple[float, float] = (0.0, _INF),
    center_bounds: tuple[float, float] | None = None,
    sigma_bounds: tuple[float, float] = (_EPS, _INF),
    gamma_bounds: tuple[float, float] = (0.0, _INF),
) -> Component:
    """A true Voigt peak: the Gaussian(sigma)⊛Lorentzian(gamma) convolution.

    Built on :func:`scipy.special.voigt_profile`, which returns a
    unit-AREA profile; this builder renormalises by the profile's own
    center value so ``amp`` stays the peak HEIGHT at ``center`` — the
    same convention every other shape here uses:

        value(E) = amp · voigt_profile(E−center, sigma, gamma)
                       / voigt_profile(0, sigma, gamma)

    ``sigma`` is the Gaussian standard deviation, ``gamma`` the
    Lorentzian HWHM (as ``gamma`` → 0 this reduces to a pure Gaussian).
    See :func:`voigt_area` for the integrated net area.
    """
    if center_bounds is None:
        center_bounds = (-_INF, _INF)

    def f(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
        a, c, s, g = p
        s = max(float(s), _EPS)
        g = max(float(g), 0.0)
        norm = max(float(voigt_profile(0.0, s, g)), _EPS)
        return np.asarray(
            a * voigt_profile(energy - c, s, g) / norm, dtype=np.float64
        )

    return Component(
        name, ("amp", "center", "sigma", "gamma"), f,
        (amp, center, sigma, gamma),
        (amp_bounds[0], center_bounds[0], sigma_bounds[0], gamma_bounds[0]),
        (amp_bounds[1], center_bounds[1], sigma_bounds[1], gamma_bounds[1]),
    )


def voigt_area(amp: float, sigma: float, gamma: float) -> float:
    """Analytic net area of :func:`voigt`: amp / voigt_profile(0, sigma, gamma).

    ``voigt_profile`` is normalised to unit area, so the height-normalised
    curve built by :func:`voigt` has net area amp·∫profile/profile(0) =
    amp/profile(0).
    """
    s = max(float(sigma), _EPS)
    g = max(float(gamma), 0.0)
    norm = max(float(voigt_profile(0.0, s, g)), _EPS)
    return float(amp) / norm
