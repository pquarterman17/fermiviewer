"""`POST /api/measure/profile-roughness` — interfacial roughness from the
box a profile averages over, rather than from the averaged profile.

The distinction is the whole point. A box profile reports an edge width,
and that width is wide for two completely different reasons: the interface
is genuinely graded in composition, or it is sharp but wavy and the lateral
averaging smeared it. They combine as
``sigma_erf² ~ sigma_chem² + sigma_w²`` (`calc.trace_roughness.sigma_chem`),
so ONE number from the averaged profile cannot separate them. Tracing the
interface column by column measures sigma_w directly, and the grading falls
out of the subtraction.

All the metrology already existed — `trace_interface`, `analyze_trace`,
`sigma_chem` — but only the cross-section layers workshop could reach it,
and only for an axis-aligned ROI. What was missing was a way to run it on
the box a user actually drew, at whatever angle they drew it.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.calibration import growth_axis_scales
from fermiviewer.calc.profile_stats import fit_interface_width
from fermiviewer.calc.tilted_profile import line_box_block
from fermiviewer.calc.trace_roughness import (
    analyze_trace,
    sigma_chem,
    trace_interface,
    window_limited_fraction,
)
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


class ProfileRoughnessRequest(BaseModel):
    image_id: str
    #: the profile line, (row, col) 1-based — the same convention
    #: `/measure/profile` takes, so a client hands over what it already has
    a: tuple[float, float]
    b: tuple[float, float]
    #: perpendicular extent of the box, image pixels. This is the number
    #: that makes a roughness measurement possible at all: a width of 1 is
    #: a single line and has no columns to trace across.
    width: float = Field(default=20.0, ge=3.0)
    #: depth along the line where the interface sits, in box pixels. Omit
    #: to fit the box's own averaged profile and use that centre.
    interface_pos: float | None = None
    #: half-height of the per-column search window, box pixels
    trace_window: int = Field(default=10, ge=3, le=200)


def _dataset(img_id: str) -> DataStruct:
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    if ds.kind is not DataKind.IMAGE:
        raise HTTPException(400, "roughness needs a 2-D image")
    return ds


@router.post("/measure/profile-roughness")
def profile_roughness(req: ProfileRoughnessRequest) -> dict[str, Any]:
    """Trace one interface across the box and report its roughness."""
    ds = _dataset(req.image_id)
    # (row, col) 1-based in, (x=col, y=row) 0-based out: `line_box_block`
    # holds a line, not a region, and follows `line_profile`'s convention
    try:
        block = line_box_block(
            ds.data,
            x1=req.a[1] - 1.0,
            y1=req.a[0] - 1.0,
            x2=req.b[1] - 1.0,
            y2=req.b[0] - 1.0,
            width=req.width,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if block.shape[1] < 3:
        raise HTTPException(
            422,
            f"a width of {req.width:g} px leaves {block.shape[1]} column(s); "
            "roughness is measured ACROSS the box, so it needs at least 3",
        )

    depth = np.arange(block.shape[0], dtype=np.float64)
    averaged = block.mean(axis=1)
    # sigma_erf comes from the AVERAGED profile — the number that mixes the
    # two effects — so that the decomposition below has something to split
    try:
        fit = fit_interface_width(depth, averaged, model="erf")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    pos = fit.center if req.interface_pos is None else float(req.interface_pos)
    if not 0 <= pos <= depth[-1]:
        raise HTTPException(
            422,
            f"interface_pos {pos:g} is outside the box's depth range "
            f"[0, {depth[-1]:g}]",
        )

    px = ds.pixel_size
    depth_size, lateral_size = growth_axis_scales(
        "y", px if np.isfinite(px) and px > 0 else 1.0, ds.pixel_spacing
    )
    trace = trace_interface(block, "y", pos, req.trace_window)
    rough = analyze_trace(trace, depth_size, lateral_size=lateral_size)
    clipped = window_limited_fraction(trace, pos, req.trace_window)

    unit = ds.pixel_unit if np.isfinite(px) and px > 0 else "px"
    sigma_erf = fit.sigma * depth_size
    body = asdict(rough)
    # arrays out as lists; the spectra are what a client plots
    for key in ("psd_wavelength", "psd_power", "detrended"):
        body[key] = np.asarray(body[key], dtype=np.float64).tolist()
    body["trace"] = np.asarray(trace, dtype=np.float64).tolist()
    return {
        **body,
        "unit": unit,
        "interface_pos": pos,
        "lateral_samples": int(block.shape[1]),
        # the averaged-profile width, and what is left of it once the
        # geometric waviness is taken out in quadrature. NaN -> null: a
        # roughness-limited interface has no resolvable grading, which is
        # an absent answer, not a zero one.
        "sigma_erf": sigma_erf,
        "sigma_chem": _nan_none(sigma_chem(sigma_erf, rough.sigma_w)),
        "r_squared": fit.r_squared,
        # How much of the trace ran into the search window's edge. This is
        # NOT `quality`, which says every column was traced -- they can all
        # be traced to the wrong place. A rough interface in a narrow window
        # under-reports sigma_w several-fold with quality still at 1.00.
        "window_limited_fraction": clipped,
        "limitations": [
            *(
                [
                    f"{clipped:.0%} of the trace is pinned against the "
                    f"+/-{req.trace_window} px search window: the interface "
                    "wanders further than the window allows, so sigma_w is a "
                    "LOWER BOUND. Re-measure with a larger trace_window."
                ]
                if clipped > 0.05
                else []
            ),
            "sigma_w is the roughness the BOX saw: a wavelength longer than "
            "the box is removed by detrending and does not appear here.",
            "Both widths are projection-limited, so sigma_chem is an upper "
            "bound on true compositional grading.",
        ],
    }


def _nan_none(value: float) -> float | None:
    return None if not np.isfinite(value) else float(value)
