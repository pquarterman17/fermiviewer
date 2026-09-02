"""Grain segmentation & statistics — W4 item 15 (ported).

Texture features (multi-scale local stats + structure-tensor
orientation encodings) → k-means clustering → per-cluster connected
components → grain measurements + boundary network. The scribble-trained
classifier variant lives in grains_trained.py (shares extract_grain_features);
rendering/CSV helpers stay MATLAB-side for now.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from skimage import graph, measure, morphology, segmentation
from skimage.filters import scharr

from fermiviewer.calc.crofton import crofton_perimeters_by_label, usable_spacing
from fermiviewer.calc.filters import apply_gaussian
from fermiviewer.calc.ml import kmeans_lite, standardize_features
from fermiviewer.calc.normalize import normalize01 as _normalize01
from fermiviewer.calc.normalize import robust_normalize01 as _robust_normalize01
from fermiviewer.calc.normalize import sanitize as _sanitize
from fermiviewer.calc.particles import RegionStats, region_stats, resolve_pixel_area
from fermiviewer.calc.segment import label_components
from fermiviewer.calc.texture import structure_tensor

__all__ = [
    "GrainSegmentation",
    "GrainStats",
    "WatershedSegmentation",
    "enforce_connected_grains",
    "extract_grain_features",
    "grain_stats",
    "segment_auto",
    "segment_watershed",
    "split_grain",
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
        # NaN/Inf-safe (no-op on clean data → golden path unchanged)
        feats = extract_grain_features(
            _sanitize(img), scales=scales, gradient_sigma=gradient_sigma
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


def _relabel_connected(
    labels: np.ndarray, min_area: int, connectivity: int = 8
) -> tuple[np.ndarray, int]:
    """Split each label into its connected components, drop those below
    min_area, and renumber 1..N (raster order)."""
    out = np.zeros(labels.shape, dtype=np.int64)
    g = 0
    for lab in np.unique(labels):
        if lab == 0:
            continue
        cc, ncc = label_components(labels == lab, connectivity)
        for j in range(1, ncc + 1):
            comp = cc == j
            if comp.sum() >= min_area:
                g += 1
                out[comp] = g
    return out, g


@dataclass(frozen=True)
class WatershedSegmentation:
    labels: np.ndarray
    n_grains: int
    method: str
    granularity: float


def _boundary_watershed(
    boundary: np.ndarray, granularity: float, compactness: float
) -> np.ndarray:
    """Marker-controlled watershed on a [0,1] boundary/gradient map.

    Interior markers are the h-minima (smooth low-gradient basins = grain
    interiors); basins grow until they meet at ridges (boundaries).
    `granularity` is h — the minimum basin depth, so higher → fewer grains.
    """
    markers_mask = morphology.h_minima(boundary, max(granularity, 1e-6)) > 0
    markers = measure.label(markers_mask)
    if markers.max() == 0:
        # granularity too aggressive → one basin at the global minimum
        markers = np.zeros(boundary.shape, dtype=np.int64)
        markers[np.unravel_index(int(np.argmin(boundary)), boundary.shape)] = 1
    return np.asarray(
        segmentation.watershed(boundary, markers, compactness=compactness),
        dtype=np.int64,
    )


def segment_watershed(
    img: np.ndarray,
    method: str = "gradient",
    granularity: float = 0.05,
    compactness: float = 0.001,
    min_area: int = 25,
    n_superpixels: int = 400,
    merge_threshold: float = 0.08,
    orientation_sigma: float = 2.0,
    denoise_sigma: float = 0.0,
    robust: bool = True,
    clip_percentile: float = 0.5,
    progress: Callable[[float, str], None] | None = None,
) -> WatershedSegmentation:
    """Modern grain segmentation (scikit-image; no MATLAB-parity target).

    method:
      "gradient"    — marker-controlled watershed on the Scharr gradient.
                      Use when grain boundaries are visible as contrast
                      lines (BF/DF-TEM, etched SEM).
      "rag"         — SLIC superpixels merged by a region-adjacency graph
                      on mean intensity. Use for diffraction-contrast
                      grains (uniform patches at different brightness).
      "orientation" — watershed on a structure-tensor misorientation map.
                      Use for atomic-resolution lattices where grains
                      differ by lattice orientation, not brightness.

    The coarseness knob is `granularity` for gradient/orientation (h-minima
    depth) and `merge_threshold` for rag (max mean-intensity gap that still
    merges two superpixels) — both higher → fewer, larger grains.

    Robustness for real EM data: ``robust`` (default) uses an outlier-
    rejecting percentile stretch (``clip_percentile`` per tail) so hot/dead
    pixels don't crush the contrast range, and NaN/Inf are filled with the
    finite median; ``denoise_sigma>0`` Gaussian-smooths first to suppress
    noise-driven over-segmentation (every gradient ridge from shot noise
    would otherwise seed a spurious basin).
    """
    d = (
        _robust_normalize01(img, clip_percentile)
        if robust
        else _normalize01(img)
    )
    if d.shape[0] < 2 or d.shape[1] < 2:
        raise ValueError("image too small to segment (need at least 2×2)")
    if denoise_sigma > 0:
        d = _normalize01(apply_gaussian(d, denoise_sigma))
    if progress:
        progress(0.1, f"segmenting ({method})")

    if method == "gradient":
        boundary = _normalize01(scharr(d))
        raw = _boundary_watershed(boundary, granularity, compactness)
        knob = granularity
    elif method == "orientation":
        st = structure_tensor(d, sigma=orientation_sigma)
        c2 = apply_gaussian(st.coherence * np.cos(2 * st.orientation), orientation_sigma)
        s2 = apply_gaussian(st.coherence * np.sin(2 * st.orientation), orientation_sigma)
        gy1, gx1 = np.gradient(c2)
        gy2, gx2 = np.gradient(s2)
        boundary = _normalize01(np.hypot(gx1, gy1) + np.hypot(gx2, gy2))
        raw = _boundary_watershed(boundary, granularity, compactness)
        knob = granularity
    elif method == "rag":
        if progress:
            progress(0.3, "superpixels")
        seg = segmentation.slic(
            d, n_segments=max(2, n_superpixels), compactness=0.1,
            channel_axis=None, start_label=1,
        )
        rag = graph.rag_mean_color(d, seg)
        raw = graph.cut_threshold(seg, rag, merge_threshold)
        knob = merge_threshold
    else:
        raise ValueError("method must be 'gradient', 'rag' or 'orientation'")

    if progress:
        progress(0.85, "labelling grains")
    # these methods tile the whole field (no background); shift to 1-based
    # so a 0-origin label (e.g. from cut_threshold) isn't dropped as bg
    raw = np.asarray(raw, dtype=np.int64)
    raw = raw - int(raw.min()) + 1
    labels, n = _relabel_connected(raw, min_area)
    return WatershedSegmentation(
        labels=labels, n_grains=n, method=method, granularity=float(knob),
    )


def split_grain(
    labels: np.ndarray,
    img: np.ndarray,
    grain_id: int,
    granularity: float = 0.03,
) -> np.ndarray:
    """Split one grain into sub-grains by re-running the gradient watershed
    restricted to that grain's mask (interactive over-segment fix). The
    first basin keeps `grain_id`, the rest get fresh ids. EVERY mask pixel
    is reassigned (watershed fills the whole mask), so no pixel is left at
    the old id — the result never has a disconnected label. A no-op
    (returns a copy) if the grain has < 2 internal basins."""
    lab = np.asarray(labels, dtype=np.int64).copy()
    mask = lab == grain_id
    if not mask.any():
        return lab
    boundary = _normalize01(scharr(_normalize01(img)))
    markers_mask = (morphology.h_minima(boundary, max(granularity, 1e-6)) > 0) & mask
    markers = measure.label(markers_mask)
    if int(markers.max()) < 2:
        return lab  # only one basin → nothing to split
    sub = np.asarray(segmentation.watershed(boundary, markers, mask=mask))
    next_id = int(lab.max()) + 1
    for s in range(1, int(sub.max()) + 1):
        comp = sub == s
        if not comp.any():
            continue
        lab[comp] = grain_id if s == 1 else next_id
        if s != 1:
            next_id += 1
    return lab


def enforce_connected_grains(
    labels: np.ndarray, min_area: int = 1
) -> np.ndarray:
    """Split each label into its connected components and renumber 1..N, so
    every grain is a single connected region — the invariant region_stats /
    grain_stats assume. Used after an interactive merge/split, where merging
    two non-adjacent grains or a split's leftover pixels could otherwise
    leave one label spanning disconnected pieces (→ phantom stats)."""
    out, _ = _relabel_connected(labels, min_area)
    return out


def _count_triple_junctions(labels: np.ndarray) -> int:
    """Number of triple (or higher) junctions — points where ≥3 grains
    meet. Found as 2×2 windows spanning ≥3 distinct grain labels."""
    lab = np.asarray(labels, dtype=np.int64)
    tl, tr = lab[:-1, :-1], lab[:-1, 1:]
    bl, br = lab[1:, :-1], lab[1:, 1:]
    # count distinct positive labels in each 2×2 window
    corners = np.stack([tl, tr, bl, br], axis=0)
    distinct = np.zeros(tl.shape, dtype=np.int64)
    for i in range(4):
        seen_before = np.zeros(tl.shape, dtype=bool)
        for j in range(i):
            seen_before |= corners[i] == corners[j]
        distinct += (corners[i] > 0) & ~seen_before
    junction = distinct >= 3
    _, n = label_components(junction, connectivity=8)
    return int(n)


@dataclass(frozen=True)
class GrainStats:
    n_grains: int
    grains: list[RegionStats]
    labels: np.ndarray
    boundary: np.ndarray
    n_boundary_segments: int
    area_px: np.ndarray
    equiv_diameter_px: np.ndarray
    area_calibrated: np.ndarray
    diameter_calibrated: np.ndarray
    # true grain-boundary NETWORK length = count of unit edges between
    # adjacent grains (border-excluding) — matches fermi-viewer's
    # corrected dh+dv grainStats formula (a57c7d5).
    boundary_network_px: float
    boundary_network_calibrated: float
    perimeter_crofton_px: np.ndarray
    #: Crofton perimeter in the calibrated unit, or NaN. Not
    #: `perimeter_crofton_px * pixel_size`: on anisotropic pixels the two
    #: are not proportional, because the boundary's two directions scale
    #: by different amounts.
    perimeter_calibrated: np.ndarray
    #: Measured in PHYSICAL space when `spacing` is given. Dimensionless
    #: is not scale-invariant when only ONE axis is scaled: a round grain
    #: on 2:1 pixels is an ellipse in the array, so pixel-space
    #: eccentricity describes the sampling rather than the grain.
    eccentricity: np.ndarray
    orientation_rad: np.ndarray
    solidity: np.ndarray
    n_triple_junctions: int


def grain_stats(
    labels: np.ndarray,
    img: np.ndarray,
    pixel_size: float = float("nan"),
    pixel_area: float = float("nan"),
    min_area: int = 1,
    connectivity: int = 8,
    *,
    spacing: tuple[float, float] | None = None,
) -> GrainStats:
    """Per-grain measurements + grain-boundary network — ported.

    `spacing` is the physical extent of one pixel as ``(row, column)``
    (`DataStruct.pixel_spacing`). Given it, the shape descriptors and the
    boundary-network length are measured in physical space; omitted, they
    are pixel-space, exactly as before spacing existed.
    """
    # A caller with only a length still gets calibrated numbers: an
    # explicit area or spacing wins, and `pixel_size` is squared for the
    # area and read as isotropic spacing when neither is given. Without
    # this, `grain_stats(pixel_size=...)` -- the signature this had before
    # per-axis calibration existed -- returns NaN diameters silently.
    pixel_area = resolve_pixel_area(pixel_area, pixel_size)
    if spacing is None and np.isfinite(pixel_size) and pixel_size > 0:
        spacing = (float(pixel_size), float(pixel_size))
    grains, lab, n = region_stats(
        labels, img, min_area=min_area, pixel_area=pixel_area
    )

    boundary = np.zeros(lab.shape, dtype=bool)
    dh = (lab[:, :-1] != lab[:, 1:]) & (lab[:, :-1] > 0) & (lab[:, 1:] > 0)
    boundary[:, :-1] |= dh
    boundary[:, 1:] |= dh
    dv = (lab[:-1, :] != lab[1:, :]) & (lab[:-1, :] > 0) & (lab[1:, :] > 0)
    boundary[:-1, :] |= dv
    boundary[1:, :] |= dv

    _, n_segments = label_components(boundary, connectivity)
    # grain-boundary NETWORK length: one unit per inter-grain edge (each
    # boundary counted once, image border excluded) — the correct length,
    # unlike summing per-grain perimeters which double-counts + adds borders
    n_dh, n_dv = int(dh.sum()), int(dv.sum())
    network_px = float(n_dh + n_dv)
    has_cal = np.isfinite(pixel_size) and pixel_size > 0
    space = usable_spacing(spacing)
    # Two horizontally-adjacent pixels share a VERTICAL edge, whose length
    # is the pixel's ROW extent -- and vice versa. Multiplying the summed
    # edge COUNT by a single scale silently assumes those two lengths are
    # equal; this reduces to that product exactly when they are.
    if space is not None:
        network_cal = n_dh * space[0] + n_dv * space[1]
    elif has_cal:
        network_cal = network_px * pixel_size
    else:
        network_cal = float("nan")

    # ── additional per-grain shape metrics ──
    if n > 0:
        # Descriptors come from the physical grid when there is one. The
        # perimeter comes from `calc.crofton` because skimage refuses
        # `perimeter_crofton` under anisotropic spacing; on square pixels
        # the two agree bit for bit.
        rpt = measure.regionprops_table(
            lab,
            properties=["label", "eccentricity", "orientation", "solidity"],
            spacing=space or (1.0, 1.0),
        )
        perim = crofton_perimeters_by_label(lab)
        if space is None:
            perim_cal = np.full(n, np.nan)
        elif space[0] == space[1]:
            # Isotropic: a perimeter is a length, so one factor is exact
            # and a second Crofton pass would recompute the same numbers.
            perim_cal = perim * space[0]
        else:
            perim_cal = crofton_perimeters_by_label(lab, space)
        ecc = np.asarray(rpt["eccentricity"], dtype=np.float64)
        orient = np.asarray(rpt["orientation"], dtype=np.float64)
        solidity = np.asarray(rpt["solidity"], dtype=np.float64)
    else:
        perim = perim_cal = ecc = orient = solidity = np.array([], dtype=np.float64)

    return GrainStats(
        n_grains=n,
        grains=grains,
        labels=lab,
        boundary=boundary,
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
        boundary_network_px=network_px,
        boundary_network_calibrated=(
            network_cal
        ),
        perimeter_crofton_px=perim,
        perimeter_calibrated=perim_cal,
        eccentricity=ecc,
        orientation_rad=orient,
        solidity=solidity,
        n_triple_junctions=_count_triple_junctions(lab),
    )
