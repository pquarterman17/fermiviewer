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

They are separate KINDS, and deliberately not one kind with the other's
coordinates massaged to fit. Encoding a radius as ellipse bounds inset by
half a pixel reproduces `dist <= r` for `r >= 0.5` and then silently fails
below it: the inset would go negative, and clamping it to zero widens the
region. `circle(4.2, 4.2, 0)` would select pixel (4, 4) — 0.283 px away —
when the exact set is empty. Fitted diffraction centres are fractional, so
that is a live case, not a corner one. Storing the convention in the kind
also means persistence round-trips the radius the user set rather than a
derived box that has to be decoded back.

Both are needed because both have callers to migrate: a drag rectangle
becomes an `ellipse`, and `test_regions.py` pins it pixel-for-pixel
against `roi_stats` over odd AND even bounds; a diffraction ROI or FFT
mask becomes a `circle`. Reading bounds with radius semantics is not a
boundary quibble — it makes an ordinary 2×2 drag select nothing at all,
because all four pixel centres lie outside an ellipse of semi-axis 0.5.

Neither is `skimage.draw.disk`, which uses `dist < r` (`disk(c, 1)` is a
single pixel, `disk(c, 2)` is 3×3); building on it would have made a
region of radius `r` disagree with the diffraction ROI of radius `r`.


This module is the VOCABULARY — what a region is and how one is built.
Turning one into pixels lives next door in `calc/region_mask.py`, which
is where the rasterization rules and their upstream dependencies are
stated; the split is what keeps either half under the module ceiling.

Pure layer: numpy and stdlib. No pydantic, no routes — `io/` owns persistence and `routes/`
owns the wire adapters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "REGION_KINDS",
    "REGION_MODES",
    "Part",
    "Region",
    "Shape",
    "circle",
    "ellipse",
    "polygon",
    "rect",
]

#: The primitive outline kinds. A LASSO is a `polygon` — a free-hand trace
#: differs from a clicked one only in vertex count, and giving it its own
#: kind would mean two code paths that must never disagree.
REGION_KINDS = ("rect", "ellipse", "circle", "polygon")

#: How a part combines with the parts before it. `exclude` is what carves
#: a bite out of a region; `holes` is what carves one out of a single
#: shape. Both exist because they are not the same: a hole belongs to its
#: shape and travels with it, an exclusion applies to the whole region.
REGION_MODES = ("include", "exclude")


@dataclass(frozen=True)
class Shape:
    """One primitive outline in canonical coordinates.

    `bounds` is `(r0, c0, r1, c1)`, 0-based and INCLUSIVE, for `rect`,
    `ellipse` and `circle`. For `rect` and `ellipse` they name PIXELS and
    are read as their footprint; for `circle` they are the true bounding
    box of the disc, so the centre is their midpoint and the radius half
    their extent — which is why a circle's bounds may be fractional and
    its row and column extents must match. `outline` is the `(N, 2)` float
    `(row, col)` ring for `polygon`, closed implicitly. Exactly one of the
    two is set for a given kind.

    `holes` are inner rings subtracted from THIS shape, in the same
    `(N, 2)` form. They are supported for every kind: a rectangle with a
    hole is as legitimate as a polygon with one.
    """

    kind: str
    bounds: tuple[float, float, float, float] | None = None
    outline: np.ndarray | None = None
    holes: tuple[np.ndarray, ...] = ()

    def __post_init__(self) -> None:
        # Validated HERE and not only in the constructors below, because
        # `Shape` is exported and is what persistence and the wire
        # adapters will build directly. A variant that carried both
        # `bounds` and an `outline` would serialize as two contradictory
        # geometries with one silently dropped at rasterization, which is
        # exactly the kind of disagreement this module exists to end.
        if self.kind not in REGION_KINDS:
            raise ValueError(
                f"region kind must be one of {REGION_KINDS}, got {self.kind!r}"
            )
        if self.kind == "polygon":
            if self.outline is None:
                raise ValueError("a polygon needs an outline")
            if self.bounds is not None:
                raise ValueError("a polygon carries an outline, not bounds")
            _checked_ring(self.outline, "a polygon")
        else:
            if self.bounds is None:
                raise ValueError(f"a {self.kind} needs bounds")
            if self.outline is not None:
                raise ValueError(f"a {self.kind} carries bounds, not an outline")
            if not all(np.isfinite(self.bounds)):
                raise ValueError(f"bounds must be finite, got {self.bounds!r}")
            r0, c0, r1, c1 = self.bounds
            if self.kind == "circle" and not math.isclose(
                r1 - r0, c1 - c0, rel_tol=1e-9, abs_tol=1e-12
            ):
                # A circle's bounds ARE its centre and radius; unequal
                # extents describe an ellipse and would be rasterized as
                # a circle of the row extent, quietly dropping the other.
                raise ValueError(
                    f"a circle needs equal row and column extents, got "
                    f"{r1 - r0} and {c1 - c0}"
                )
            if r0 > r1 or c0 > c1:
                # The constructors sort; a hand-built or deserialized
                # Shape may not, and unsorted bounds mean a different
                # ellipse rather than a rejected one.
                raise ValueError(
                    f"bounds must be (r0, c0, r1, c1) with r0 <= r1 and "
                    f"c0 <= c1, got {self.bounds!r}"
                )
        for hole in self.holes:
            _checked_ring(hole, "a hole")


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
    """`(N, 2)` float64 `(row, col)`, shape-checked. Accepts any array-like
    so a caller can hand over a list of tuples without ceremony."""
    ring = np.asarray(points, dtype=np.float64)
    if ring.ndim != 2 or ring.shape[1] != 2:
        raise ValueError(
            f"a ring must be (N, 2) (row, col) points, got shape {ring.shape}"
        )
    return ring


def _checked_ring(points: Any, what: str) -> np.ndarray:
    """`_ring` plus the two conditions a ring must meet to enclose area.

    Fewer than three vertices encloses nothing, and a non-finite vertex
    makes the whole mask undefined rather than merely clipped — both are
    rejected at construction so a malformed region cannot be persisted
    and then silently rasterize to something.
    """
    ring = _ring(points)
    if ring.shape[0] < 3:
        raise ValueError(f"{what} needs at least 3 vertices, got {ring.shape[0]}")
    if not np.isfinite(ring).all():
        raise ValueError(f"{what} has non-finite coordinates")
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

    Its own kind, storing the true bounding box of the disc — centre at
    the midpoint, radius at half the extent — so `dist <= radius` holds
    for EVERY radius, fractional centres included. A small radius on a
    fractional centre selects nothing, which is what the distance test
    says: a click landing between pixel centres covers none of them.
    """
    if not radius >= 0:                      # also rejects NaN
        raise ValueError(f"a circle needs a radius >= 0, got {radius!r}")
    r, cr, cc = float(radius), float(centre_row), float(centre_col)
    return Shape(
        kind="circle",
        bounds=(cr - r, cc - r, cr + r, cc + r),
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
