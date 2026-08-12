"""EDS peak deconvolution: constrained multi-Gaussian fit for overlaps.

Resolves endemic EDS line overlaps (S-K/Mo-L/Pb-M, Ti-Kβ/V-Kα, …) that
window-integration mis-assigns, by fitting all elements' characteristic
peaks jointly. Each element contributes one Gaussian whose **center** is
its known line energy (from the :mod:`eds` line table) and whose **width**
is fixed from the Fano detector-resolution model (:mod:`eds_calib`); only
the per-element **amplitude** is free. A joint least-squares fit then
partitions blended counts among elements by their fixed line shapes.

The integrated net area of each peak (``amp·σ·√(2π)``, via
:func:`~fermiviewer.calc.spectral_fit.gaussian_area`) feeds the existing
:func:`fermiviewer.calc.eds.cliff_lorimer` / ``zaf_correction`` maps
unchanged — this module only changes how net intensities are *measured*.

Built on :mod:`fermiviewer.calc.spectral_fit`; pure library. Peaks default
to Gaussian (EDS lines are detector-resolution-limited); passing
``lorentzian_hwhm_kev > 0`` to :func:`element_peak_component` /
:func:`fit_peaks` / :func:`quantify_peaks` opt in to a fixed-γ Voigt
profile (:mod:`fermiviewer.calc.peak_shapes`) for the natural linewidth —
``0.0`` (default) is exactly the original Gaussian-only path.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.special import voigt_profile

from fermiviewer.calc.eds import ClResult, cliff_lorimer, line_energy
from fermiviewer.calc.eds_calib import fano_sigma_kev
from fermiviewer.calc.peak_shapes import voigt_area
from fermiviewer.calc.spectral_fit import Component, FitResult, fit_spectrum, gaussian_area

__all__ = [
    "PeakFitResult",
    "element_peak_component",
    "fit_peaks",
    "quantify_peaks",
]


def element_peak_component(
    symbol: str,
    center_kev: float,
    sigma_kev: float,
    amp0: float,
    *,
    center_tol_kev: float = 0.0,
    lorentzian_hwhm_kev: float = 0.0,
) -> Component:
    """One element's characteristic peak as a fit component.

    Amplitude-only (``center_tol_kev == 0``, the constrained default) so
    the line position and Fano width are fixed; with a tolerance the
    center may wander ±``center_tol_kev`` (a 2-param ``amp, center``) to
    absorb a small residual energy miscalibration. ``sigma`` is always
    fixed (the Fano model is trusted).

    ``lorentzian_hwhm_kev`` is ``0.0`` by default — a pure Gaussian,
    identical to the original behaviour. Passing a positive natural-
    linewidth HWHM (keV) switches the peak shape to a Voigt profile
    (Gaussian ``sigma_kev`` ⊛ Lorentzian ``lorentzian_hwhm_kev``, both
    fixed) via :func:`fermiviewer.calc.peak_shapes.voigt`'s height
    convention; only amplitude (and optionally center) stays free.
    """
    s = max(float(sigma_kev), 1e-9)
    g = max(float(lorentzian_hwhm_kev), 0.0)

    if g > 0.0:
        norm = max(float(voigt_profile(0.0, s, g)), 1e-300)

        if center_tol_kev > 0.0:

            def fv2(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
                a, c = p
                return np.asarray(
                    a * voigt_profile(energy - c, s, g) / norm, dtype=np.float64
                )

            return Component(
                symbol, ("amp", "center"), fv2,
                (amp0, center_kev),
                (0.0, center_kev - center_tol_kev),
                (np.inf, center_kev + center_tol_kev),
            )

        def fv1(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
            (a,) = p
            return np.asarray(
                a * voigt_profile(energy - center_kev, s, g) / norm, dtype=np.float64
            )

        return Component(symbol, ("amp",), fv1, (amp0,), (0.0,), (np.inf,))

    if center_tol_kev > 0.0:

        def f2(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
            a, c = p
            return np.asarray(a * np.exp(-0.5 * ((energy - c) / s) ** 2), dtype=np.float64)

        return Component(
            symbol, ("amp", "center"), f2,
            (amp0, center_kev),
            (0.0, center_kev - center_tol_kev),
            (np.inf, center_kev + center_tol_kev),
        )

    def f1(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
        (a,) = p
        return np.asarray(a * np.exp(-0.5 * ((energy - center_kev) / s) ** 2), dtype=np.float64)

    return Component(symbol, ("amp",), f1, (amp0,), (0.0,), (np.inf,))


@dataclass(frozen=True)
class PeakFitResult:
    """Outcome of :func:`fit_peaks`.

    ``net_areas`` is the integrated counts per element — ``amp·σ·√(2π)``
    for the default Gaussian peaks, or the Voigt net area (see
    :func:`fermiviewer.calc.peak_shapes.voigt_area`) when
    ``lorentzian_hwhm_kev`` was passed — ordered to match ``elements``;
    ``net_area_errors`` propagates the amplitude 1σ through the same
    area scale. Elements with no known line get NaN and no component.
    """

    elements: list[str]
    net_areas: dict[str, float]
    net_area_errors: dict[str, float]
    line_energies: dict[str, float]
    lines: dict[str, str]
    fit: FitResult


def _amp0(energy: np.ndarray, counts: np.ndarray, center: float, sigma: float) -> float:
    """Initial amplitude guess: peak counts within ±2σ of the line."""
    sel = (energy >= center - 2 * sigma) & (energy <= center + 2 * sigma)
    if not sel.any():
        return 1.0
    return max(float(counts[sel].max()), 1.0)


def fit_peaks(
    energy: np.ndarray,
    counts: np.ndarray,
    elements: Sequence[str],
    *,
    beam_kv: float = 200.0,
    background: Component | Sequence[Component] | None = None,
    weights: np.ndarray | str | None = "poisson",
    center_tol_kev: float = 0.0,
    lorentzian_hwhm_kev: float = 0.0,
) -> PeakFitResult:
    """Jointly fit per-element peaks (+ optional background) to a spectrum.

    Parameters
    ----------
    energy, counts : 1-D keV axis + spectrum (equal length).
    elements : symbols to fit. The principal line (K→L→M by overvoltage at
        ``beam_kv``) is used; width is the Fano FWHM at that energy.
    background : an optional pre-built :class:`Component` (or several) —
        e.g. ``eds_continuum.bremsstrahlung_component(...)`` or
        ``spectral_fit.linear_background(...)`` — fit jointly with the peaks.
    weights : ``"poisson"`` (default), ``None`` (uniform) or a 1/σ² array.
    center_tol_kev : allow each peak center to wander ±this (default 0 =
        fixed positions).
    lorentzian_hwhm_kev : ``0.0`` (default) fits pure Gaussian peaks,
        byte-identical to the original behaviour. A positive natural-
        linewidth HWHM (keV) switches every element peak to a fixed-γ
        Voigt profile (see :func:`element_peak_component`); net areas
        then use :func:`~fermiviewer.calc.peak_shapes.voigt_area`
        instead of the Gaussian area.

    Returns
    -------
    PeakFitResult with per-element net areas and their 1σ errors.
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    counts = np.asarray(counts, dtype=np.float64).ravel()
    if energy.shape != counts.shape:
        raise ValueError("energy and counts must have equal length")
    if not elements:
        raise ValueError("need at least one element")

    gamma = max(float(lorentzian_hwhm_kev), 0.0)

    bg: list[Component] = []
    if isinstance(background, Component):
        bg = [background]
    elif background is not None:
        bg = list(background)

    components: list[Component] = list(bg)
    line_e: dict[str, float] = {}
    line_fam: dict[str, str] = {}
    sigmas: dict[str, float] = {}
    fitted: list[str] = []
    for sym in elements:
        e_line, fam = line_energy(sym, beam_kv=beam_kv)
        if not fam or not np.isfinite(e_line):
            warnings.warn(f"no characteristic line for '{sym}'", stacklevel=2)
            line_e[sym], line_fam[sym] = float("nan"), ""
            continue
        sigma = float(fano_sigma_kev(e_line))
        line_e[sym], line_fam[sym], sigmas[sym] = e_line, fam, sigma
        components.append(
            element_peak_component(
                sym, e_line, sigma, _amp0(energy, counts, e_line, sigma),
                center_tol_kev=center_tol_kev,
                lorentzian_hwhm_kev=gamma,
            )
        )
        fitted.append(sym)

    if not fitted:
        raise ValueError("no fittable element lines")

    result = fit_spectrum(energy, counts, components, weights=weights)

    net_areas: dict[str, float] = {}
    net_errs: dict[str, float] = {}
    for sym in elements:
        if sym not in fitted:
            net_areas[sym] = float("nan")
            net_errs[sym] = float("nan")
            continue
        amp = result.params[f"{sym}_amp"]
        amp_err = result.errors[f"{sym}_amp"]
        if gamma > 0.0:
            net_areas[sym] = voigt_area(amp, sigmas[sym], gamma)
            net_errs[sym] = voigt_area(amp_err, sigmas[sym], gamma)
        else:
            net_areas[sym] = gaussian_area(amp, sigmas[sym])
            net_errs[sym] = gaussian_area(amp_err, sigmas[sym])

    return PeakFitResult(
        elements=list(elements),
        net_areas=net_areas,
        net_area_errors=net_errs,
        line_energies=line_e,
        lines=line_fam,
        fit=result,
    )


def quantify_peaks(
    energy: np.ndarray,
    counts: np.ndarray,
    elements: Sequence[str],
    *,
    k_factors: np.ndarray | None = None,
    **fit_kwargs: object,
) -> tuple[PeakFitResult, ClResult]:
    """Deconvolve peaks then Cliff-Lorimer quantify a single spectrum.

    Net peak areas (from :func:`fit_peaks`) become 1×1 intensity maps fed
    to the unchanged :func:`fermiviewer.calc.eds.cliff_lorimer` — the
    ``quant_source="peakfit"`` path. Returns ``(peakfit, cl)`` where
    ``cl.mean_atomic_pct`` / ``cl.mean_weight_pct`` are the composition.
    """
    pf = fit_peaks(energy, counts, elements, **fit_kwargs)  # type: ignore[arg-type]
    maps = [np.array([[max(pf.net_areas[s], 0.0)]], dtype=np.float64) for s in elements]
    cl = cliff_lorimer(maps, list(elements), k_factors=k_factors)
    return pf, cl
