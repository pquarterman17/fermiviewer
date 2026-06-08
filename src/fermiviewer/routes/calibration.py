"""Calibration endpoints — per-user DB + apply-to-image (checklist M)."""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.calibration_db import (
    delete_calibration,
    extract_calibration_key,
    list_calibrations,
    lookup,
    save_calibration,
)
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _get(img_id: str) -> DataStruct:
    try:
        return store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None


def recalibrate(ds: DataStruct, pixel_size: float, unit: str) -> DataStruct:
    """New DataStruct with recalibrated spatial axes (frozen dataclass)."""
    cal = AxisCal(scale=pixel_size, origin=0.0, units=unit)
    axes: tuple[AxisCal, ...]
    if ds.kind is DataKind.SPECTRUM_IMAGE:
        axes = (cal, cal, ds.axes[2])
    elif ds.kind is DataKind.IMAGE:
        axes = (cal, cal)
    else:
        raise HTTPException(400, "1D spectra have no spatial calibration")
    return DataStruct(
        data=ds.data, kind=ds.kind, axes=axes, metadata=dict(ds.metadata)
    )


def auto_apply_calibration(img_id: str, ds: DataStruct) -> bool:
    """Apply a stored calibration to an UNCALIBRATED import whose
    metadata yields a known key. Returns True when applied."""
    if ds.kind is DataKind.SPECTRUM:
        return False
    if ds.pixel_cal.calibrated:
        return False
    key = extract_calibration_key(ds.metadata)
    if key is None:
        return False
    entry = lookup(key)
    if entry is None:
        return False
    new_ds = recalibrate(ds, float(entry["pixel_size"]), str(entry["unit"]))
    new_ds.metadata["calibration_source"] = f"db:{key}"
    store.replace(img_id, new_ds)
    return True


@router.get("/calibration")
def calibration_list() -> dict[str, Any]:
    return {"entries": list_calibrations()}


class CalibrationSaveRequest(BaseModel):
    key: str | None = None
    image_id: str | None = None  # derive key from this image's metadata
    pixel_size: float = Field(gt=0)
    unit: str
    note: str = ""


@router.post("/calibration")
def calibration_save(req: CalibrationSaveRequest) -> dict[str, str]:
    key = req.key
    if key is None and req.image_id is not None:
        key = extract_calibration_key(_get(req.image_id).metadata)
    if not key:
        raise HTTPException(
            422, "no key given and none derivable from the image metadata"
        )
    save_calibration(key, req.pixel_size, req.unit, req.note)
    return {"key": key}


@router.delete("/calibration/{key:path}")
def calibration_delete(key: str) -> dict[str, str]:
    if not delete_calibration(key):
        raise HTTPException(404, f"no calibration stored for key: {key}")
    return {"deleted": key}


class CalibrationApplyRequest(BaseModel):
    image_id: str
    # either a stored key…
    key: str | None = None
    # …or a manual pixel size
    pixel_size: float | None = Field(default=None, gt=0)
    unit: str = "nm"
    save_as_key: str | None = None  # offer-save after manual calibration


@router.post("/calibration/detect-bar")
def calibration_detect_bar(req: CalibrationApplyRequest) -> dict[str, Any]:
    """Auto-detect a burned-in scale bar (bottom-strip search). Only
    image_id is used from the request body."""
    from fermiviewer.calc.scalebar_detect import detect_scale_bar

    ds = _get(req.image_id)
    if ds.kind is DataKind.SPECTRUM:
        raise HTTPException(400, "1D spectra have no scale bar")
    raster = (
        np.asarray(ds.data, dtype=np.float64).sum(axis=2)
        if ds.kind is DataKind.SPECTRUM_IMAGE
        else np.asarray(ds.data, dtype=np.float64)
    )
    r = detect_scale_bar(raster)
    return {
        "found": r.found,
        "bar_len": r.bar_len,
        "bar_x1": r.bar_x1,
        "bar_x2": r.bar_x2,
        "bar_y": r.bar_y,
        "msg": r.msg,
    }


@router.post("/calibration/apply")
def calibration_apply(req: CalibrationApplyRequest) -> dict[str, Any]:
    ds = _get(req.image_id)
    if req.key is not None:
        entry = lookup(req.key)
        if entry is None:
            raise HTTPException(404, f"no calibration for key: {req.key}")
        px, unit = float(entry["pixel_size"]), str(entry["unit"])
    elif req.pixel_size is not None:
        px, unit = req.pixel_size, req.unit
    else:
        raise HTTPException(422, "give either key or pixel_size")

    new_ds = recalibrate(ds, px, unit)
    store.replace(req.image_id, new_ds)
    if req.save_as_key:
        save_calibration(req.save_as_key, px, unit)
    assert np.isfinite(px)
    return {
        "image": ImageMeta.from_datastruct(
            req.image_id, store.name(req.image_id), new_ds
        ).model_dump()
    }
