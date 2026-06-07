"""Particle segmentation & measurement — W3 tranche 2 (audit doc).

watershed is a FULL verbatim port. The audit originally proposed a
hybrid (skimage flood on −D), but the empirical divergence was large —
the priority-flood partitions basins differently from MATLAB's
descending-D adoption flood (areas off by up to ~70 px on the golden
synthetic), so the flood is ported exactly: process foreground pixels
in descending-distance order (column-major tie order), each adopting
the label of its highest-D labelled neighbour, multi-pass until stable.
Python-loop flood is O(passes·N); fine to ~1k² images, revisit with a
compiled path if 4k watershed becomes interactive.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.segment import (
    distance_transform,
    label_components,
    multi_otsu,
)

__all__ = [
    "ParticleAnalysis",
    "RegionStats",
    "auto_markers",
    "particle_analysis",
    "region_stats",
    "watershed",
]


def auto_markers(
    dist: np.ndarray, mask: np.ndarray, min_distance: float
) -> tuple[np.ndarray, int]:
    """Regional-maxima markers via grid-based greedy NMS — ported.

    Candidates are sorted by descending distance with MATLAB's
    column-major tie order; a candidate must be a (non-strict) 3×3
    local max and farther than min_distance from every accepted marker.
    """
    h, w = dist.shape
    markers = np.zeros((h, w), dtype=np.int64)
    cc, rr = np.nonzero(mask.T)  # column-major like MATLAB find()
    if rr.size == 0:
        return markers, 0
    vals = dist[rr, cc]
    order = np.argsort(-vals, kind="stable")
    rr, cc, vals = rr[order], cc[order], vals[order]

    cell = max(1.0, min_distance)
    min_d2 = min_distance**2
    grid: dict[tuple[int, int], list[int]] = {}
    k = 0
    accepted_r: list[int] = []
    accepted_c: list[int] = []

    for i in range(rr.size):
        if vals[i] <= 0:
            continue
        r, c = int(rr[i]), int(cc[i])
        v = dist[r, c]
        patch = dist[max(0, r - 1) : r + 2, max(0, c - 1) : c + 2]
        if (patch > v).any():
            continue
        gr = int(r // cell)
        gc = int(c // cell)
        too_close = False
        for dgr in (-1, 0, 1):
            for dgc in (-1, 0, 1):
                for j in grid.get((gr + dgr, gc + dgc), ()):
                    if (r - accepted_r[j]) ** 2 + (
                        c - accepted_c[j]
                    ) ** 2 < min_d2:
                        too_close = True
                        break
                if too_close:
                    break
            if too_close:
                break
        if too_close:
            continue
        k += 1
        markers[r, c] = k
        grid.setdefault((gr, gc), []).append(len(accepted_r))
        accepted_r.append(r)
        accepted_c.append(c)

    return markers, k


def watershed(
    bw: np.ndarray,
    min_marker_distance: float = 3.0,
    markers: np.ndarray | None = None,
    connectivity: int = 8,
) -> tuple[np.ndarray, int]:
    """Marker-based watershed split of a binary mask — hybrid port.

    Returns (labels, n_regions); 0 = background. Unmarked disconnected
    foreground gets fresh labels via connected components (straggler
    fallback, as in MATLAB).
    """
    if connectivity not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")
    mask = np.asarray(bw) > 0
    if not mask.any():
        return np.zeros(mask.shape, dtype=np.int64), 0

    dist = distance_transform(mask, metric="chamfer34")
    if markers is None:
        marker_img, n_markers = auto_markers(dist, mask, min_marker_distance)
    else:
        marker_img = np.asarray(markers, dtype=np.int64)
        if marker_img.shape != mask.shape:
            raise ValueError("markers must match bw shape")
        n_markers = int(marker_img.max())

    if n_markers == 0:
        return label_components(mask, connectivity)

    labels = _adoption_flood(dist, mask, marker_img, connectivity)

    stragglers = mask & (labels == 0)
    if stragglers.any():
        rest, n_rest = label_components(stragglers, connectivity)
        labels[stragglers] = rest[stragglers] + n_markers
        n_markers += n_rest

    return labels, n_markers


_OFFSETS_4 = ((-1, 0), (0, -1), (0, 1), (1, 0))
_OFFSETS_8 = (  # MATLAB scan order — ties pick the first scanned neighbour
    (-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1),
)


def _adoption_flood(
    dist: np.ndarray,
    mask: np.ndarray,
    markers: np.ndarray,
    connectivity: int,
) -> np.ndarray:
    """MATLAB watershed flood — ported verbatim.

    Pixels are processed in descending-distance order (column-major tie
    order, like MATLAB find + stable sort); each adopts the label of
    its highest-D labelled neighbour. Unresolved pixels retry on the
    next pass (max 10; 2–3 suffice in practice).
    """
    h, w = mask.shape
    labels = markers.astype(np.int64).copy()
    offsets = _OFFSETS_4 if connectivity == 4 else _OFFSETS_8

    todo = mask & (markers == 0)
    cc, rr = np.nonzero(todo.T)  # column-major like MATLAB find()
    vals = dist[rr, cc]
    order = np.argsort(-vals, kind="stable")
    rr = rr[order]
    cc = cc[order]

    for _ in range(10):
        any_assigned = False
        remaining: list[int] = []
        for k in range(rr.size):
            r = int(rr[k])
            c = int(cc[k])
            if labels[r, c] != 0:
                continue
            best_label = 0
            best_d = -np.inf
            for dr, dc in offsets:
                nr = r + dr
                nc = c + dc
                if 0 <= nr < h and 0 <= nc < w:
                    lbl = labels[nr, nc]
                    if lbl > 0 and dist[nr, nc] > best_d:
                        best_d = dist[nr, nc]
                        best_label = int(lbl)
            if best_label > 0:
                labels[r, c] = best_label
                any_assigned = True
            else:
                remaining.append(k)
        rr = rr[remaining]
        cc = cc[remaining]
        if rr.size == 0 or not any_assigned:
            break

    return labels


@dataclass(frozen=True)
class RegionStats:
    id: int
    area: int
    centroid: tuple[float, float]  # (row, col), 1-based like MATLAB
    bbox: tuple[int, int, int, int]  # (rmin, cmin, rmax, cmax), 1-based
    equiv_diameter: float
    mean_intensity: float
    area_calibrated: float
    diameter_calibrated: float


def region_stats(
    labels: np.ndarray,
    img: np.ndarray,
    min_area: int = 1,
    pixel_size: float = float("nan"),
) -> tuple[list[RegionStats], np.ndarray, int]:
    """Per-region measurements with MinArea filter + compact renumber.

    1-based centroid/bbox to mirror the MATLAB convention (the wire/API
    layer converts as needed). Returns (regions, renumbered_labels, n).
    """
    lab = np.asarray(labels, dtype=np.int64)
    d = np.asarray(img, dtype=np.float64)
    has_cal = np.isfinite(pixel_size) and pixel_size > 0

    out: list[RegionStats] = []
    n = int(lab.max())
    for k in range(1, n + 1):
        sel = lab == k
        area = int(sel.sum())
        if area < min_area or area == 0:
            continue
        rs, cs = np.nonzero(sel)
        eq_d = float(np.sqrt(4 * area / np.pi))
        out.append(
            RegionStats(
                id=len(out) + 1,
                area=area,
                centroid=(float(rs.mean()) + 1, float(cs.mean()) + 1),
                bbox=(
                    int(rs.min()) + 1,
                    int(cs.min()) + 1,
                    int(rs.max()) + 1,
                    int(cs.max()) + 1,
                ),
                equiv_diameter=eq_d,
                mean_intensity=float(d[sel].mean()),
                area_calibrated=area * pixel_size**2 if has_cal else np.nan,
                diameter_calibrated=eq_d * pixel_size if has_cal else np.nan,
            )
        )

    if len(out) < n:
        renumbered = np.zeros_like(lab)
        keep_ids = []
        # recover original ids in kept order: re-walk labels
        kept = 0
        for k in range(1, n + 1):
            sel = lab == k
            area = int(sel.sum())
            if area < min_area or area == 0:
                continue
            kept += 1
            renumbered[sel] = kept
            keep_ids.append(k)
        return out, renumbered, len(out)
    return out, lab, len(out)


@dataclass(frozen=True)
class ParticleAnalysis:
    mask: np.ndarray
    labels: np.ndarray
    n_particles: int
    threshold: float
    particles: list[RegionStats]


def particle_analysis(
    img: np.ndarray,
    threshold: float | None = None,
    polarity: str = "bright",
    connectivity: int = 8,
    min_area: int = 1,
    pixel_size: float = float("nan"),
    use_watershed: bool = False,
    min_marker_distance: float = 3.0,
) -> ParticleAnalysis:
    """Threshold → label (optionally watershed-split) → measure — ported."""
    if polarity not in ("bright", "dark"):
        raise ValueError("polarity must be 'bright' or 'dark'")
    d = np.asarray(img, dtype=np.float64)

    thr = (
        float(multi_otsu(d, n_classes=2).thresholds[0])
        if threshold is None
        else float(threshold)
    )
    mask = d >= thr if polarity == "bright" else d < thr

    if use_watershed:
        lab, _ = watershed(
            mask,
            min_marker_distance=min_marker_distance,
            connectivity=connectivity,
        )
    else:
        lab, _ = label_components(mask, connectivity)

    parts, lab, kept = region_stats(
        lab, d, min_area=min_area, pixel_size=pixel_size
    )
    return ParticleAnalysis(
        mask=mask,
        labels=lab,
        n_particles=kept,
        threshold=thr,
        particles=parts,
    )
