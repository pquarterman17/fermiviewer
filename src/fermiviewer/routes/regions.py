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

from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.calc.region_propose import propose_region
from fermiviewer.datastruct import DataStruct
from fermiviewer.project_session import project
from fermiviewer.region_resolve import resolve_region
from fermiviewer.routes._arrays import value_error_as_422
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


class RegionPreviewRequest(BaseModel):
    """What an analysis WOULD read, asked before it reads it."""

    image_id: str = Field(min_length=1)
    #: ``"set_id"`` or ``"set_id/region_id"``. Named `region_ref`, not
    #: `region`, because that is already the wire name for a SYMBOLIC
    #: reference everywhere else it appears — `/measure/roi`, batch steps,
    #: recipe steps — while `region` on the wire means an op's inline
    #: geometry. A third spelling of the same idea is how a caller learns
    #: to guess.
    #:
    #: Exactly one of this and `roi`; both empty previews the whole image,
    #: which is what an unscoped analysis reads and is worth being able to
    #: compare a region against.
    region_ref: str = ""
    #: The frozen ``"r1,c1,r2,c2"`` 1-based inclusive rect string.
    roi: str = ""


class RegionPreviewResponse(BaseModel):
    #: Pixels the analysis will actually read. This IS the area in px^2 —
    #: a pixel is one square pixel — so no separate `area_px` is reported;
    #: two names for one number is how they start to disagree.
    pixel_count: int
    image_pixels: int
    #: `pixel_count / image_pixels`, precomputed because "is this the
    #: scope I meant?" is the question the summary exists to answer and a
    #: raw count answers it only against a number the caller must fetch.
    fraction: float
    #: 1-based inclusive bounding box, clamped to the image.
    rect: tuple[int, int, int, int]
    bbox_pixels: int
    #: Whether the selection is narrower than its bounding box. False for
    #: a plain rectangle, and the signal that `bbox_pixels` overstates the
    #: scope — the honest version of "this region has holes".
    is_exact: bool
    #: Physical area, or ABSENT when the image has no pixel size. Null
    #: rather than the pixel count, because an area that silently changes
    #: units is worse than one that admits it is unknown (ADR 0004).
    area_calibrated: float | None
    #: The LENGTH unit, matching `/regions/propose` — area is in `unit^2`.
    unit: str
    provenance: dict[str, Any]


@router.post("/regions/preview")
def preview_region_route(req: RegionPreviewRequest) -> RegionPreviewResponse:
    """How much a region selects, without running anything over it.

    The roadmap asks for this "before expensive execution", and that is
    the whole design constraint: it resolves the reference exactly as the
    analysis will — same `resolve_region`, same clamping, same image
    binding — and then reports the scope instead of reducing over it. A
    preview computed by a second code path would be a preview of
    something else, which is worse than no preview at all.

    A region selecting no pixels raises out of the resolver rather than
    returning zeros, matching every other consumer: nothing to analyse is
    an answer the caller must handle, not a measurement of zero.
    """
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    raster = _raster(ds)
    height, width = int(raster.shape[0]), int(raster.shape[1])

    with value_error_as_422():
        resolved = resolve_region(
            (height, width),
            region=req.region_ref,
            roi=req.roi,
            sets=project.current().region_sets,
            image_id=req.image_id,
        )

    r1, c1, r2, c2 = resolved.rect
    image_pixels = height * width
    px = ds.pixel_size
    return RegionPreviewResponse(
        pixel_count=resolved.pixel_count,
        image_pixels=image_pixels,
        fraction=resolved.pixel_count / image_pixels,
        rect=(r1, c1, r2, c2),
        bbox_pixels=(r2 - r1 + 1) * (c2 - c1 + 1),
        is_exact=resolved.is_exact,
        area_calibrated=(
            float(resolved.pixel_count) * px * px if np.isfinite(px) else None
        ),
        unit=ds.pixel_unit or "px",
        provenance=resolved.provenance,
    )
