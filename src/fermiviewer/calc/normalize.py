"""Intensity normalization helpers shared across calc/ analyses.

NaN/Inf sanitation plus plain and outlier-rejecting ``[0, 1]`` contrast
stretches. Real EM frames carry dead/hot pixels, masked regions and detector
spikes; left unhandled they poison min/max, gradients and clustering, so these
keep the downstream methods robust. A clean (all-finite) array is returned
unchanged, so golden/parity paths stay untouched.
"""

from __future__ import annotations

import numpy as np

__all__ = ["normalize01", "robust_normalize01", "sanitize"]


def sanitize(a: np.ndarray) -> np.ndarray:
    """Replace NaN/±Inf with the median of the finite values.

    Filling with the finite median keeps the value in-range without inventing
    a feature. A clean (all-finite) array is returned unchanged.
    """
    a = np.asarray(a, dtype=np.float64)
    if np.all(np.isfinite(a)):
        return a
    finite = a[np.isfinite(a)]
    fill = float(np.median(finite)) if finite.size else 0.0
    return np.where(np.isfinite(a), a, fill)


def normalize01(a: np.ndarray) -> np.ndarray:
    """Plain min/max contrast stretch to ``[0, 1]`` (NaN/Inf-safe)."""
    a = sanitize(a)
    lo, hi = float(a.min()), float(a.max())
    return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)


def robust_normalize01(a: np.ndarray, clip_percentile: float = 0.5) -> np.ndarray:
    """``[0, 1]`` contrast stretch that rejects intensity outliers.

    Maps the ``[p, 100-p]`` percentile range to ``[0, 1]`` and clips the
    tails, so a handful of hot/dead pixels can't compress the whole image
    into a sliver of the range (which makes every boundary/gradient method
    fail). ``clip_percentile=0`` falls back to plain min/max. NaN/Inf-safe.
    """
    a = sanitize(a)
    if clip_percentile and clip_percentile > 0:
        lo, hi = (float(v) for v in np.percentile(a, [clip_percentile, 100 - clip_percentile]))
    else:
        lo, hi = float(a.min()), float(a.max())
    if hi <= lo:                                  # percentiles collapsed → widen
        lo, hi = float(a.min()), float(a.max())
    if hi <= lo:                                  # truly constant image
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0.0, 1.0)
