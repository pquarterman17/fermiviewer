"""Reciprocal-space detector geometry for 4D-STEM virtual detectors.

This is original pure math, not a MATLAB port — unlike ``calc/radial.py``
and ``calc/eds_maps.py`` (whose 1-based "pixel-center" coordinates exist
only because they mirror a MATLAB reference). Coordinates here are plain
0-based array indices throughout: pixel ``(row, col)`` of a ``det_shape``
array sits at coordinate ``(row, col)``, matching numpy indexing with no
offset. Center tuples are always ``(ky, kx)`` == ``(row, col)`` order.

Distances are built via the same broadcast-arange + ``np.hypot`` idiom
used in ``eds_maps.virtual_dark_field`` (read for the pattern; that
function serves a different purpose — FFT-aperture masking of a single
real-space image — and is not modified here).
"""

from __future__ import annotations

import numpy as np

__all__ = ["aperture_mask", "pattern_center", "radial_coverage"]

_SHAPES = ("circle", "annulus")


def _distance_grid(
    det_shape: tuple[int, int], center: tuple[float, float]
) -> np.ndarray:
    """0-based (ky, kx) pixel-distance grid from ``center``, shape ``det_shape``."""
    ky_dim, kx_dim = det_shape
    cy, cx = center
    ky = np.arange(ky_dim, dtype=np.float64)[:, None] - cy
    kx = np.arange(kx_dim, dtype=np.float64)[None, :] - cx
    return np.hypot(ky, kx)


def aperture_mask(
    det_shape: tuple[int, int],
    center: tuple[float, float],
    inner_r: float,
    outer_r: float,
    shape: str = "circle",
) -> np.ndarray:
    """Boolean reciprocal-space aperture mask over a detector frame.

    ``center`` is ``(ky, kx)`` in float pixels (0-based); radii are in
    pixels. ``shape="circle"`` keeps pixels with ``r <= outer_r``
    (``inner_r`` is accepted but unused, so callers can pass a uniform
    signature); ``shape="annulus"`` keeps ``inner_r <= r <= outer_r``.

    Raises ``ValueError`` for an unknown shape, a negative radius, or an
    annulus with ``inner_r >= outer_r``.
    """
    if shape not in _SHAPES:
        raise ValueError(f"shape must be one of {_SHAPES}, got {shape!r}")
    if inner_r < 0 or outer_r < 0:
        raise ValueError("radii must be >= 0")
    if shape == "annulus" and inner_r >= outer_r:
        raise ValueError("inner_r must be < outer_r for an annulus")

    dist = _distance_grid(det_shape, center)
    if shape == "circle":
        return np.asarray(dist <= outer_r)
    return np.asarray((dist >= inner_r) & (dist <= outer_r))


def pattern_center(
    mean_dp: np.ndarray, method: str = "centroid"
) -> tuple[float, float]:
    """Seed a detector center from a (mean) diffraction pattern.

    ``method="centroid"`` is the intensity-weighted first moment (only
    finite values contribute; non-finite entries are treated as 0
    weight). ``method="max"`` is the argmax pixel (non-finite entries are
    never selected). Both fall back to the geometric center
    ``((h-1)/2, (w-1)/2)`` when the pattern is all-zero, all-NaN, or the
    total finite intensity is <= 0 — a degenerate pattern carries no
    information to seed a center from.

    Returns ``(cy, cx)``.
    """
    dp = np.asarray(mean_dp, dtype=np.float64)
    if dp.ndim != 2:
        raise ValueError("mean_dp must be a 2D diffraction pattern")
    h, w = dp.shape
    if h == 0 or w == 0:
        raise ValueError("mean_dp must be non-empty")
    geometric = ((h - 1) / 2.0, (w - 1) / 2.0)
    finite = np.isfinite(dp)

    if method == "max":
        if not finite.any():
            return geometric
        vals = np.where(finite, dp, -np.inf)
        if float(vals.max()) <= 0:
            # all-zero (or all non-positive) — no peak to seed a center from
            return geometric
        iy, ix = np.unravel_index(np.argmax(vals), vals.shape)
        return (float(iy), float(ix))

    if method == "centroid":
        weights = np.where(finite, dp, 0.0)
        total = float(weights.sum())
        if not finite.any() or total <= 0:
            return geometric
        ys = np.arange(h, dtype=np.float64)[:, None]
        xs = np.arange(w, dtype=np.float64)[None, :]
        cy = float((weights * ys).sum() / total)
        cx = float((weights * xs).sum() / total)
        return (cy, cx)

    raise ValueError(f"method must be 'centroid' or 'max', got {method!r}")


def radial_coverage(
    det_shape: tuple[int, int],
    center: tuple[float, float],
    n_bins: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-radial-bin detector pixel counts, for a coverage plot.

    ``calc/radial.py`` (``radial_profile``/``azimuthal_integrate``) was
    checked first per the task brief, but its bincount reduction only
    returns per-bin average/max *values* — raw per-bin pixel counts are
    never exposed — and its bin grid uses MATLAB-style 1-based pixel
    centers plus an ``(x, y)`` center order, both of which would put its
    bins a half-pixel off from this module's 0-based ``(ky, kx)`` grid.
    Delegating would silently break exact pixel-count parity with
    ``aperture_mask`` (the property the test suite checks), so this
    function is a small dedicated counter that mirrors radial_profile's
    *bin-width formula* (corner-to-corner ``max_radius / n_bins``,
    ``n_bins <= 0`` auto-resolves to ``min(det_shape) // 2``) without
    reusing its code, over this module's own 0-based distance grid.

    Returns ``(radii, counts)`` — bin-center radii and float64 pixel
    counts. ``counts.sum()`` always equals the total pixel count.
    """
    h, w = det_shape
    if n_bins <= 0:
        n_bins = max(min(h, w) // 2, 1)

    dist = _distance_grid(det_shape, center)
    max_radius = float(dist.max())
    if max_radius <= 0:
        # degenerate 1x1 (or center-only) detector: everything is bin 0
        counts = np.zeros(n_bins, dtype=np.float64)
        counts[0] = dist.size
        radii = (np.arange(n_bins, dtype=np.float64) + 0.5) * 0.0
        return radii, counts

    bin_width = max_radius / n_bins
    radii = (np.arange(n_bins, dtype=np.float64) + 0.5) * bin_width
    idx = np.minimum((dist / bin_width).astype(np.int64), n_bins - 1)
    counts = np.bincount(idx.ravel(), minlength=n_bins).astype(np.float64)
    return radii, counts
