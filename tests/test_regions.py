"""The canonical region/mask contract (roadmap item 4A):
`fermiviewer.calc.regions`.

The contract exists because this repo has nine disagreeing ways to name a
region. So the tests that matter are the ones pinning the choices that
make it ONE thing: that a rectangle covers the pixels its inclusive
bounds name, that a radius means what the rest of the repo means by it,
and that holes/exclusions/disjoint parts compose in a stated order.

## Ground truth comes from outside the module under test

Review caught two defects here that the first round of tests could not
have caught, both the same mistake: the expected values were derived from
the same assumption the implementation made, so they could only confirm
it. A hand-counted "5 px" for a circle of radius 1, and integer centres
throughout, agreed with a representation that widened every sub-half-pixel
radius on a fractional centre.

So expectations here are computed independently wherever one can be:

* `inclusive_box` builds an axis-aligned mask straight from the definition
  of inclusive bounds, never through the rasterizer under test;
* an ellipse over bounds is compared against `profile_stats.roi_stats`,
  the inscribed-ellipse ROI this contract claims parity with;
* a circle is compared against an explicit `dist <= r` grid AND against
  `fourd.geometry.aperture_mask` and `diffraction.apply_roi`, the repo
  functions whose convention it claims to share.

Where a literal number is unavoidable it is a fact about the pixel grid
("a 2x2 drag is 4 pixels"), not a restatement of a formula in the source.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.diffraction import apply_roi
from fermiviewer.calc.fourd.geometry import aperture_mask
from fermiviewer.calc.profile_stats import roi_stats
from fermiviewer.calc.region_mask import bounding_box, rasterize, to_rect_roi
from fermiviewer.calc.regions import (
    Part,
    Region,
    Shape,
    circle,
    ellipse,
    polygon,
    rect,
)

SHAPE = (9, 9)


def one(shape, **kw) -> Region:
    """A region of a single included shape."""
    return Region(id="r1", parts=(Part(shape),), **kw)


def inclusive_box(r0, c0, r1, c1) -> np.ndarray:
    """Ground truth for an axis-aligned inclusive rectangle.

    Built from the DEFINITION — a pixel is in when its `(row, col)` falls
    within the bounds on both axes, endpoints included — rather than
    through `polygon2mask`, so it is independent of the code it checks.
    Clamping falls out for free: the grid only spans the image, so bounds
    reaching off the edge simply contribute nothing there.
    """
    rows, cols = np.mgrid[0 : SHAPE[0], 0 : SHAPE[1]]
    return (rows >= r0) & (rows <= r1) & (cols >= c0) & (cols <= c1)


def distance_grid(centre_row, centre_col) -> np.ndarray:
    """Euclidean distance from every pixel centre to a point."""
    rows, cols = np.mgrid[0 : SHAPE[0], 0 : SHAPE[1]]
    return np.hypot(rows - centre_row, cols - centre_col)


# ── the equalities the contract is FOR ───────────────────────────────


RECTS = [
    (1, 1, 3, 3),        # odd extent
    (0, 0, 1, 1),        # even extent, at the origin
    (2, 3, 6, 4),        # oblong
    (4, 4, 4, 4),        # a single pixel
    (3, 1, 3, 7),        # ONE PIXEL TALL — a single row of pixels
    (1, 5, 7, 5),        # ONE PIXEL WIDE — a single column
    (0, 0, 0, 8),        # one pixel tall, against the top edge
    (-4, -4, 2, 2),      # over the top-left edge
    (6, 6, 20, 20),      # over the bottom-right edge
    (-3, -3, -1, -1),    # entirely off the image
]


@pytest.mark.parametrize("bounds", RECTS)
def test_a_rect_covers_exactly_the_pixels_its_bounds_name(bounds) -> None:
    """Against `inclusive_box`, which is built from the definition rather
    than from the rasterizer — so a half-open rect, an off-by-one, or a
    change in how `polygon2mask` treats an edge all show up here.

    The off-edge cases are in the same sweep on purpose: clamping is a
    property of the same rule ("the pixels within the bounds that exist"),
    not a separate behaviour needing separate expectations.
    """
    assert np.array_equal(rasterize(one(rect(*bounds)), SHAPE), inclusive_box(*bounds))


def test_a_rect_and_its_corner_polygon_are_the_same_pixels() -> None:
    """The equality the inclusive convention is FOR, and it is now a real
    test rather than a tautology: `rect` no longer routes through its
    corner polygon, so the two spellings agree because both are correct,
    not because they share an implementation.

    They were made to share one precisely so they could not drift — and
    that is what broke a one-pixel-wide rectangle, since a rect can be
    degenerate and a ring cannot. See the pair of tests below.
    """
    assert np.array_equal(
        rasterize(one(rect(1, 1, 3, 3)), SHAPE),
        rasterize(one(polygon([(1, 1), (1, 3), (3, 3), (3, 1)])), SHAPE),
    )


def test_a_one_pixel_wide_rect_is_a_line_of_pixels_not_two_corners() -> None:
    """The defect this pair exists to prevent, called out on its own.

    Rasterizing a rect through its corner polygon made a rect with one
    degenerate axis a ZERO-AREA ring, and a ring enclosing nothing gives
    back only its vertices — so a single column of pixels came out as its
    two endpoints. Silently, and with a bounding box that still looked
    right, because those two corners span exactly the box the caller
    asked for. A single-column spectrum ROI would have summed 2 pixels
    instead of 23.
    """
    column = rasterize(one(rect(1, 5, 7, 5)), SHAPE)
    assert column.sum() == 7
    assert np.array_equal(column, inclusive_box(1, 5, 7, 5))

    row = rasterize(one(rect(3, 1, 3, 7)), SHAPE)
    assert row.sum() == 7
    assert np.array_equal(row, inclusive_box(3, 1, 3, 7))

    # the bounding box was never the tell: it is right either way
    assert bounding_box(one(rect(1, 5, 7, 5)), SHAPE) == (1, 5, 7, 5)


def test_a_degenerate_ring_returns_only_its_vertices() -> None:
    """Why a rect must not BE a polygon, measured rather than asserted.

    A zero-area ring comes back as exactly its vertex pixels — not the
    line of pixels its edges pass through, and not nothing.
    `grid_points_in_poly` labels a vertex (2) but finds no edge (3) when
    the polygon encloses no area, so three collinear points give three
    pixels and four give two.

    That is an upstream artifact, not a designed answer: it is neither of
    the two defensible ones. It is pinned here so the behaviour is known
    rather than discovered later, and it is exactly why routing `rect`
    through this path made a one-pixel-wide rectangle return its corners.
    A rect is a pair of BOUNDS and can be degenerate; a ring cannot.

    Left as-is deliberately — a collinear lasso is a strange input, and
    redesigning polygon semantics does not belong in a fix for a rect.
    """
    four = rasterize(one(polygon([(3, 1), (3, 7), (3, 7), (3, 1)])), SHAPE)
    assert [tuple(p) for p in np.argwhere(four)] == [(3, 1), (3, 7)]

    three = rasterize(one(polygon([(3, 1), (3, 4), (3, 7)])), SHAPE)
    assert [tuple(p) for p in np.argwhere(three)] == [(3, 1), (3, 4), (3, 7)]

    # the rect spelling of that same line is the whole line
    assert rasterize(one(rect(3, 1, 3, 7)), SHAPE).sum() == 7


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
    (1, 1, 7, 7),      # 7x7, nearly the whole grid
    (0, 3, 8, 4),      # tall and narrow
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
    image = np.arange(SHAPE[0] * SHAPE[1], dtype=np.float64).reshape(SHAPE)
    assert mask.sum() == roi_stats(image, 1, 1, 2, 2, shape="ellipse")["n_pixels"]
    assert mask.sum() == 4                    # all four, which is the whole 2x2
    assert bounding_box(one(ellipse(0, 0, 1, 1)), SHAPE) == (0, 0, 1, 1)


@pytest.mark.parametrize("centre", [(4.0, 4.0), (4.2, 4.2), (4.5, 3.5), (3.7, 5.1)])
@pytest.mark.parametrize("radius", [0, 0.4, 1, 2, 3.3])
def test_a_circle_is_the_same_mask_as_the_4d_aperture(centre, radius) -> None:
    """The docstring claims a region of radius `r` covers the same pixels
    as the existing radius ROIs. That claim was never checked against any
    of them — it was checked against numbers I derived the same way the
    code did, which is how a representation that widened small radii got
    through. `aperture_mask` produces a boolean mask directly, so the
    claim can simply be asserted against the real thing.
    """
    mask = rasterize(one(circle(*centre, radius)), SHAPE)
    assert np.array_equal(mask, aperture_mask(SHAPE, centre, 0.0, radius))


@pytest.mark.parametrize("radius", [1, 2, 3])
def test_a_circle_keeps_what_the_diffraction_roi_keeps(radius) -> None:
    """The other radius consumer, and the one item 4C has to migrate.
    `apply_roi` zeroes pixels outside the circle instead of returning a
    mask, so the kept set is recovered by cropping an all-ones image —
    still its selection rule, not a restatement of ours.
    """
    ones = np.ones(SHAPE, dtype=np.float64)
    patch, (r0, c0) = apply_roi(ones, {"kind": "circle", "cr": 4, "cc": 4,
                                       "radius": radius})
    kept = np.zeros(SHAPE, dtype=bool)
    kept[r0 : r0 + patch.shape[0], c0 : c0 + patch.shape[1]] = patch > 0

    assert np.array_equal(rasterize(one(circle(4, 4, radius)), SHAPE), kept)


def test_a_circle_is_not_skimage_draw_disk() -> None:
    """The disagreement the module docstring rests on, asserted rather
    than described: `disk` tests `dist < r`, so it is one ring behind at
    every radius and would silently shrink a migrated ROI."""
    from skimage.draw import disk

    for radius in (1, 2, 3):
        theirs = np.zeros(SHAPE, dtype=bool)
        theirs[disk((4, 4), radius, shape=SHAPE)] = True
        ours = rasterize(one(circle(4, 4, radius)), SHAPE)
        assert not np.array_equal(ours, theirs)
        assert np.all(ours[theirs])              # strictly larger, not different


@pytest.mark.parametrize("centre", [(4.0, 4.0), (4.2, 4.2), (4.5, 3.5), (3.7, 5.1)])
@pytest.mark.parametrize("radius", [0, 0.1, 0.49, 0.5, 1, 1.5, 2, 2.7])
def test_a_circle_is_exactly_the_distance_grid(centre, radius) -> None:
    """Compared against an explicit `dist <= r` grid rather than a hand
    counted number, over FRACTIONAL centres and radii including 0 — fitted
    diffraction centres are fractional, so integer-centre cases alone
    cannot see a representation that widens a small radius.

    An earlier draft stored a circle as ellipse bounds inset by half a
    pixel. That reproduces `dist <= r` from 0.5 up and then fails below
    it: the inset goes negative, clamping it to zero rounds the region
    outwards, and `circle(4.2, 4.2, 0)` selected the pixel 0.283 px away
    when the exact set is empty.
    """
    cr, cc = centre
    rows, cols = np.mgrid[0 : SHAPE[0], 0 : SHAPE[1]]
    expected = np.hypot(rows - cr, cols - cc) <= radius
    assert np.array_equal(rasterize(one(circle(cr, cc, radius)), SHAPE), expected)


@pytest.mark.parametrize("nudge", [-1e-9, 0.0, 1e-9])
def test_the_radius_is_used_exactly_with_no_tolerance(nudge) -> None:
    """Pixel (4, 6) lies at distance exactly 2 from (4, 4), so a radius a
    hair under 2 must drop it and a hair over must keep it.

    Worth its own case because the sweeps above cannot see this: a radius
    perturbed by less than the gap between neighbouring pixel distances
    changes no mask anywhere, so an epsilon slipped into the comparison —
    or a radius quietly padded to be "safe" — passes every one of them.
    Only a radius sitting on an exact pixel distance discriminates.

    A circle is the only kind where this test exists to be written. An
    ellipse's footprint semi-axis is a half-integer when its extent is
    even and an integer when it is odd, and the pixel offsets are the
    other one of the two, so an ellipse boundary always falls BETWEEN
    pixel centres and never lands on one.
    """
    mask = rasterize(one(circle(4, 4, 2.0 + nudge)), SHAPE)
    assert bool(mask[4, 6]) is (nudge >= 0)
    assert np.array_equal(mask, distance_grid(4, 4) <= 2.0 + nudge)
    assert np.array_equal(mask, aperture_mask(SHAPE, (4.0, 4.0), 0.0, 2.0 + nudge))


def test_a_sub_pixel_circle_off_centre_selects_nothing() -> None:
    """Called out on its own because it is the case the old encoding got
    wrong, and because "radius 0 is one pixel" is only true when the
    centre sits exactly on a pixel centre."""
    assert rasterize(one(circle(4.2, 4.2, 0)), SHAPE).sum() == 0
    assert rasterize(one(circle(4.2, 4.2, 0.1)), SHAPE).sum() == 0
    assert rasterize(one(circle(4.0, 4.0, 0)), SHAPE).sum() == 1   # on-centre


def test_a_circle_is_not_the_ellipse_over_its_square_bounds() -> None:
    """The two conventions are kept apart on purpose. If `circle(c, r)`
    were spelled `ellipse(cr-r, cc-r, cr+r, cc+r)`, the footprint would add
    half a pixel to the semi-axis and pull in a ring the radius excludes —
    which is how a converted diffraction ROI would quietly grow."""
    as_circle = rasterize(one(circle(4, 4, 2)), SHAPE)
    as_ellipse = rasterize(one(ellipse(2, 2, 6, 6)), SHAPE)
    image = np.arange(SHAPE[0] * SHAPE[1], dtype=np.float64).reshape(SHAPE)

    assert np.array_equal(as_circle, distance_grid(4, 4) <= 2)
    assert as_ellipse.sum() == roi_stats(image, 3, 3, 7, 7, shape="ellipse")[
        "n_pixels"
    ]
    assert as_circle.sum() < as_ellipse.sum()
    assert np.all(as_ellipse[as_circle])                 # strictly contained


def test_a_negative_radius_is_rejected() -> None:
    with pytest.raises(ValueError, match="radius >= 0"):
        circle(4, 4, -1)
    with pytest.raises(ValueError, match="radius >= 0"):
        circle(4, 4, float("nan"))


def test_a_square_ellipse_is_a_circle_and_stays_inside_its_bounds() -> None:
    mask = rasterize(one(ellipse(1, 1, 7, 7)), SHAPE)
    rows = np.flatnonzero(mask.any(axis=1))
    assert (rows[0], rows[-1]) == (1, 7)
    assert not mask[0].any() and not mask[8].any()


# ── composition: holes, exclusions, disjoint ─────────────────────────


def test_a_hole_is_subtracted_from_its_own_shape() -> None:
    """Against the composed ground truth — outer box AND NOT inner box —
    so a hole that came out shifted, or clipped to the wrong side, fails
    here rather than passing on a pixel count that happens to match."""
    holed = rasterize(
        one(rect(1, 1, 7, 7, holes=[[(3, 3), (3, 5), (5, 5), (5, 3)]])), SHAPE
    )
    assert np.array_equal(
        holed, inclusive_box(1, 1, 7, 7) & ~inclusive_box(3, 3, 5, 5)
    )


def test_an_exclusion_carves_the_whole_region_not_one_shape() -> None:
    region = Region(
        id="r1",
        parts=(Part(rect(1, 1, 7, 7)), Part(rect(3, 3, 5, 5), mode="exclude")),
    )
    assert np.array_equal(
        rasterize(region, SHAPE),
        inclusive_box(1, 1, 7, 7) & ~inclusive_box(3, 3, 5, 5),
    )


def test_a_hole_and_an_exclusion_of_the_same_box_agree() -> None:
    """They are different mechanisms — a hole belongs to its shape, an
    exclusion to the region — and over one shape they must still select
    the same pixels, or converting between the two spellings moves the
    region. Neither side is the module's own count of the other."""
    holed = rasterize(
        one(rect(1, 1, 7, 7, holes=[[(3, 3), (3, 5), (5, 5), (5, 3)]])), SHAPE
    )
    excluded = rasterize(
        Region(
            id="r1",
            parts=(Part(rect(1, 1, 7, 7)), Part(rect(3, 3, 5, 5), mode="exclude")),
        ),
        SHAPE,
    )
    assert np.array_equal(holed, excluded)


def test_two_includes_make_one_disjoint_region() -> None:
    """A specimen in two pieces is one selection, not two."""
    region = Region(
        id="r1", parts=(Part(rect(1, 1, 2, 2)), Part(rect(6, 6, 7, 7)))
    )
    assert np.array_equal(
        rasterize(region, SHAPE),
        inclusive_box(1, 1, 2, 2) | inclusive_box(6, 6, 7, 7),
    )


def test_part_order_decides_the_answer() -> None:
    """Documented as significant, so it needs a test that would fail if
    parts were ever treated as an unordered set of layers."""
    a, b = rect(1, 1, 5, 5), rect(3, 3, 7, 7)
    minus = rasterize(Region(id="x", parts=(Part(a), Part(b, mode="exclude"))), SHAPE)
    back = rasterize(
        Region(id="x", parts=(Part(a), Part(b, mode="exclude"), Part(b))), SHAPE
    )
    # Both answers pinned, not merely ordered by size: `minus.sum() <
    # back.sum()` would also hold if either were the wrong set.
    assert np.array_equal(minus, inclusive_box(1, 1, 5, 5) & ~inclusive_box(3, 3, 7, 7))
    assert np.array_equal(back, inclusive_box(1, 1, 5, 5) | inclusive_box(3, 3, 7, 7))


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
    clamps, and a half-visible region is a normal thing to draw. The
    pixels themselves are checked in the `RECTS` sweep, which carries
    three off-edge cases; what is asserted here is that none of them
    raises and one lying entirely outside is empty rather than an error.
    """
    assert rasterize(one(rect(-4, -4, 2, 2)), SHAPE).any()
    assert not rasterize(one(rect(-3, -3, -1, -1)), SHAPE).any()
    assert not rasterize(one(circle(-5.0, -5.0, 1.0)), SHAPE).any()


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


# ── what rasterization actually does ─────────────────────────────────


def test_a_pixel_is_in_when_its_centre_lies_on_the_edge() -> None:
    """The inclusive rectangle rests on this and nothing else: the edges
    of `rect(1, 1, 3, 3)` run exactly THROUGH the centres of rows and
    columns 1 and 3. If `polygon2mask` ever treated an edge as outside,
    every inclusive rect here would silently lose its first row and
    column — 4 px instead of 9 — so the dependency is pinned rather than
    trusted to survive a scikit-image upgrade."""
    edge = rasterize(one(polygon([(1, 1), (1, 3), (3, 3), (3, 1)])), SHAPE)
    assert np.array_equal(edge, inclusive_box(1, 1, 3, 3))
    assert edge[1, 1] and edge[1, 3] and edge[3, 1]   # corners: vertices
    assert edge[1, 2] and edge[2, 1]                  # sides: on an edge


@pytest.mark.parametrize(
    "offset", [0.0, 0.001, 0.2, 0.49, 0.5, 0.51, 0.99, 0.999, 1.0, 1.5]
)
def test_a_sub_pixel_shift_moves_the_mask_by_the_centre_in_polygon_rule(
    offset,
) -> None:
    """Against `inclusive_box` at the shifted bounds — the centre-in-square
    rule stated directly — rather than against counts read off a run.

    This is the test that would have caught the wrong docstring. The
    original sampled 0.2/0.49/0.51/0.99, four offsets that all happen to
    cross no pixel centre, saw one mask from all four, and concluded
    "rounds to nearest centre, snapping at .5". The oracle here disagrees
    with a rounding model at 0.001 and at 0.999 without anyone having to
    guess which offsets are the interesting ones.
    """
    square = np.array([[1.0, 1.0], [1.0, 3.0], [3.0, 3.0], [3.0, 1.0]]) + offset
    assert np.array_equal(
        rasterize(one(polygon(square)), SHAPE),
        inclusive_box(1 + offset, 1 + offset, 3 + offset, 3 + offset),
    )


def test_a_sliver_between_two_centres_masks_nothing() -> None:
    """The cost of centre sampling, stated in the module docstring: a mask
    population count is not a sub-pixel area. A caller needing true area
    wants the shoelace area of the outline instead."""
    sliver = polygon([(1.1, 1.0), (1.1, 7.0), (1.4, 7.0), (1.4, 1.0)])
    assert not rasterize(one(sliver), SHAPE).any()


# ── Shape is the persistence contract, so it validates itself ────────


def test_a_shape_cannot_carry_two_contradictory_geometries() -> None:
    """`Shape` is exported and is what the persistence and wire adapters
    will build directly, so the invariant the docstring states has to be
    enforced here — not only in the constructors. Carrying both would
    serialize two geometries and silently rasterize one."""
    ring = [(1, 1), (1, 3), (3, 3)]
    with pytest.raises(ValueError, match="bounds, not an outline"):
        Shape(kind="rect", bounds=(0, 0, 1, 1), outline=np.array(ring, float))
    with pytest.raises(ValueError, match="outline, not bounds"):
        Shape(kind="polygon", outline=np.array(ring, float), bounds=(0, 0, 1, 1))


def test_unsorted_or_non_finite_bounds_are_rejected() -> None:
    """The constructors sort; a deserialized Shape will not have been.
    Unsorted bounds are a DIFFERENT ellipse rather than an invalid one,
    which is the sort of quiet disagreement this contract exists to end."""
    with pytest.raises(ValueError, match="r0 <= r1"):
        Shape(kind="ellipse", bounds=(3, 1, 1, 3))
    with pytest.raises(ValueError, match="c0 <= c1"):
        Shape(kind="rect", bounds=(1, 3, 3, 1))
    with pytest.raises(ValueError, match="must be finite"):
        Shape(kind="rect", bounds=(0, 0, float("nan"), 2))


def test_a_hole_must_be_a_ring_that_can_enclose_something() -> None:
    """Holes reach `Shape` unchecked from every constructor, and a
    two-point or non-finite hole encloses nothing while still round-
    tripping through persistence as if it did."""
    with pytest.raises(ValueError, match="a hole needs at least 3 vertices"):
        rect(1, 1, 5, 5, holes=[[(2, 2), (3, 3)]])
    with pytest.raises(ValueError, match="a hole has non-finite"):
        rect(1, 1, 5, 5, holes=[[(2, 2), (2, 4), (float("inf"), 4)]])


def test_a_polygon_outline_must_be_finite() -> None:
    with pytest.raises(ValueError, match="a polygon has non-finite"):
        polygon([(1, 1), (1, 3), (np.nan, 3)])


def test_a_circle_shape_must_really_be_round() -> None:
    """A circle's bounds ARE its centre and radius, so unequal extents are
    an ellipse wearing the wrong kind — it would rasterize with the row
    extent and drop the column one. Reachable only by building the Shape
    directly, which persistence will do."""
    with pytest.raises(ValueError, match="equal row and column extents"):
        Shape(kind="circle", bounds=(3.0, 3.0, 5.0, 6.0))
    Shape(kind="circle", bounds=(3.0, 4.0, 5.0, 6.0))       # offset, still round
