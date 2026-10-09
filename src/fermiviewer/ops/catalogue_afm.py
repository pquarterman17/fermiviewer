"""AFM/SPM ops: levelling (calc/afm_level.py) — the same functions the
/filter route's AFM kinds call, so a script or batch recipe levels exactly
like the GUI — and surface analysis (ISO 25178 texture, step height), with
the unit helpers routes/afm_analysis.py shares."""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc import afm_features, afm_level, afm_surface
from fermiviewer.calc.raster import raster_of
from fermiviewer.datastruct import DataStruct
from fermiviewer.io.tiff_units import TO_NM
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.catalogue import _image_op
from fermiviewer.ops.registry import register

_PCT = OpParam(float, 100.0, minimum=1.0, maximum=100.0,
               doc="fit only pixels at or below this height percentile (100 = all)")

register(OpSpec(
    name="plane_level", category="filter",
    summary="Remove a fitted plane / polynomial background",
    params={"order": OpParam(int, 1, minimum=1, maximum=3), "fit_percentile": _PCT},
    fn=_image_op(
        "plane_level",
        lambda d, p: afm_level.level_plane(d, order=p["order"],
                                           fit_percentile=p["fit_percentile"]),
    ),
))
register(OpSpec(
    name="row_level", category="filter",
    summary="Level each scan line (AFM line-by-line flatten)",
    params={
        "method": OpParam(str, "median", choices=afm_level.ROW_METHODS),
        "order": OpParam(int, 1, minimum=1, maximum=3, doc="for method=poly"),
        "fit_percentile": _PCT,
    },
    fn=_image_op(
        "row_level",
        lambda d, p: afm_level.level_rows(d, method=p["method"], order=p["order"],
                                          fit_percentile=p["fit_percentile"]),
    ),
))
register(OpSpec(
    name="scar_removal", category="filter",
    summary="Repair scan-line scars (feedback jumps)",
    params={
        "threshold": OpParam(float, 3.0, minimum=0.1, doc="× robust line-difference σ"),
        "max_width": OpParam(int, 2, minimum=1, maximum=16, doc="scan lines"),
        "min_length": OpParam(int, 8, minimum=1, doc="pixels along the line"),
    },
    fn=_image_op(
        "scar_removal",
        lambda d, p: afm_level.remove_scars(
            d, threshold=p["threshold"], max_width=p["max_width"],
            min_length=p["min_length"]).corrected,
    ),
))
register(OpSpec(
    name="zero_level", category="filter",
    summary="Shift heights so the min / mean / median is zero",
    params={"mode": OpParam(str, "min", choices=afm_level.ZERO_MODES)},
    fn=_image_op("zero_level", lambda d, p: afm_level.zero_level(d, p["mode"])),
))


# ── surface analysis (calc/afm_surface.py, calc/afm_features.py) ──────


def _nm(unit: str) -> float:
    return TO_NM.get(unit.strip().lower().replace("μ", "µ"), float("nan"))


def lateral_scale(ds: DataStruct) -> tuple[float, float, str]:
    """(dy, dx, unit) — the pixel spacing, or (1, 1, "px") uncalibrated."""
    dy, dx = ds.pixel_spacing
    if np.isfinite(dy) and np.isfinite(dx) and dy > 0 and dx > 0:
        return float(dy), float(dx), ds.pixel_unit
    return 1.0, 1.0, "px"


def z_to_lateral(ds: DataStruct) -> float:
    """Factor converting a height into the lateral unit; NaN unless both
    the value unit and the pixel unit are known lengths."""
    _, _, lat = lateral_scale(ds)
    return _nm(str(ds.metadata.get("value_unit") or "")) / _nm(lat)


def level_for_analysis(z: np.ndarray, level: str) -> np.ndarray:
    """'none' | 'plane' | 'quadratic' background removal before analysis."""
    if level == "none":
        return np.asarray(z, dtype=np.float64)
    return afm_level.level_plane(z, order=1 if level == "plane" else 2)


def areal_values(ds: DataStruct, z: np.ndarray) -> dict[str, Any]:
    """ISO 25178 parameters of `z` (a levelled raster of `ds`) with units."""
    dy, dx, lat = lateral_scale(ds)
    p = afm_surface.areal_parameters(z, dy, dx, z_to_lateral(ds))
    zu = str(ds.metadata.get("value_unit") or "")
    return {
        "Sa": p.sa, "Sq": p.sq, "Ssk": p.ssk, "Sku": p.sku, "Sp": p.sp, "Sv": p.sv,
        "Sz": p.sz, "Sdq": p.sdq, "Sdr": p.sdr, "Sal": p.sal, "Str": p.str_, "Std": p.std,
        "n_pixels": p.n_pixels, "unit": zu, "lateral_unit": lat,
    }


_LEVEL = OpParam(str, "plane", choices=("none", "plane", "quadratic"))


def _surface_texture(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    z = level_for_analysis(raster_of(ds), params["level"])
    return OpResult(op="surface_texture", params=params,
                    label="areal surface texture (ISO 25178)", value=areal_values(ds, z))


def _step_height(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    s = afm_features.step_height(raster_of(ds), edge=params["edge"])
    value = {"height": s.height, "lower_std": s.lower_std, "upper_std": s.upper_std,
             "n_lower": s.n_lower, "n_upper": s.n_upper,
             "unit": str(ds.metadata.get("value_unit") or "")}
    return OpResult(op="step_height", params=params, label="step height", value=value)


register(OpSpec(
    name="surface_texture", category="analysis",
    summary="ISO 25178 areal parameters (Sa…Sz, Sdq, Sdr, Sal, Str, Std)",
    params={"level": _LEVEL}, fn=_surface_texture,
))
register(OpSpec(
    name="step_height", category="analysis",
    summary="Height of the step between two terraces (crop to the step first)",
    params={"edge": OpParam(int, 2, minimum=0, maximum=20,
                            doc="pixels left out on each side of the step edge")},
    fn=_step_height,
))


def height_columns(ds: DataStruct, labels: np.ndarray, z: np.ndarray) -> dict[str, Any]:
    """Per-region height and volume for a particle/grain table — only for a
    height map (its value unit is a length); {} for any other image, so EM
    tables are unchanged. Regions are labels 1..n in table order."""
    zu = str(ds.metadata.get("value_unit") or "")
    if not np.isfinite(_nm(zu)):
        return {}
    k = z_to_lateral(ds)
    rh = afm_features.region_heights(labels, z, ds.pixel_area)
    _, _, lat = lateral_scale(ds)
    same = np.isfinite(k)
    volume = rh.volume_above_base * k if same else rh.volume_above_base
    return {
        "max_height": [_none(v) for v in rh.max_height],
        "height_above_base": [_none(v) for v in rh.height_above_base],
        "volume": [_none(v) for v in volume],
        "height_unit": zu,
        "volume_unit": f"{lat}³" if same else f"{zu}·{lat}²",
    }


def _none(v: float) -> float | None:
    return float(v) if np.isfinite(v) else None
