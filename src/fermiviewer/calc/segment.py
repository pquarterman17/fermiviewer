"""Segmentation & morphology — W3 tranche 1 (docs/w3_imaging_audit.md).

multi_otsu and distance_transform port the MATLAB algorithms exactly
(skimage equivalents differ in threshold mapping / metric); morphology
and labelling map to scipy with zero-padding semantics matching the
MATLAB conv2-based implementations.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations

import numpy as np
from scipy import ndimage

__all__ = [
    "MultiOtsuResult",
    "distance_transform",
    "label_components",
    "morph_op",
    "multi_otsu",
]


# ── multi-Otsu ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MultiOtsuResult:
    thresholds: np.ndarray
    label_map: np.ndarray
    class_fractions: np.ndarray
    class_ranges: np.ndarray


def _between_class_var_table(
    prob: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Prefix sums for O(1) class weight/mean evaluation.

    Bin indices are kept 1-based to mirror the MATLAB math exactly.
    """
    idx = np.arange(1, prob.size + 1, dtype=np.float64)
    cw = np.concatenate(([0.0], np.cumsum(prob)))        # cw[t] = Σ prob[1..t]
    cm = np.concatenate(([0.0], np.cumsum(prob * idx)))  # cm[t] = Σ p·i
    return cw, cm


def _best_thresholds(prob: np.ndarray, n_classes: int) -> np.ndarray:
    """Exhaustive between-class-variance maximization (1-based indices)."""
    n_b = prob.size
    cw, cm = _between_class_var_table(prob)
    mu_total = cm[-1]
    eps = np.finfo(np.float64).eps

    def var_for(bounds: tuple[int, ...]) -> float:
        edges = (0, *bounds, n_b)
        s = 0.0
        for k in range(len(edges) - 1):
            wk = cw[edges[k + 1]] - cw[edges[k]]
            if wk < eps:
                continue
            muk = (cm[edges[k + 1]] - cm[edges[k]]) / wk
            s += wk * (muk - mu_total) ** 2
        return s

    best = -np.inf
    best_t: tuple[int, ...] = tuple(
        int(t) for t in np.round(np.linspace(1, n_b, n_classes + 1))[1:-1]
    )
    for combo in combinations(range(1, n_b), n_classes - 1):
        v = var_for(combo)
        if v > best:
            best = v
            best_t = combo
    return np.array(best_t, dtype=np.int64)


def _five_class_thresholds(
    build_hist: Callable[[int], tuple[np.ndarray, np.ndarray]],
    d_min: float,
    d_max: float,
    n_bins: int,
) -> np.ndarray:
    """Coarse(64)→windowed-fine search (avoids O(nB⁴) full search)."""
    prob_c, _ = build_hist(64)
    idx_c = _best_thresholds(prob_c, 5)
    edges_c = np.linspace(d_min, d_max, 65)
    centres_c = (edges_c[:-1] + edges_c[1:]) / 2
    coarse_vals = centres_c[idx_c - 1]

    prob_f, edges_f = build_hist(n_bins)
    bin_width = (d_max - d_min) / n_bins
    coarse_w = (d_max - d_min) / 64
    fine_centre = (
        np.round((coarse_vals - d_min) / bin_width).astype(np.int64) + 1
    )
    window = max(2, int(round(coarse_w / bin_width)) * 2)

    cw, cm = _between_class_var_table(prob_f)
    mu_total = cm[-1]
    eps = np.finfo(np.float64).eps

    def var_for(bounds: tuple[int, ...]) -> float:
        edges = (0, *bounds, n_bins)
        s = 0.0
        for k in range(len(edges) - 1):
            wk = cw[edges[k + 1]] - cw[edges[k]]
            if wk < eps:
                continue
            muk = (cm[edges[k + 1]] - cm[edges[k]]) / wk
            s += wk * (muk - mu_total) ** 2
        return s

    rngs = [
        range(
            max(1, fine_centre[i] - window),
            min(n_bins - 3 + i, fine_centre[i] + window) + 1,
        )
        for i in range(4)
    ]
    best = -np.inf
    best_idx = tuple(int(t) for t in fine_centre)
    for t1 in rngs[0]:
        for t2 in (t for t in rngs[1] if t > t1):
            for t3 in (t for t in rngs[2] if t > t2):
                for t4 in (t for t in rngs[3] if t > t3):
                    v = var_for((t1, t2, t3, t4))
                    if v > best:
                        best = v
                        best_idx = (t1, t2, t3, t4)
    return np.asarray(edges_f[list(best_idx)], dtype=np.float64)


def multi_otsu(
    img: np.ndarray, n_classes: int = 3, n_bins: int = 256
) -> MultiOtsuResult:
    """Multi-level Otsu thresholding — ported verbatim.

    Thresholds are UPPER BIN EDGES of the optimal boundary bins (MATLAB
    edgesF(idx+1)), which differs from skimage's bin-centre convention.
    5-class uses the coarse(64)→fine(windowed 256) scheme.
    """
    if not 2 <= n_classes <= 5:
        raise ValueError("n_classes must be in [2, 5]")
    d = np.asarray(img, dtype=np.float64)
    d_min, d_max = d.min(), d.max()

    if d_max == d_min:
        return MultiOtsuResult(
            thresholds=np.full(n_classes - 1, d_min),
            label_map=np.ones(d.shape, dtype=np.uint8),
            class_fractions=np.array([1.0] + [0.0] * (n_classes - 1)),
            class_ranges=np.tile([d_min, d_max], (n_classes, 1)),
        )

    def build_hist(n_b: int) -> tuple[np.ndarray, np.ndarray]:
        edges = np.linspace(d_min, d_max, n_b + 1)
        counts, _ = np.histogram(d.ravel(), bins=edges)
        prob = counts / counts.sum()
        return prob, edges

    if n_classes == 5:
        thresh_vals = _five_class_thresholds(build_hist, d_min, d_max, n_bins)
    else:
        prob_f, edges_f = build_hist(n_bins)
        best_idx_arr = _best_thresholds(prob_f, n_classes)
        thresh_vals = edges_f[best_idx_arr]  # upper edge of boundary bin

    label_map = np.ones(d.shape, dtype=np.uint8)
    for k, t in enumerate(thresh_vals):
        label_map[d > t] = np.uint8(k + 2)

    n_px = d.size
    fracs = np.zeros(n_classes)
    ranges = np.zeros((n_classes, 2))
    for k in range(n_classes):
        m = label_map == k + 1
        fracs[k] = m.sum() / n_px
        if m.any():
            ranges[k] = [d[m].min(), d[m].max()]
        else:
            ranges[k] = [np.nan, np.nan]

    return MultiOtsuResult(
        thresholds=np.asarray(thresh_vals, dtype=np.float64),
        label_map=label_map,
        class_fractions=fracs,
        class_ranges=ranges,
    )


# ── morphology ────────────────────────────────────────────────────────


def _structuring_element(radius: int, shape: str) -> np.ndarray:
    r = int(radius)
    if shape == "square":
        return np.ones((2 * r + 1, 2 * r + 1), dtype=bool)
    if shape == "disk":
        yy, xx = np.mgrid[-r : r + 1, -r : r + 1]
        return np.asarray(np.hypot(xx, yy) <= r)
    raise ValueError("shape must be 'square' or 'disk'")


def morph_op(
    img: np.ndarray, operation: str, radius: int = 1, shape: str = "square"
) -> np.ndarray:
    """Binary morphology — maps to scipy with zero-border semantics.

    The MATLAB version is conv2-based with zero padding, so borders
    erode; scipy's border_value=0 default matches. open/close are
    composed explicitly to keep both stages on border_value=0.
    """
    bw = np.asarray(img) > 0
    se = _structuring_element(radius, shape)
    if operation == "erode":
        out = ndimage.binary_erosion(bw, structure=se, border_value=0)
    elif operation == "dilate":
        out = ndimage.binary_dilation(bw, structure=se, border_value=0)
    elif operation == "open":
        out = ndimage.binary_dilation(
            ndimage.binary_erosion(bw, structure=se, border_value=0),
            structure=se,
            border_value=0,
        )
    elif operation == "close":
        out = ndimage.binary_erosion(
            ndimage.binary_dilation(bw, structure=se, border_value=0),
            structure=se,
            border_value=0,
        )
    else:
        raise ValueError("operation must be erode/dilate/open/close")
    return np.asarray(out, dtype=bool)


# ── connected components ─────────────────────────────────────────────


def label_components(
    bw: np.ndarray, connectivity: int = 8
) -> tuple[np.ndarray, int]:
    """Connected-component labelling — maps to scipy.ndimage.label.

    Same partition as the MATLAB union-find; numbering is raster-order
    first-encounter in both. conn 4 → cross structure, 8 → full 3×3.
    """
    if connectivity not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")
    structure = (
        np.ones((3, 3), dtype=bool)
        if connectivity == 8
        else ndimage.generate_binary_structure(2, 1)
    )
    labels, n = ndimage.label(np.asarray(bw) > 0, structure=structure)
    return labels, int(n)


# ── distance transform ───────────────────────────────────────────────


def distance_transform(
    bw: np.ndarray, metric: str = "chamfer34"
) -> np.ndarray:
    """Two-pass chamfer distance — ported verbatim (do-not-"fix").

    chamfer34 (orthogonal 3 / diagonal 4) is the classic integer
    approximation to 3× Euclidean; divide by 3 for pixel units. scipy
    offers exact-EDT/taxicab/chessboard but not chamfer 3-4, and the
    MATLAB goldens encode this metric. Row scans use the running-min
    identity min_k(base[k] + s·(c−k)) = s·c + runmin(base[k] − s·k) so
    the within-row propagation vectorizes.
    """
    if metric == "chamfer34":
        d_ort, d_diag = 3.0, 4.0
    elif metric == "cityblock":
        d_ort, d_diag = 1.0, np.inf
    else:
        raise ValueError("metric must be 'chamfer34' or 'cityblock'")

    mask = np.asarray(bw) > 0
    h, w = mask.shape
    if not mask.any():
        return np.zeros((h, w))

    dist = np.where(mask, np.inf, 0.0)
    cols = np.arange(w, dtype=np.float64)

    def row_scan(base: np.ndarray, step: float, reverse: bool) -> np.ndarray:
        """min over k≤c of base[k] + step·(c−k) (or k≥c when reverse)."""
        if reverse:
            shifted = base[::-1] - step * cols  # reindexed running min
            run = np.minimum.accumulate(shifted)
            return (run + step * cols)[::-1]
        shifted = base - step * cols
        run = np.minimum.accumulate(shifted)
        return run + step * cols

    # forward pass: incorporate the row above, then propagate leftward
    for r in range(h):
        base = dist[r].copy()
        if r > 0:
            base = np.minimum(base, dist[r - 1] + d_ort)
            if np.isfinite(d_diag):
                up = dist[r - 1]
                base[1:] = np.minimum(base[1:], up[:-1] + d_diag)
                base[:-1] = np.minimum(base[:-1], up[1:] + d_diag)
        dist[r] = row_scan(base, d_ort, reverse=False)

    # backward pass: row below, then propagate rightward
    for r in range(h - 1, -1, -1):
        base = dist[r].copy()
        if r < h - 1:
            base = np.minimum(base, dist[r + 1] + d_ort)
            if np.isfinite(d_diag):
                dn = dist[r + 1]
                base[1:] = np.minimum(base[1:], dn[:-1] + d_diag)
                base[:-1] = np.minimum(base[:-1], dn[1:] + d_diag)
        dist[r] = row_scan(base, d_ort, reverse=True)

    dist[~mask] = 0.0
    return dist
