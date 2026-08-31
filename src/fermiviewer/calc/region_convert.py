"""Label images ⇄ editable regions, losslessly (item 4B).

4C made every analysis read a region. This is the other direction: a
segmentation produces a LABEL IMAGE, and a user wants to correct it by
hand — which means it has to become regions, be edited, and become a
label image again without the round trip quietly changing which pixels
belong to what.

`calc/contours.py` already turns a mask into a polygon and is NOT what
this uses. That module exists for the UI's "detect region" assist: it
Douglas-Peucker simplifies to a manageable vertex count and traces the
outer boundary of a single connected foreground. Both are right for a
human about to drag vertices, and both are fatal here — simplification
is precisely the loss this module must not have. They are different
operations on the same data, and conflating them would trade the
round trip for a tidier outline.

## Why the rings are the structure, not the components

The load-bearing choice is that ring NESTING defines the parts, not
connected-component labelling.

Grouping by components first looks natural and is a trap. With
8-connectivity two diagonally-touching pixels are ONE component, but
marching squares traces them as TWO rings — so a rule like "the largest
ring is the outline, the rest are holes" turns the second pixel into a
hole. That is a silently plausible region: it rasterizes, it looks like a
shape, and it is not the label. With 4-connectivity the components match
the rings, but then a diagonal pair becomes two regions and the LABEL's
identity is lost, which is the other thing 4B may not do.

Rings avoid both. `find_contours` at the half-level is the same
description of the boundary that `polygon2mask` inverts, so taking its
output as the truth is what makes the round trip exact; nesting depth
then says which ring bounds material and which bounds a hole, with no
appeal to a connectivity convention at all. A label's diagonal pair
becomes one region with two parts — its identity kept, its shape exact.

Depth is computed by CONTAINMENT rather than winding direction.
`calc/contours.py` already refuses to trust skimage's start vertex and
direction, and the same caution applies to the sign of a signed area:
containment is a fact about the pixels, orientation is a fact about the
library version.

## Why the mask is padded before tracing

`find_contours` leaves a path OPEN where a feature runs off the edge of
the array, and an open path closed by `polygon2mask` cuts the corner. A
4x4 block in an array corner round-tripped as 6 pixels of 16. One ring of
background padding gives every feature somewhere to close, and the
coordinates shift back by one. Measured over 300 random masks plus the
structural cases (border contact, whole-image, single pixel, one-pixel
line, a hole, an island inside a hole), the round trip is EXACT.

## What lossless costs

Refusing to simplify has a price worth stating rather than discovering:
an outline keeps a vertex per boundary step. 150 grains at 512x512 trace
to ~32,000 vertices and a 0.5 MB `regions` section. That is the trade
this module exists to make — a simplified outline is smaller and is not
the segmentation — but a caller converting a large map should expect a
large region set, and one that wants small should be reaching for
`calc/contours.py` and accepting the loss knowingly.

Pure layer: numpy + scikit-image + scipy + stdlib.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import find_objects
from skimage.draw import polygon2mask
from skimage.measure import find_contours

from fermiviewer.calc.region_mask import rasterize
from fermiviewer.calc.regions import Part, Region, Shape

__all__ = [
    "LabelOverlapError",
    "labels_to_regions",
    "regions_to_labels",
]


class LabelOverlapError(ValueError):
    """Two regions claim the same pixel, which a label image cannot hold.

    Raised rather than resolved. A label image gives each pixel exactly
    one value, so writing overlapping regions into one means dropping a
    claim — and whichever rule picked the winner (last wins, lowest id
    wins) would be invisible in the result. A caller who genuinely wants
    one to win can order the regions and say so; a caller who did not
    know they overlapped is being told.
    """


def _rings(mask: np.ndarray) -> list[np.ndarray]:
    """Every boundary ring of `mask`, in the array's own coordinates.

    Padded first: `find_contours` leaves a path open where a feature
    meets the edge of the array, and closing it afterwards cuts across
    the corner. The pad gives the path somewhere to close and costs one
    subtraction.
    """
    padded = np.pad(np.asarray(mask, dtype=float), 1)
    return [ring - 1.0 for ring in find_contours(padded, 0.5)]


def _depths(filled: list[np.ndarray], counts: list[int]) -> list[int]:
    """How many other rings each ring lies inside.

    Even depth bounds material, odd bounds a hole — the standard
    even-odd rule, read off containment rather than winding direction so
    a scikit-image change to traversal order cannot silently invert it.

    Takes the rasterized rings rather than the rings, because the caller
    needs them too and rasterizing twice is the whole cost of this.
    """
    depths = []
    for i, inner in enumerate(filled):
        depth = 0
        for j, outer in enumerate(filled):
            # a ring never contains itself; ties on area cannot nest, and
            # comparing them both ways would make each the other's parent
            if i != j and counts[j] > counts[i] and (inner & ~outer).sum() == 0:
                depth += 1
        depths.append(depth)
    return depths


def _parts_of(mask: np.ndarray, origin: tuple[int, int] = (0, 0)) -> tuple[Part, ...]:
    """One mask as ordered `include` parts, holes attached to their own
    outline.

    A hole belongs to the ring one level out that contains it. Under that
    depth filter the parent is UNIQUE — two candidates would have to be
    rings at equal depth that overlap, and rings at equal depth are
    disjoint (nested ones differ in depth) — so the `min` below is a
    tiebreak that cannot fire, kept because relying on the argument
    rather than the code is how the argument stops being checked.
    Verified to 4-deep nesting: every hole has exactly one candidate.

    `mask` may be a CROP of a larger image; `origin` is its top-left in
    the full image and every ring is shifted by it on the way out, so the
    outlines a caller receives are always in full-image coordinates. That
    shift is the only thing standing between a correct outline and one
    that is right relative to a box nobody else knows about, so the
    round-trip tests place their labels away from the origin
    deliberately — at the origin the offset is zero and a dropped shift
    looks correct.
    """
    rings = _rings(mask)
    if not rings:
        return ()
    shift = np.asarray(origin, dtype=np.float64)
    if len(rings) == 1:
        # The common case by far — a solid label with no holes. Nesting is
        # what the rasterization below is for, and one ring has nowhere to
        # nest, so computing it would cost a full crop rasterization to
        # learn that a lone ring is at depth 0.
        return (Part(Shape(kind="polygon", outline=rings[0] + shift)),)
    shape = (int(mask.shape[0]), int(mask.shape[1]))
    filled = [polygon2mask(shape, ring) for ring in rings]
    counts = [int(m.sum()) for m in filled]
    depths = _depths(filled, counts)

    holes: dict[int, list[np.ndarray]] = {i: [] for i in range(len(rings))}
    for i, depth in enumerate(depths):
        if depth % 2 == 0:
            continue
        parent = min(
            (
                j
                for j in range(len(rings))
                if depths[j] == depth - 1
                and counts[j] > counts[i]
                and (filled[i] & ~filled[j]).sum() == 0
            ),
            key=lambda j: counts[j],
            default=None,
        )
        if parent is not None:
            holes[parent].append(rings[i])

    return tuple(
        Part(
            Shape(
                kind="polygon",
                outline=rings[i] + shift,
                holes=tuple(h + shift for h in holes[i]),
            )
        )
        for i, depth in enumerate(depths)
        if depth % 2 == 0
    )


def labels_to_regions(
    labels: np.ndarray, *, prefix: str = "label"
) -> tuple[Region, ...]:
    """A label image as one `Region` per distinct non-zero value.

    0 is background and produces no region. Every other value becomes one
    region whose parts are its outlines — several parts when the label is
    disconnected, holes attached to the outline that encloses them — so a
    label's IDENTITY survives even when its pixels do not touch.

    Ids are `f"{prefix}_{value}"`, and regions come back in ascending
    value order, so the same label image always converts identically.
    """
    array = np.asarray(labels)
    if array.ndim != 2:
        raise ValueError("a label image must be 2-D")
    if not np.issubdtype(array.dtype, np.integer):
        # a float label map is a rounding decision this module must not
        # make silently: 1.9999 is either label 1 or label 2 depending on
        # a convention the caller knows and this does not
        raise ValueError(f"labels must be an integer array, got {array.dtype}")
    if array.min() < 0:
        raise ValueError("labels must be non-negative (0 = background)")

    # one pass for every label's bounding box; `find_objects` indexes by
    # `value - 1` and returns None for a value the array does not use
    boxes = find_objects(array)
    regions: list[Region] = []
    for value in np.unique(array):
        if value == 0:
            continue
        # Crop to the label's own bounding box before tracing. Every step
        # below is proportional to the array it is given, so tracing a
        # 40x40 grain through a 2048x2048 grid costs ~2600x what the
        # grain needs. The boxes come from ONE `find_objects` pass rather
        # than a full-image comparison per label, which is the difference
        # between one scan of the array and one per distinct value.
        box = boxes[int(value) - 1]
        if box is None:  # pragma: no cover - unique() said it is present
            continue
        rows, cols = box
        crop = array[rows, cols] == value
        parts = _parts_of(crop, (rows.start, cols.start))
        if parts:
            regions.append(Region(id=f"{prefix}_{int(value)}", parts=parts))
    return tuple(regions)


def regions_to_labels(
    regions: tuple[Region, ...],
    shape: tuple[int, int],
    *,
    values: dict[str, int] | None = None,
) -> np.ndarray:
    """Regions as a label image, one value per region.

    `values` maps region id → label value; without it, regions take
    1..n in the order given. Background stays 0.

    Overlap RAISES (`LabelOverlapError`): a label image holds one value
    per pixel, so two regions covering one pixel means a claim is being
    dropped, and any rule for picking the winner would be invisible in
    the array that comes back.
    """
    grid = (int(shape[0]), int(shape[1]))
    assigned = values or {r.id: i + 1 for i, r in enumerate(regions)}
    out = np.zeros(grid, dtype=np.int64)
    claimed = np.zeros(grid, dtype=bool)
    for region in regions:
        if region.id not in assigned:
            raise ValueError(f"no label value given for region {region.id!r}")
        value = int(assigned[region.id])
        if value == 0:
            raise ValueError(
                f"region {region.id!r} cannot take label 0, which is background"
            )
        mask = rasterize(region, grid)
        overlap = mask & claimed
        if overlap.any():
            row, col = (int(a[0]) for a in np.nonzero(overlap))
            raise LabelOverlapError(
                f"region {region.id!r} overlaps an earlier region at "
                f"pixel ({row}, {col}); a label image cannot hold both"
            )
        out[mask] = value
        claimed |= mask
    return out
