"""AFM/SPM levelling ops (calc/afm_level.py) — the same functions the
/filter route's AFM kinds call, so a script or batch recipe levels exactly
like the GUI."""

from __future__ import annotations

from fermiviewer.calc import afm_level
from fermiviewer.ops.base import OpParam, OpSpec
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
