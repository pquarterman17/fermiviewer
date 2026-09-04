"""Measurement operation catalogue — wave D (roadmap 3E): batch/scripting
reach for the interactive measure tools (line profile, ROI statistics,
box integration, tilt-corrected distance). The whole-image read ops
(`sum_spectrum`, `intensity_histogram`, `scalebar_detect`) live in
``catalogue_measure_reads.py`` — split so neither module crosses the
500-line ceiling. New modules on the ``catalogue_analysis.py``
precedent; a ``measure`` category was argued and rejected in the
ADR 0005 wave-D addendum — these are ``analysis`` ops, and the category
implies their value result (``produces_value`` deliberately UNSET).

Every op calls the SAME calc function its route calls (ADR 0005 §1);
each ``summary`` names the shared calc entry point, and the route is:
POST /measure/profile | /measure/roi | /measure/box-profile |
/measure/distance-tilted, GET /image/{id}/spectrum | /image/{id}/histogram,
POST /calibration/detect-bar respectively.

Coordinate conventions — read before wiring a caller:

* `line_profile` / `roi_stats` / `box_profile` / `tilted_distance` /
  `sum_spectrum` speak MATLAB-style **1-based inclusive** pixel
  coordinates (the calc/profiles + wire convention). This is NOT
  catalogue_diffraction's 0-based half-open rect, and NOT the 1-based
  ``"r1,c1,r2,c2"`` corner-ROI *string* other catalogues take — here each
  corner is its own float param, mirroring the routes' request models.
* `box_profile`'s returned positions are **0-based pixels from the box
  edge** (the calc contract: the caller applies calibration).

Deliberate divergences from the routes (each annotated on its audit row):

* `line_profile` drops the route's OPTIONAL polyline ``points`` mode
  (the ADR 0005 wave-D optional-input omission rule — a variable-length
  coordinate list is gap 2, and the mode calls a DIFFERENT calc
  function, ``polyline_profile``). The op registers the two-point a+b
  arm only; supplying an unknown ``points`` param is a hard ParamError.
* `sum_spectrum` errors on a region given for a non-cube spectral input,
  where the route silently ignores the region and returns the whole
  spectrum — the strict-ROI "never silently analyze more than asked"
  discipline (the `parse_roi_param` rationale).
* `scalebar_detect` errors on ``rgb_image`` input: the route's local
  reduction (``np.asarray(ds.data, dtype=np.float64)``) hands a 3-D
  array to ``detect_scale_bar``, which is an unhandled 500 — there is no
  working route behavior to mirror, so the op raises a clean ValueError
  instead of inventing a luma path the route does not have.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from fermiviewer.calc.profile_stats import box_integrate, measure_distance, roi_stats
from fermiviewer.calc.profiles import line_profile_stats
from fermiviewer.calc.raster import raster_of
from fermiviewer.datastruct import DataStruct
from fermiviewer.ops._envelopes import nan_none, output, scalar
from fermiviewer.ops._parsing import clean_values, pixel_cal
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


def _finite_scalar(outputs: list[dict[str, Any]], name: str, value: float, unit: str = "") -> None:
    """Append a scalar envelope only when the value is finite — non-finite
    scalars are absent, not null (ADR 0005 §5)."""
    if math.isfinite(value):
        outputs.append(scalar(name, float(value), unit=unit))


# ── line_profile ──────────────────────────────────────────────────────


def _line_profile(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    # raster first: a 1D spectrum raises NoRasterError here (the route's
    # 400), BEFORE pixel_cal could trip on its missing spatial axes — the
    # same order the route's _raster-then-pixel-size arm runs in, which is
    # why its `kind is SPECTRUM -> NaN` special case never actually fires
    raster = raster_of(ds, native=True)
    px, unit = pixel_cal(ds)
    dist, inten, sem = line_profile_stats(
        raster,
        x1=params["a_col"],
        y1=params["a_row"],
        x2=params["b_col"],
        y2=params["b_row"],
        pixel_size=px,
        tilt_angle_deg=params["tilt_angle_deg"],
        tilt_axis=params["tilt_axis"],
        geometry=params["geometry"],
        width=params["width"],
        reduce=params["reduce"],
        spacing=ds.pixel_spacing,
    )
    curve: dict[str, Any] = {
        "x_name": "dist",
        "x_unit": unit,
        "y_name": "intensity",
        "y_unit": "",
        "x": dist.tolist(),
        "y": clean_values(inten),
        "reduce": params["reduce"],
    }
    # sigma only when honest: the calc returns sem (std/sqrt(n)) ONLY for a
    # genuine per-point average of >1 sample — round(width)>1 AND
    # reduce=='mean'; otherwise the key is absent, never null/zero
    if sem is not None:
        curve["y_sigma"] = clean_values(sem)
    outputs = [
        output("curve", "intensity", curve),
        scalar("length", float(dist[-1]), unit=unit),
    ]
    return OpResult(
        op="line_profile", params=params, label="line profile", value={"outputs": outputs}
    )


register(
    OpSpec(
        name="line_profile",
        category="analysis",
        summary="Sub-pixel two-point intensity profile with optional width "
        "averaging and tilt correction (calc/profiles.line_profile_stats). "
        "The route's optional polyline `points` mode has no op "
        "(optional-input omission rule; a different calc function)",
        params={
            "a_row": OpParam(float, required=True, doc="start row, 1-based pixel centre"),
            "a_col": OpParam(float, required=True, doc="start col, 1-based pixel centre"),
            "b_row": OpParam(float, required=True, doc="end row, 1-based pixel centre"),
            "b_col": OpParam(float, required=True, doc="end col, 1-based pixel centre"),
            "width": OpParam(float, 1.0, doc="perpendicular averaging width (px)"),
            "reduce": OpParam(
                str, "mean", choices=("mean", "sum"), doc="'mean' averages, 'sum' integrates"
            ),
            "tilt_angle_deg": OpParam(float, 0.0, doc="stage tilt; must be in (-90, 90)"),
            "tilt_axis": OpParam(str, "Y", choices=("Y", "X")),
            "geometry": OpParam(
                str,
                "cross-section",
                choices=("cross-section", "surface"),
                doc="1/sin vs 1/cos tilt scaling",
            ),
        },
        fn=_line_profile,
    )
)


# ── roi_stats ─────────────────────────────────────────────────────────


def _roi_stats(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds, native=True)
    px, unit = pixel_cal(ds)  # == the route's ds.pixel_size / unit-or-'px'
    # the calc raises on an ROI empty after clamping (the route's 422), so
    # the strict-ROI "never silently the whole image" discipline is already
    # satisfied in the shared code path
    stats = roi_stats(
        raster,
        params["row1"],
        params["col1"],
        params["row2"],
        params["col2"],
        pixel_area=ds.pixel_area,
        shape=params["shape"],
    )
    outputs: list[dict[str, Any]] = []
    for name in ("mean", "std", "min", "max"):
        _finite_scalar(outputs, name, stats[name])
    _finite_scalar(outputs, "n_pixels", stats["n_pixels"], unit="px")
    # like the route, area falls back to the pixel count when uncalibrated
    # (pixel_cal's unit falls back to 'px' in lockstep)
    _finite_scalar(outputs, "area", stats["area"], unit=f"{unit}^2")
    return OpResult(
        op="roi_stats", params=params, label="ROI statistics", value={"outputs": outputs}
    )


register(
    OpSpec(
        name="roi_stats",
        category="analysis",
        summary="Rectangle or inscribed-ellipse intensity statistics "
        "(calc/profile_stats.roi_stats). Corners are 1-BASED INCLUSIVE "
        "pixel coordinates — not the diffraction catalogue's 0-based "
        "half-open rect, and not the corner-ROI string other ops take",
        params={
            "row1": OpParam(float, required=True, doc="corner row, 1-based inclusive"),
            "col1": OpParam(float, required=True, doc="corner col, 1-based inclusive"),
            "row2": OpParam(float, required=True, doc="opposite row, 1-based inclusive"),
            "col2": OpParam(float, required=True, doc="opposite col, 1-based inclusive"),
            "shape": OpParam(
                str, "rect", choices=("rect", "ellipse"), doc="'ellipse': inscribed ellipse only"
            ),
        },
        fn=_roi_stats,
    )
)


# ── box_profile ───────────────────────────────────────────────────────


def _box_profile(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds, native=True)
    x_pos, x_int, y_pos, y_int, rect = box_integrate(
        raster,
        params["row1"],
        params["col1"],
        params["row2"],
        params["col2"],
        reduce=params["reduce"],
    )
    px, unit = pixel_cal(ds)

    def curve(pos: np.ndarray, inten: np.ndarray) -> dict[str, Any]:
        # positions are 0-based px from the box edge (the calc contract);
        # pixel_size/unit ride the data so the caller can calibrate, None
        # when uncalibrated — exactly the route payload's spelling
        return {
            "x_name": "position",
            "x_unit": "px",
            "y_name": "intensity",
            "y_unit": "",
            "x": pos.tolist(),
            "y": clean_values(inten),
            "pixel_size": nan_none(px),
            "pixel_unit": unit,
            "reduce": params["reduce"],
        }

    r1, c1, r2, c2 = rect
    outputs = [
        output("curve", "x_profile", curve(x_pos, x_int)),
        output("curve", "y_profile", curve(y_pos, y_int)),
        # the clamped rect actually integrated, 1-based inclusive
        scalar("rect_row1", r1, unit="px"),
        scalar("rect_col1", c1, unit="px"),
        scalar("rect_row2", r2, unit="px"),
        scalar("rect_col2", c2, unit="px"),
    ]
    return OpResult(
        op="box_profile", params=params, label="box integration", value={"outputs": outputs}
    )


register(
    OpSpec(
        name="box_profile",
        category="analysis",
        summary="Axis-aligned box integrated along both axes → horizontal "
        "(x, over columns) and vertical (y, over rows) profiles "
        "(calc/profile_stats.box_integrate). Corners are 1-based inclusive; "
        "returned positions are 0-based px from the box edge",
        params={
            "row1": OpParam(float, required=True, doc="corner row, 1-based inclusive"),
            "col1": OpParam(float, required=True, doc="corner col, 1-based inclusive"),
            "row2": OpParam(float, required=True, doc="opposite row, 1-based inclusive"),
            "col2": OpParam(float, required=True, doc="opposite col, 1-based inclusive"),
            "reduce": OpParam(
                str, "sum", choices=("sum", "mean"), doc="'sum' is the true box integral"
            ),
        },
        fn=_box_profile,
    )
)


# ── tilted_distance ───────────────────────────────────────────────────


def _tilted_distance(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    px, unit = pixel_cal(ds)
    result = measure_distance(
        params["x1"],
        params["y1"],
        params["x2"],
        params["y2"],
        pixel_size=px,
        pixel_unit=unit,
        tilt_angle_deg=params["tilt_angle_deg"],
        tilt_axis=params["tilt_axis"],
        geometry=params["geometry"],
        spacing=ds.pixel_spacing,
    )
    outputs = [
        scalar("raw_px", result.raw_px, unit="px"),
        scalar("corrected_px", result.corrected_px, unit="px"),
    ]
    # the route spells the uncalibrated case as null; the envelope contract
    # spells it as absent — not null
    if result.raw_calibrated is not None:
        outputs.append(scalar("raw_calibrated", result.raw_calibrated, unit=result.unit))
    if result.corrected_calibrated is not None:
        outputs.append(
            scalar("corrected_calibrated", result.corrected_calibrated, unit=result.unit)
        )
    return OpResult(
        op="tilted_distance",
        params=params,
        label="tilt-corrected distance",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="tilted_distance",
        category="analysis",
        summary="Tilt-corrected Euclidean distance between two points "
        "(calc/profile_stats.measure_distance, the measureDistance.m "
        "port). x is the column axis, y the row axis, 1-based; the "
        "calibrated scalars are absent on an uncalibrated image",
        params={
            "x1": OpParam(float, required=True, doc="start col, 1-based pixel coords"),
            "y1": OpParam(float, required=True, doc="start row, 1-based pixel coords"),
            "x2": OpParam(float, required=True, doc="end col, 1-based pixel coords"),
            "y2": OpParam(float, required=True, doc="end row, 1-based pixel coords"),
            "tilt_angle_deg": OpParam(float, 0.0, doc="stage tilt; must be in (-90, 90)"),
            "tilt_axis": OpParam(str, "Y", choices=("Y", "X")),
            "geometry": OpParam(
                str,
                "cross-section",
                choices=("cross-section", "surface"),
                doc="1/sin vs 1/cos tilt scaling",
            ),
        },
        fn=_tilted_distance,
    )
)
