"""POST /regions/propose — edge auto-detect assist (PROJECT_WORKFLOW_PLAN.md
item 16): segmentation PROPOSES an outline from a seed, the user corrects it.

The proposal is nothing more than a list of normalized (x, y) points — the
same shape the frontend already uses for a hand-drawn `polygon` measure
(store/viewerTypes.ts `Measure.pts`). There is no separate "detected
region" concept: once these points land in `addMeasure`, the region rides
every existing rail (overlay rendering, vertex dragging, the region table,
CSV export, persistence, undo) with zero special-casing.

The window/seed/segmentation pipeline lives in `calc/region_propose.py`
(lifted there for wave A, ADR 0005 §1, so the registered `propose_region`
op and this route run the SAME code); this module is the thin HTTP
adapter — session lookup, calibration, and ValueError → 422.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.calc.region_propose import propose_region
from fermiviewer.datastruct import DataStruct
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


class ProposeRegionRequest(BaseModel):
    image_id: str
    # Normalized (x, y) in [0, 1] — a click point, same convention as
    # store/viewerTypes.ts Measure.pts. Selects WHICH region to propose.
    seed: tuple[float, float] | None = None
    # Normalized (x0, y0, x1, y1) in [0, 1] — a rough box seed. When given
    # without `seed`, its centre is used as the seed point; either way it
    # also localizes the segmentation search (see calc/region_propose.py).
    rect: tuple[float, float, float, float] | None = None
    n_classes: int = 3
    morph_radius: int = 1
    tolerance: float = 2.0


class ProposeRegionResponse(BaseModel):
    # normalized (x, y) pairs, NOT closed (matches Measure.pts) — ready to
    # hand straight to addMeasure(imageId, {kind: "polygon", pts}).
    points: list[tuple[float, float]]
    area_px: float
    area_calibrated: float | None
    unit: str


def _raster(ds: DataStruct) -> np.ndarray:
    try:
        return raster_of(ds)
    except NoRasterError:
        raise HTTPException(400, "1D spectra have no raster to segment") from None


@router.post("/regions/propose")
def propose_region_route(req: ProposeRegionRequest) -> ProposeRegionResponse:
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    raster = _raster(ds)

    # Segmentation params (n_classes, morph_radius, tolerance) are all
    # client-supplied; every stage validates its own args (multi_otsu on
    # n_classes, morph_op on radius/shape), so one catch-all keeps a bad
    # value a clean 422 instead of a 500 no matter which stage rejects it.
    try:
        proposal = propose_region(
            raster,
            seed=req.seed,
            rect=req.rect,
            n_classes=req.n_classes,
            morph_radius=req.morph_radius,
            tolerance=req.tolerance,
            pixel_size=ds.pixel_size,
            unit=ds.pixel_unit or "px",
        )
    except (ValueError, TypeError) as e:  # NoContourError subclasses ValueError
        raise HTTPException(422, str(e)) from None

    return ProposeRegionResponse(
        points=list(proposal.points),
        area_px=proposal.area_px,
        area_calibrated=proposal.area_calibrated,
        unit=proposal.unit,
    )
