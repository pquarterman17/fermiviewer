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
from skimage.measure import find_contours, points_in_poly

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


def _boxes(rings: list[np.ndarray]) -> np.ndarray:
    """Each ring's bounding box as `(r0, c0, r1, c1)` — the cheap reject."""
    return np.array(
        [
            (r[:, 0].min(), r[:, 1].min(), r[:, 0].max(), r[:, 1].max())
            for r in rings
        ],
        dtype=np.float64,
    )


def _areas(rings: list[np.ndarray]) -> np.ndarray:
    """|shoelace area| per ring, for ordering containment."""
    out = np.empty(len(rings), dtype=np.float64)
    for i, r in enumerate(rings):
        x, y = r[:, 0], r[:, 1]
        out[i] = abs(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)) / 2.0
    return out


def _contains(i: int, j: int, rings: list[np.ndarray]) -> bool:
    """Does ring `j` enclose ring `i`? The authority, and the slow part.

    Nested marching-squares rings never cross, so ONE point of the inner
    ring decides it: if any point of `i` lies inside `j` then all of it
    does. A vertex of `i` cannot land ON `j`, because strict nesting
    always leaves at least one pixel between them.

    Called only on pairs `_containers` has screened, never directly —
    which is why it takes no boxes and no areas. The screen's conditions
    are NECESSARY for containment, which is what makes screening safe;
    re-checking them here would be one rule written in two places.
    """
    return bool(points_in_poly(rings[i][:1], rings[j])[0])


#: Boolean elements per bounding-box screening block. The screen is
#: pairwise, so a whole-matrix pass costs n^2 — 16,384 rings (a 256x256
#: checkerboard, which is what a noisy segmentation looks like) is 268
#: million booleans per temporary, which measured at 592 MB peak. Row
#: blocks make the peak a property of this constant instead of the
#: input: ~4 million elements, so ~20 MB of temporaries whatever the
#: ring count, at no measurable cost in time since each block is still
#: one vectorized numpy pass.
_SCREEN_BLOCK = 1 << 22


def _containers(
    rings: list[np.ndarray], boxes: np.ndarray, areas: np.ndarray
) -> list[list[int]]:
    """For each ring, the indices of the rings that enclose it.

    Two stages, because the pairwise question is cheap to ask wrongly and
    expensive to ask well.

    Stage one is the screen below, and it is the only statement of the
    two conditions containment requires: `j`'s box encloses `i`'s, and
    `j`'s area is strictly the greater. Both are NECESSARY, so nothing
    real is lost, and neither is sufficient, so survivors still face the
    polygon test. It is vectorized because this is where a fragmented
    label costs — 268 million Python-level comparisons take over a minute
    where numpy takes a moment — and because it rejects almost everything
    it meets: 100 disjoint blobs of differing sizes leave 4,374 pairs
    after the area test and none at all after the boxes.

    Containment is computed ONCE and returned, rather than recomputed
    when a hole looks for its parent: depth is the length of this list and
    the parent is an element of it, so both read the same answer and
    cannot disagree.
    """
    n = len(rings)
    r0, c0, r1, c1 = (boxes[:, k] for k in range(4))
    out: list[list[int]] = []
    step = max(1, _SCREEN_BLOCK // max(n, 1))
    for start in range(0, n, step):
        stop = min(start + step, n)
        block = (
            (r0[None, :] <= r0[start:stop, None])
            & (c0[None, :] <= c0[start:stop, None])
            & (r1[None, :] >= r1[start:stop, None])
            & (c1[None, :] >= c1[start:stop, None])
            & (areas[None, :] > areas[start:stop, None])
        )
        for offset in range(stop - start):
            i = start + offset
            out.append(
                [
                    int(j)
                    for j in np.flatnonzero(block[offset])
                    if _contains(i, int(j), rings)
                ]
            )
    return out


def _parts_of(mask: np.ndarray, origin: tuple[int, int] = (0, 0)) -> tuple[Part, ...]:
    """One mask as ordered `include` parts, holes attached to their own
    outline.

    A hole belongs to the ring one level out that contains it, which is
    the smallest of the rings containing it — see below. A hole at odd
    depth always has at least one container, since the depth IS the
    container count, so the selection cannot come up empty.

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
        # The common case by far — a solid label with no holes. A lone
        # ring has nowhere to nest, so the whole containment computation
        # below would run to establish that it is at depth 0.
        return (Part(Shape(kind="polygon", outline=rings[0] + shift)),)
    boxes = _boxes(rings)
    areas = _areas(rings)
    containers = _containers(rings, boxes, areas)
    # Even depth bounds material, odd bounds a hole — the standard
    # even-odd rule, read off containment rather than winding direction so
    # a scikit-image change to traversal order cannot silently invert it.
    depths = [len(c) for c in containers]

    holes: dict[int, list[np.ndarray]] = {i: [] for i in range(len(rings))}
    for i, depth in enumerate(depths):
        if depth % 2 == 0:
            continue
        # The SMALLEST container is the immediate one. Containment
        # orders rings by area — a container is strictly larger, so a
        # container of the parent is larger than the parent — which makes
        # this the ring exactly one level out with no appeal to the depth
        # numbers. Filtering `containers[i]` for `depth - 1` instead picks
        # the same ring by a second rule; one rule cannot drift from
        # itself, so this is the only one.
        holes[min(containers[i], key=lambda j: areas[j])].append(rings[i])

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
    if array.size == 0:
        # `min()` on an empty array raises from inside numpy, which tells
        # a caller nothing about label images. An empty image has no
        # labels, which is an answer rather than an error.
        return ()
    if array.min() < 0:
        raise ValueError("labels must be non-negative (0 = background)")

    # One pass for every label's bounding box — but over COMPACTED values.
    # `find_objects` returns a list of length max(labels), so handing it
    # the raw array costs memory proportional to the largest label VALUE
    # rather than to the image: an 8x8 array holding the single value
    # 10,000,000 took 433 MB, and 2**31 (a plausible global instance id)
    # would need ~80 GB to describe 64 pixels. `unique` gives dense
    # indices, so the cost follows the number of distinct labels instead.
    present, inverse = np.unique(array, return_inverse=True)
    boxes = find_objects(inverse.reshape(array.shape).astype(np.intp) + 1)
    regions: list[Region] = []
    for index, value in enumerate(present):
        if value == 0:
            continue
        # Crop to the label's own bounding box before tracing. Every step
        # below is proportional to the array it is given, so tracing a
        # 40x40 grain through a 2048x2048 grid costs ~2600x what the
        # grain needs. The boxes come from ONE `find_objects` pass rather
        # than a full-image comparison per label, which is the difference
        # between one scan of the array and one per distinct value.
        box = boxes[index]
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

    Every way two regions can end up indistinguishable is refused, because
    each of them drops a claim as silently as an overlap does:

    * two regions covering one PIXEL (`LabelOverlapError`) — a label image
      holds one value per pixel, so any rule for picking the winner would
      be invisible in the array that comes back;
    * two regions sharing an ID, which would collapse in the default
      mapping and quietly renumber the rest;
    * two regions given the same VALUE, which merges their identities on
      the way in and cannot be told apart on the way back out.

    A value must be a positive integer, and that is enforced rather than
    coerced: `labels_to_regions` refuses a float array because rounding is
    the caller's convention to choose, and truncating 2.7 to 2 here would
    make exactly that choice one function later.
    """
    grid = (int(shape[0]), int(shape[1]))
    ids = [r.id for r in regions]
    if len(set(ids)) != len(ids):
        duplicate = next(i for i in ids if ids.count(i) > 1)
        raise ValueError(f"two regions share the id {duplicate!r}")
    # `values or {...}` would treat an EXPLICIT empty mapping as "none
    # given" and auto-number, which is the one case where every id is
    # missing and so the one that most needs the refusal below
    assigned = (
        values if values is not None else {r.id: i + 1 for i, r in enumerate(regions)}
    )
    out = np.zeros(grid, dtype=np.int64)
    claimed = np.zeros(grid, dtype=bool)
    seen: dict[int, str] = {}
    for region in regions:
        if region.id not in assigned:
            raise ValueError(f"no label value given for region {region.id!r}")
        raw = assigned[region.id]
        if isinstance(raw, bool) or not isinstance(raw, (int, np.integer)):
            raise ValueError(
                f"region {region.id!r}: label value must be an integer, "
                f"got {raw!r}"
            )
        value = int(raw)
        if value <= 0:
            raise ValueError(
                f"region {region.id!r}: label value must be positive "
                f"(0 is background), got {value}"
            )
        if value in seen:
            raise ValueError(
                f"regions {seen[value]!r} and {region.id!r} were both given "
                f"label {value}, which would merge them"
            )
        seen[value] = region.id
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
