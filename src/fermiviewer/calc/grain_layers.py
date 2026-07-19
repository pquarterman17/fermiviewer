"""Spatial grain measurements inside reviewed cross-section layers.

The layer detector reports interface depths in ROI-local, zero-based pixels.
This module intersects those reviewed bands with an integer grain-label map and
measures each resulting grain slice in depth/lateral coordinates.  It does not
infer crystallographic orientation: ``shape_angle_deg`` is the major-axis angle
of the segmented shape relative to the layer plane.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.roi import RectRoi, embed_rect_roi, extract_rect_roi


@dataclass(frozen=True)
class LayerBounds:
    index: int
    top: float
    bottom: float


@dataclass(frozen=True)
class GrainSlice:
    source_grain_id: int
    area_px: int
    lateral_width_px: float
    depth_height_px: float
    lateral_width: float
    depth_height: float
    aspect_ratio: float
    shape_angle_deg: float
    centroid_lateral_px: float
    centroid_depth_px: float
    fraction_of_source_grain: float


@dataclass(frozen=True)
class LayerGrainSummary:
    index: int
    top_px: float
    bottom_px: float
    thickness_px: float
    thickness: float
    area_px: int
    area: float
    n_grains: int
    density_per_mpx: float
    density_per_unit2: float
    occupied_fraction: float
    mean_lateral_width: float
    median_lateral_width: float
    mean_depth_height: float
    mean_aspect_ratio: float
    mean_shape_angle_deg: float
    cross_layer_grains: int
    grains: tuple[GrainSlice, ...]


@dataclass(frozen=True)
class GrainLayerResult:
    axis: str
    pixel_size: float
    unit: str
    layers: tuple[LayerGrainSummary, ...]
    assignment: np.ndarray


def _boundary(
    traces: Sequence[np.ndarray | None], index: int, fallback: float, width: int,
) -> np.ndarray:
    if index >= len(traces) or traces[index] is None:
        return np.full(width, fallback, dtype=np.float64)
    values = np.asarray(traces[index], dtype=np.float64)
    if values.ndim != 1 or values.size != width:
        raise ValueError("interface trace length must match the ROI lateral dimension")
    return np.where(np.isfinite(values), values, fallback)


def _shape_angle(lateral: np.ndarray, depth: np.ndarray) -> float:
    if lateral.size < 2:
        return 0.0
    points = np.column_stack((lateral, depth)).astype(np.float64)
    covariance = np.cov(points, rowvar=False, ddof=0)
    values, vectors = np.linalg.eigh(covariance)
    major = vectors[:, int(np.argmax(values))]
    angle = abs(float(np.degrees(np.arctan2(major[1], major[0]))))
    return 180.0 - angle if angle > 90.0 else angle


def measure_grains_by_layer(
    labels: np.ndarray,
    layers: Sequence[LayerBounds],
    *,
    selected_indices: Sequence[int],
    axis: str,
    roi: RectRoi | None = None,
    interface_traces: Sequence[np.ndarray | None] = (),
    pixel_size: float = 1.0,
    unit: str = "px",
) -> GrainLayerResult:
    """Measure labelled grain slices inside selected reviewed layer bands.

    ``labels`` is a full-image integer map (0 means boundary/background).
    ``layers`` and optional interface traces use coordinates local to ``roi``.
    A grain crossing a material interface contributes one clipped slice to each
    intersected selected layer; ``fraction_of_source_grain`` makes that split
    explicit. Width is lateral to the stack and height is through-film depth.
    """
    arr = np.asarray(labels)
    if arr.ndim != 2:
        raise ValueError("grain-layer measurement needs a 2-D label map")
    if not np.all(np.isfinite(arr)) or np.any(arr < 0):
        raise ValueError("grain labels must be finite non-negative values")
    if not np.allclose(arr, np.rint(arr)):
        raise ValueError("grain labels must be integer-valued")
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'x' or 'y'")
    if not np.isfinite(pixel_size) or pixel_size <= 0:
        raise ValueError("pixel_size must be finite and positive")

    selected = set(int(i) for i in selected_indices)
    bands = [band for band in layers if band.index in selected]
    if not bands:
        raise ValueError("select at least one detected layer")
    if any(
        not np.isfinite((band.top, band.bottom)).all() or band.bottom <= band.top
        for band in bands
    ):
        raise ValueError("layer bounds must be finite and increasing")

    roi_labels = np.rint(extract_rect_roi(arr, roi)).astype(np.int64)
    depth_labels = roi_labels if axis == "y" else roi_labels.T
    depth_size, lateral_size = depth_labels.shape
    depth = np.arange(depth_size, dtype=np.float64)[:, None]
    totals = np.bincount(depth_labels.ravel())
    assignment_depth = np.zeros_like(depth_labels, dtype=np.int32)
    summaries: list[LayerGrainSummary] = []

    for band in bands:
        top = _boundary(interface_traces, band.index, band.top, lateral_size)
        bottom = _boundary(interface_traces, band.index + 1, band.bottom, lateral_size)
        mask = (depth >= top[None, :]) & (depth < bottom[None, :])
        assignment_depth[mask & (depth_labels > 0)] = band.index + 1
        grain_ids = np.unique(depth_labels[mask & (depth_labels > 0)])
        slices: list[GrainSlice] = []
        for grain_id in grain_ids:
            rr, cc = np.nonzero(mask & (depth_labels == grain_id))
            area_px = int(rr.size)
            lateral_width_px = float(np.ptp(cc) + 1)
            depth_height_px = float(np.ptp(rr) + 1)
            fraction = area_px / int(totals[int(grain_id)])
            slices.append(GrainSlice(
                source_grain_id=int(grain_id), area_px=area_px,
                lateral_width_px=lateral_width_px, depth_height_px=depth_height_px,
                lateral_width=lateral_width_px * pixel_size,
                depth_height=depth_height_px * pixel_size,
                aspect_ratio=lateral_width_px / depth_height_px,
                shape_angle_deg=_shape_angle(cc, rr),
                centroid_lateral_px=float(np.mean(cc)),
                centroid_depth_px=float(np.mean(rr)),
                fraction_of_source_grain=float(fraction),
            ))
        area_px = int(np.count_nonzero(mask))
        occupied = sum(item.area_px for item in slices)
        widths = np.asarray([item.lateral_width for item in slices], dtype=np.float64)
        heights = np.asarray([item.depth_height for item in slices], dtype=np.float64)
        aspects = np.asarray([item.aspect_ratio for item in slices], dtype=np.float64)
        angles = np.asarray([item.shape_angle_deg for item in slices], dtype=np.float64)
        n_grains = len(slices)
        summaries.append(LayerGrainSummary(
            index=band.index, top_px=band.top, bottom_px=band.bottom,
            thickness_px=band.bottom - band.top,
            thickness=(band.bottom - band.top) * pixel_size,
            area_px=area_px, area=area_px * pixel_size ** 2,
            n_grains=n_grains,
            density_per_mpx=n_grains * 1_000_000.0 / area_px if area_px else 0.0,
            density_per_unit2=n_grains / (area_px * pixel_size ** 2) if area_px else 0.0,
            occupied_fraction=occupied / area_px if area_px else 0.0,
            mean_lateral_width=float(np.mean(widths)) if n_grains else 0.0,
            median_lateral_width=float(np.median(widths)) if n_grains else 0.0,
            mean_depth_height=float(np.mean(heights)) if n_grains else 0.0,
            mean_aspect_ratio=float(np.mean(aspects)) if n_grains else 0.0,
            mean_shape_angle_deg=float(np.mean(angles)) if n_grains else 0.0,
            cross_layer_grains=sum(item.fraction_of_source_grain < 0.999 for item in slices),
            grains=tuple(slices),
        ))

    assignment_roi = assignment_depth if axis == "y" else assignment_depth.T
    assignment = embed_rect_roi(assignment_roi, arr.shape, roi)
    return GrainLayerResult(axis, pixel_size, unit, tuple(summaries), assignment)
