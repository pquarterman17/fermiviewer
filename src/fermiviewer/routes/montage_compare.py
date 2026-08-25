"""Comparison montage endpoint (project-workflow plan item #25).

Publication panel: one representative tile per sample, tiled and labelled
with that sample's parameter value, sharing ONE scale bar. Plain
/analyze/montage (imaging_ops.py) tiles pixel-for-pixel, which is correct
for a same-scale stack but MISLEADING for cross-sample comparison — a
sample imaged at higher magnification would simply look bigger. This
endpoint resamples every tile to ONE common physical scale first (see
calc.montage.montage_physical_scale), then registers the composite as a
derived library image exactly like /analyze/montage does.

New module rather than an addition to imaging_ops.py (457/500 lines) per
the MAIN_PLAN cross-cutting note: extend the roomy calc module, land the
route in a fresh file.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.export import ScaleBar
from fermiviewer.calc.montage_physical import (
    montage_physical_scale,
    order_by_param_value,
)
from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.routes._arrays import value_error_as_422
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _raster(img_id: str) -> tuple[DataStruct, np.ndarray]:
    """Fetch a stored image's 2-D raster (mirrors imaging_ops._raster)."""
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    try:
        return ds, raster_of(ds)
    except NoRasterError:
        raise HTTPException(400, f"image {img_id} has no 2-D raster") from None


def _scale_bar_dict(bar: ScaleBar) -> dict[str, object]:
    return {
        "x": bar.x, "y": bar.y, "width": bar.width, "height": bar.height,
        "label": bar.label, "color": bar.color,
    }


class MontageTile(BaseModel):
    image_id: str
    # None -> falls back to the image's own library name. The caller
    # (e.g. a "Montage samples" panel action) composes sample name +
    # parameter value into this string; this endpoint has no opinion on
    # sample/param modelling, only on tiling + a shared scale.
    label: str | None = None
    # Plan item 29: a sample's params[primary_param].value (schema field
    # `primary_param`, io/project_manifest.py), for ordering the panel as
    # a trend rather than in creation/request order. The caller (frontend
    # or a future "Montage samples" action) resolves the value; this
    # endpoint only knows how to sort by it — see
    # calc.montage_physical.order_by_param_value.
    param_value: float | str | bool | None = None


class MontageCompareRequest(BaseModel):
    tiles: list[MontageTile]
    cols: int | None = None          # None -> ceil(sqrt(n)); mirrors auto mode
    gap: int = Field(default=4, ge=0, le=64)
    bg: float = 0.0
    font_size: int = Field(default=14, ge=6, le=48)
    bar_color: str = "#ffffff"


@router.post("/analyze/montage-compare")
def analyze_montage_compare(req: MontageCompareRequest) -> dict:
    """Comparison montage: ONE common physical scale, ONE shared scale bar.

    Every tile MUST already carry a pixel calibration — a common physical
    scale is undefined otherwise, and this endpoint refuses (422, naming
    the offending image) rather than silently falling back to pixel-space
    tiling with a scale bar that would be wrong for some tiles.

    The common scale is the COARSEST tile's µm/px (see
    calc.montage.montage_physical_scale) — every other tile is downsampled,
    never upsampled beyond its own real resolution.

    Tiles are reordered ascending by `param_value` before tiling (plan
    item 29), so a panel built from a sample series reads as a trend left-
    to-right / top-to-bottom instead of in creation order — see
    calc.montage_physical.order_by_param_value for the exact rule,
    including the non-numeric/missing case. A request that never sets
    `param_value` tiles in request order, unchanged from before this
    existed.

    Request
    -------
    tiles     : [{"image_id": str, "label": str | null,
                  "param_value": float | str | bool | null}], >= 1 entries.
    cols      : grid columns; null -> ceil(sqrt(n)).
    gap, bg, font_size, bar_color : passed through to
                calc.montage.montage_physical_scale.

    Response
    --------
    {"image": <ImageMeta>, "scale_bar": {...}} — the registered derived
    montage image (its own pixel_size/pixel_unit ARE the common scale)
    plus the baked bar's geometry/label for the caller to report.
    """
    if not req.tiles:
        raise HTTPException(422, "montage-compare: provide at least 1 tile")

    ordered_tiles = [
        req.tiles[i]
        for i in order_by_param_value([t.param_value for t in req.tiles])
    ]

    frames: list[np.ndarray] = []
    pixel_sizes: list[float] = []
    pixel_units: list[str] = []
    labels: list[str] = []
    for tile in ordered_tiles:
        ds, raster = _raster(tile.image_id)
        if not ds.pixel_cal.calibrated:
            raise HTTPException(
                422,
                f"montage-compare: image {tile.image_id} "
                f"('{store.name(tile.image_id)}') has no pixel calibration — "
                f"a common physical scale is undefined for this panel",
            )
        frames.append(raster)
        pixel_sizes.append(ds.pixel_size)
        pixel_units.append(ds.pixel_unit)
        labels.append(tile.label if tile.label else store.name(tile.image_id))

    with value_error_as_422():
        result = montage_physical_scale(
            frames, pixel_sizes, pixel_units, labels=labels,
            cols=req.cols, gap=req.gap, bg=req.bg, font_size=req.font_size,
            bar_color=req.bar_color,
        )

    cal = AxisCal(scale=result.pixel_size, origin=0.0, units=result.pixel_unit)
    derived = DataStruct(
        data=np.ascontiguousarray(result.canvas),
        kind=DataKind.IMAGE,
        axes=(cal, cal),
        metadata={
            "source": "montage-compare",
            "parser": "derived",
            "tile_labels": labels,
            "n_tiles": len(req.tiles),
        },
    )
    name = f"montage-compare({len(req.tiles)})"
    new_id = store.add_derived(derived, name, req.tiles[0].image_id)
    image_meta = ImageMeta.from_datastruct(new_id, name, derived).model_dump()

    return {"image": image_meta, "scale_bar": _scale_bar_dict(result.scale_bar)}
