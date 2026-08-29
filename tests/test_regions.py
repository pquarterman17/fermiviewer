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

from fermiviewer.calc.profile_stats import roi_stats
from fermiviewer.calc.regions import (
    Part,
    Region,
    bounding_box,
    circle,
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


# ── the two round conventions, which are not the same set ────────────

# Odd and even extents, square and oblong, degenerate and offset. Even
# extents are the ones that matter: they are where a footprint semi-axis
# and an endpoint-centre one diverge most, and (0, 0, 1, 1) is the 2x2
# drag that selected NOTHING before this was pinned.
ELLIPSE_BOUNDS = [
    (0, 0, 1, 1),      # 2x2 — a short drag
    (0, 0, 2, 2),      # 3x3
    (1, 1, 4, 4),      # 4x4
    (0, 0, 4, 4),      # 5x5
    (2, 2, 7, 7),      # 6x6, offset from the origin
    (1, 1, 2, 5),      # oblong, even rows
    (2, 2, 6, 5),      # oblong, odd rows
    (3, 3, 3, 3),      # a single pixel
    (4, 1, 4, 6),      # zero height — a flat drag
]


@pytest.mark.parametrize("bounds", ELLIPSE_BOUNDS)
def test_an_ellipse_selects_exactly_what_roi_stats_selects(bounds) -> None:
    """`ellipse` takes BOUNDS, and the repo already has an inscribed
    ellipse over bounds: `roi_stats(shape="ellipse")`. Migrating an
    existing elliptical ROI through this contract must not change which
    pixels an analysis reads, so the two are pinned pixel-for-pixel — over
    even extents as well as odd, since that is where a semi-axis taken
    between endpoint CENTRES diverges from one taken over the pixels'
    FOOTPRINT (and where a 2x2 drag came out empty).

    `n_pixels` alone would pass for any mask of the right size; comparing
    the mean of an all-distinct image pins the actual selection.
    """
    r0, c0, r1, c1 = bounds
    image = np.arange(SHAPE[0] * SHAPE[1], dtype=np.float64).reshape(SHAPE)
    mask = rasterize(one(ellipse(r0, c0, r1, c1)), SHAPE)
    # roi_stats is 1-based inclusive; this contract is 0-based inclusive.
    stats = roi_stats(image, r0 + 1, c0 + 1, r1 + 1, c1 + 1, shape="ellipse")

    assert mask.sum() == stats["n_pixels"]
    assert image[mask].mean() == pytest.approx(stats["mean"])


def test_a_two_by_two_drag_is_four_pixels_not_an_empty_region() -> None:
    """Called out on its own because the failure mode was silent: with a
    semi-axis of 0.5 all four pixel centres sit outside the ellipse, so an
    ordinary short drag selected nothing — and an empty region has no
    bounding box, so the caller downstream raised instead."""
    mask = rasterize(one(ellipse(0, 0, 1, 1)), SHAPE)
    assert mask.sum() == 4
    assert bounding_box(one(ellipse(0, 0, 1, 1)), SHAPE) == (0, 0, 1, 1)


def test_a_circle_radius_is_inclusive_like_every_other_radius_here() -> None:
    """`skimage.draw.disk` would give 1 px for r=1 and 9 px for r=2, since
    it tests distance < r. Every radius convention in this repo is <= —
    diffraction's ROI, the FFT mask, the 4D aperture. A circle of radius 1
    must therefore cover the centre pixel AND its four neighbours."""
    mask = rasterize(one(circle(4, 4, 1)), SHAPE)
    assert mask.sum() == 5                               # plus-shape, not 1 px
    assert mask[4, 4] and mask[3, 4] and mask[5, 4]
    assert mask[4, 3] and mask[4, 5]
    assert not mask[3, 3]                                # corners are outside


@pytest.mark.parametrize(
    ("radius", "expected"),
    [(0, 1), (0.4, 1), (0.5, 1), (1, 5), (1.5, 9), (2, 13)],
)
def test_a_circle_is_the_pixels_within_the_radius(radius, expected) -> None:
    """The `dist <= r` set, counted directly — `disk` would give 1, 1, 1,
    1, 5 and 9 for these, one step behind at every radius."""
    mask = rasterize(one(circle(4, 4, radius)), SHAPE)
    rows, cols = np.nonzero(mask)
    assert np.all((rows - 4) ** 2 + (cols - 4) ** 2 <= radius**2 + 1e-9)
    assert mask.sum() == expected


def test_a_circle_is_not_the_ellipse_over_its_square_bounds() -> None:
    """The two conventions are kept apart on purpose. If `circle(c, r)`
    were spelled `ellipse(cr-r, cc-r, cr+r, cc+r)`, the footprint would add
    half a pixel to the semi-axis and pull in a ring the radius excludes —
    which is how a converted diffraction ROI would quietly grow."""
    as_circle = rasterize(one(circle(4, 4, 2)), SHAPE)
    as_ellipse = rasterize(one(ellipse(2, 2, 6, 6)), SHAPE)
    assert as_circle.sum() == 13
    assert as_ellipse.sum() == 21
    assert np.all(as_ellipse[as_circle])                 # strictly contained


def test_a_negative_radius_is_rejected() -> None:
    with pytest.raises(ValueError, match="radius >= 0"):
        circle(4, 4, -1)


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
