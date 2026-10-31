"""Scan distortion correction ops (calc/jitter): scan-line jitter within
one image, and drift across a series of frames.

``line_jitter`` returns the corrected image as a derived struct.
``frame_drift`` follows the multi-image convention of ``catalogue_stack``:
the subject is frame 0 (the origin of the reported shifts) and ``others``
carries the rest; it returns the drift-corrected average, the usual reason
for registering a series. Per wave D's standing rule, each derived struct
carries its diagnostics (offsets, shifts, crop) in its metadata.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.jitter import (
    apply_frame_drift,
    correct_line_jitter,
    estimate_frame_drift,
    estimate_line_jitter,
)
from fermiviewer.calc.raster import raster_of
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops.base import OpInput, OpParam, OpResult, OpSpec
from fermiviewer.ops.catalogue_stack import _RASTER_KINDS
from fermiviewer.ops.registry import register

__all__: list[str] = []


def _cropped_axis(axis: AxisCal, start: int) -> AxisCal:
    """The same calibration for an image cut to begin at index ``start``:
    value = (index − origin) × scale keeps every pixel's physical position."""
    return AxisCal(scale=axis.scale, origin=axis.origin - start, units=axis.units)


# ── line_jitter (derived image) ─────────────────────────────────────────


def _line_jitter(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind is not DataKind.IMAGE:
        raise ValueError("scan-line jitter correction needs a 2-D greyscale image")
    img = np.asarray(ds.data, dtype=np.float64)
    res = estimate_line_jitter(
        img, max_shift=params["max_shift"], trend_rows=params["trend_rows"]
    )
    derived = DataStruct(
        data=np.ascontiguousarray(correct_line_jitter(img, res.offsets)),
        kind=DataKind.IMAGE,
        axes=(ds.axes[0], ds.axes[1]),
        metadata={
            "parser": "derived",
            "source": "line_jitter",
            "filter_kind": "line_jitter",
            "jitter_rms_px": res.rms,
            "jitter_max_px": res.max_abs,
            "jitter_offsets_px": res.offsets.tolist(),
        },
    )
    return OpResult(
        op="line_jitter",
        params=params,
        label=f"scan-line jitter corrected (rms {res.rms:.2f} px)",
        derived=derived,
    )


register(
    OpSpec(
        name="line_jitter",
        category="filter",
        summary="Correct row-to-row horizontal jitter in a scanned image: "
        "each row's sub-pixel offset is solved from its correlation with "
        "the rows above it, then rows are resampled (calc/jitter)",
        params={
            "max_shift": OpParam(
                float,
                5.0,
                minimum=1.0,
                maximum=64.0,
                doc="largest row offset searched (px); keep below half the "
                "period of any strong horizontal lattice",
            ),
            "trend_rows": OpParam(
                float,
                20.0,
                minimum=0.0,
                maximum=1000.0,
                doc="slow trends over about this many rows (Gaussian sigma) "
                "are kept as genuine structure; 0 keeps none",
            ),
        },
        fn=_line_jitter,
    )
)


# ── frame_drift (derived average; variadic input) ───────────────────────


def _frame_drift(
    ds: DataStruct, params: dict[str, Any], inputs: dict[str, Any]
) -> OpResult:
    rasters = [raster_of(f) for f in [ds, *inputs["others"]]]
    drift = estimate_frame_drift(rasters, reference=params["reference"])
    aligned, (top, _bottom, left, _right) = apply_frame_drift(
        rasters, drift.shifts, crop=params["crop"]
    )
    derived = DataStruct(
        data=np.ascontiguousarray(np.mean(aligned, axis=0)),
        kind=DataKind.IMAGE,
        axes=(_cropped_axis(ds.axes[0], top), _cropped_axis(ds.axes[1], left)),
        metadata={
            "parser": "derived",
            "source": "frame_drift",
            "frame_drift_shifts_px": drift.shifts.tolist(),
            "frame_drift_max_px": drift.max_abs,
            "frame_drift_frames": len(rasters),
        },
    )
    return OpResult(
        op="frame_drift",
        params=params,
        label=f"drift-corrected average of {len(rasters)} frames "
        f"(max drift {drift.max_abs:.1f} px)",
        derived=derived,
    )


register(
    OpSpec(
        name="frame_drift",
        category="filter",
        summary="Sub-pixel drift correction across a series: frames are "
        "registered by phase correlation, resampled onto frame 0 and "
        "averaged; with crop, only the area every frame covers is kept "
        "(calc/jitter)",
        params={
            "reference": OpParam(
                str,
                "mean",
                choices=("mean", "first"),
                doc="register to the first frame, or (mean) re-register to "
                "the average of a first alignment — better for noisy frames",
            ),
            "crop": OpParam(
                bool,
                True,
                doc="cut to the region every frame covers, so the average "
                "has no padded edges",
            ),
        },
        inputs={
            "others": OpInput(
                doc="the remaining frames, in order; the subject is frame 0",
                variadic=True,
                min_count=1,
                kinds=_RASTER_KINDS,
            ),
        },
        fn=_frame_drift,
    )
)
