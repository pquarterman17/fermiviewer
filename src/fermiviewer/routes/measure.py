"""Measurement + FFT endpoints (handoff §8: /measure/profile, /measure/roi,
/image/{id}/fft)."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.fourier import compute_fft, local_fft_region
from fermiviewer.calc.profile_stats import box_integrate, measure_distance, roi_stats
from fermiviewer.calc.profiles import line_profile_stats, polyline_profile
from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.project_results import ResultOutput
from fermiviewer.models import ImageMeta
from fermiviewer.result_capture import capture_result
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _raster(img_id: str) -> tuple[DataStruct, np.ndarray]:
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    try:
        return ds, raster_of(ds, native=True)
    except NoRasterError:
        raise HTTPException(400, "1D spectra have no raster") from None


class ProfileRequest(BaseModel):
    image_id: str
    a: tuple[float, float] | None = None      # (row, col), 1-based
    b: tuple[float, float] | None = None
    points: list[tuple[float, float]] | None = None   # polyline (row, col)
    width: float = 1.0                        # ⊥ averaging width (px)
    reduce: str = "mean"                      # "mean" | "sum"
    tilt_angle_deg: float = 0.0
    tilt_axis: str = "Y"
    geometry: str = "cross-section"
    #: Capture this run as a persisted ResultRecord (1C). Default off until
    #: the client grows its capture affordance — recording is a user
    #: decision, not a side effect of every exploratory run.
    record: bool = False


@router.post("/measure/profile")
def measure_profile(req: ProfileRequest) -> dict:
    """Two-point or polyline intensity profile.

    The two-point (a+b) response additionally carries ``intensity_sigma``
    (sem = std/sqrt(n), same "uncertainty of the mean" convention as
    /analyze/radial) whenever the plotted value is a genuine per-point
    average of >1 sample — width rounds to more than one perpendicular
    line AND reduce=='mean'. Omitted for width=1 (a single bilinear
    sample has no spread to estimate), for reduce='sum' (an integral, not
    a mean), and for polyline (points) requests.
    """
    ds, raster = _raster(req.image_id)
    px = ds.pixel_size if ds.kind is not DataKind.SPECTRUM else float("nan")
    sem: np.ndarray | None = None
    # Input resolution is done; from here a ValueError out of the calc layer
    # is a COMPUTATION failure, which a requested capture must record rather
    # than lose (the 1B contract's failed-state requirement). The
    # "need either a+b or points" HTTPException raised below is deliberately
    # NOT caught here: that is request validation — no computation was
    # attempted — so it is never captured.
    try:
        if req.points is not None and len(req.points) >= 2:
            pts = np.asarray(req.points, dtype=np.float64)
            dist, inten = polyline_profile(
                raster, xs=pts[:, 1], ys=pts[:, 0],
                pixel_size=px, width=req.width, reduce=req.reduce,
            )
        elif req.a is not None and req.b is not None:
            dist, inten, sem = line_profile_stats(
                raster,
                x1=req.a[1], y1=req.a[0], x2=req.b[1], y2=req.b[0],
                pixel_size=px,
                tilt_angle_deg=req.tilt_angle_deg,
                tilt_axis=req.tilt_axis,
                geometry=req.geometry,
                width=req.width,
                reduce=req.reduce,
            )
        else:
            raise HTTPException(422, "need either a+b or points (≥2)")
    except ValueError as e:
        if req.record:
            capture_result(
                analysis="measure.profile",
                label=f"Intensity profile of {store.name(req.image_id)}",
                source_ids=[req.image_id],
                params=req.model_dump(exclude={"record"}),
                regions=_profile_regions(req),
                status="failed",
                error=str(e),
            )
        raise HTTPException(422, str(e)) from None
    calibrated = bool(np.isfinite(px))
    unit = (ds.pixel_unit or "px") if calibrated else "px"
    body: dict = {
        "dist": dist.tolist(),
        "intensity": [None if not np.isfinite(v) else v for v in inten],
        "length": float(dist[-1]),
        "unit": unit,
        "reduce": req.reduce,
    }
    if sem is not None:
        body["intensity_sigma"] = [
            None if not np.isfinite(v) else float(v) for v in sem
        ]
    if req.record:
        body["result"] = _capture_profile(req, dist, inten, sem, unit, calibrated)
    return body


def _profile_regions(req: ProfileRequest) -> list[dict]:
    """The geometry this run measured, snapshotted so the record can be
    reopened after the live region is edited or deleted (ADR 0004 §6).

    Each shape names its coordinate convention explicitly: this repo's
    families genuinely differ (profile endpoints take (row, col) 1-based
    points, the ROI/box endpoints a (row1, col1, row2, col2) rect), so a
    bare list of numbers would not be self-describing on reopen. Empty
    when neither branch is satisfied — that request never computes.
    """
    if req.points is not None and len(req.points) >= 2:
        return [{
            "kind": "polyline",
            "convention": "(row, col), 1-based",
            "points": [list(p) for p in req.points],
            "width": req.width,
        }]
    if req.a is not None and req.b is not None:
        return [{
            "kind": "line",
            "convention": "(row, col), 1-based",
            "a": list(req.a),
            "b": list(req.b),
            "width": req.width,
        }]
    return []


def _capture_profile(
    req: ProfileRequest,
    dist: np.ndarray,
    inten: np.ndarray,
    sem: np.ndarray | None,
    unit: str,
    calibrated: bool,
) -> dict:
    """This run as a persisted ResultRecord (ADR 0004 §3): the sampled
    profile as a member-backed curve — (N, 2) [dist, intensity], or (N, 3)
    with the per-point sem when the two-point branch estimated one — plus
    the measured length and the sample count as scalars.
    """
    columns = [dist, inten] if sem is None else [dist, inten, sem]
    # NaN stays in the member array: it is .npy, not JSON, and a sample that
    # ran off the raster is a real gap, not a zero. The JSON surfaces (the
    # wire body above, /api/results/.../data) scrub it to null themselves.
    curve = np.column_stack([np.asarray(c, dtype=np.float64) for c in columns])
    warnings: list[str] = []
    if not calibrated:
        warnings.append(
            "image has no finite pixel size — distances are in pixels, "
            "not calibrated units"
        )
    n_nonfinite = int(np.count_nonzero(~np.isfinite(inten)))
    if n_nonfinite:
        warnings.append(
            f"{n_nonfinite} of {inten.size} sampled intensities are "
            f"non-finite — the profile ran outside the image raster"
        )
    outputs = [
        ResultOutput(
            kind="curve",
            name="profile",
            data={
                "x_name": "distance",
                "x_unit": unit,
                "y_name": "intensity",
                # Raster values carry no calibrated intensity unit in this
                # build; "" is the honest answer, not an invented "counts".
                "y_unit": "",
                "reduce": req.reduce,
            },
            array=curve,
        ),
        ResultOutput(
            kind="scalar",
            name="length",
            data={"value": float(dist[-1]), "unit": unit},
        ),
        ResultOutput(
            kind="scalar",
            name="n_samples",
            data={"value": int(dist.size), "unit": ""},
        ),
    ]
    record = capture_result(
        analysis="measure.profile",
        label=f"Intensity profile of {store.name(req.image_id)}",
        source_ids=[req.image_id],
        # The fully resolved reproduction key, defaults filled — never the
        # capture toggle itself.
        params=req.model_dump(exclude={"record"}),
        outputs=outputs,
        regions=_profile_regions(req),
        warnings=warnings,
    )
    return {"id": record.id, "created_at": record.created_at}


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


class BoxProfileRequest(BaseModel):
    image_id: str
    rect: tuple[float, float, float, float]   # (row1, col1, row2, col2), 1-based
    reduce: str = "sum"                         # "sum" (integration) | "mean"


@router.post("/measure/box-profile")
def measure_box_profile(req: BoxProfileRequest) -> dict:
    """Integrate an axis-aligned box along both axes → two 1-D profiles.

    Returns the horizontal (x, over columns) and vertical (y, over rows)
    profiles in one payload so a single CSV can carry both. Positions are
    in pixels (0-based from the box edge); the client applies pixel-size
    calibration. reduce='sum' is the true box integral (counts/EELS).
    """
    ds, raster = _raster(req.image_id)
    try:
        x_pos, x_int, y_pos, y_int, rect = box_integrate(
            raster, *req.rect, reduce=req.reduce
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    px = ds.pixel_size if ds.kind is not DataKind.SPECTRUM else float("nan")
    cal = bool(np.isfinite(px))

    def _clean(arr: np.ndarray) -> list[float | None]:
        return [None if not np.isfinite(v) else float(v) for v in arr]

    return {
        "x_pos": x_pos.tolist(),
        "x_intensity": _clean(x_int),
        "y_pos": y_pos.tolist(),
        "y_intensity": _clean(y_int),
        "pixel_size": float(px) if cal else None,
        "unit": (ds.pixel_unit or "px") if cal else "px",
        "reduce": req.reduce,
        "rect": list(rect),
    }


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
        # window/clamp arithmetic lives in calc (wave B, ADR 0005 §1 —
        # shared with the registered `fft` op)
        try:
            raster = local_fft_region(raster, req.rect)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
    mag, _ = compute_fft(raster)
    derived = DataStruct(
        data=np.ascontiguousarray(mag), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata={"source": f"FFT of {store.name(img_id)}", "parser": "derived"},
    )
    new_id = store.add_derived(derived, f"FFT({store.name(img_id)})", img_id)
    return ImageMeta.from_datastruct(new_id, store.name(new_id), derived)
