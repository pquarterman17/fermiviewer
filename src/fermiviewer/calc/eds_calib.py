"""EDS detector calibration primitives: Fano FWHM model + energy recal.

Two small, dependency-free primitives that the EDS model-fitting modules
(`eds_continuum` #4, `eds_peakfit` #5, `eds_zeta` #7) consume:

* **Fano FWHM(E)** — the Si(Li)/SDD detector-resolution model
  (Fiori–Newbury): ``FWHM(E)² = FWHM_noise² + (2.3548)²·ε·F·E`` with the
  electronic-noise term back-solved from a reference line (Mn-Kα,
  130 eV @ 5.899 keV by default). Gives the Gaussian width of any
  characteristic peak so the peak-fit need not free every width.
* **Two-point energy recalibration** — a linear ``E' = gain·E + offset``
  axis correction from one or more known lines, optionally locating the
  observed peak centroid in the measured spectrum.

Pure library (numpy only); no fastapi/pydantic/route imports.

References
----------
Fiori & Newbury, *SEM/1978*; Goldstein et al., *Scanning Electron
Microscopy and X-ray Microanalysis*, 4th ed., ch. 7 (detector
resolution and the Fano-limited line width).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

__all__ = [
    "DEFAULT_EPSILON_EV",
    "DEFAULT_FANO",
    "MN_KA_FWHM_EV",
    "MN_KA_KEV",
    "RecalResult",
    "fano_fwhm",
    "fano_sigma_kev",
    "recalibrate",
]

# 2·sqrt(2·ln2): the FWHM ↔ Gaussian-σ conversion factor.
_FWHM_PER_SIGMA = 2.0 * np.sqrt(2.0 * np.log(2.0))

# Si detector constants.
DEFAULT_EPSILON_EV = 3.85   # mean energy per electron-hole pair (Si), eV
DEFAULT_FANO = 0.12         # Fano factor for Si

# Reference line that anchors the electronic-noise term.
MN_KA_KEV = 5.899
MN_KA_FWHM_EV = 130.0       # spec resolution of a typical SDD at Mn-Kα


def fano_fwhm(
    energy_kev: np.ndarray | float,
    *,
    fano: float = DEFAULT_FANO,
    epsilon_ev: float = DEFAULT_EPSILON_EV,
    ref_energy_kev: float = MN_KA_KEV,
    ref_fwhm_ev: float = MN_KA_FWHM_EV,
) -> np.ndarray | float:
    """Detector energy resolution FWHM (in **eV**) at ``energy_kev``.

    Fiori–Newbury model ``FWHM(E)² = FWHM_noise² + k·F·ε·E`` with
    ``k = (2·√(2·ln2))²``. The electronic-noise term is back-solved so the
    curve passes exactly through ``(ref_energy_kev, ref_fwhm_ev)`` — by
    default the Mn-Kα 130 eV detector spec.

    Parameters
    ----------
    energy_kev : scalar or array of line energies, keV.
    fano, epsilon_ev : Fano factor and e-h pair energy (Si defaults).
    ref_energy_kev, ref_fwhm_ev : the calibration anchor (line energy keV,
        its FWHM eV).

    Returns
    -------
    FWHM in eV, matching the shape of ``energy_kev``. The value under the
    square root is clamped at 0 so far-below-reference energies return a
    real (small) width rather than NaN.

    Examples
    --------
    >>> round(float(fano_fwhm(5.899)), 1)   # Mn-Kα anchor
    130.0
    >>> float(fano_fwhm(8.048)) > 130.0      # Cu-Kα is broader
    True
    """
    e_ev = np.asarray(energy_kev, dtype=np.float64) * 1000.0
    ref_ev = ref_energy_kev * 1000.0
    slope = (_FWHM_PER_SIGMA**2) * fano * epsilon_ev   # eV² per eV
    noise_sq = ref_fwhm_ev**2 - slope * ref_ev
    var = np.maximum(noise_sq + slope * e_ev, 0.0)
    out = np.sqrt(var)
    return float(out) if np.isscalar(energy_kev) or np.ndim(energy_kev) == 0 else out


def fano_sigma_kev(
    energy_kev: np.ndarray | float, **kwargs: float
) -> np.ndarray | float:
    """Gaussian σ (in **keV**) of a peak at ``energy_kev``.

    Convenience wrapper over :func:`fano_fwhm` for the peak-fit modules,
    which work on a keV axis: ``σ_keV = FWHM_eV / 2.3548 / 1000``. Accepts
    the same keyword overrides as :func:`fano_fwhm`.
    """
    fwhm_ev = np.asarray(fano_fwhm(energy_kev, **kwargs), dtype=np.float64)
    sigma = fwhm_ev / _FWHM_PER_SIGMA / 1000.0
    return float(sigma) if np.isscalar(energy_kev) or np.ndim(energy_kev) == 0 else sigma


@dataclass(frozen=True)
class RecalResult:
    """Outcome of :func:`recalibrate`.

    ``corrected_energy`` is the input axis mapped through
    ``gain·E + offset``; ``anchors`` are the (observed_keV, true_keV) pairs
    actually used for the fit (after any peak location).
    """

    corrected_energy: np.ndarray
    gain: float
    offset: float
    anchors: tuple[tuple[float, float], ...]


def _locate_peak_kev(
    energy: np.ndarray, counts: np.ndarray, target_kev: float, search_kev: float
) -> float:
    """Intensity-weighted centroid of the peak nearest ``target_kev``.

    Centroid over the ``±search_kev`` window around the target; falls back
    to the target itself if the window is empty or has no counts.
    """
    lo, hi = target_kev - search_kev, target_kev + search_kev
    sel = (energy >= lo) & (energy <= hi)
    if not sel.any():
        return float(target_kev)
    e_win = energy[sel]
    c_win = np.clip(counts[sel], 0.0, None)
    total = float(c_win.sum())
    if total <= 0.0:
        return float(target_kev)
    return float((e_win * c_win).sum() / total)


def recalibrate(
    energy: np.ndarray,
    counts: np.ndarray,
    anchors: Sequence[float | tuple[float, float]],
    *,
    search_kev: float = 0.15,
) -> RecalResult:
    """Linear energy-axis recalibration from known characteristic lines.

    Each anchor is either a known **true** line energy (keV) — in which
    case the observed peak centroid is located in ``counts`` within
    ``±search_kev`` — or an explicit ``(observed_keV, true_keV)`` pair used
    verbatim. The correction ``E' = gain·E + offset`` is then:

    * ≥2 anchors → least-squares linear fit (gain + offset),
    * 1 anchor   → offset-only shift (gain = 1),
    * 0 anchors  → identity.

    Parameters
    ----------
    energy, counts : 1-D arrays of equal length (keV axis + spectrum).
    anchors : known lines (true keV) and/or (observed, true) keV pairs.
    search_kev : half-width for locating a peak around a bare true energy.

    Returns
    -------
    RecalResult with the corrected axis and the (gain, offset) applied.
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    counts = np.asarray(counts, dtype=np.float64).ravel()
    if energy.shape != counts.shape:
        raise ValueError("energy and counts must have equal length")

    pairs: list[tuple[float, float]] = []
    for a in anchors:
        if isinstance(a, tuple):
            observed, true = float(a[0]), float(a[1])
        else:
            true = float(a)
            observed = _locate_peak_kev(energy, counts, true, search_kev)
        pairs.append((observed, true))

    if not pairs:
        gain, offset = 1.0, 0.0
    elif len(pairs) == 1:
        gain, offset = 1.0, pairs[0][1] - pairs[0][0]
    else:
        obs = np.array([p[0] for p in pairs], dtype=np.float64)
        tru = np.array([p[1] for p in pairs], dtype=np.float64)
        # least-squares true = gain·obs + offset
        a_mat = np.vstack([obs, np.ones_like(obs)]).T
        (gain, offset), *_ = np.linalg.lstsq(a_mat, tru, rcond=None)
        gain, offset = float(gain), float(offset)

    corrected = gain * energy + offset
    return RecalResult(corrected, gain, offset, tuple(pairs))
