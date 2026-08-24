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
from fermiviewer.calc.raster import raster_of
from fermiviewer.calc.roughness import surface_roughness
from fermiviewer.calc.segment import morph_op, multi_otsu
from fermiviewer.calc.texture import noise_estimate
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.metadata import databar_content_rows, databar_stripped_metadata
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

# raster_of lives in calc/raster.py now (the one raster boundary, ADR 0003);
# re-exported here because catalogue_spectral and the op tests import it from
# this module.
__all__ = ["raster_of"]


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
register(OpSpec(
    name="plane_level", category="filter", summary="Remove a fitted plane",
    params={"order": OpParam(int, 1, minimum=1, maximum=2)},
    fn=_image_op(
        "plane_level",
        lambda d, p: filters.plane_level(d, order=p["order"]).leveled,
    ),
))
register(OpSpec(
    name="morph", category="filter", summary="Binary morphology at image mean",
    params={
        "operation": OpParam(
            str, "open", choices=("erode", "dilate", "open", "close")
        ),
        "radius": OpParam(int, 1, minimum=1),
        "shape": OpParam(str, "square", choices=("square", "disk")),
    },
    fn=_image_op(
        "morph",
        lambda d, p: morph_op(
            d > d.mean(),
            operation=p["operation"],
            radius=p["radius"],
            shape=p["shape"],
        ).astype(float),
    ),
))
register(OpSpec(
    name="multiotsu", category="filter", summary="Multi-level Otsu labels",
    params={"n_classes": OpParam(int, 3, minimum=2, maximum=5)},
    fn=_image_op(
        "multiotsu",
        lambda d, p: multi_otsu(d, n_classes=p["n_classes"]).label_map.astype(float),
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


def _noise(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    result = noise_estimate(raster_of(ds), method=params["method"])

    def finite(value: float) -> float | None:
        return float(value) if np.isfinite(value) else None

    value = {
        "sigma": result.sigma,
        "snr_db": finite(result.snr_db),
        "snr_linear": finite(result.snr_linear),
        "noise_type": result.noise_type,
        "regression_slope": finite(result.regression_slope),
        "regression_intercept": finite(result.regression_intercept),
        "regression_r_squared": finite(result.regression_r_squared),
    }
    return OpResult(op="noise", params=params, label="noise estimate", value=value)


register(OpSpec(
    name="noise", category="analysis", summary="Noise, SNR, and type estimate",
    params={
        "method": OpParam(str, "mad", choices=("mad", "localvar", "both")),
    },
    fn=_noise,
))


def _roughness(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    px = ds.pixel_size if np.isfinite(ds.pixel_size) and ds.pixel_size > 0 else 1.0
    result = surface_roughness(raster, pixel_size=px, level=params["level"])
    value = {
        "Ra": result.ra,
        "Rq": result.rq,
        "Rz": result.rz,
        "Rsk": result.rsk,
        "Rku": result.rku,
        "Rp": result.rp,
        "Rv": result.rv,
        "SAR": result.sar,
        "n_pixels": result.n_pixels,
        "unit": ds.pixel_unit or "px",
    }
    return OpResult(
        op="roughness", params=params, label="surface roughness", value=value,
    )


register(OpSpec(
    name="roughness", category="analysis", summary="ISO-style surface roughness",
    params={
        "level": OpParam(
            str, "plane", choices=("none", "plane", "quadratic")
        ),
    },
    fn=_roughness,
))


# ── strip_databar (wave D) — derived image, appended per ADR 0005 §2 ─

# NOTE: this op introduces the tree's first ops -> io import (top of file).
# Both are PURE_LAYERS — the layering guard forbids only fastapi/pydantic/
# starlette/routes — and it is deliberate: the databar geometry
# (io.metadata.databar_content_rows) and the metadata carry-forward rule
# (io.metadata.databar_stripped_metadata) live beside the parsers that
# record them, exactly as the route consumes them (ADR 0005 §1).


def _strip_databar(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    """Crop the vendor-baked databar off the bottom of an image — the
    POST /strip-databar composition (routes/filter.py), sharing
    io.metadata's geometry + carry-forward rules with the route."""
    if ds.kind is not DataKind.IMAGE:
        raise ValueError("only 2-D images carry a vendor databar")
    rows = databar_content_rows(ds.metadata, int(ds.data.shape[0]))
    if rows is None:
        raise ValueError("no vendor databar recorded for this image")
    # acquisition provenance is carried forward (databar_stripped_metadata
    # drops only the geometry keys, so a second strip correctly errors);
    # the pure layer cannot compose a session-name `source`, so it carries
    # the static filter-op spelling instead (the wave-B naming-divergence
    # note). dtype is preserved: a pure crop justifies no float64 widening.
    derived = DataStruct(
        data=np.asarray(ds.data)[:rows, :].copy(),
        kind=DataKind.IMAGE,
        axes=(ds.axes[0], ds.axes[1]),
        metadata={
            **databar_stripped_metadata(ds.metadata),
            "parser": "derived",
            "filter_kind": "strip_databar",
            "source": "strip_databar",
        },
    )
    return OpResult(
        op="strip_databar", params=params, label="strip vendor databar", derived=derived
    )


register(
    OpSpec(
        name="strip_databar",
        category="filter",
        summary="Crop the vendor-baked info bar (Thermo Fisher SEM/FIB "
        "TIFFs) off the bottom of an image using the recorded databar "
        "geometry (io.metadata.databar_content_rows); errors when no "
        "databar is recorded",
        fn=_strip_databar,
    )
)
