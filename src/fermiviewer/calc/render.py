"""Display rendering math — window/level, gamma, histogram.

Pure library (numpy only). PNG encoding lives in routes; this module is
the testable math the WebGL shader will eventually mirror client-side.
"""

from __future__ import annotations

import numpy as np

__all__ = ["histogram", "to_display", "to_uint16_norm", "window_level"]


def auto_window(data: np.ndarray) -> tuple[float, float] | None:
    """The (lo, hi) `window_level` would pick for `data`, or None when
    nothing in it is finite.

    Split out so a caller that must window a DOWNSAMPLED copy can take
    the bounds from the full-resolution original and get identical
    contrast -- there is one definition of the auto stretch, not one here
    and a lookalike at the call site.
    """
    d = np.asarray(data)
    if d.size == 0:
        return None
    if d.dtype.kind != "f":
        # integer data has no NaN; min/max directly rather than masking,
        # which would copy the whole array to find that out
        return (float(d.min()), float(d.max()))
    finite = d[np.isfinite(d)]
    if finite.size == 0:
        return None
    return (float(finite.min()), float(finite.max()))


def window_level(
    data: np.ndarray, lo: float | None = None, hi: float | None = None, gamma: float = 1.0
) -> np.ndarray:
    """Map data to [0, 1] with a linear window then gamma. NaN-safe.

    Defaults: lo/hi = data min/max (auto full-range stretch).
    """
    d = np.asarray(data, dtype=np.float64)
    if lo is None or hi is None:
        auto = auto_window(d)
        if auto is None:
            return np.zeros_like(d)
        lo = auto[0] if lo is None else float(lo)
        hi = auto[1] if hi is None else float(hi)
    lo, hi = float(lo), float(hi)
    if hi <= lo:
        hi = lo + 1.0
    out = np.clip((d - lo) / (hi - lo), 0.0, 1.0)
    out[~np.isfinite(d)] = 0.0
    if gamma > 0 and gamma != 1.0:
        out = out ** (1.0 / gamma)
    return out


def to_display(
    data: np.ndarray, lo: float | None = None, hi: float | None = None, gamma: float = 1.0
) -> np.ndarray:
    """Window/level/gamma to an 8-bit grayscale display buffer."""
    return (window_level(data, lo, hi, gamma) * 255.0 + 0.5).astype(np.uint8)


def to_uint16_norm(data: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Full-range normalize to uint16 for the client-side WebGL LUT.

    Returns (u16, vmin, vmax) where u16 = (data - vmin)/(vmax - vmin)
    * 65535 rounded; the client reconstructs real values from the
    headers. NaN/Inf map to 0 (mirrors window_level's NaN policy).
    """
    d = np.asarray(data, dtype=np.float64)
    finite = d[np.isfinite(d)]
    if finite.size == 0:
        return np.zeros(d.shape, dtype=np.uint16), 0.0, 1.0
    vmin = float(finite.min())
    vmax = float(finite.max())
    span = vmax - vmin if vmax > vmin else 1.0
    out = np.clip((d - vmin) / span, 0.0, 1.0)
    out[~np.isfinite(d)] = 0.0
    return (out * 65535.0 + 0.5).astype(np.uint16), vmin, vmax


def histogram(data: np.ndarray, bins: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """(bin_centers, counts) over the finite data range."""
    d = np.asarray(data, dtype=np.float64).ravel()
    d = d[np.isfinite(d)]
    if d.size == 0:
        edges = np.linspace(0, 1, bins + 1)
        return (edges[:-1] + edges[1:]) / 2, np.zeros(bins)
    counts, edges = np.histogram(d, bins=bins)
    return (edges[:-1] + edges[1:]) / 2, counts.astype(np.float64)
