"""POST /filter — apply an imaging filter, register the derived image
(handoff §8: {id, kind, params} → new image meta)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc import filters
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


class FilterRequest(BaseModel):
    image_id: str
    kind: str
    params: dict[str, Any] = {}


def _scaled_axes(ds: DataStruct, factor_r: float, factor_c: float) -> tuple:
    """Carry pixel calibration through a resampling (scale × factor)."""

    def scaled(cal: AxisCal, f: float) -> AxisCal:
        if not cal.calibrated:
            return AxisCal()
        return AxisCal(scale=cal.scale * f, origin=0.0, units=cal.units)

    return (scaled(ds.axes[0], factor_r), scaled(ds.axes[1], factor_c))


# kind → (callable, resamples?) — dispatch table, never eval
_FILTERS: dict[str, Callable[[np.ndarray, dict[str, Any]], np.ndarray]] = {
    "gaussian": lambda d, p: filters.apply_gaussian(
        d, sigma=float(p.get("sigma", 1.0))
    ),
    "median": lambda d, p: filters.apply_median(
        d, window_size=int(p.get("window_size", 3))
    ),
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
    "plane_level": lambda d, p: filters.plane_level(
        d, order=int(p.get("order", 1))
    ).leveled,
}

_RESAMPLING = {"bin"}


@router.post("/filter")
def apply_filter(req: FilterRequest) -> ImageMeta:
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    if ds.kind is DataKind.IMAGE:
        raster = np.asarray(ds.data, dtype=np.float64)
    elif ds.kind is DataKind.SPECTRUM_IMAGE:
        raster = np.asarray(ds.data, dtype=np.float64).sum(axis=2)
    else:
        raise HTTPException(400, "1D spectra have no raster to filter")

    fn = _FILTERS.get(req.kind)
    if fn is None:
        raise HTTPException(
            422, f"unknown filter '{req.kind}' (have: {sorted(_FILTERS)})"
        )
    try:
        out = fn(raster, req.params)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e)) from None

    if req.kind in _RESAMPLING:
        axes = _scaled_axes(
            ds, raster.shape[0] / out.shape[0], raster.shape[1] / out.shape[1]
        )
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
    new_id = store.add_derived(
        derived, f"{req.kind}({name})", req.image_id
    )
    return ImageMeta.from_datastruct(new_id, store.name(new_id), derived)
