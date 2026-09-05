"""Calibration endpoints — per-user DB + apply-to-image (checklist M).

Spatial calibration is per axis (ADR 0008): an edit writes the two spatial
`AxisCal`s, `DataStruct.pixel_spacing` is what the calcs read, and
`pixel_size` is the COLUMN scale -- a display and single-length view of
the same record. Every path into an edit goes through `recalibrate_axes`,
so nothing here can square an anisotropic image by accident.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from fermiviewer.calc.calibration import spacing_at_column_scale
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.calibration_db import (
    delete_calibration,
    entry_spacing,
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


def recalibrate_axes(
    ds: DataStruct, spacing: tuple[float, float], unit: str
) -> DataStruct:
    """New DataStruct whose spatial axes carry `spacing` as ``(row, column)``
    extents in `unit` (frozen dataclass, so a copy).

    The one place a spatial calibration is written. A spectrum image keeps
    its energy axis; an RGB image carries spatial axes only (ADR 0003); a
    1D spectrum has no spatial axes to write.
    """
    row = AxisCal(scale=float(spacing[0]), origin=0.0, units=unit)
    col = AxisCal(scale=float(spacing[1]), origin=0.0, units=unit)
    axes: tuple[AxisCal, ...]
    if ds.kind is DataKind.SPECTRUM_IMAGE:
        axes = (row, col, ds.axes[2])
    elif ds.kind is DataKind.IMAGE or ds.kind is DataKind.RGB_IMAGE:
        axes = (row, col)
    else:
        raise HTTPException(400, "1D spectra have no spatial calibration")
    return DataStruct(
        data=ds.data, kind=ds.kind, axes=axes, metadata=dict(ds.metadata)
    )


def recalibrate(ds: DataStruct, pixel_size: float, unit: str) -> DataStruct:
    """New DataStruct with SQUARE pixels of `pixel_size`: the isotropic form
    of :func:`recalibrate_axes`. Callers with one user-entered length and
    an image that may be anisotropic want :func:`single_length_spacing`
    first, so the image's ratio survives the edit."""
    return recalibrate_axes(ds, (pixel_size, pixel_size), unit)


def single_length_spacing(ds: DataStruct, pixel_size: float) -> tuple[float, float]:
    """The ``(row, column)`` extents ONE entered length means for `ds`.

    The length is the column scale, as `pixel_size` is everywhere. When
    the image already has two usable extents that differ, the row extent
    follows their ratio (`calc/calibration.spacing_at_column_scale`, the
    rule every calc applies to a typed pixel size) -- correcting the
    magnitude of a 0.5 x 2.0 nm AFM scan must not square its pixels
    (ADR 0008 §3, gate G1). An uncalibrated, square or mixed-unit image
    gets square pixels, exactly as before.
    """
    if ds.kind is DataKind.SPECTRUM:
        return pixel_size, pixel_size
    return spacing_at_column_scale(pixel_size, ds.pixel_spacing) or (
        pixel_size,
        pixel_size,
    )


def auto_apply_calibration(img_id: str, ds: DataStruct) -> bool:
    """Apply a stored calibration to an UNCALIBRATED import whose
    metadata yields a known key. Returns True when applied. A per-axis
    entry applies per axis; an older single-length entry applies square."""
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
    new_ds = recalibrate_axes(ds, entry_spacing(entry), str(entry["unit"]))
    new_ds.metadata["calibration_source"] = f"db:{key}"
    store.replace(img_id, new_ds)
    return True


@router.get("/calibration")
def calibration_list() -> dict[str, Any]:
    return {"entries": list_calibrations()}


def _positive_pair(spacing: tuple[float, float] | None, what: str) -> None:
    if spacing is not None and not all(
        np.isfinite(v) and v > 0 for v in spacing
    ):
        raise ValueError(f"{what} extents must be positive")


class CalibrationSaveRequest(BaseModel):
    key: str | None = None
    image_id: str | None = None  # derive key from this image's metadata
    # exactly one of: a single length (square pixels) or a (row, column) pair
    pixel_size: float | None = Field(default=None, gt=0)
    pixel_spacing: tuple[float, float] | None = None
    unit: str
    note: str = ""

    @model_validator(mode="after")
    def _one_length_form(self) -> CalibrationSaveRequest:
        if (self.pixel_size is None) == (self.pixel_spacing is None):
            raise ValueError("give exactly one of pixel_size or pixel_spacing")
        _positive_pair(self.pixel_spacing, "pixel_spacing")
        return self


@router.post("/calibration")
def calibration_save(req: CalibrationSaveRequest) -> dict[str, str]:
    key = req.key
    if key is None and req.image_id is not None:
        key = extract_calibration_key(_get(req.image_id).metadata)
    if not key:
        raise HTTPException(
            422, "no key given and none derivable from the image metadata"
        )
    save_calibration(
        key, req.pixel_size, req.unit, req.note, pixel_spacing=req.pixel_spacing
    )
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
    # …or a manual pixel size (the column scale; an anisotropic image keeps
    # its ratio), or an explicit (row, column) pair
    pixel_size: float | None = Field(default=None, gt=0)
    pixel_spacing: tuple[float, float] | None = None
    unit: str = "nm"
    save_as_key: str | None = None  # offer-save after manual calibration

    @model_validator(mode="after")
    def _at_most_one_manual_form(self) -> CalibrationApplyRequest:
        if self.pixel_size is not None and self.pixel_spacing is not None:
            raise ValueError("give either pixel_size or pixel_spacing, not both")
        _positive_pair(self.pixel_spacing, "pixel_spacing")
        return self


@router.post("/calibration/detect-bar")
def calibration_detect_bar(req: CalibrationApplyRequest) -> dict[str, Any]:
    """Auto-detect a burned-in scale bar (bottom-strip search). Only
    image_id is used from the request body."""
    from fermiviewer.calc.scalebar_detect import detect_scale_bar

    ds = _get(req.image_id)
    if ds.kind is DataKind.SPECTRUM:
        raise HTTPException(400, "1D spectra have no scale bar")
    raster = (
        # accumulate into float64 rather than casting the whole cube first
        np.asarray(np.sum(ds.data, axis=2, dtype=np.float64))
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


class ClearRequest(BaseModel):
    image_id: str


@router.post("/calibration/clear")
def calibration_clear(req: ClearRequest) -> dict[str, Any]:
    """Drop a manual/auto calibration back to uncalibrated (pixels). Used by
    the Calibration card's Clear button when a calibration was wrong."""
    ds = _get(req.image_id)
    if ds.kind is DataKind.SPECTRUM:
        raise HTTPException(400, "1D spectra have no spatial calibration")
    # scale 0 + empty units → AxisCal.calibrated is False (datastruct.py),
    # on BOTH axes
    new_ds = recalibrate(ds, 0.0, "")
    store.replace(req.image_id, new_ds)
    return {
        "image": ImageMeta.from_datastruct(
            req.image_id, store.name(req.image_id), new_ds
        ).model_dump()
    }


@router.post("/calibration/apply")
def calibration_apply(req: CalibrationApplyRequest) -> dict[str, Any]:
    """Calibrate an image from a stored key, one length, or a
    ``(row, column)`` pair. One length is the column scale and keeps an
    anisotropic image's ratio (:func:`single_length_spacing`); a stored
    entry applies as stored, per axis when it has both extents."""
    ds = _get(req.image_id)
    if req.key is not None:
        entry = lookup(req.key)
        if entry is None:
            raise HTTPException(404, f"no calibration for key: {req.key}")
        spacing, unit = entry_spacing(entry), str(entry["unit"])
    elif req.pixel_spacing is not None:
        spacing, unit = req.pixel_spacing, req.unit
    elif req.pixel_size is not None:
        if ds.kind is DataKind.SPECTRUM:
            raise HTTPException(400, "1D spectra have no spatial calibration")
        spacing, unit = single_length_spacing(ds, req.pixel_size), req.unit
    else:
        raise HTTPException(422, "give either key, pixel_size or pixel_spacing")

    new_ds = recalibrate_axes(ds, spacing, unit)
    store.replace(req.image_id, new_ds)
    if req.save_as_key:
        # what was APPLIED, so a pair that came from the image's ratio is
        # stored per axis and a later apply of the key reproduces it
        save_calibration(req.save_as_key, None, unit, pixel_spacing=spacing)
    assert all(np.isfinite(v) for v in spacing)
    return {
        "image": ImageMeta.from_datastruct(
            req.image_id, store.name(req.image_id), new_ds
        ).model_dump()
    }
