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

    angle = float(p.get("angle", 0.0))
    out: np.ndarray = _ndrot(d, angle, reshape=False, order=1, mode="nearest")
    return out


# kind → (callable, resamples?) — dispatch table, never eval
_FILTERS: dict[str, Callable[[np.ndarray, dict[str, Any]], np.ndarray]] = {
    "rotate": _rotate_arbitrary,
    "gaussian": lambda d, p: filters.apply_gaussian(d, sigma=float(p.get("sigma", 1.0))),
    "median": lambda d, p: filters.apply_median(d, window_size=int(p.get("window_size", 3))),
    "unsharp": lambda d, p: filters.unsharp_mask(
        d, sigma=float(p.get("sigma", 2.0)), amount=float(p.get("amount", 1.0))
    ),
    "butterworth": lambda d, p: filters.butterworth_filter(
        d,
        low_cutoff=float(p.get("low_cutoff", 0.0)),
        high_cutoff=float(p.get("high_cutoff", 0.5)),
        order=int(p.get("order", 2)),
    ),
    "clahe": lambda d, p: filters.clahe(
        d,
        tile_size=tuple(p.get("tile_size", (8, 8))),
        clip_limit=float(p.get("clip_limit", 0.01)),
        num_bins=int(p.get("num_bins", 256)),
    ),
    "bin": lambda d, p: filters.bin_image(
        d, bin_size=int(p.get("bin_size", 2)), mode=str(p.get("mode", "average"))
    ),
    "plane_level": lambda d, p: filters.plane_level(d, order=int(p.get("order", 1))).leveled,
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
    "morph": lambda d, p: morph_op(
        d > d.mean(),
        operation=str(p.get("operation", "open")),
        radius=int(p.get("radius", 1)),
        shape=str(p.get("shape", "square")),
    ).astype(float),
    "multiotsu": lambda d, p: multi_otsu(d, n_classes=int(p.get("n_classes", 3))).label_map.astype(
        float
    ),
}

_RESAMPLING = {"bin"}
_SWAPS_AXES = {"rotate90", "rotate270"}  # row/col cal swap


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
        axes = (ds.axes[1], ds.axes[0])
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
