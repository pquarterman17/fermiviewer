"""The canonical region/mask contract — roadmap item 4A.

This repo currently carries NINE structurally distinct ways to say "this
part of the image", none sharing a type and several disagreeing about
their coordinate convention: 1-based inclusive `(r1, c1, r2, c2)` rects
(`calc/roi`), the same thing as a CSV op-param, diffraction's 0-based
HALF-OPEN rect, diffraction's 0-based centre + INCLUSIVE radius, measure's
1-based inclusive FLOAT corners, normalized 0–1 `(x, y)` measure points,
`grains_edit`'s 0-based `(x, y)` clicks, `(row, col, radius)` FFT masks,
and a `(row, col, height, width)` template rect. This module does not
replace them; it is the one form they can all be converted INTO, so that
an analysis can consume a precise region instead of a bounding box.

## The canonical convention, stated once

**0-based `(row, col)`, float, with rings closed implicitly and every
bound INCLUSIVE.** Chosen to match `calc/contours.Contour`, which already
traces masks into exactly this form — so mask → region → mask composes
with no conversion layer, and the two halves of item 4 cannot drift.

Inclusive bounds are not an arbitrary pick. They make the two ways of
writing the same square agree exactly:

    rect(1, 1, 3, 3)                          == 9 px
    polygon([(1,1), (1,3), (3,3), (3,1)])     == 9 px

A half-open rect would make those differ by a row and a column, which is
the shape of bug this contract exists to prevent. `test_regions.py` pins
the equality.

## Two inclusive round conventions, which are NOT the same set

Everything round in this repo is inclusive at its boundary: the radius of
`calc/diffraction.apply_roi` (`> rad**2` is excluded),
`calc/fourier.fft_mask_inverse` (`<= radius`) and
`calc/fourd/geometry.aperture_mask` (`dist <= outer_r`), and equally the
inscribed ellipse of `calc/profile_stats.roi_stats`. But "inclusive"
selects DIFFERENT pixels in those two cases, and collapsing them into one
primitive is itself the bug:

    ellipse(3, 3, 5, 5)     9 px — inscribed in a 3×3 ROI
    circle(4, 4, 1)         5 px — within distance 1 of (4, 4)

Same centre, same nominal size, both inclusive. `ellipse` takes BOUNDS
and inscribes into their pixel FOOTPRINT — a bound at row 5 contributes
its whole cell out to 5.5, so the semi-axis is `(5 - 3 + 1) / 2`, which is
exactly `roi_stats`' `ry = sh / 2` over the inclusive extent `sh`.
`circle` takes a CENTRE AND RADIUS and keeps `dist <= radius`.

Both are needed because both have callers to migrate: a drag rectangle
becomes an `ellipse`, and `test_regions.py` pins it pixel-for-pixel
against `roi_stats` over odd AND even bounds; a diffraction ROI or FFT
mask becomes a `circle`. Reading bounds with radius semantics is not a
boundary quibble — it makes an ordinary 2×2 drag select nothing at all,
because all four pixel centres lie outside an ellipse of semi-axis 0.5.

Neither is `skimage.draw.disk`, which uses `dist < r` (`disk(c, 1)` is a
single pixel, `disk(c, 2)` is 3×3); building on it would have made a
region of radius `r` disagree with the diffraction ROI of radius `r`.

## What rasterization does NOT preserve

`skimage.draw.polygon2mask` rounds vertices to the nearest pixel centre:
a corner at 0.2, 0.49, 0.51 and 0.99 all produce the same mask, snapping
at .5. Sub-pixel outline precision is therefore LOST at rasterization.
That is fine for selecting pixels, but it means `mask.sum()` is a pixel
count, not a sub-pixel-accurate area — a lasso drawn 0.4 px outside a
feature masks the same pixels as one drawn on it. Callers wanting true
geometric area should use the shoelace area of the outline
(`calc/contours`), not the mask's population count.

Pure layer: numpy + scikit-image (already a runtime dependency, BSD) and
stdlib. No pydantic, no routes — `io/` owns persistence and `routes/`
owns the wire adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from skimage.draw import polygon2mask

__all__ = [
    "REGION_KINDS",
    "REGION_MODES",
    "Part",
    "Region",
    "Shape",
    "bounding_box",
    "circle",
    "ellipse",
    "polygon",
    "rasterize",
    "rect",
    "to_rect_roi",
]

#: The primitive outline kinds. A LASSO is a `polygon` — a free-hand trace
#: differs from a clicked one only in vertex count, and giving it its own
#: kind would mean two code paths that must never disagree.
REGION_KINDS = ("rect", "ellipse", "polygon")

#: How a part combines with the parts before it. `exclude` is what carves
#: a bite out of a region; `holes` is what carves one out of a single
#: shape. Both exist because they are not the same: a hole belongs to its
#: shape and travels with it, an exclusion applies to the whole region.
REGION_MODES = ("include", "exclude")


@dataclass(frozen=True)
class Shape:
    """One primitive outline in canonical coordinates.

    `bounds` is `(r0, c0, r1, c1)`, 0-based and INCLUSIVE, for `rect` and
    `ellipse`; an ellipse is the one inscribed in those bounds. `outline`
    is the `(N, 2)` float `(row, col)` ring for `polygon`, closed
    implicitly. Exactly one of the two is set for a given kind.

    `holes` are inner rings subtracted from THIS shape, in the same
    `(N, 2)` form. They are supported for every kind: a rectangle with a
    hole is as legitimate as a polygon with one.
    """

    kind: str
    bounds: tuple[float, float, float, float] | None = None
    outline: np.ndarray | None = None
    holes: tuple[np.ndarray, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in REGION_KINDS:
            raise ValueError(
                f"region kind must be one of {REGION_KINDS}, got {self.kind!r}"
            )
        if self.kind == "polygon":
            if self.outline is None:
                raise ValueError("a polygon needs an outline")
            if _ring(self.outline).shape[0] < 3:
                raise ValueError("a polygon needs at least 3 vertices")
        elif self.bounds is None:
            raise ValueError(f"a {self.kind} needs bounds")


@dataclass(frozen=True)
class Part:
    """One shape and how it combines with the parts before it."""

    shape: Shape
    mode: str = "include"

    def __post_init__(self) -> None:
        if self.mode not in REGION_MODES:
            raise ValueError(
                f"region mode must be one of {REGION_MODES}, got {self.mode!r}"
            )


@dataclass(frozen=True)
class Region:
    """A named region: an ordered list of parts over one image grid.

    ORDER IS SIGNIFICANT and is the whole reason parts are a list rather
    than two sets: parts apply left to right, so an `include` after an
    `exclude` puts pixels back. `[include A, exclude B]` is A minus B;
    `[exclude B, include A]` is just A. A renderer showing them as
    unordered layers would be showing a different region than the one
    that gets rasterized.

    Several `include` parts make a DISJOINT region — two separate blobs
    are one region, which is what lets "the specimen" be one selection
    even when it is in two pieces.

    `region_class` is the user's label for what KIND of thing this is
    (`"substrate"`, `"precipitate"`), distinct from `name`, which
    identifies this particular one. Free text: the vocabulary is the
    user's, and constraining it here would make the contract wrong for
    every specimen it did not anticipate.
    """

    id: str
    parts: tuple[Part, ...]
    name: str | None = None
    region_class: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.parts:
            raise ValueError("a region needs at least one part")
        if self.parts[0].mode != "include":
            raise ValueError(
                "the first part must be an 'include' — a region that opens "
                "with an exclusion subtracts from nothing and is always empty"
            )


# ── constructors ─────────────────────────────────────────────────────


def _ring(points: Any) -> np.ndarray:
    """`(N, 2)` float64 `(row, col)`, validated. Accepts any array-like so
    a caller can hand over a list of tuples without ceremony."""
    ring = np.asarray(points, dtype=np.float64)
    if ring.ndim != 2 or ring.shape[1] != 2:
        raise ValueError(
            f"a ring must be (N, 2) (row, col) points, got shape {ring.shape}"
        )
    return ring


def rect(
    r0: float, c0: float, r1: float, c1: float, *, holes: Any = ()
) -> Shape:
    """An axis-aligned rectangle, 0-based INCLUSIVE on all four sides.

    Corners are sorted, so `(3, 3, 1, 1)` is the same rectangle as
    `(1, 1, 3, 3)` — a drag that ends up-and-left of where it started is
    not a degenerate region, and rejecting it would only push the sort
    into every caller.
    """
    lo_r, hi_r = sorted((float(r0), float(r1)))
    lo_c, hi_c = sorted((float(c0), float(c1)))
    return Shape(
        kind="rect",
        bounds=(lo_r, lo_c, hi_r, hi_c),
        holes=tuple(_ring(h) for h in holes),
    )


def ellipse(
    r0: float, c0: float, r1: float, c1: float, *, holes: Any = ()
) -> Shape:
    """The ellipse inscribed in the FOOTPRINT of the given INCLUSIVE bounds.

    Bounds rather than centre+radii because that is what a drag produces
    and what `roi_stats(shape="ellipse")` already means by an ellipse —
    the two select the same pixels for the same bounds, which is the point
    of routing an existing elliptical ROI through here.

    "Footprint" is the load-bearing word: the bounds name PIXELS, and each
    named pixel is included whole, so bounds spanning `n` pixels give a
    semi-axis of `n / 2` rather than `(n - 1) / 2`. For a square-bounds
    circle that is NOT the same as a radius — see `circle`, and the module
    docstring for why both exist.
    """
    lo_r, hi_r = sorted((float(r0), float(r1)))
    lo_c, hi_c = sorted((float(c0), float(c1)))
    return Shape(
        kind="ellipse",
        bounds=(lo_r, lo_c, hi_r, hi_c),
        holes=tuple(_ring(h) for h in holes),
    )


def circle(
    centre_row: float, centre_col: float, radius: float, *, holes: Any = ()
) -> Shape:
    """The pixels within an INCLUSIVE `radius` of a centre — `dist <= r`.

    The convention `calc/diffraction.apply_roi`, `fourier.fft_mask_inverse`
    and `fourd.geometry.aperture_mask` all use, and the one to convert
    those ROIs into. It is deliberately NOT `ellipse` over the square
    bounds `(cr - r, cc - r, cr + r, cc + r)`: those bounds span `2r + 1`
    pixels, so the inscribed ellipse has semi-axis `r + 0.5` and takes in
    a ring of pixels the radius excludes.

    Carried as an `ellipse` shape rather than a fourth kind, since it is
    one — the bounds are inset by half a pixel so that the footprint
    semi-axis works out to exactly `radius`. A radius under half a pixel
    is the centre pixel alone, which is what `dist <= r` says and what a
    click without a drag should give.
    """
    if not radius >= 0:                      # also rejects NaN
        raise ValueError(f"a circle needs a radius >= 0, got {radius!r}")
    inset = max(float(radius) - 0.5, 0.0)
    return Shape(
        kind="ellipse",
        bounds=(
            float(centre_row) - inset,
            float(centre_col) - inset,
            float(centre_row) + inset,
            float(centre_col) + inset,
        ),
        holes=tuple(_ring(h) for h in holes),
    )


def polygon(outline: Any, *, holes: Any = ()) -> Shape:
    """A polygon (or lasso) from an implicitly-closed `(row, col)` ring."""
    return Shape(
        kind="polygon",
        outline=_ring(outline),
        holes=tuple(_ring(h) for h in holes),
    )


# ── rasterization ────────────────────────────────────────────────────


def _outline_mask(ring: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """One closed ring as a boolean mask (see the module docstring on the
    round-to-nearest-centre behaviour this inherits)."""
    return np.asarray(polygon2mask(shape, ring), dtype=bool)


def _shape_mask(item: Shape, shape: tuple[int, int]) -> np.ndarray:
    """One shape's mask, with its own holes already subtracted."""
    if item.kind == "polygon":
        assert item.outline is not None  # Shape.__post_init__ guarantees it
        mask = _outline_mask(item.outline, shape)
    else:
        assert item.bounds is not None
        r0, c0, r1, c1 = item.bounds
        if item.kind == "rect":
            # A rectangle IS its corner polygon — same vertices, same
            # inclusive boundary — so routing it through the same
            # rasterizer is what makes the two agree by construction
            # rather than by two implementations happening to match.
            mask = _outline_mask(
                np.array([[r0, c0], [r0, c1], [r1, c1], [r1, c0]], float), shape
            )
        else:
            rows = np.arange(shape[0], dtype=np.float64)[:, None]
            cols = np.arange(shape[1], dtype=np.float64)[None, :]
            centre_r, centre_c = (r0 + r1) / 2.0, (c0 + c1) / 2.0
            # Semi-axes span the bounds' pixel FOOTPRINT, not the distance
            # between the endpoint centres: bounds (1, 1, 3, 3) name three
            # pixels whose cells run from 0.5 to 3.5, so the semi-axis is
            # 1.5. That is `roi_stats`' `ry = sh / 2` over the inclusive
            # extent, and `test_regions.py` pins the two equal over odd and
            # even bounds. Endpoint-centre distance would give 1.0 here and
            # 0.5 for a 2x2 drag, where all four pixel centres then fall
            # outside and the drag selects nothing at all.
            #
            # Bounds are sorted, so each extent is >= 0 and each semi-axis
            # is >= 0.5: there is no degenerate case to special-case, and a
            # zero-height drag falls out as the line of pixels it covers.
            semi_r = (r1 - r0 + 1.0) / 2.0
            semi_c = (c1 - c0 + 1.0) / 2.0
            norm = ((rows - centre_r) / semi_r) ** 2 + (
                (cols - centre_c) / semi_c
            ) ** 2
            mask = norm <= 1.0  # INCLUSIVE — see the module docstring
    for hole in item.holes:
        mask &= ~_outline_mask(hole, shape)
    return mask


def rasterize(region: Region, shape: tuple[int, int]) -> np.ndarray:
    """`region` as an exact boolean mask over an image of `shape`.

    Parts apply IN ORDER (see `Region`): `include` unions, `exclude`
    subtracts. Pixels outside the grid are simply absent — a region
    drawn partly off the edge masks the part that exists rather than
    raising, because clamping is what every existing ROI helper here
    already does and a half-visible region is a normal thing to draw.
    """
    height, width = int(shape[0]), int(shape[1])
    if height <= 0 or width <= 0:
        raise ValueError(f"image shape must be positive, got {shape!r}")
    grid = (height, width)
    mask = np.zeros(grid, dtype=bool)
    for part in region.parts:
        part_mask = _shape_mask(part.shape, grid)
        if part.mode == "include":
            mask |= part_mask
        else:
            mask &= ~part_mask
    return mask


# ── bounding boxes, for migrating bbox-shaped callers ────────────────


def bounding_box(region: Region, shape: tuple[int, int]) -> tuple[int, int, int, int]:
    """The region's tight bbox as 0-based INCLUSIVE `(r0, c0, r1, c1)`.

    Derived from the RASTERIZED mask, not from the outlines, so it is the
    box that actually contains the selected pixels — an `exclude` that
    trims the region's edge shrinks the box, which reading the outlines
    alone would miss.

    Raises `ValueError` for a region that selects nothing: there is no
    honest bounding box for an empty selection, and returning the whole
    image would silently widen every caller that migrates through here.
    """
    mask = rasterize(region, shape)
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        raise ValueError("region selects no pixels, so it has no bounding box")
    return int(rows[0]), int(cols[0]), int(rows[-1]), int(cols[-1])


def to_rect_roi(region: Region, shape: tuple[int, int]) -> tuple[int, int, int, int]:
    """The region's bbox as a `calc.roi.RectRoi` — 1-BASED inclusive
    `(r1, c1, r2, c2)`.

    The migration seam. Every bbox-shaped analysis in the repo already
    speaks `RectRoi`, so this lets a caller accept a precise region today
    and keep passing a rectangle downstream, losing precision but never
    correctness. An analysis that can consume a mask should call
    `rasterize` instead and leave this alone.
    """
    r0, c0, r1, c1 = bounding_box(region, shape)
    return r0 + 1, c0 + 1, r1 + 1, c1 + 1
