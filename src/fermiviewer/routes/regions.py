"""POST /regions/propose — edge auto-detect assist (PROJECT_WORKFLOW_PLAN.md
item 16): segmentation PROPOSES an outline from a seed, the user corrects it.

The proposal is nothing more than a list of normalized (x, y) points — the
same shape the frontend already uses for a hand-drawn `polygon` measure
(store/viewerTypes.ts `Measure.pts`). There is no separate "detected
region" concept: once these points land in `addMeasure`, the region rides
every existing rail (overlay rendering, vertex dragging, the region table,
CSV export, persistence, undo) with zero special-casing.

Pipeline: multi-Otsu (calc.segment.multi_otsu) classes the raster, morphology
(calc.segment.morph_op) cleans the chosen class up, connected-component
labelling isolates the ONE region overlapping the seed pixel, and
calc.contours.trace_outer_contour turns that single-region mask into a
simplified polygon. A `rect` seed additionally crops the search to a local
window (padded so the traced boundary is never clipped at the crop edge) —
running multi-Otsu over a small local window is both faster and less likely
to be dominated by a large, unrelated background class than running it over
the whole frame.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.contours import trace_outer_contour
from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.calc.segment import label_components, morph_op, multi_otsu
from fermiviewer.datastruct import DataStruct
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")

# Rough rectangle seeds are padded by this fraction of their own size (each
# side) before cropping, so a region whose true boundary touches the rect
# the user drew is not sliced off at the crop edge.
_RECT_PAD_FRAC = 0.25
_MIN_WINDOW_PX = 4


class ProposeRegionRequest(BaseModel):
    image_id: str
    # Normalized (x, y) in [0, 1] — a click point, same convention as
    # store/viewerTypes.ts Measure.pts. Selects WHICH region to propose.
    seed: tuple[float, float] | None = None
    # Normalized (x0, y0, x1, y1) in [0, 1] — a rough box seed. When given
    # without `seed`, its centre is used as the seed point; either way it
    # also localizes the segmentation search (see module docstring).
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


def _window(
    rect: tuple[float, float, float, float] | None, h: int, w: int
) -> tuple[int, int, int, int]:
    """Normalized rect -> padded pixel-space (r0, r1, c0, c1), clamped to
    the raster. Returns the full raster when `rect` is None."""
    if rect is None:
        return 0, h, 0, w
    x0, x1 = sorted((rect[0], rect[2]))
    y0, y1 = sorted((rect[1], rect[3]))
    px = (x1 - x0) * _RECT_PAD_FRAC
    py = (y1 - y0) * _RECT_PAD_FRAC
    x0, x1 = max(0.0, x0 - px), min(1.0, x1 + px)
    y0, y1 = max(0.0, y0 - py), min(1.0, y1 + py)
    r0, r1 = int(np.floor(y0 * h)), int(np.ceil(y1 * h))
    c0, c1 = int(np.floor(x0 * w)), int(np.ceil(x1 * w))
    r0, c0 = max(0, r0), max(0, c0)
    r1, c1 = min(h, r1), min(w, c1)
    if r1 - r0 < _MIN_WINDOW_PX or c1 - c0 < _MIN_WINDOW_PX:
        raise ValueError("rect seed is too small to segment")
    return r0, r1, c0, c1


def _seed_pixel(
    req: ProposeRegionRequest, h: int, w: int
) -> tuple[float, float]:
    """Normalized seed (or rect centre) -> (x, y) in [0, 1], validated."""
    if req.seed is not None:
        x, y = req.seed
    elif req.rect is not None:
        x = (req.rect[0] + req.rect[2]) / 2.0
        y = (req.rect[1] + req.rect[3]) / 2.0
    else:
        raise ValueError("need either seed or rect")
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError("seed must be within the image (normalized 0-1)")
    return x, y


@router.post("/regions/propose")
def propose_region(req: ProposeRegionRequest) -> ProposeRegionResponse:
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    raster = _raster(ds)
    h, w = raster.shape

    try:
        x, y = _seed_pixel(req, h, w)
        r0, r1, c0, c1 = _window(req.rect, h, w)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    seed_row = min(int(y * h), h - 1)
    seed_col = min(int(x * w), w - 1)
    if not (r0 <= seed_row < r1 and c0 <= seed_col < c1):
        # only possible when both seed and rect were given and disagree
        raise HTTPException(422, "seed point falls outside the rect seed")
    local_row, local_col = seed_row - r0, seed_col - c0
    window = raster[r0:r1, c0:c1]

    # Segmentation params (n_classes, morph_radius, tolerance) are all
    # client-supplied; every stage below validates its own args (multi_otsu
    # on n_classes, morph_op on radius/shape), so one catch-all keeps a bad
    # value a clean 422 instead of a 500 no matter which stage rejects it.
    try:
        otsu = multi_otsu(window, n_classes=req.n_classes)
        seed_class = int(otsu.label_map[local_row, local_col])
        bw = otsu.label_map == seed_class
        bw = morph_op(bw, operation="close", radius=req.morph_radius, shape="disk")
        labels, n = label_components(bw, connectivity=8)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e)) from None
    if n == 0:
        raise HTTPException(422, "no detectable region at this seed")
    chosen = int(labels[local_row, local_col])
    if chosen == 0:
        raise HTTPException(
            422, "seed does not overlap a detected region after cleanup"
        )
    region_mask = labels == chosen

    try:
        contour = trace_outer_contour(region_mask, tolerance=req.tolerance)
    except (ValueError, TypeError) as e:  # NoContourError subclasses ValueError
        raise HTTPException(422, str(e)) from None

    px = ds.pixel_size
    unit = ds.pixel_unit or "px"
    calibrated = float(contour.area_px * px * px) if np.isfinite(px) else None

    points = [
        ((col + c0) / w, (row + r0) / h) for row, col in contour.points
    ]
    return ProposeRegionResponse(
        points=points,
        area_px=contour.area_px,
        area_calibrated=calibrated,
        unit=unit,
    )
