"""Seed-to-polygon region proposal — the composition behind
POST /regions/propose, lifted out of the route (3B, ADR 0005 §1) so the
registered `propose_region` op and the HTTP route call the SAME code
instead of the op re-implementing window/seed maths that used to live in
`routes/regions.py`.

Pipeline (unchanged from the route's original docstring): multi-Otsu
classes the raster, morphology cleans the seed's class up,
connected-component labelling isolates the ONE region overlapping the
seed pixel, and `trace_outer_contour` turns that single-region mask into
a simplified polygon. A `rect` seed additionally crops the search to a
padded local window — faster, and less likely to be dominated by a
large unrelated background class than the whole frame.

Every rejection is a ValueError: the route maps them to 422, the op
surfaces them as-is.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.contours import trace_outer_contour
from fermiviewer.calc.segment import label_components, morph_op, multi_otsu

__all__ = ["ProposedRegion", "propose_region"]

#: Rough rectangle seeds are padded by this fraction of their own size (each
#: side) before cropping, so a region whose true boundary touches the rect
#: the user drew is not sliced off at the crop edge.
RECT_PAD_FRAC = 0.25
MIN_WINDOW_PX = 4


@dataclass(frozen=True)
class ProposedRegion:
    """The proposal: normalized (x, y) points, NOT closed — the exact shape
    of a hand-drawn `polygon` measure (`Measure.pts`), plus its area."""

    points: tuple[tuple[float, float], ...]
    area_px: float
    area_calibrated: float | None
    unit: str


def _window(
    rect: tuple[float, float, float, float] | None, h: int, w: int
) -> tuple[int, int, int, int]:
    """Normalized rect -> padded pixel-space (r0, r1, c0, c1), clamped to
    the raster. Returns the full raster when `rect` is None."""
    if rect is None:
        return 0, h, 0, w
    x0, x1 = sorted((rect[0], rect[2]))
    y0, y1 = sorted((rect[1], rect[3]))
    px = (x1 - x0) * RECT_PAD_FRAC
    py = (y1 - y0) * RECT_PAD_FRAC
    x0, x1 = max(0.0, x0 - px), min(1.0, x1 + px)
    y0, y1 = max(0.0, y0 - py), min(1.0, y1 + py)
    r0, r1 = int(np.floor(y0 * h)), int(np.ceil(y1 * h))
    c0, c1 = int(np.floor(x0 * w)), int(np.ceil(x1 * w))
    r0, c0 = max(0, r0), max(0, c0)
    r1, c1 = min(h, r1), min(w, c1)
    if r1 - r0 < MIN_WINDOW_PX or c1 - c0 < MIN_WINDOW_PX:
        raise ValueError("rect seed is too small to segment")
    return r0, r1, c0, c1


def _seed_point(
    seed: tuple[float, float] | None,
    rect: tuple[float, float, float, float] | None,
) -> tuple[float, float]:
    """Normalized seed (or rect centre) -> (x, y) in [0, 1], validated."""
    if seed is not None:
        x, y = seed
    elif rect is not None:
        x = (rect[0] + rect[2]) / 2.0
        y = (rect[1] + rect[3]) / 2.0
    else:
        raise ValueError("need either seed or rect")
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError("seed must be within the image (normalized 0-1)")
    return x, y


def propose_region(
    raster: np.ndarray,
    *,
    seed: tuple[float, float] | None = None,
    rect: tuple[float, float, float, float] | None = None,
    n_classes: int = 3,
    morph_radius: int = 1,
    tolerance: float = 2.0,
    pixel_size: float = float("nan"),
    unit: str = "px",
) -> ProposedRegion:
    """Propose one region's polygon from a click/box seed on a 2D raster."""
    h, w = raster.shape
    x, y = _seed_point(seed, rect)
    r0, r1, c0, c1 = _window(rect, h, w)

    seed_row = min(int(y * h), h - 1)
    seed_col = min(int(x * w), w - 1)
    if not (r0 <= seed_row < r1 and c0 <= seed_col < c1):
        # only possible when both seed and rect were given and disagree
        raise ValueError("seed point falls outside the rect seed")
    local_row, local_col = seed_row - r0, seed_col - c0
    window = raster[r0:r1, c0:c1]

    otsu = multi_otsu(window, n_classes=n_classes)
    seed_class = int(otsu.label_map[local_row, local_col])
    bw = otsu.label_map == seed_class
    bw = morph_op(bw, operation="close", radius=morph_radius, shape="disk")
    labels, n = label_components(bw, connectivity=8)
    if n == 0:
        raise ValueError("no detectable region at this seed")
    chosen = int(labels[local_row, local_col])
    if chosen == 0:
        raise ValueError("seed does not overlap a detected region after cleanup")
    region_mask = labels == chosen

    contour = trace_outer_contour(region_mask, tolerance=tolerance)
    calibrated = (
        float(contour.area_px * pixel_size * pixel_size) if np.isfinite(pixel_size) else None
    )
    points = tuple(((col + c0) / w, (row + r0) / h) for row, col in contour.points)
    return ProposedRegion(
        points=points,
        area_px=contour.area_px,
        area_calibrated=calibrated,
        unit=unit,
    )
