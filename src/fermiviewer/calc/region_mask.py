"""Turning a canonical region into pixels — the other half of item 4A.

`calc/regions` says what a region IS; this says which pixels one covers.
They are separate modules because the contract outgrew a single file, and
because the two answer different questions: one is a vocabulary a caller
builds, the other is a rule about sampling a grid.

## What rasterization actually does

A pixel belongs to a polygon iff its CENTRE is inside it, lies ON an edge,
or IS a vertex. That is `skimage.measure.grid_points_in_poly`, which
labels those three cases 1, 3 and 2, and `polygon2mask` keeps all three.
Centre sampling, boundary INCLUSIVE — nothing is rounded to a centre.

The boundary half of that rule is load-bearing here, not incidental:
`rect(1, 1, 3, 3)` puts its edges exactly THROUGH the centres of rows and
columns 1 and 3, so those pixels are in and the rectangle is 9 px. A
rasterizer treating edges as outside would return 4 px for the same
inclusive bounds, so `test_regions.py` pins the edge case directly rather
than trusting it to stay true across a scikit-image upgrade.

Sub-pixel coordinates are therefore NOT discarded — they change the mask
whenever an edge crosses a pixel centre. Shifting that same square by
+0.001 drops its top row and left column (4 px); +1.0 restores nine, one
pixel down and right. What centre sampling does cost is area fidelity:
`mask.sum()` counts pixels whose centres were captured, so a lasso drawn
0.4 px outside a feature usually masks the same pixels as one drawn on
it, and a sliver crossing no centre masks nothing at all. Callers wanting
true geometric area should take the shoelace area of the outline
(`calc/contours`), not the mask's population count.

Pure layer: numpy + scikit-image (already a runtime dependency, BSD) and
stdlib. No pydantic, no routes.
"""

from __future__ import annotations

import numpy as np
from skimage.draw import polygon2mask

from fermiviewer.calc.regions import Region, Shape

__all__ = ["bounding_box", "mask_and_rect", "rasterize", "to_rect_roi"]


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
            # Straight from the bounds, NOT through the corner polygon.
            # Routing it through `polygon2mask` made the two spellings
            # agree by construction, but a rect with one degenerate axis
            # is a ZERO-AREA ring, and a ring that encloses nothing gives
            # back only its own vertices: a one-pixel-wide rectangle came
            # out as its two surviving corners instead of the line of
            # pixels its bounds name. Silently — the bounding box still
            # looked right, because those two corners span it.
            #
            # The bounds already state exactly which pixels are in, and
            # for every non-degenerate rect this is the identical set
            # `polygon2mask` returns (pinned in `test_regions.py`). A
            # degenerate POLYGON still selects nothing, which is the
            # honest answer for a ring: that is where the two spellings
            # genuinely part company, rather than one of them being wrong.
            rows = np.arange(shape[0], dtype=np.float64)[:, None]
            cols = np.arange(shape[1], dtype=np.float64)[None, :]
            mask = (rows >= r0) & (rows <= r1) & (cols >= c0) & (cols <= c1)
        else:
            rows = np.arange(shape[0], dtype=np.float64)[:, None]
            cols = np.arange(shape[1], dtype=np.float64)[None, :]
            centre_r, centre_c = (r0 + r1) / 2.0, (c0 + c1) / 2.0
            if item.kind == "circle":
                # RADIUS semantics: the bounds are the disc's bounding
                # box, so the radius is half the extent and the test is
                # the plain `dist <= r` of `diffraction.apply_roi` and
                # friends. No footprint half-pixel here — adding one is
                # what makes a circle disagree with the ROI it came from.
                radius = (r1 - r0) / 2.0
                mask = (rows - centre_r) ** 2 + (
                    cols - centre_c
                ) ** 2 <= radius**2
                for hole in item.holes:
                    mask &= ~_outline_mask(hole, shape)
                return mask
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


def mask_and_rect(
    mask: np.ndarray,
) -> tuple[tuple[int, int, int, int], np.ndarray | None, int]:
    """A rasterized mask as ``(rect, mask_or_None, pixel_count)``.

    ADR 0007 §3's invariant, in one place: the returned mask is ``None``
    EXACTLY when the selection fills its own bounding box, so a consumer
    that only knows how to slice a rectangle is correct precisely when it
    sees ``None``, and the field it is ignoring is the signal that it must
    not. `rect` is 1-based inclusive, tight around the selected pixels.

    Lives here rather than in `region_resolve` because two callers now
    need it — a region named in the workspace and a region given inline as
    an op param — and a second copy of an invariant is how the rule starts
    meaning two different things.

    Raises `ValueError` for a mask selecting nothing, matching
    `bounding_box`: there is no honest rectangle for an empty selection.
    """
    count = int(np.count_nonzero(mask))
    if count == 0:
        raise ValueError("region selects no pixels of this image")
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    rect = (
        int(rows[0]) + 1, int(cols[0]) + 1, int(rows[-1]) + 1, int(cols[-1]) + 1,
    )
    r1, c1, r2, c2 = rect
    exact = count != (r2 - r1 + 1) * (c2 - c1 + 1)
    return rect, (mask if exact else None), count
