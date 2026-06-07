"""Grain segmentation & statistics — W4 item 15 (ported).

Texture features (multi-scale local stats + structure-tensor
orientation encodings) → k-means clustering → per-cluster connected
components → grain measurements + boundary network. Scribble-trained
segmentation and rendering/CSV helpers stay MATLAB-side for now.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.filters import apply_gaussian
from fermiviewer.calc.ml import kmeans_lite, standardize_features
from fermiviewer.calc.particles import RegionStats, region_stats
from fermiviewer.calc.segment import label_components
from fermiviewer.calc.texture import structure_tensor

__all__ = [
    "GrainSegmentation",
    "GrainStats",
    "extract_grain_features",
    "grain_stats",
    "segment_auto",
]


def extract_grain_features(
    img: np.ndarray,
    scales: tuple[float, ...] = (2.0, 4.0),
    gradient_sigma: float = 0.0,
) -> np.ndarray:
    """(H, W, F) texture feature stack — ported.

    Per scale: local mean/std (Gaussian moments), structure-tensor
    coherence and the 2θ orientation encoded as coherence·(cos, sin)
    so it is continuous across the ±90° wrap.
    """
    d = np.asarray(img, dtype=np.float64)
    if gradient_sigma > 0:
        d = apply_gaussian(d, gradient_sigma)

    gy, gx = np.gradient(d)
    layers = [d, np.hypot(gx, gy)]
    for s in scales:
        local_mean = apply_gaussian(d, s)
        local_msq = apply_gaussian(d**2, s)
        local_std = np.sqrt(np.maximum(local_msq - local_mean**2, 0))
        st = structure_tensor(d, sigma=s)
        layers.extend(
            [
                local_mean,
                local_std,
                st.coherence,
                st.coherence * np.cos(2 * st.orientation),
                st.coherence * np.sin(2 * st.orientation),
            ]
        )
    return np.stack(layers, axis=2)


@dataclass(frozen=True)
class GrainSegmentation:
    labels: np.ndarray
    n_grains: int
    cluster_map: np.ndarray
    inertia: float
    k: int


def segment_auto(
    img: np.ndarray,
    k: int = 4,
    scales: tuple[float, ...] = (2.0, 4.0),
    gradient_sigma: float = 0.0,
    features: np.ndarray | None = None,
    seed: int = 0,
    replicates: int = 3,
    min_area: int = 25,
    connectivity: int = 8,
    progress: Callable[[float, str], None] | None = None,
) -> GrainSegmentation:
    """Unsupervised grain segmentation — ported (pixel path; the
    superpixel fast path stays MATLAB-side until needed)."""
    if progress:
        progress(0.05, "extracting texture features")
    if features is None:
        feats = extract_grain_features(
            img, scales=scales, gradient_sigma=gradient_sigma
        )
    else:
        feats = np.asarray(features, dtype=np.float64)
    h, w, f = feats.shape

    # MATLAB reshape is column-major; keep the same sample order so the
    # RNG-dependent seeding sees the same rows
    if progress:
        progress(0.35, "clustering")
    x = feats.reshape(h * w, f, order="F")
    z, _, _ = standardize_features(x)
    labels_flat, _, info = kmeans_lite(
        z, k, seed=seed, replicates=replicates
    )
    cluster_map = labels_flat.reshape(h, w, order="F")

    if progress:
        progress(0.8, "labelling grains")
    labels = np.zeros((h, w), dtype=np.int64)
    g = 0
    for c in range(1, info.k + 1):
        mask = cluster_map == c
        if not mask.any():
            continue
        lc, nc = label_components(mask, connectivity)
        for j in range(1, nc + 1):
            comp = lc == j
            if comp.sum() >= min_area:
                g += 1
                labels[comp] = g

    return GrainSegmentation(
        labels=labels,
        n_grains=g,
        cluster_map=cluster_map,
        inertia=info.inertia,
        k=info.k,
    )


@dataclass(frozen=True)
class GrainStats:
    n_grains: int
    grains: list[RegionStats]
    labels: np.ndarray
    boundary: np.ndarray
    boundary_length_px: int
    boundary_length_calibrated: float
    n_boundary_segments: int
    area_px: np.ndarray
    equiv_diameter_px: np.ndarray
    area_calibrated: np.ndarray
    diameter_calibrated: np.ndarray


def grain_stats(
    labels: np.ndarray,
    img: np.ndarray,
    pixel_size: float = float("nan"),
    min_area: int = 1,
    connectivity: int = 8,
) -> GrainStats:
    """Per-grain measurements + grain-boundary network — ported."""
    grains, lab, n = region_stats(
        labels, img, min_area=min_area, pixel_size=pixel_size
    )

    boundary = np.zeros(lab.shape, dtype=bool)
    dh = (lab[:, :-1] != lab[:, 1:]) & (lab[:, :-1] > 0) & (lab[:, 1:] > 0)
    boundary[:, :-1] |= dh
    boundary[:, 1:] |= dh
    dv = (lab[:-1, :] != lab[1:, :]) & (lab[:-1, :] > 0) & (lab[1:, :] > 0)
    boundary[:-1, :] |= dv
    boundary[1:, :] |= dv

    _, n_segments = label_components(boundary, connectivity)
    length_px = int(boundary.sum())
    has_cal = np.isfinite(pixel_size) and pixel_size > 0

    return GrainStats(
        n_grains=n,
        grains=grains,
        labels=lab,
        boundary=boundary,
        boundary_length_px=length_px,
        boundary_length_calibrated=(
            length_px * pixel_size if has_cal else float("nan")
        ),
        n_boundary_segments=n_segments,
        area_px=np.array([g.area for g in grains], dtype=np.float64),
        equiv_diameter_px=np.array(
            [g.equiv_diameter for g in grains], dtype=np.float64
        ),
        area_calibrated=np.array(
            [g.area_calibrated for g in grains], dtype=np.float64
        ),
        diameter_calibrated=np.array(
            [g.diameter_calibrated for g in grains], dtype=np.float64
        ),
    )
