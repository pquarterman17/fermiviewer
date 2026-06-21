"""Operation catalogue — register analysis verbs as thin calc/ adapters
(Scripting #1).

Every op here calls the SAME pure ``calc/`` function the FastAPI routes call —
this layer is wiring + schema only, never reimplemented physics. Importing
this module registers the ops (see ``ops/__init__.py``). Start with the
filter + image-stats set the macro/batch already exercise, so parity with the
HTTP path is provable by test.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from fermiviewer.calc import filters
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__ = ["raster_of"]


def raster_of(ds: DataStruct) -> np.ndarray:
    """The 2D raster to operate on: an image directly, or a SI's summed map
    (mirrors routes/filter.py). 1D spectra have no raster."""
    if ds.kind is DataKind.IMAGE:
        img: np.ndarray = np.asarray(ds.data, dtype=np.float64)
        return img
    if ds.kind is DataKind.SPECTRUM_IMAGE:
        summed: np.ndarray = np.asarray(ds.data, dtype=np.float64).sum(axis=2)
        return summed
    raise ValueError("operation needs a 2D raster (got a 1D spectrum)")


def _scaled_axes(ds: DataStruct, fr: float, fc: float) -> tuple[AxisCal, AxisCal]:
    def scaled(cal: AxisCal, f: float) -> AxisCal:
        if not cal.calibrated:
            return AxisCal()
        return AxisCal(scale=cal.scale * f, origin=0.0, units=cal.units)

    return scaled(ds.axes[0], fr), scaled(ds.axes[1], fc)


def _image_op(
    kind: str,
    apply: Callable[[np.ndarray, dict[str, Any]], np.ndarray],
    *,
    resamples: bool = False,
    swaps_axes: bool = False,
) -> Callable[[DataStruct, dict[str, Any]], OpResult]:
    """Build an op fn that applies `apply` to the raster and returns a derived
    IMAGE DataStruct with calibration carried through."""

    def fn(ds: DataStruct, params: dict[str, Any]) -> OpResult:
        raster = raster_of(ds)
        out = np.ascontiguousarray(apply(raster, params))
        if resamples:
            axes = _scaled_axes(
                ds, raster.shape[0] / out.shape[0], raster.shape[1] / out.shape[1]
            )
        elif swaps_axes:
            axes = (ds.axes[1], ds.axes[0])
        else:
            axes = (ds.axes[0], ds.axes[1])
        derived = DataStruct(
            data=out,
            kind=DataKind.IMAGE,
            axes=axes,
            metadata={"parser": "derived", "filter_kind": kind, "source": kind},
        )
        return OpResult(op=kind, params=params, label=kind, derived=derived)

    return fn


# ── filter ops (image → derived image) ───────────────────────────────

register(OpSpec(
    name="gaussian", category="filter", summary="Gaussian blur",
    params={"sigma": OpParam(float, 1.0, minimum=0.0, doc="blur radius (px)")},
    fn=_image_op("gaussian", lambda d, p: filters.apply_gaussian(d, sigma=p["sigma"])),
))
register(OpSpec(
    name="median", category="filter", summary="Median denoise",
    params={"window_size": OpParam(int, 3, minimum=1, doc="window (px)")},
    fn=_image_op("median", lambda d, p: filters.apply_median(d, window_size=p["window_size"])),
))
register(OpSpec(
    name="unsharp", category="filter", summary="Unsharp mask (sharpen)",
    params={
        "sigma": OpParam(float, 2.0, minimum=0.0),
        "amount": OpParam(float, 1.0, minimum=0.0),
    },
    fn=_image_op(
        "unsharp",
        lambda d, p: filters.unsharp_mask(d, sigma=p["sigma"], amount=p["amount"]),
    ),
))
register(OpSpec(
    name="butterworth", category="filter", summary="Butterworth band filter",
    params={
        "low_cutoff": OpParam(float, 0.0, minimum=0.0, maximum=1.0),
        "high_cutoff": OpParam(float, 0.5, minimum=0.0, maximum=1.0),
        "order": OpParam(int, 2, minimum=1),
    },
    fn=_image_op(
        "butterworth",
        lambda d, p: filters.butterworth_filter(
            d, low_cutoff=p["low_cutoff"], high_cutoff=p["high_cutoff"], order=p["order"]
        ),
    ),
))
register(OpSpec(
    name="clahe", category="filter", summary="CLAHE local contrast",
    params={
        "clip_limit": OpParam(float, 0.01, minimum=0.0),
        "num_bins": OpParam(int, 256, minimum=2),
    },
    fn=_image_op(
        "clahe",
        lambda d, p: filters.clahe(d, clip_limit=p["clip_limit"], num_bins=p["num_bins"]),
    ),
))
register(OpSpec(
    name="bin", category="filter", summary="Bin / downsample",
    params={
        "bin_size": OpParam(int, 2, minimum=1),
        "mode": OpParam(str, "average", choices=("average", "sum")),
    },
    fn=_image_op(
        "bin",
        lambda d, p: filters.bin_image(d, bin_size=p["bin_size"], mode=p["mode"]),
        resamples=True,
    ),
))

# ── geometry ops (axis-aware) ────────────────────────────────────────

register(OpSpec(
    name="rotate90", category="geometry", summary="Rotate 90° clockwise",
    fn=_image_op("rotate90", lambda d, p: np.rot90(d, k=-1), swaps_axes=True),
))
register(OpSpec(
    name="rotate180", category="geometry", summary="Rotate 180°",
    fn=_image_op("rotate180", lambda d, p: np.rot90(d, k=2)),
))
register(OpSpec(
    name="rotate270", category="geometry", summary="Rotate 90° counter-clockwise",
    fn=_image_op("rotate270", lambda d, p: np.rot90(d, k=1), swaps_axes=True),
))
register(OpSpec(
    name="fliph", category="geometry", summary="Flip horizontal",
    fn=_image_op("fliph", lambda d, p: d[:, ::-1]),
))
register(OpSpec(
    name="flipv", category="geometry", summary="Flip vertical",
    fn=_image_op("flipv", lambda d, p: d[::-1, :]),
))


# ── analysis op (value, not an image) ────────────────────────────────

def _image_stats(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    r = raster_of(ds)
    finite = r[np.isfinite(r)]
    value = {
        "mean": float(finite.mean()) if finite.size else float("nan"),
        "std": float(finite.std()) if finite.size else float("nan"),
        "min": float(finite.min()) if finite.size else float("nan"),
        "max": float(finite.max()) if finite.size else float("nan"),
        "shape": list(r.shape),
    }
    return OpResult(op="image_stats", params=params, label="image statistics", value=value)


register(OpSpec(
    name="image_stats", category="analysis", summary="Raster mean/std/min/max",
    fn=_image_stats,
))
