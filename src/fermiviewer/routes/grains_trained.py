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
    rasterize_strokes,
    segment_trained,
    train_from_scribbles,
)
from fermiviewer.routes.structure import _grains_payload, _raster

router = APIRouter(prefix="/api")


class Stroke(BaseModel):
    class_id: int = Field(..., ge=1, le=16)
    radius: float = Field(default=4.0, ge=0.5, le=200.0)
    # painted polyline in image-pixel coords (x, y), 0-based
    points: list[tuple[float, float]]


class TrainSegmentRequest(BaseModel):
    image_id: str
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
    scales = tuple(float(s) for s in req.scales) or (2.0, 4.0)
    try:
        model = train_from_scribbles(
            raster,
            label_mask,
            scales=scales,
            gradient_sigma=req.gradient_sigma,
            classifier=req.classifier,
        )
        seg = segment_trained(
            raster,
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
    return _grains_payload(seg.labels, "trained", ds, raster_f, req.image_id)
