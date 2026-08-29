"""The canonical region/mask contract (roadmap item 4A):
`fermiviewer.calc.regions`.

The contract exists because this repo has nine disagreeing ways to name a
region. So the tests that matter are the ones pinning the choices that
make it ONE thing: that two spellings of the same square agree, that an
inclusive radius means what the rest of the repo means by it, and that
holes/exclusions/disjoint parts compose in a stated order.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.regions import (
    Part,
    Region,
    bounding_box,
    ellipse,
    polygon,
    rasterize,
    rect,
    to_rect_roi,
)

SHAPE = (9, 9)


def one(shape, **kw) -> Region:
    """A region of a single included shape."""
    return Region(id="r1", parts=(Part(shape),), **kw)


# ── the equalities the contract is FOR ───────────────────────────────


def test_a_rect_and_its_corner_polygon_are_the_same_pixels() -> None:
    """The reason bounds are inclusive. If these differed by a row and a
    column, every caller converting between the two spellings would
    silently move the region — the exact bug this contract prevents."""
    as_rect = rasterize(one(rect(1, 1, 3, 3)), SHAPE)
    as_poly = rasterize(
        one(polygon([(1, 1), (1, 3), (3, 3), (3, 1)])), SHAPE
    )
    assert np.array_equal(as_rect, as_poly)
    assert as_rect.sum() == 9        # 3x3 inclusive, not 2x2 half-open


def test_an_ellipse_radius_is_inclusive_like_every_other_radius_here() -> None:
    """`skimage.draw.disk` would give 1 px for r=1 and 9 px for r=2, since
    it tests distance < r. Every radius convention in this repo is <= —
    diffraction's ROI, the FFT mask, the 4D aperture. A region of radius 1
    must therefore cover the centre pixel AND its four neighbours."""
    mask = rasterize(one(ellipse(3, 3, 5, 5)), SHAPE)   # centre (4,4), semi 1
    assert mask.sum() == 5                               # plus-shape, not 1 px
    assert mask[4, 4] and mask[3, 4] and mask[5, 4]
    assert mask[4, 3] and mask[4, 5]
    assert not mask[3, 3]                                # corners are outside


def test_a_square_ellipse_is_a_circle_and_stays_inside_its_bounds() -> None:
    mask = rasterize(one(ellipse(1, 1, 7, 7)), SHAPE)
    rows = np.flatnonzero(mask.any(axis=1))
    assert (rows[0], rows[-1]) == (1, 7)
    assert not mask[0].any() and not mask[8].any()


# ── composition: holes, exclusions, disjoint ─────────────────────────


def test_a_hole_is_subtracted_from_its_own_shape() -> None:
    solid = rasterize(one(rect(1, 1, 7, 7)), SHAPE)
    holed = rasterize(
        one(rect(1, 1, 7, 7, holes=[[(3, 3), (3, 5), (5, 5), (5, 3)]])), SHAPE
    )
    assert solid.sum() == 49
    assert holed.sum() == 49 - 9
    assert not holed[4, 4] and holed[1, 1]


def test_an_exclusion_carves_the_whole_region_not_one_shape() -> None:
    region = Region(
        id="r1",
        parts=(Part(rect(1, 1, 7, 7)), Part(rect(3, 3, 5, 5), mode="exclude")),
    )
    mask = rasterize(region, SHAPE)
    assert mask.sum() == 49 - 9
    assert not mask[4, 4]


def test_two_includes_make_one_disjoint_region() -> None:
    """A specimen in two pieces is one selection, not two."""
    region = Region(
        id="r1", parts=(Part(rect(1, 1, 2, 2)), Part(rect(6, 6, 7, 7)))
    )
    mask = rasterize(region, SHAPE)
    assert mask.sum() == 8
    assert mask[1, 1] and mask[7, 7] and not mask[4, 4]


def test_part_order_decides_the_answer() -> None:
    """Documented as significant, so it needs a test that would fail if
    parts were ever treated as an unordered set of layers."""
    a, b = rect(1, 1, 5, 5), rect(3, 3, 7, 7)
    minus = rasterize(Region(id="x", parts=(Part(a), Part(b, mode="exclude"))), SHAPE)
    back = rasterize(
        Region(id="x", parts=(Part(a), Part(b, mode="exclude"), Part(b))), SHAPE
    )
    assert minus.sum() < back.sum()
    assert not minus[4, 4] and back[4, 4]


# ── bounding boxes: the migration seam ───────────────────────────────


def test_the_bbox_follows_the_mask_not_the_outlines() -> None:
    """Derived from the rasterized mask, so trimming the region's edge
    shrinks the box. Reading the outlines alone would miss that and hand
    a migrating caller a box wider than the pixels it selected."""
    region = Region(
        id="r1",
        parts=(Part(rect(1, 1, 7, 7)), Part(rect(1, 1, 7, 3), mode="exclude")),
    )
    assert bounding_box(region, SHAPE) == (1, 4, 7, 7)


def test_to_rect_roi_hands_back_the_repos_1_based_inclusive_rect() -> None:
    """`calc.roi.RectRoi` is 1-based inclusive; every bbox analysis here
    speaks it. Off by one in this conversion would shift every migrated
    caller by a pixel."""
    region = one(rect(0, 0, 2, 2))
    assert bounding_box(region, SHAPE) == (0, 0, 2, 2)
    assert to_rect_roi(region, SHAPE) == (1, 1, 3, 3)


def test_an_empty_selection_has_no_bounding_box() -> None:
    """Returning the whole image would silently widen every caller that
    migrates through here."""
    region = Region(
        id="r1",
        parts=(Part(rect(2, 2, 4, 4)), Part(rect(0, 0, 8, 8), mode="exclude")),
    )
    assert not rasterize(region, SHAPE).any()
    with pytest.raises(ValueError, match="no pixels"):
        bounding_box(region, SHAPE)


# ── edges and clamping ───────────────────────────────────────────────


def test_a_region_over_the_edge_masks_the_part_that_exists() -> None:
    """Clamping, not raising — every ROI helper in this repo already
    clamps, and a half-visible region is a normal thing to draw."""
    mask = rasterize(one(rect(-4, -4, 2, 2)), SHAPE)
    assert mask[0, 0] and mask[2, 2]
    assert not mask[3, 3]


def test_corners_may_be_given_in_any_order() -> None:
    assert np.array_equal(
        rasterize(one(rect(3, 3, 1, 1)), SHAPE),
        rasterize(one(rect(1, 1, 3, 3)), SHAPE),
    )


def test_a_flat_ellipse_is_a_line_of_pixels_not_an_error() -> None:
    """A zero-height drag is something a user can really do."""
    mask = rasterize(one(ellipse(4, 1, 4, 5)), SHAPE)
    assert mask.any()
    assert np.flatnonzero(mask.any(axis=1)).tolist() == [4]


# ── validation ───────────────────────────────────────────────────────


def test_a_region_cannot_open_with_an_exclusion() -> None:
    with pytest.raises(ValueError, match="subtracts from nothing"):
        Region(id="r1", parts=(Part(rect(1, 1, 3, 3), mode="exclude"),))


def test_a_region_needs_a_part_and_a_polygon_needs_vertices() -> None:
    with pytest.raises(ValueError, match="at least one part"):
        Region(id="r1", parts=())
    with pytest.raises(ValueError, match="at least 3 vertices"):
        polygon([(1, 1), (2, 2)])


def test_unknown_kinds_and_modes_are_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="region mode"):
        Part(rect(1, 1, 3, 3), mode="maybe")
    with pytest.raises(ValueError, match="must be \\(N, 2\\)"):
        polygon([1, 2, 3])
