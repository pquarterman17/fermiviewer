"""Measurement + FFT endpoints (handoff §8: /measure/profile, /measure/roi,
/image/{id}/fft)."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.fourier import compute_fft
from fermiviewer.calc.profiles import (
    line_profile,
    measure_distance,
    polyline_profile,
    roi_stats,
)
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _raster(img_id: str) -> tuple[DataStruct, np.ndarray]:
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    if ds.kind is DataKind.IMAGE:
        return ds, ds.data
    if ds.kind is DataKind.SPECTRUM_IMAGE:
        return ds, np.asarray(ds.data, dtype=np.float64).sum(axis=2)
    raise HTTPException(400, "1D spectra have no raster")


class ProfileRequest(BaseModel):
    image_id: str
    a: tuple[float, float] | None = None      # (row, col), 1-based
    b: tuple[float, float] | None = None
    points: list[tuple[float, float]] | None = None   # polyline (row, col)
    width: float = 1.0                        # ⊥ averaging width (px)
    tilt_angle_deg: float = 0.0
    tilt_axis: str = "Y"
    geometry: str = "cross-section"


@router.post("/measure/profile")
def measure_profile(req: ProfileRequest) -> dict:
    ds, raster = _raster(req.image_id)
    px = ds.pixel_size if ds.kind is not DataKind.SPECTRUM else float("nan")
    try:
        if req.points is not None and len(req.points) >= 2:
            pts = np.asarray(req.points, dtype=np.float64)
            dist, inten = polyline_profile(
                raster, xs=pts[:, 1], ys=pts[:, 0],
                pixel_size=px, width=req.width,
            )
        elif req.a is not None and req.b is not None:
            dist, inten = line_profile(
                raster,
                x1=req.a[1], y1=req.a[0], x2=req.b[1], y2=req.b[0],
                pixel_size=px,
                tilt_angle_deg=req.tilt_angle_deg,
                tilt_axis=req.tilt_axis,
                geometry=req.geometry,
                width=req.width,
            )
        else:
            raise HTTPException(422, "need either a+b or points (≥2)")
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    unit = ds.pixel_unit or "px"
    return {
        "dist": dist.tolist(),
        "intensity": [None if not np.isfinite(v) else v for v in inten],
        "length": float(dist[-1]),
        "unit": unit if np.isfinite(px) else "px",
    }


class RoiRequest(BaseModel):
    image_id: str
    rect: tuple[float, float, float, float]   # (row1, col1, row2, col2), 1-based
    shape: str = "rect"                        # rect | ellipse


@router.post("/measure/roi")
def measure_roi(req: RoiRequest) -> dict:
    ds, raster = _raster(req.image_id)
    try:
        stats = roi_stats(raster, *req.rect, pixel_size=ds.pixel_size,
                          shape=req.shape)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {**stats, "unit": ds.pixel_unit or "px"}


class TiltedDistanceRequest(BaseModel):
    image_id: str
    x1: float                       # 1-based (col, row) pixel coords
    y1: float
    x2: float
    y2: float
    tilt_angle_deg: float = 0.0
    tilt_axis: str = "Y"            # Y | X
    geometry: str = "cross-section" # cross-section | surface


@router.post("/measure/distance-tilted")
def measure_distance_tilted(req: TiltedDistanceRequest) -> dict:
    """Tilt-corrected Euclidean distance (#34 — port of measureDistance.m).

    Returns both the raw pixel distance and the tilt-corrected distance in
    both pixels and calibrated units (null when the image is uncalibrated).
    The correction scales the in-tilt-axis component by 1/sin(θ) for
    cross-section geometry or 1/cos(θ) for plan-view surface geometry.
    """
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    px = ds.pixel_size
    pu = ds.pixel_unit or "px"
    try:
        result = measure_distance(
            req.x1, req.y1, req.x2, req.y2,
            pixel_size=px,
            pixel_unit=pu,
            tilt_angle_deg=req.tilt_angle_deg,
            tilt_axis=req.tilt_axis,
            geometry=req.geometry,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {
        "raw_px": result.raw_px,
        "raw_calibrated": result.raw_calibrated,
        "corrected_px": result.corrected_px,
        "corrected_calibrated": result.corrected_calibrated,
        "unit": result.unit,
        "tilt_angle_deg": result.tilt_angle_deg,
        "tilt_axis": result.tilt_axis,
        "geometry": result.geometry,
    }


class FftRequest(BaseModel):
    # optional 1-based inclusive region (live/local FFT, checklist J)
    rect: tuple[float, float, float, float] | None = None


@router.post("/image/{img_id}/fft")
def image_fft(img_id: str, req: FftRequest | None = None) -> ImageMeta:
    """Log-magnitude FFT registered as a derived image. An optional
    rect computes the LOCAL FFT of that region only."""
    ds, raster = _raster(img_id)
    if req is not None and req.rect is not None:
        h, w = raster.shape
        r0, r1 = sorted((int(req.rect[0]), int(req.rect[2])))
        c0, c1 = sorted((int(req.rect[1]), int(req.rect[3])))
        r0, c0 = max(r0, 1), max(c0, 1)
        r1, c1 = min(r1, h), min(c1, w)
        if r1 - r0 < 4 or c1 - c0 < 4:
            raise HTTPException(422, "FFT region too small (≥5 px)")
        raster = raster[r0 - 1:r1, c0 - 1:c1]
    mag, _ = compute_fft(raster)
    derived = DataStruct(
        data=np.ascontiguousarray(mag), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata={"source": f"FFT of {store.name(img_id)}", "parser": "derived"},
    )
    new_id = store.add_derived(derived, f"FFT({store.name(img_id)})", img_id)
    return ImageMeta.from_datastruct(new_id, store.name(new_id), derived)
