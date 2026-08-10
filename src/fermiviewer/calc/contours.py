"""Mask → editable polygon outline (PROJECT_WORKFLOW_PLAN.md item 16).

Converts a boolean region mask into a traced, Douglas-Peucker-simplified
closed polygon outline in (row, col) pixel coordinates — the same space
`routes/regions.py` normalizes to 0-1 before handing the result to the
frontend as an ordinary, editable `polygon` measure. There is no separate
"detected region" concept anywhere in this stack: this module's only job
is mask -> vertex list.

Holes: `trace_outer_contour` traces the OUTER boundary only, by design —
its own callers (routes/regions.py's single-seed "Detect Region" assist)
still get a single ring back, unchanged. If `mask` has a hole (a
background island fully enclosed by foreground), `trace_outer_contour`'s
returned polygon covers the hole as if it were solid, which overestimates
the true area by the hole's area — that remains true and is pinned by
test_hole_is_not_subtracted_outer_boundary_only.

`trace_region_with_holes` is the item-19 follow-through: same single-
connected-foreground-region precondition, but it also traces every OTHER
boundary `find_contours` finds inside that region as a hole and nets its
area out of the total. Nothing currently calls it end to end from the UI —
wiring routes/regions.py's response and the frontend detect-flow
(RegionsCard.tsx) to request and apply holes is a follow-up, not attempted
here; this function is the tested, ready-to-wire computation.

Determinism: the same mask always yields the same polygon — same vertex
order, same start vertex — every call. skimage's `find_contours` /
`approximate_polygon` are themselves deterministic for a fixed input
array, but this module does not rely on that alone: winding direction and
start vertex are canonicalized explicitly (`_canonicalize`), so a future
skimage version that walks contours in a different starting corner or
direction cannot make this module's output — or any test / undo-redo
sequence built on it — flaky.

PURE: numpy + scikit-image only. No fastapi/pydantic/starlette/routes
imports — tests/test_repo_integrity.py enforces this for every module
under calc/.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from skimage.measure import approximate_polygon, find_contours

__all__ = [
    "Contour",
    "NoContourError",
    "trace_outer_contour",
    "trace_region_with_holes",
]


class NoContourError(ValueError):
    """Raised when `mask` has no traceable boundary (empty or fully-filled —
    marching squares needs at least one foreground/background transition)."""


@dataclass(frozen=True)
class Contour:
    """A traced, simplified, closed polygon outline, with optional holes.

    `points` is (N, 2) float64, one row per vertex as (row, col) pixel
    coordinates. The ring is closed IMPLICITLY — the last point does not
    repeat the first, matching the frontend's `Measure.pts` convention
    (closed by returning to vertex 0).

    `holes` is a tuple of the same (N_i, 2) open-ring arrays, one per
    enclosed hole (item 19). Empty for `trace_outer_contour` (which never
    populates it) and for a `trace_region_with_holes` call on a mask with
    no holes — both cases mean "no holes", not "not computed".

    `area_px` is always the NET area — outer minus every hole — so for
    `trace_outer_contour` (holes always empty) it is simply the outer
    ring's area, unchanged from before this field existed.
    """

    points: np.ndarray
    area_px: float
    holes: tuple[np.ndarray, ...] = ()


def _shoelace_signed(points: np.ndarray) -> float:
    """Signed area of a closed ring given as (row, col) pairs that do NOT
    repeat the first point. Sign encodes winding direction; magnitude is
    the enclosed area in px²."""
    r = points[:, 0]
    c = points[:, 1]
    return float(np.sum(r * np.roll(c, -1) - np.roll(r, -1) * c)) / 2.0


def _canonicalize(points: np.ndarray) -> np.ndarray:
    """Fix winding direction (signed area >= 0) and start vertex (the
    lexicographically-smallest (row, col)) so the same ring always
    serializes identically regardless of which direction or corner the
    tracer happened to start from."""
    if _shoelace_signed(points) < 0:
        points = points[::-1]
    start = int(np.lexsort((points[:, 1], points[:, 0]))[0])
    return np.asarray(np.roll(points, -start, axis=0), dtype=np.float64)


def _largest_ring(open_rings: list[np.ndarray]) -> np.ndarray:
    """The OUTER boundary is the ring enclosing the largest area — a
    hole's inner ring is always smaller and is discarded here (see the
    module docstring). `open_rings` entries must NOT repeat their first
    point (see `_shoelace_signed`)."""
    return max(open_rings, key=lambda r: abs(_shoelace_signed(r)))


def _simplify(ring: np.ndarray, tolerance: float, max_vertices: int) -> np.ndarray:
    """Douglas-Peucker simplify, escalating `tolerance` if it still leaves
    an unusable (> max_vertices) outline. Guarantees the "manageable vertex
    count" requirement holds even if a caller passes a too-small tolerance —
    a 5000-vertex outline defeats the entire point of hand-correction.

    Escalation starts from a floor scaled to the RING's own extent, not
    from `tolerance` itself: repeatedly doubling a near-zero seed (e.g. a
    caller-passed tolerance of 1e-9) would still be near-zero after a
    handful of doublings and never actually shrink the vertex count.
    """
    closed = np.vstack([ring, ring[:1]])
    tol = float(tolerance)
    simplified = approximate_polygon(closed, tolerance=tol)[:-1]
    if len(simplified) > max_vertices:
        span = max(float(np.ptp(ring[:, 0])), float(np.ptp(ring[:, 1])), 1.0)
        step = max(tol, span * 0.01)
        for _ in range(16):
            simplified = approximate_polygon(closed, tolerance=step)[:-1]
            if len(simplified) <= max_vertices:
                break
            step *= 2.0
    if len(simplified) < 3:
        # Tolerance collapsed the ring to a line/point — fall back to the
        # un-simplified ring rather than return an unusable degenerate shape.
        return ring
    return np.asarray(simplified, dtype=np.float64)


def trace_outer_contour(
    mask: np.ndarray,
    *,
    tolerance: float = 2.0,
    max_vertices: int = 200,
) -> Contour:
    """Trace the outer boundary of a single-region boolean mask.

    Parameters
    ----------
    mask
        2-D boolean (or 0/1) array. Exactly one connected foreground
        region is expected — callers isolate a single labelled region
        (e.g. `mask = labels == chosen_label`) before calling this.
    tolerance
        Douglas-Peucker distance tolerance in pixels
        (`skimage.measure.approximate_polygon`). Larger = fewer vertices.
        This is the primary "manageable vertex count" knob.
    max_vertices
        Safety net: if `tolerance` still leaves more vertices than this,
        tolerance is escalated (doubled, up to 8 times) until the count
        fits, so an accidentally-tiny tolerance can never produce an
        outline nobody could hand-correct.

    Returns
    -------
    Contour
        `points` in (row, col) pixel coordinates, `area_px` the enclosed
        area of the SIMPLIFIED polygon (not the raw pixel count — see
        the module docstring re: holes).

    Raises
    ------
    NoContourError
        `mask` has no boundary to trace (all-background or all-foreground
        — marching squares needs a 0/1 transition somewhere).
    """
    bw = np.asarray(mask) > 0
    if not bw.any() or bw.all():
        raise NoContourError(
            "mask must have both foreground and background pixels"
        )

    rings = find_contours(bw.astype(np.float64), level=0.5)
    if not rings:
        raise NoContourError("no boundary found in mask")

    # find_contours repeats the first point to close the ring; drop it so
    # every ring in `rings` (and every helper below) uses the open-ring
    # convention consistently.
    open_rings = [r[:-1] for r in rings]
    ring = _largest_ring(open_rings)

    simplified = _simplify(ring, tolerance=tolerance, max_vertices=max_vertices)
    canon = _canonicalize(simplified)
    return Contour(points=canon, area_px=abs(_shoelace_signed(canon)))


def trace_region_with_holes(
    mask: np.ndarray,
    *,
    tolerance: float = 2.0,
    max_vertices: int = 200,
) -> Contour:
    """Trace a single-region mask's outer boundary AND every enclosed hole
    (plan item 19 — the follow-through `trace_outer_contour` explicitly
    defers; see that function's docstring and the module docstring).

    Same single-connected-foreground-region precondition as
    `trace_outer_contour`: the largest traced ring is taken as the outer
    boundary, and every OTHER ring `find_contours` finds is treated as a
    hole. That holds exactly as long as the precondition does — an
    unrelated second foreground blob would be mistaken for a hole the same
    way it would confuse `trace_outer_contour`'s single-ring assumption.

    `area_px` is the NET area: the outer ring's area minus every hole
    ring's area, each taken as `abs(signed shoelace area)` on BOTH sides
    before subtracting — never a raw signed-area sum. Marching squares can
    trace a hole's boundary in either winding direction depending on mask
    geometry; summing signed areas would only subtract correctly for one
    of the two directions and silently ADD the hole's area for the other.
    Taking the absolute value of each ring first makes the subtraction
    correct regardless of which way either ring happens to wind, and the
    net area is clamped to >= 0 (a degenerate/oversized "hole" can never
    make the reported area negative).

    Parameters, Returns and Raises are as `trace_outer_contour`; the
    returned `Contour.holes` tuple holds one canonicalized ring per hole
    (empty when the mask has none — identical to `trace_outer_contour` in
    that case, other than the always-populated `holes` field).
    """
    bw = np.asarray(mask) > 0
    if not bw.any() or bw.all():
        raise NoContourError(
            "mask must have both foreground and background pixels"
        )

    rings = find_contours(bw.astype(np.float64), level=0.5)
    if not rings:
        raise NoContourError("no boundary found in mask")

    open_rings = [r[:-1] for r in rings]
    outer_ring = _largest_ring(open_rings)
    hole_rings = [r for r in open_rings if r is not outer_ring]

    outer_canon = _canonicalize(
        _simplify(outer_ring, tolerance=tolerance, max_vertices=max_vertices)
    )
    outer_area = abs(_shoelace_signed(outer_canon))

    holes: list[np.ndarray] = []
    hole_area_total = 0.0
    for hole in hole_rings:
        hole_canon = _canonicalize(
            _simplify(hole, tolerance=tolerance, max_vertices=max_vertices)
        )
        holes.append(hole_canon)
        hole_area_total += abs(_shoelace_signed(hole_canon))

    net_area = max(0.0, outer_area - hole_area_total)
    return Contour(points=outer_canon, area_px=net_area, holes=tuple(holes))
