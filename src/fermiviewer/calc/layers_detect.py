"""Interface detection for cross-section layer analysis.

The separable "where are the interfaces?" concern of :mod:`fermiviewer.calc.layers`:
locate depth-profile gradient peaks, either at a single smoothing scale
(:func:`detect_interfaces`, for monotonic HAADF/EELS) or by scale-space
persistence (:func:`detect_interfaces_scale_space`, which rejects BF/DF
thickness fringes). Pure numpy/scipy; consumed by ``layers.analyze_layers``
and re-exported from :mod:`fermiviewer.calc.layers` for back-compat.
"""

from __future__ import annotations

import numpy as np

__all__ = ["detect_interfaces", "detect_interfaces_scale_space"]


def detect_interfaces(
    profile: np.ndarray,
    sensitivity: float = 0.3,
    n_layers: int = 0,
    smooth: float = 1.5,
    min_separation: int = 5,
) -> np.ndarray:
    """Interface positions (integer profile indices) = gradient-peak depths.

    The smoothed depth profile's |gradient| peaks mark interfaces.
    ``sensitivity`` is the peak-height threshold as a fraction of the max
    gradient (lower → more interfaces). ``n_layers`` (>1) keeps only the
    ``n_layers-1`` strongest peaks; ``min_separation`` rejects near-duplicates.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks

    prof = np.asarray(profile, dtype=np.float64).ravel()
    if prof.size < 5:
        return np.array([], dtype=int)
    grad = np.abs(np.gradient(gaussian_filter1d(prof, max(smooth, 1e-6))))
    gmax = float(grad.max())
    if gmax <= 0:
        return np.array([], dtype=int)
    peaks, props = find_peaks(
        grad, height=sensitivity * gmax, distance=max(1, int(min_separation))
    )
    if n_layers > 1 and peaks.size > n_layers - 1:
        order = np.argsort(props["peak_heights"])[::-1][: n_layers - 1]
        peaks = np.sort(peaks[order])
    return np.asarray(peaks, dtype=int)


def detect_interfaces_scale_space(
    profile: np.ndarray,
    scales: tuple[float, ...] = (2.0, 4.0, 8.0),
    sensitivity: float = 0.3,
    n_layers: int = 0,
    min_separation: int = 5,
    persistence: int | None = None,
) -> np.ndarray:
    """Interfaces that PERSIST across smoothing scales (BF/DF robustness).

    Gradient peaks are found at each Gaussian scale; a candidate is kept
    only if a peak sits within ``min_separation`` of it at ≥``persistence``
    scales (default: a majority). Real interfaces survive coarse smoothing;
    thickness fringes / diffraction-contrast wiggles wash out and are
    rejected. ``n_layers`` (>1) keeps the (n−1) strongest by coarse-scale
    gradient height.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks

    prof = np.asarray(profile, dtype=np.float64).ravel()
    if prof.size < 5 or not scales:
        return np.array([], dtype=int)
    if persistence is None:
        persistence = len(scales) // 2 + 1

    per_scale: list[np.ndarray] = []
    coarse_grad = np.zeros_like(prof)
    for s in scales:
        g = np.abs(np.gradient(gaussian_filter1d(prof, s)))
        coarse_grad = g                       # last (coarsest) scale
        gmax = float(g.max())
        if gmax <= 0:
            per_scale.append(np.array([], dtype=int))
            continue
        pk, _ = find_peaks(g, height=sensitivity * gmax, distance=max(1, int(min_separation)))
        per_scale.append(pk)

    candidates = sorted({int(p) for pks in per_scale for p in pks})
    kept: list[int] = []
    for c in candidates:
        support = sum(
            1 for pks in per_scale if pks.size and int(np.min(np.abs(pks - c))) <= min_separation
        )
        if support >= persistence:
            kept.append(c)

    deduped: list[int] = []
    for c in sorted(kept):
        if not deduped or c - deduped[-1] > min_separation:
            deduped.append(c)
    out = np.array(deduped, dtype=int)
    if n_layers > 1 and out.size > n_layers - 1:
        order = np.argsort(coarse_grad[out])[::-1][: n_layers - 1]
        out = np.sort(out[order])
    return out
