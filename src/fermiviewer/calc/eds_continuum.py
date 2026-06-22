"""EDS bremsstrahlung continuum (Kramers' law) background model.

A physical continuum background for EDS, fittable *through* the
characteristic peaks: the peak regions are masked out and the smooth
bremsstrahlung shape is fit to the remaining channels, giving a net-area
background far better than a local linear interpolation for trace and
light elements.

Model (Kramers, detector-shaped)::

    I(E) = amp · (E0 − E) / E · exp(−absorption / E)      0 < E < E0

The bare ``(E0−E)/E`` is Kramers' law (continuum ∝ Z̄, diverging as
E→0, vanishing at the Duane–Hunt limit E0). The optional
``exp(−absorption/E)`` rolloff approximates the low-energy detector
window / dead-layer absorption that suppresses the divergence;
``absorption = 0`` recovers pure Kramers.

Built on :mod:`fermiviewer.calc.spectral_fit`; pure library (numpy +
that core), no route/pydantic imports.

References
----------
Kramers, *Phil. Mag.* **46** (1923) 836; Goldstein et al., *Scanning
Electron Microscopy and X-ray Microanalysis*, 4th ed., ch. 6
(continuum X-ray generation).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.eds import line_energy
from fermiviewer.calc.eds_calib import fano_fwhm
from fermiviewer.calc.spectral_fit import Component, FitResult, fit_spectrum

__all__ = [
    "ContinuumFit",
    "bremsstrahlung_component",
    "fit_continuum",
    "kramers_continuum",
    "subtract_continuum",
]

_EPS = 1e-9


def kramers_continuum(
    energy_kev: np.ndarray | float,
    e0_kev: float,
    amp: float = 1.0,
    absorption: float = 0.0,
) -> np.ndarray:
    """Detector-shaped Kramers continuum over ``energy_kev`` (keV).

    ``amp·(E0−E)/E·exp(−absorption/E)`` for ``0 < E < E0``, zero at and
    above the beam energy ``e0_kev``. ``absorption=0`` is pure Kramers.
    """
    e = np.maximum(np.asarray(energy_kev, dtype=np.float64), _EPS)
    cont = amp * np.maximum(e0_kev - e, 0.0) / e
    if absorption > 0.0:
        cont = cont * np.exp(-absorption / e)
    return np.asarray(cont, dtype=np.float64)


def bremsstrahlung_component(
    e0_kev: float,
    *,
    amp: float = 1.0,
    absorption: float = 0.0,
    fit_absorption: bool = True,
    amp_bounds: tuple[float, float] = (0.0, np.inf),
    absorption_bounds: tuple[float, float] = (0.0, 50.0),
) -> Component:
    """A :class:`~fermiviewer.calc.spectral_fit.Component` for the continuum.

    With ``fit_absorption`` the component has params ``(amp, absorption)``;
    otherwise just ``(amp,)`` and the rolloff is fixed at ``absorption``.
    ``e0_kev`` is fixed (the known beam energy), not a fit parameter.
    """
    if fit_absorption:

        def f2(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
            a, b = p
            return kramers_continuum(energy, e0_kev, a, b)

        return Component(
            "continuum", ("amp", "absorption"), f2,
            (amp, absorption),
            (amp_bounds[0], absorption_bounds[0]),
            (amp_bounds[1], absorption_bounds[1]),
        )

    def f1(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
        (a,) = p
        return kramers_continuum(energy, e0_kev, a, absorption)

    return Component(
        "continuum", ("amp",), f1, (amp,),
        (amp_bounds[0],), (amp_bounds[1],),
    )


def _resolve_line_energies(item: float | str, e0_kev: float) -> list[float]:
    """Energies (keV) to mask for one exclude entry (energy or symbol)."""
    if not isinstance(item, str):
        return [float(item)]
    out: list[float] = []
    for fam in ("K", "L", "M"):
        e, used = line_energy(item, fam, beam_kv=e0_kev)
        if used and np.isfinite(e):
            out.append(float(e))
    return out


def _peak_mask(
    energy: np.ndarray,
    excludes: Iterable[float | str],
    e0_kev: float,
    width_factor: float,
) -> np.ndarray:
    """Boolean keep-mask: True where NO excluded peak sits (fit those)."""
    keep = np.ones(energy.shape, dtype=bool)
    for item in excludes:
        for e_line in _resolve_line_energies(item, e0_kev):
            half = width_factor * float(fano_fwhm(e_line)) / 1000.0  # keV
            keep &= ~((energy >= e_line - half) & (energy <= e_line + half))
    return keep


@dataclass(frozen=True)
class ContinuumFit:
    """Outcome of :func:`fit_continuum`.

    ``continuum`` is the fitted curve over the full input axis;
    ``keep_mask`` is the channels used (peaks excluded); ``fit`` is the
    underlying :class:`~fermiviewer.calc.spectral_fit.FitResult`.
    """

    continuum: np.ndarray
    amp: float
    absorption: float
    e0_kev: float
    keep_mask: np.ndarray
    fit: FitResult


def fit_continuum(
    energy: np.ndarray,
    counts: np.ndarray,
    e0_kev: float,
    *,
    exclude_lines: Sequence[float | str] | None = None,
    exclude_windows: Sequence[tuple[float, float]] | None = None,
    exclude_width_factor: float = 3.0,
    fit_absorption: bool = True,
    weights: str | None = "poisson",
) -> ContinuumFit:
    """Fit the bremsstrahlung continuum through the masked peak regions.

    Parameters
    ----------
    energy, counts : 1-D keV axis + spectrum (equal length).
    e0_kev : beam energy (Duane–Hunt cutoff); fixed, not fitted.
    exclude_lines : element symbols and/or line energies (keV) whose
        characteristic peaks are masked out before fitting. Symbol entries
        mask all present K/L/M families; window half-width is
        ``exclude_width_factor × FWHM(E)`` from the Fano model.
    exclude_windows : explicit ``(lo, hi)`` keV regions to also mask.
    fit_absorption : free the low-energy detector-absorption rolloff.
    weights : ``"poisson"`` (default) counting-statistics weighting, or
        ``None`` for uniform. Channels under masked peaks get zero weight.

    Returns
    -------
    ContinuumFit with the fitted continuum over the full axis.
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    counts = np.asarray(counts, dtype=np.float64).ravel()
    if energy.shape != counts.shape:
        raise ValueError("energy and counts must have equal length")

    keep = _peak_mask(energy, exclude_lines or [], e0_kev, exclude_width_factor)
    for lo, hi in exclude_windows or []:
        keep &= ~((energy >= lo) & (energy <= hi))
    # only fit the sub-beam-energy continuum region
    keep &= energy < e0_kev
    if keep.sum() < 2:
        raise ValueError("fewer than 2 channels remain after peak masking")

    # weights array: base scheme × keep-mask (0 under peaks ⇒ excluded)
    if weights == "poisson":
        base = 1.0 / np.maximum(counts, 1.0)
    elif weights is None:
        base = np.ones_like(counts)
    else:
        raise ValueError(f"unknown weights scheme '{weights}'")
    w = base * keep

    amp0 = max(float(np.median(counts[keep])) * 1.0, 1e-6)
    comp = bremsstrahlung_component(e0_kev, amp=amp0, fit_absorption=fit_absorption)
    result = fit_spectrum(energy, counts, [comp], weights=w)

    amp = result.params["continuum_amp"]
    absorption = result.params.get("continuum_absorption", 0.0)
    return ContinuumFit(
        continuum=result.component_curves["continuum"],
        amp=amp,
        absorption=absorption,
        e0_kev=e0_kev,
        keep_mask=keep,
        fit=result,
    )


def subtract_continuum(
    energy: np.ndarray,
    counts: np.ndarray,
    e0_kev: float,
    *,
    clip: bool = True,
    **fit_kwargs: object,
) -> tuple[np.ndarray, ContinuumFit]:
    """Background-subtract the fitted continuum from ``counts``.

    Returns ``(net, fit)`` where ``net = counts − continuum`` (clipped at
    0 when ``clip``). Extra keywords pass through to :func:`fit_continuum`.
    """
    fit = fit_continuum(energy, counts, e0_kev, **fit_kwargs)  # type: ignore[arg-type]
    net = np.asarray(counts, dtype=np.float64) - fit.continuum
    if clip:
        net = np.clip(net, 0.0, None)
    return net, fit
