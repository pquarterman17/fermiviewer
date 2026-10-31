"""Scan distortion correction routes (calc/jitter): scan-line jitter within
one image, and drift across a series of images."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.jitter import (
    apply_frame_drift,
    correct_line_jitter,
    estimate_frame_drift,
    estimate_line_jitter,
)
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.ops.catalogue_jitter import _cropped_axis
from fermiviewer.routes._arrays import value_error_as_422
from fermiviewer.routes.structure import _raster
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _add(
    data: np.ndarray, name: str, parent: DataStruct, parent_id: str, axes: tuple, meta: dict
) -> dict:
    derived = DataStruct(
        data=np.ascontiguousarray(data),
        kind=DataKind.IMAGE,
        axes=axes,
        metadata={"source": name, "parser": "derived", **meta},
    )
    new_id = store.add_derived(derived, name, parent_id)
    return ImageMeta.from_datastruct(new_id, name, derived).model_dump()


class LineJitterRequest(BaseModel):
    image_id: str
    max_shift: float = Field(5.0, ge=1.0, le=64.0)
    trend_rows: float = Field(20.0, ge=0.0, le=1000.0)


@router.post("/analyze/line-jitter")
def analyze_line_jitter(req: LineJitterRequest) -> dict:
    """Correct row-to-row horizontal jitter; registers the corrected image
    and returns it with the per-row offsets (px)."""
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    if ds.kind is not DataKind.IMAGE:
        raise HTTPException(400, "scan-line jitter correction needs a 2-D greyscale image")
    img = np.asarray(ds.data, dtype=np.float64)
    with value_error_as_422():
        res = estimate_line_jitter(img, max_shift=req.max_shift, trend_rows=req.trend_rows)
    image = _add(
        correct_line_jitter(img, res.offsets),
        f"dejitter({store.name(req.image_id)})",
        ds,
        req.image_id,
        (ds.axes[0], ds.axes[1]),
        {"filter_kind": "line_jitter", "jitter_rms_px": res.rms, "jitter_max_px": res.max_abs},
    )
    return {
        "image": image,
        "offsets": res.offsets.tolist(),
        "rms": res.rms,
        "max_abs": res.max_abs,
    }


class FrameDriftRequest(BaseModel):
    image_ids: list[str]
    reference: str = Field("mean", pattern="^(mean|first)$")
    crop: bool = True
    keep_frames: bool = False


@router.post("/analyze/frame-drift")
def analyze_frame_drift(req: FrameDriftRequest) -> dict:
    """Sub-pixel drift correction across images (the first is the origin):
    registers the drift-corrected average and, with ``keep_frames``, every
    aligned frame; returns the per-frame (dy, dx) shifts (px)."""
    if len(req.image_ids) < 2:
        raise HTTPException(422, "need at least 2 images to correct drift")
    pairs = [_raster(i) for i in req.image_ids]
    rasters = [r for _, r in pairs]
    with value_error_as_422():
        drift = estimate_frame_drift(rasters, reference=req.reference)
        aligned, (top, bottom, left, right) = apply_frame_drift(
            rasters, drift.shifts, crop=req.crop
        )
    first, first_id = pairs[0][0], req.image_ids[0]
    axes = (_cropped_axis(first.axes[0], top), _cropped_axis(first.axes[1], left))
    meta = {"frame_drift_max_px": drift.max_abs, "frame_drift_frames": len(rasters)}
    average = _add(
        np.mean(aligned, axis=0),
        f"drift-corrected average({len(rasters)})",
        first,
        first_id,
        axes,
        meta,
    )
    frames = []
    if req.keep_frames:
        for img_id, arr in zip(req.image_ids, aligned, strict=True):
            frames.append(
                _add(arr, f"dedrift({store.name(img_id)})", first, img_id, axes, meta)
            )
    return {
        "average": average,
        "frames": frames,
        "shifts": drift.shifts.tolist(),
        "max_abs": drift.max_abs,
        "crop": [top, bottom, left, right],
    }
