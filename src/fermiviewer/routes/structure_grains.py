"""Grain segmentation endpoints: methods, interactive merge/split (plan
item 28 — adapters over W3/W4 calc). Split out of routes/structure.py to
keep both files comfortably under the 500-line ceiling; shares that
module's _raster/_register/_nan_none helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.grains import (
    GrainSegmentation,
    WatershedSegmentation,
    astm_grain_size_number,
    enforce_connected_grains,
    grain_stats,
    segment_auto,
    segment_watershed,
    split_grain,
)
from fermiviewer.calc.roi import embed_rect_roi, extract_rect_roi, parse_rect_roi
from fermiviewer.datastruct import DataStruct
from fermiviewer.jobs import JobQueueFullError, jobs
from fermiviewer.routes._arrays import value_error_as_422
from fermiviewer.routes.structure import _nan_none, _raster, _register
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


# ── grain segmentation ───────────────────────────────────────────────


class GrainRequest(BaseModel):
    image_id: str
    roi: tuple[int, int, int, int] | None = None  # 1-based, inclusive
    # "kmeans" is the ported MATLAB texture-clustering path (kept for parity);
    # the others are scikit-image methods chosen per EM image type
    method: Literal["kmeans", "gradient", "rag", "orientation"] = "gradient"
    # k-means params
    k: int = Field(default=4, ge=2, le=10)
    seed: int = 0
    replicates: int = 3
    # gradient / orientation watershed params
    granularity: float = Field(default=0.05, ge=0.0, le=1.0)
    compactness: float = Field(default=0.001, ge=0.0, le=1.0)
    orientation_sigma: float = Field(default=2.0, ge=0.5, le=8.0)
    # superpixel-RAG params
    n_superpixels: int = Field(default=400, ge=50, le=4000)
    merge_threshold: float = Field(default=0.08, ge=0.0, le=1.0)
    # robustness (watershed methods): denoise pre-pass + outlier-clipped stretch
    denoise_sigma: float = Field(default=0.0, ge=0.0, le=10.0)
    robust: bool = True
    # shared
    min_area: int = 25
    run_async: bool = False


def _grains_payload(
    labels: np.ndarray, method: str, ds: DataStruct, raster: np.ndarray,
    source_id: str, roi: tuple[int, int, int, int] | None = None,
) -> dict:
    """Build the grain-analysis response (shared by initial segmentation and
    interactive merge/split). Registers the renumbered label map tagged so
    the stage can recognize and further edit it."""
    px = ds.pixel_size if np.isfinite(ds.pixel_size) else float("nan")
    stats = grain_stats(labels, raster, pixel_size=px)
    name = store.name(source_id)
    unit = ds.pixel_unit or "px"
    diam_cal = stats.diameter_calibrated
    mean_diam_cal = float(np.nanmean(diam_cal)) if diam_cal.size else float("nan")
    return {
        "n_grains": stats.n_grains,
        "method": method,
        "labels": _register(
            stats.labels.astype(np.float64), f"grains({name})", ds, source_id,
            extra_meta={
                "grain_labels": True,
                "grain_source": source_id,
                "grain_method": method,
            } | ({"grain_roi": ",".join(map(str, roi))} if roi is not None else {}),
        ),
        # true (border-excluding) inter-grain network length
        "boundary_network_px": stats.boundary_network_px,
        "boundary_network_calibrated": _nan_none(stats.boundary_network_calibrated),
        "n_boundary_segments": stats.n_boundary_segments,
        "n_triple_junctions": stats.n_triple_junctions,
        "mean_diameter_px": (
            float(stats.equiv_diameter_px.mean())
            if stats.equiv_diameter_px.size
            else 0.0
        ),
        "astm_grain_size": _nan_none(astm_grain_size_number(mean_diam_cal, unit)),
        "areas_px": stats.area_px.tolist(),
        "perimeters_px": stats.perimeter_crofton_px.tolist(),
        "eccentricity": stats.eccentricity.tolist(),
        # per-grain diameter feeds a size-distribution histogram (#6/R6)
        "equiv_diameter_px": stats.equiv_diameter_px.tolist(),
        "diameter_calibrated": [_nan_none(d) for d in stats.diameter_calibrated],
        "unit": unit,
    }


def _run_grains(
    req: GrainRequest,
    progress: Callable[[float, str], None] | None = None,
) -> dict:
    ds, raster = _raster(req.image_id)
    analysis_raster = extract_rect_roi(raster, req.roi)
    seg: GrainSegmentation | WatershedSegmentation
    if req.method == "kmeans":
        seg = segment_auto(
            analysis_raster, k=req.k, min_area=req.min_area,
            seed=req.seed, replicates=req.replicates, progress=progress,
        )
    else:
        seg = segment_watershed(
            analysis_raster, method=req.method, granularity=req.granularity,
            compactness=req.compactness, min_area=req.min_area,
            n_superpixels=req.n_superpixels, merge_threshold=req.merge_threshold,
            orientation_sigma=req.orientation_sigma,
            denoise_sigma=req.denoise_sigma, robust=req.robust, progress=progress,
        )
    labels = embed_rect_roi(seg.labels, raster.shape, req.roi)
    return _grains_payload(labels, req.method, ds, raster, req.image_id, req.roi)


class GrainEditRequest(BaseModel):
    labels_id: str  # a grain-label map produced by /analyze/grains
    op: Literal["merge", "split"]
    # image-pixel clicks (x, y), 0-based; merge needs ≥2 on distinct grains,
    # split takes the first point's grain
    points: list[tuple[float, float]]
    granularity: float = Field(default=0.03, ge=0.0, le=1.0)


@router.post("/grains/edit")
def grains_edit(req: GrainEditRequest) -> dict:
    try:
        labels_ds = store.get(req.labels_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.labels_id}") from None
    source_id = labels_ds.metadata.get("grain_source")
    if not isinstance(source_id, str):
        raise HTTPException(422, "not an editable grain-label map")
    source_ds, raster = _raster(source_id)
    labels = np.asarray(labels_ds.data, dtype=np.int64).copy()
    h, w = labels.shape

    pts = [
        (int(round(y)), int(round(x)))
        for x, y in req.points
        if 0 <= int(round(y)) < h and 0 <= int(round(x)) < w
    ]
    if not pts:
        raise HTTPException(422, "no points inside the image")

    base = str(labels_ds.metadata.get("grain_method", "edited"))
    if req.op == "merge":
        ids = {int(labels[r, c]) for r, c in pts if labels[r, c] > 0}
        if len(ids) < 2:
            raise HTTPException(422, "merge needs ≥2 distinct grains")
        keep = min(ids)
        for i in ids:
            labels[labels == i] = keep
        method = f"{base}+merge"
    else:  # split
        gid = int(labels[pts[0]])
        if gid <= 0:
            raise HTTPException(422, "click is not on a grain")
        labels = split_grain(labels, raster, gid, granularity=req.granularity)
        method = f"{base}+split"

    # guarantee every grain is one connected region (a merge of non-adjacent
    # grains, or a split, must not leave a label spanning disconnected pieces)
    labels = enforce_connected_grains(labels)
    roi_text = labels_ds.metadata.get("grain_roi")
    roi = parse_rect_roi(roi_text)
    return _grains_payload(labels, method, source_ds, raster, source_id, roi)


@router.post("/analyze/grains")
def analyze_grains(req: GrainRequest) -> dict:
    if req.run_async:
        # validate the image id up front so the 404 is synchronous
        _raster(req.image_id)
        try:
            return {"job_id": jobs.submit(lambda p: _run_grains(req, p))}
        except JobQueueFullError as e:
            raise HTTPException(429, str(e)) from None
    with value_error_as_422():
        return _run_grains(req)
