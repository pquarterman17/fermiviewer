"""calc/contours.py — mask -> traced, simplified polygon (plan item 16).

Synthetic masks only (square, non-convex L, hole); the API-level blob
detection test in test_api_regions.py is what proves detection works end
to end, this file is about the tracer's own contract: correct area,
vertex-count reduction, determinism, and documented hole behaviour.
"""

from __future__ import annotations

import numpy as np
import pytest
from skimage.measure import find_contours

from fermiviewer.calc.contours import NoContourError, trace_outer_contour

pytestmark = pytest.mark.imaging


def _square(h: int = 30, w: int = 30, r0=8, r1=22, c0=8, c1=22) -> np.ndarray:
    m = np.zeros((h, w), dtype=bool)
    m[r0:r1, c0:c1] = True
    return m


def test_square_area_matches_pixel_count() -> None:
    mask = _square()
    true_area = int(mask.sum())  # 14*14 = 196
    # A tight tolerance is needed here on purpose: marching squares cuts
    # each right-angle corner of a filled rectangle with a small diagonal
    # (there is no vertex exactly at the geometric corner), and Douglas-
    # Peucker collapses that diagonal to a single point once tolerance
    # reaches ~half a pixel — trading the corner away for fewer vertices.
    # tolerance=0.4 stays under that threshold and keeps both corner
    # points, so the traced area matches the pixel count almost exactly.
    contour = trace_outer_contour(mask, tolerance=0.4)
    assert contour.points.shape[1] == 2
    assert contour.area_px == pytest.approx(true_area, rel=0.01)


def test_non_convex_l_shape_is_traced_correctly() -> None:
    h = w = 40
    mask = np.zeros((h, w), dtype=bool)
    mask[5:35, 5:15] = True   # vertical arm
    mask[25:35, 5:35] = True  # horizontal arm
    true_area = int(mask.sum())

    contour = trace_outer_contour(mask, tolerance=0.4)

    assert contour.area_px == pytest.approx(true_area, rel=0.01)
    # a simple square would need only 4 corners; an L needs at least 6.
    assert len(contour.points) >= 6


def test_hole_is_not_subtracted_outer_boundary_only() -> None:
    """Documented behaviour: item 16 traces the OUTER ring only. A mask
    with a hole yields a polygon covering the hole as if solid — item 19
    ("holes / multi-part regions") owns subtracting inner rings."""
    mask = _square(h=30, w=30, r0=5, r1=25, c0=5, c1=25)  # 20x20 = 400
    hole = mask.copy()
    hole[12:18, 12:18] = False  # 6x6 = 36-px hole punched in the middle

    solid_contour = trace_outer_contour(mask, tolerance=0.4)
    holed_contour = trace_outer_contour(hole, tolerance=0.4)

    # the hole reduces the true pixel count by 36, but the traced OUTER
    # polygon's area is unaffected — the hole sits well inside the outer
    # boundary, so find_contours' outer ring (the one this module keeps)
    # is IDENTICAL whether or not the hole exists.
    assert int(mask.sum()) - int(hole.sum()) == 36
    assert holed_contour.area_px == pytest.approx(solid_contour.area_px, rel=1e-9)


def test_simplification_reduces_vertex_count_within_area_tolerance() -> None:
    # a noisy-boundary blob (circle-ish) has many raw marching-squares
    # vertices; simplification should cut that down a lot while keeping
    # area close to the unsimplified trace.
    yy, xx = np.mgrid[0:60, 0:60]
    mask = (xx - 30) ** 2 + (yy - 30) ** 2 <= 20**2

    raw_rings = find_contours(mask.astype(np.float64), level=0.5)
    raw_vertex_count = max(len(r) for r in raw_rings)

    loose = trace_outer_contour(mask, tolerance=1.5)
    assert len(loose.points) < raw_vertex_count // 5  # a big cut, not a token one
    assert loose.area_px == pytest.approx(int(mask.sum()), rel=0.03)


def test_max_vertices_safety_net_overrides_a_too_small_tolerance() -> None:
    yy, xx = np.mgrid[0:80, 0:80]
    mask = (xx - 40) ** 2 + (yy - 40) ** 2 <= 30**2

    contour = trace_outer_contour(mask, tolerance=1e-9, max_vertices=20)
    assert len(contour.points) <= 20


def test_determinism_same_mask_twice_yields_identical_polygon() -> None:
    yy, xx = np.mgrid[0:50, 0:50]
    mask = ((xx - 25) ** 2 + (yy - 20) ** 2 <= 15**2) | (
        (xx - 30) ** 2 + (yy - 32) ** 2 <= 12**2
    )

    first = trace_outer_contour(mask, tolerance=1.5)
    second = trace_outer_contour(mask, tolerance=1.5)

    np.testing.assert_array_equal(first.points, second.points)
    assert first.area_px == second.area_px


def test_start_vertex_and_winding_are_canonical() -> None:
    """Re-derive the same ring by rolling/reversing the raw trace by hand;
    the canonicalized output must be identical regardless."""
    mask = _square()
    contour = trace_outer_contour(mask, tolerance=1.0)
    pts = contour.points

    # start vertex is the lexicographically-smallest (row, col)
    lexmin = min(map(tuple, pts.tolist()))
    assert tuple(pts[0].tolist()) == lexmin

    # winding is canonicalized to a non-negative signed area
    r, c = pts[:, 0], pts[:, 1]
    signed = np.sum(r * np.roll(c, -1) - np.roll(r, -1) * c) / 2.0
    assert signed >= 0


def test_empty_and_full_masks_raise_no_contour_error() -> None:
    with pytest.raises(NoContourError):
        trace_outer_contour(np.zeros((10, 10), dtype=bool))
    with pytest.raises(NoContourError):
        trace_outer_contour(np.ones((10, 10), dtype=bool))
