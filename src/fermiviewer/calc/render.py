"""Display rendering math — window/level, gamma, histogram.

Pure library (numpy only). PNG encoding lives in routes; this module is
the testable math the WebGL shader will eventually mirror client-side.
"""

from __future__ import annotations

import numpy as np

__all__ = ["histogram", "to_display", "window_level"]


def window_level(
    data: np.ndarray, lo: float | None = None, hi: float | None = None, gamma: float = 1.0
) -> np.ndarray:
    """Map data to [0, 1] with a linear window then gamma. NaN-safe.

    Defaults: lo/hi = data min/max (auto full-range stretch).
    """
    d = np.asarray(data, dtype=np.float64)
    finite = d[np.isfinite(d)]
    if finite.size == 0:
        return np.zeros_like(d)
    lo = float(finite.min()) if lo is None else float(lo)
    hi = float(finite.max()) if hi is None else float(hi)
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


def histogram(data: np.ndarray, bins: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """(bin_centers, counts) over the finite data range."""
    d = np.asarray(data, dtype=np.float64).ravel()
    d = d[np.isfinite(d)]
    if d.size == 0:
        edges = np.linspace(0, 1, bins + 1)
        return (edges[:-1] + edges[1:]) / 2, np.zeros(bins)
    counts, edges = np.histogram(d, bins=bins)
    return (edges[:-1] + edges[1:]) / 2, counts.astype(np.float64)
