"""Scribble-trained grain segmentation endpoint (parity item #8).

Thin adapter over calc.grains_trained: the frontend paints class strokes on
an image, posts them here, and gets back an editable grain-label map (the
same payload shape as /analyze/grains, so merge/split editing works on the
result). Lives in its own module because routes/structure.py is at the
500-line ceiling.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.grains_trained import (
    preview_trained,
    rasterize_strokes,
    segment_trained,
    train_from_scribbles,
)
from fermiviewer.calc.roi import embed_rect_roi, extract_rect_roi, roi_slices
from fermiviewer.routes.structure import _grains_payload, _raster

router = APIRouter(prefix="/api")


class Stroke(BaseModel):
    class_id: int = Field(..., ge=1, le=16)
    radius: float = Field(default=4.0, ge=0.5, le=200.0)
    # painted polyline in image-pixel coords (x, y), 0-based
    points: list[tuple[float, float]]


class TrainSegmentRequest(BaseModel):
    image_id: str
    roi: tuple[int, int, int, int] | None = None
    strokes: list[Stroke]
    scales: list[float] = Field(default=[2.0, 4.0])
    gradient_sigma: float = Field(default=0.0, ge=0.0, le=10.0)
    min_area: int = Field(default=25, ge=0)
    # class id(s) painted on grain boundaries / background, excluded from
    # grain labelling (each predicted as that class drops out)
    boundary_class: list[int] = Field(default=[])
    # "softmax" (linear, default) or "forest" (nonlinear random forest, #8)
    classifier: Literal["softmax", "forest"] = "softmax"


@router.post("/grains/train-segment")
def grains_train_segment(req: TrainSegmentRequest) -> dict:
    ds, raster = _raster(req.image_id)
    h, w = raster.shape

    label_mask = rasterize_strokes(
        (h, w), [s.model_dump() for s in req.strokes]
    )
    rows, cols = roi_slices(raster.shape, req.roi)
    analysis_raster = extract_rect_roi(raster, req.roi)
    analysis_mask = label_mask[rows, cols]
    scales = tuple(float(s) for s in req.scales) or (2.0, 4.0)
    try:
        model = train_from_scribbles(
            analysis_raster,
            analysis_mask,
            scales=scales,
            gradient_sigma=req.gradient_sigma,
            classifier=req.classifier,
        )
        seg = segment_trained(
            analysis_raster,
            model,
            boundary_class=tuple(req.boundary_class),
            min_area=req.min_area,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    if seg.n_grains == 0:
        raise HTTPException(
            422, "no grains found — paint more strokes or lower min area"
        )

    raster_f = np.asarray(raster, dtype=np.float64)
    labels = embed_rect_roi(seg.labels, raster.shape, req.roi)
    return _grains_payload(labels, "trained", ds, raster_f, req.image_id, req.roi)


class TrainPreviewRequest(BaseModel):
    image_id: str
    roi: tuple[int, int, int, int] | None = None
    strokes: list[Stroke]
    scales: list[float] = Field(default=[2.0, 4.0])
    gradient_sigma: float = Field(default=0.0, ge=0.0, le=10.0)
    # class id(s) flagged as boundary/background — reported so the preview can
    # mark them ∅; does NOT change the classification itself
    boundary_class: list[int] = Field(default=[])
    classifier: Literal["softmax", "forest"] = "softmax"


@router.post("/grains/train-preview")
def grains_train_preview(req: TrainPreviewRequest) -> dict:
    """Optional, non-committing preview: fit the pixel classifier on the
    painted strokes and report the per-class pixel composition, WITHOUT
    labelling grains or registering any image. Lets the UI show how the paint
    generalizes before the user commits with /grains/train-segment."""
    _ds, raster = _raster(req.image_id)
    h, w = raster.shape

    label_mask = rasterize_strokes(
        (h, w), [s.model_dump() for s in req.strokes]
    )
    rows, cols = roi_slices(raster.shape, req.roi)
    analysis_raster = extract_rect_roi(raster, req.roi)
    analysis_mask = label_mask[rows, cols]
    scales = tuple(float(s) for s in req.scales) or (2.0, 4.0)
    try:
        model = train_from_scribbles(
            analysis_raster,
            analysis_mask,
            scales=scales,
            gradient_sigma=req.gradient_sigma,
            classifier=req.classifier,
        )
        prev = preview_trained(analysis_raster, model)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    boundary = {int(b) for b in req.boundary_class}
    return {
        "classes": [
            {
                "class_id": int(c),
                "fraction": prev.fractions[int(c)],
                "is_boundary": int(c) in boundary,
            }
            for c in prev.classes
        ],
    }
