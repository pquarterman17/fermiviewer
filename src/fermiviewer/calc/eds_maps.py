"""EDS hypercube map helpers: element maps, pixel/ROI spectra.

Port of elementMap.m / pixelSpectrum.m / extractElementMaps.m.
Self-consistency oracle: pixel_spectrum(cube, all-True mask) equals the
cube column-sum (the BCF sum-spectrum invariant).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.eds import line_energy

__all__ = ["ElementMapEntry", "element_map", "extract_element_maps", "pixel_spectrum"]


def element_map(
    cube: np.ndarray,
    energy: np.ndarray,
    e_lo: float,
    e_hi: float,
    bg: str = "none",
    bg_width: float = float("nan"),
    bg_gap: float = 0.0,
) -> np.ndarray:
    """Energy-window integration map with optional two-sided linear
    background (port of elementMap.m)."""
    if e_hi < e_lo:
        e_lo, e_hi = e_hi, e_lo
    cube = np.asarray(cube)
    energy = np.asarray(energy, dtype=np.float64).ravel()
    h, w, c = cube.shape
    if energy.size != c:
        raise ValueError("energy length must equal cube channel count")

    peak = (energy >= e_lo) & (energy <= e_hi)
    if not peak.any():
        return np.zeros((h, w))
    cube_d = np.asarray(cube, dtype=np.float64)
    peak_sum: np.ndarray = cube_d[:, :, peak].sum(axis=2)

    if bg.lower() != "linear":
        return peak_sum

    pw = e_hi - e_lo
    bw = pw if (np.isnan(bg_width) or bg_width <= 0) else bg_width
    gap = max(bg_gap, 0.0)
    lo = (energy >= e_lo - gap - bw) & (energy < e_lo - gap)
    hi = (energy > e_hi + gap) & (energy <= e_hi + gap + bw)
    n_peak = int(peak.sum())

    if lo.any() and hi.any():
        lo_rate = cube_d[:, :, lo].sum(axis=2) / lo.sum()
        hi_rate = cube_d[:, :, hi].sum(axis=2) / hi.sum()
        out = peak_sum - 0.5 * (lo_rate + hi_rate) * n_peak
    elif lo.any():
        out = peak_sum - cube_d[:, :, lo].sum(axis=2) / lo.sum() * n_peak
    elif hi.any():
        out = peak_sum - cube_d[:, :, hi].sum(axis=2) / hi.sum() * n_peak
    else:
        out = peak_sum
    return np.asarray(np.maximum(out, 0.0))


def pixel_spectrum(
    cube: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray | None = None,
) -> np.ndarray:
    """Pixel-list or boolean-mask summed spectrum (port of pixelSpectrum.m).

    rows may be a [H, W] boolean mask (cols ignored), or 1-based row
    indices paired with cols.
    """
    cube = np.asarray(cube)
    h, w, c = cube.shape
    flat = np.asarray(cube, dtype=np.float64).reshape(h * w, c)

    rows = np.asarray(rows)
    if rows.dtype == bool:
        if rows.shape != (h, w):
            raise ValueError(f"mask must be [{h} x {w}]")
        out: np.ndarray = flat[rows.ravel()].sum(axis=0)
        return out

    if cols is None:
        raise ValueError("cols required when rows is an index list")
    r = np.round(np.asarray(rows, dtype=np.float64)).astype(int).ravel()
    cc = np.round(np.asarray(cols, dtype=np.float64)).astype(int).ravel()
    if r.size != cc.size:
        raise ValueError("rows and cols must have equal length")
    keep = (r >= 1) & (r <= h) & (cc >= 1) & (cc <= w)
    r, cc = r[keep], cc[keep]
    if r.size == 0:
        return np.zeros(c)
    summed: np.ndarray = flat[(r - 1) * w + (cc - 1)].sum(axis=0)
    return summed


@dataclass(frozen=True)
class ElementMapEntry:
    symbol: str
    line: str
    energy_kev: float
    window: tuple[float, float]
    map: np.ndarray
    total: float


def extract_element_maps(
    cube: np.ndarray,
    energy: np.ndarray,
    elements: list[str],
    half_window: float = 0.085,
    bg: str = "linear",
    beam_kv: float = float("inf"),
) -> list[ElementMapEntry]:
    """Per-element maps at each element's principal line (port of
    extractElementMaps.m). Unknown / out-of-range lines warn and skip."""
    energy = np.asarray(energy, dtype=np.float64).ravel()
    e_min, e_max = float(energy.min()), float(energy.max())
    out: list[ElementMapEntry] = []
    for sym in elements:
        if not sym:
            continue
        e, line = line_energy(sym, beam_kv=beam_kv)
        if np.isnan(e):
            warnings.warn(f"no known line for '{sym}' — skipped", stacklevel=2)
            continue
        if not e_min <= e <= e_max:
            warnings.warn(
                f"{sym} {line}α line ({e:.3f} keV) outside the energy axis — skipped",
                stacklevel=2,
            )
            continue
        m = element_map(cube, energy, e - half_window, e + half_window, bg=bg)
        out.append(ElementMapEntry(sym, line, e, (e - half_window, e + half_window),
                                   m, float(m.sum())))
    return out
