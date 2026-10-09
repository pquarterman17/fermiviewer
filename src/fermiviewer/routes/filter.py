"""POST /filter — apply an imaging filter, register the derived image
(handoff §8: {id, kind, params} → new image meta)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc import filters
from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.calc.segment import morph_op, multi_otsu
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.metadata import databar_content_rows, databar_stripped_metadata
from fermiviewer.models import ImageMeta
from fermiviewer.routes._afm_filters import AFM_FILTERS
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


class FilterRequest(BaseModel):
    image_id: str
    kind: str
    params: dict[str, Any] = {}


class StripDatabarRequest(BaseModel):
    image_id: str


def _scaled_axes(ds: DataStruct, factor_r: float, factor_c: float) -> tuple:
    """Carry pixel calibration through a resampling (scale × factor)."""

    def scaled(cal: AxisCal, f: float) -> AxisCal:
        if not cal.calibrated:
            return AxisCal()
        return AxisCal(scale=cal.scale * f, origin=0.0, units=cal.units)

    return (scaled(ds.axes[0], factor_r), scaled(ds.axes[1], factor_c))


# Upper bounds for filter params that size an allocation. Beyond these the
# result is meaningless anyway (a blur wider than the image is flat; a
# structuring element past ~100 px makes binary morphology take minutes), and
# huge values (1e9) used to surface as a 500 from numpy's allocator.
_MAX_MORPH_RADIUS = 100
_MAX_CLAHE_BINS = 65536
_MAX_BUTTERWORTH_ORDER = 10


def _num(p: dict[str, Any], key: str, default: float, label: str, *,
         lo: float | None = None, hi: float | None = None,
         positive: bool = False, integer: bool = False) -> float:
    """Read a numeric filter param, raising ValueError (→ 422) with a
    user-facing message instead of letting numpy fail on it."""
    raw = p.get(key, default)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number (got {raw!r})") from None
    if not np.isfinite(v):
        raise ValueError(f"{label} must be a finite number")
    if integer and v != int(v):
        raise ValueError(f"{label} must be a whole number")
    if positive and v <= 0:
        raise ValueError(f"{label} must be greater than 0")
    if lo is not None and v < lo:
        raise ValueError(f"{label} must be at least {lo:g}")
    if hi is not None and v > hi:
        raise ValueError(f"{label} must be at most {hi:g}")
    return v


def _sigma(d: np.ndarray, p: dict[str, Any], default: float) -> float:
    """Blur sigma: > 0 and no wider than the image."""
    return _num(p, "sigma", default, "sigma (px)", positive=True,
                hi=float(max(d.shape)))


def _gaussian(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    return filters.apply_gaussian(d, sigma=_sigma(d, p, 1.0))


def _unsharp(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    return filters.unsharp_mask(
        d, sigma=_sigma(d, p, 2.0),
        amount=_num(p, "amount", 1.0, "amount", lo=0.0),
    )


def _butterworth(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    return filters.butterworth_filter(
        d,
        low_cutoff=_num(p, "low_cutoff", 0.0, "low cutoff"),
        high_cutoff=_num(p, "high_cutoff", 0.5, "high cutoff"),
        order=int(_num(p, "order", 2, "order", integer=True, lo=1,
                       hi=_MAX_BUTTERWORTH_ORDER)),
    )


def _clahe(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    tiles = p.get("tile_size", (8, 8))
    if not isinstance(tiles, (list, tuple)) or len(tiles) != 2:
        raise ValueError("tile size must be a pair of whole numbers")
    tile_size = tuple(
        int(_num({"t": t}, "t", 8, "tile count", integer=True, lo=1, hi=float(n)))
        for t, n in zip(tiles, d.shape, strict=True)
    )
    return filters.clahe(
        d,
        tile_size=tile_size,  # type: ignore[arg-type]
        clip_limit=_num(p, "clip_limit", 0.01, "clip limit", lo=0.0, hi=1.0),
        num_bins=int(_num(p, "num_bins", 256, "bins", integer=True, lo=2,
                          hi=_MAX_CLAHE_BINS)),
    )


def _bin(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    return filters.bin_image(
        d,
        bin_size=int(_num(p, "bin_size", 2, "bin size", integer=True, lo=1,
                          hi=float(min(d.shape)))),
        mode=str(p.get("mode", "average")),
    )


def _morph(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    radius = int(_num(p, "radius", 1, "radius (px)", integer=True, lo=1,
                      hi=_MAX_MORPH_RADIUS))
    return morph_op(
        d > d.mean(),
        operation=str(p.get("operation", "open")),
        radius=radius,
        shape=str(p.get("shape", "square")),
    ).astype(float)


def _crop(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    """Crop to a 1-based inclusive (row0, col0)–(row1, col1) rect
    (MATLAB convention, matching the measure endpoints)."""
    r0, r1 = sorted((int(p["row0"]), int(p["row1"])))
    c0, c1 = sorted((int(p["col0"]), int(p["col1"])))
    r0, c0 = max(r0, 1), max(c0, 1)
    out = d[r0 - 1 : r1, c0 - 1 : c1]
    if out.size == 0:
        raise ValueError("crop rectangle is empty")
    return out


def _rotate_arbitrary(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    """Arbitrary-angle rotate (CCW degrees), same dims, edge-extended fill —
    used by the cross-section 'level' action to make tilted layers axis-
    aligned. Square pixels assumed (the project's pixel_cal convention), so
    the calibration scale is unchanged."""
    from scipy.ndimage import rotate as _ndrot

    angle = _num(p, "angle", 0.0, "angle")
    out: np.ndarray = _ndrot(d, angle, reshape=False, order=1, mode="nearest")
    return out


# kind → (callable, resamples?) — dispatch table, never eval
_FILTERS: dict[str, Callable[[np.ndarray, dict[str, Any]], np.ndarray]] = {
    "rotate": _rotate_arbitrary,
    "gaussian": _gaussian,
    "median": lambda d, p: filters.apply_median(d, window_size=int(p.get("window_size", 3))),
    "unsharp": _unsharp,
    "butterworth": _butterworth,
    "clahe": _clahe,
    "bin": _bin,
    # geometric ops (stage toolbar): np.rot90 k>0 is CCW, so CW = k=-1
    "rotate90": lambda d, p: np.rot90(d, k=-1),  # 90° clockwise
    "rotate180": lambda d, p: np.rot90(d, k=2),
    "rotate270": lambda d, p: np.rot90(d, k=1),  # 90° CCW
    "fliph": lambda d, p: d[:, ::-1],  # mirror left-right
    "flipv": lambda d, p: d[::-1, :],  # mirror top-bottom
    "crop": _crop,
    # segmentation dialogs (checklist K): morphology thresholds at the
    # image mean first (binary op on grayscale input); multi-Otsu
    # returns the class-label map for visualization
    "morph": _morph,
    "multiotsu": lambda d, p: multi_otsu(d, n_classes=int(p.get("n_classes", 3))).label_map.astype(
        float
    ),
}

# AFM/SPM levelling (plane_level is NaN-safe, order 1–3, base-only fit)
_FILTERS.update(AFM_FILTERS(_num))

_RESAMPLING = {"bin"}
# outputs that are no longer the input's physical quantity (labels, a
# binary mask, contrast-equalised 0–1): every other kind keeps its value
# unit, so a levelled AFM height map stays in nm
_UNITLESS = {"morph", "multiotsu", "clahe"}
_SWAPS_AXES = {"rotate90", "rotate270"}  # row/col cal swap


def _carried_units(ds: DataStruct, kind: str) -> dict[str, Any]:
    """Value unit and channel of the source, unless the filter changes
    what the pixel values mean."""
    if kind in _UNITLESS:
        return {}
    return {k: ds.metadata[k] for k in ("value_unit", "channel") if k in ds.metadata}


@router.post("/filter")
def apply_filter(req: FilterRequest) -> ImageMeta:
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    try:
        raster = raster_of(ds)
    except NoRasterError:
        raise HTTPException(400, "1D spectra have no raster to filter") from None

    fn = _FILTERS.get(req.kind)
    if fn is None:
        raise HTTPException(422, f"unknown filter '{req.kind}' (have: {sorted(_FILTERS)})")
    try:
        out = fn(raster, req.params)
    except KeyError as e:
        raise HTTPException(422, f"missing param: {e}") from None
    except (ValueError, TypeError, ZeroDivisionError, IndexError) as e:
        # bin_size=0 (ZeroDivisionError, calc.filters.bin_image) and
        # clahe tile_size=[0, 0] (IndexError, empty tile-centre array in
        # calc.filters.clahe) are malformed-but-well-typed params that
        # otherwise escape this catch-all as an unhandled 500.
        raise HTTPException(422, str(e)) from None

    if req.kind in _RESAMPLING:
        axes = _scaled_axes(ds, raster.shape[0] / out.shape[0], raster.shape[1] / out.shape[1])
    elif req.kind in _SWAPS_AXES:
        axes = ds.transposed_spatial_axes()
    else:
        axes = (ds.axes[0], ds.axes[1])

    name = store.name(req.image_id)
    derived = DataStruct(
        data=np.ascontiguousarray(out),
        kind=DataKind.IMAGE,
        axes=axes,
        metadata={
            "source": f"{req.kind} of {name}",
            "parser": "derived",
            "filter_kind": req.kind,
            **_carried_units(ds, req.kind),
        },
    )
    new_id = store.add_derived(derived, f"{req.kind}({name})", req.image_id)
    return ImageMeta.from_datastruct(new_id, store.name(new_id), derived)


@router.post("/strip-databar")
def strip_databar(req: StripDatabarRequest) -> ImageMeta:
    """Crop a vendor-baked databar off the bottom of an image.

    Thermo Fisher SEM/FIB TIFFs bake an info strip (magnification, HV, and
    the vendor's own scale bar) into the pixels, which is unusable in a
    figure and collides with FermiViewer's scale bar. The geometry lives
    server-side (io.metadata.databar_content_rows) so the client only has
    to ask, and the cut is exact rather than eyeballed against an ROI.
    """
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    if ds.kind is not DataKind.IMAGE:
        raise HTTPException(400, "only 2-D images carry a vendor databar")
    rows = databar_content_rows(ds.metadata, int(ds.data.shape[0]))
    if rows is None:
        raise HTTPException(422, "no vendor databar recorded for this image")

    name = store.name(req.image_id)
    # Carry the acquisition provenance forward (unlike the generic /filter
    # path, which rebuilds metadata from scratch) — the rule and its
    # rationale live on io.metadata.databar_stripped_metadata.
    carried = databar_stripped_metadata(ds.metadata)
    # dtype is preserved: this is a pure crop, so unlike the filter path
    # there is no computation to justify widening to float64.
    derived = DataStruct(
        data=np.asarray(ds.data)[:rows, :].copy(),
        kind=DataKind.IMAGE,
        axes=(ds.axes[0], ds.axes[1]),
        metadata={
            **carried,
            "source": f"databar stripped from {name}",
            "parser": "derived",
            "filter_kind": "strip_databar",
        },
    )
    new_id = store.add_derived(derived, f"nobar({name})", req.image_id)
    return ImageMeta.from_datastruct(new_id, store.name(new_id), derived)
