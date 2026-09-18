"""Interfacial roughness from a box profile, as a registered operation.

The route (`routes/profile_roughness.py`) explains why the measurement
exists: the averaged profile's edge width mixes compositional grading with
geometric waviness, and only a per-column trace separates them.

`produces_value=True`: the answer is a set of numbers and two spectra, not
a derived image. The line travels as four scalars rather than a region
reference so the step replays on any machine (ADR 0007 §11).
"""

from __future__ import annotations

from typing import Any

import numpy as np

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
from fermiviewer.ops._envelopes import output
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


def _profile_roughness(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind is not DataKind.IMAGE:
        raise ValueError("profile_roughness requires a 2-D image")
    width = float(params["width"])
    block = line_box_block(
        ds.data,
        x1=params["col1"] - 1.0,
        y1=params["row1"] - 1.0,
        x2=params["col2"] - 1.0,
        y2=params["row2"] - 1.0,
        width=width,
    )
    if block.shape[1] < 3:
        raise ValueError(
            "roughness is measured ACROSS the box and needs at least 3 columns"
        )
    depth = np.arange(block.shape[0], dtype=np.float64)
    fit = fit_interface_width(depth, block.mean(axis=1), model="erf")
    requested = float(params["interface_pos"])
    pos = fit.center if requested < 0 else requested
    if not 0 <= pos <= depth[-1]:
        raise ValueError(f"interface_pos {pos:g} is outside the box")

    px = ds.pixel_size
    depth_size, lateral_size = growth_axis_scales(
        "y", px if np.isfinite(px) and px > 0 else 1.0, ds.pixel_spacing
    )
    window = int(params["trace_window"])
    trace = trace_interface(block, "y", pos, window)
    rough = analyze_trace(trace, depth_size, lateral_size=lateral_size)
    clipped = window_limited_fraction(trace, pos, window)
    s_erf = fit.sigma * depth_size
    unit = ds.pixel_unit if np.isfinite(px) and px > 0 else "px"

    def _scalar(name: str, value: float, scalar_unit: str) -> dict[str, Any]:
        # NaN through the envelope unchanged: an unmeasurable roughness is
        # absent, and a 0 would read as a perfectly flat interface
        return output("scalar", name, {"value": float(value), "unit": scalar_unit})

    return OpResult(
        op="profile_roughness",
        params=params,
        label="interfacial roughness",
        value={
            "outputs": [
                _scalar("sigma_w", rough.sigma_w, unit),
                _scalar("sigma_erf", s_erf, unit),
                _scalar("sigma_chem", sigma_chem(s_erf, rough.sigma_w), unit),
                _scalar("xi", rough.xi, unit),
                _scalar("hurst", rough.hurst, ""),
                _scalar("trace_quality", rough.quality, ""),
                # the signal that says sigma_w is a lower bound; `quality`
                # can read 1.0 while every column was clipped alike
                _scalar("window_limited_fraction", clipped, ""),
                output(
                    "curve",
                    "interface_trace",
                    {
                        "x_name": "lateral position",
                        "x_unit": unit,
                        "y_name": "interface depth",
                        "y_unit": unit,
                    },
                ),
            ],
            "trace": np.asarray(trace, dtype=np.float64).tolist(),
            "interface_pos": pos,
            "lateral_samples": int(block.shape[1]),
        },
    )


register(
    OpSpec(
        name="profile_roughness",
        category="analysis",
        produces_value=True,
        summary="Interfacial roughness traced column-by-column across a box "
        "profile (calc/trace_roughness). The averaged profile's edge width "
        "mixes compositional grading with geometric waviness — "
        "sigma_erf^2 ~ sigma_chem^2 + sigma_w^2 — so one number from it "
        "cannot separate them; tracing every column measures sigma_w "
        "directly and the grading falls out of the subtraction",
        params={
            # required, with no default: a profile line has no sensible
            # one, and defaulting all four to the same corner would make a
            # zero-length line the thing a caller gets by saying nothing
            # (`roi_stats` and `line_profile` take the same position)
            "row1": OpParam(float, required=True, doc="profile start row, 1-based"),
            "col1": OpParam(float, required=True, doc="profile start column, 1-based"),
            "row2": OpParam(float, required=True, doc="profile end row, 1-based"),
            "col2": OpParam(float, required=True, doc="profile end column, 1-based"),
            "width": OpParam(
                float,
                20.0,
                minimum=3.0,
                doc="perpendicular box width in pixels; this is what gives "
                "the columns to trace across, so a width of 1 is a line and "
                "has no roughness to measure",
            ),
            "interface_pos": OpParam(
                float,
                -1.0,
                doc="depth along the box where the interface sits, in box "
                "pixels; negative fits the averaged profile and uses that "
                "centre",
            ),
            "trace_window": OpParam(
                float,
                10.0,
                minimum=3.0,
                doc="half-height of the per-column search window. An "
                "interface that wanders further than this is CLIPPED and "
                "sigma_w comes back a lower bound — check "
                "window_limited_fraction",
            ),
        },
        fn=_profile_roughness,
    )
)
