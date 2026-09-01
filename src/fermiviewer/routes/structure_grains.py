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

from fermiviewer.calc.grain_edit import edit_grains
from fermiviewer.calc.grain_report import grain_report
from fermiviewer.calc.grains import (
    GrainSegmentation,
    WatershedSegmentation,
    segment_auto,
    segment_watershed,
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
    interactive merge/split). The numbers come from calc/grain_report.py —
    the same report the registered `grains` op emits (ADR 0005 §1); this
    wrapper registers the renumbered label map tagged so the stage can
    recognize and further edit it, and shapes the JSON."""
    px = ds.pixel_size if np.isfinite(ds.pixel_size) else float("nan")
    report = grain_report(
        labels, raster, pixel_size=px, pixel_area=ds.pixel_area,
        unit=ds.pixel_unit or "px",
    )
    name = store.name(source_id)
    return {
        "n_grains": report.n_grains,
        "method": method,
        "labels": _register(
            report.labels.astype(np.float64), f"grains({name})", ds, source_id,
            extra_meta={
                "grain_labels": True,
                "grain_source": source_id,
                "grain_method": method,
            } | ({"grain_roi": ",".join(map(str, roi))} if roi is not None else {}),
        ),
        # true (border-excluding) inter-grain network length
        "boundary_network_px": report.boundary_network_px,
        "boundary_network_calibrated": _nan_none(report.boundary_network_calibrated),
        "n_boundary_segments": report.n_boundary_segments,
        "n_triple_junctions": report.n_triple_junctions,
        "mean_diameter_px": report.mean_diameter_px,
        "astm_grain_size": _nan_none(report.astm_grain_size),
        "areas_px": report.area_px.tolist(),
        "perimeters_px": report.perimeter_crofton_px.tolist(),
        "eccentricity": report.eccentricity.tolist(),
        # per-grain diameter feeds a size-distribution histogram (#6/R6)
        "equiv_diameter_px": report.equiv_diameter_px.tolist(),
        "diameter_calibrated": [_nan_none(d) for d in report.diameter_calibrated],
        "unit": report.unit,
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

    # One composition, shared with the `grains_edit` op (ADR 0005 §1):
    # click rounding, the merge relabelling and the connectivity re-enforce
    # all live in calc/grain_edit.py. `value_error_as_422` is new here — a
    # ValueError out of split_grain used to escape as a 500, unlike the
    # sibling /analyze/grains route which has always wrapped.
    base = str(labels_ds.metadata.get("grain_method", "edited"))
    with value_error_as_422():
        edit = edit_grains(
            np.asarray(labels_ds.data, dtype=np.int64),
            raster,
            req.op,
            req.points,
            granularity=req.granularity,
        )
    labels = edit.labels
    method = f"{base}+{edit.op}"
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
