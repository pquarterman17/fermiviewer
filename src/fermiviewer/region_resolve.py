"""The one place a region reference becomes pixels — 4C's shared resolver.

Every analysis that scopes itself to part of an image has, until now,
interpreted that scope for itself: the op catalogues parse the frozen
``"r1,c1,r2,c2"`` string through `ops/_parsing.parse_roi_param`,
`routes/images.py` takes loose ``row0/col0/row1/col1`` query params, and
neither can name a region from the ADR 0006 workspace at all. Migrating
each consumer independently onto the canonical contract would mean each
one deciding again what an id means, which frame the numbers are in, and
what to do when a region is empty or drawn on a different image. This
module makes those decisions once.

**What it returns is deliberately shaped for a gradual migration.**
`ResolvedRegion` always carries a `rect` — the 1-based inclusive bounding
box every bbox-shaped analysis in the repo already speaks — so a consumer
can adopt the resolver without changing what it does downstream. `mask` is
the new capability, and it is ``None`` exactly when the selection IS its
whole bounding box. That invariant is what makes the migration safe: a
consumer that only knows how to slice a rectangle stays *correct* rather
than merely unbroken, because ``mask is None`` is precisely the case where
slicing the rect and applying the mask give the same pixels. A consumer
that has learned to mask checks the field and gets exact geometry.

**Provenance is structural, not prose.** The repo's existing
``"convention"`` metadata field is free text carrying at least ten
mutually incompatible kinds of claim — coordinate frames
(``"(row, col), 1-based"``), label encodings (``"0 = background; values
are grain labels"``) and value semantics (``"1 = defect-line pixel"``) —
so a consumer cannot tell from the field which of the three it is holding.
Emitting one more such string here would leave 4C with an additional
dialect rather than one fewer, so `ResolvedRegion.provenance` names the
frame in typed fields (`REFERENCE_FRAME`) and records what was resolved
from what.

App layer on purpose, for the same reason as `result_capture.py`: naming a
region by id requires the server-carried session, so this cannot live in
the pure `calc/`/`io/`/`ops/` layers. The geometry itself stays pure — the
rasterization is `calc.region_mask`'s and is not duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from fermiviewer.calc.region_mask import rasterize
from fermiviewer.calc.regions import Region
from fermiviewer.calc.roi import RectRoi, roi_slices
from fermiviewer.io.regions_model import RegionSet
from fermiviewer.ops._parsing import parse_roi_param
from fermiviewer.project_session import project

__all__ = [
    "REFERENCE_FRAME",
    "RegionReferenceError",
    "ResolvedRegion",
    "resolve_region",
    "resolve_region_params",
]

#: How to read `ResolvedRegion.rect`, as typed fields rather than a prose
#: `convention` string. This describes the RECT only: `mask` is a NumPy
#: array and is therefore 0-based by construction, which is why the two
#: are never reported under one convention label.
REFERENCE_FRAME = {
    "axis_order": "row-col",
    "index_base": 1,
    "bounds": "inclusive",
    "origin": "top-left",
}

#: How many ids an error message will list before truncating. A project
#: can carry hundreds of regions and an exception is not a listing API.
_MAX_LISTED_IDS = 10


class RegionReferenceError(ValueError):
    """A region reference that cannot be resolved.

    A `ValueError` subclass so the op catalogues' existing
    ``except (ValueError, TypeError)`` handlers map it to their 422
    without every one of them needing to learn a new exception type.
    """


@dataclass(frozen=True)
class ResolvedRegion:
    """A region reference resolved against one image grid.

    `rect` is the 1-based inclusive bounding box, clamped to the image —
    read it through `REFERENCE_FRAME`. `mask` is a full-image ``[H, W]``
    boolean array, or ``None`` when the selection is exactly `rect` (see
    the module docstring: that is the invariant a rectangle-only consumer
    relies on). `pixel_count` is how many pixels are actually selected,
    which for a ``None`` mask is the area of `rect`.
    """

    rect: RectRoi
    mask: np.ndarray | None
    pixel_count: int
    provenance: dict[str, Any]

    @property
    def is_exact(self) -> bool:
        """Whether the selection is narrower than its bounding box."""
        return self.mask is not None

    def rect_slices(self) -> tuple[slice, slice]:
        """NumPy slices for `rect` — the 1-based to 0-based conversion, in
        one place, so no consumer open-codes the ``- 1`` again."""
        r1, c1, r2, c2 = self.rect
        return slice(r1 - 1, r2), slice(c1 - 1, c2)

    def cropped_mask(self) -> np.ndarray:
        """The mask restricted to `rect`, ALWAYS as an array.

        The counterpart to `mask` for consumers that already slice their
        data to the ROI: they get a mask of the same shape as that slice,
        and an all-True one when the selection is a plain rectangle,
        instead of having to branch on ``None`` themselves.
        """
        rows, cols = self.rect_slices()
        if self.mask is None:
            return np.ones((rows.stop - rows.start, cols.stop - cols.start), dtype=bool)
        cropped: np.ndarray = self.mask[rows, cols]
        return cropped


def _clamped_rect(shape: tuple[int, int], roi: RectRoi | None) -> RectRoi:
    """`roi` clamped to `shape`, as a 1-based inclusive rect. Delegates the
    clamp to `calc.roi.roi_slices` so the resolver cannot drift from the
    rule every existing ROI consumer already follows."""
    rows, cols = roi_slices(shape, roi)
    return rows.start + 1, cols.start + 1, rows.stop, cols.stop


def _mask_bounds(mask: np.ndarray) -> RectRoi:
    """Tight 1-based inclusive bbox of a non-empty boolean mask."""
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    return (
        int(rows[0]) + 1,
        int(cols[0]) + 1,
        int(rows[-1]) + 1,
        int(cols[-1]) + 1,
    )


def _listed(ids: list[str]) -> str:
    """Ids for an error message, truncated so a large project's exception
    stays readable."""
    if not ids:
        return "none"
    shown = ", ".join(repr(i) for i in ids[:_MAX_LISTED_IDS])
    extra = len(ids) - _MAX_LISTED_IDS
    return f"{shown}, +{extra} more" if extra > 0 else shown


def _split_reference(reference: str) -> tuple[str, str | None]:
    """``"set/region"`` -> ``("set", "region")``; ``"set"`` -> ``("set", None)``.

    Splits on the LAST separator, so a set id containing a slash still
    resolves. An empty half is an error rather than a silent whole-set
    read: ``"set/"`` reads as a typo'd region id, not as "the whole set".
    """
    head, sep, tail = reference.rpartition("/")
    if not sep:
        return reference, None
    if not head or not tail:
        raise RegionReferenceError(
            f"region reference {reference!r} must be 'set_id' or "
            "'set_id/region_id', with both halves non-empty"
        )
    return head, tail


def _find_set(sets: tuple[RegionSet, ...], set_id: str) -> RegionSet:
    for group in sets:
        if group.id == set_id:
            return group
    raise RegionReferenceError(
        f"unknown region set {set_id!r}; available: {_listed([g.id for g in sets])}"
    )


def _find_regions(group: RegionSet, region_id: str | None) -> tuple[Region, ...]:
    """The referenced regions: one named region, or every region in the set.

    A whole-set reference unions the set's regions, which is what makes
    "the specimen" analyzable when it was drawn as several separate
    selections. An EMPTY set is an error, not an empty union: silently
    resolving it would analyze nothing while looking like it worked.
    """
    if region_id is None:
        if not group.regions:
            raise RegionReferenceError(f"region set {group.id!r} contains no regions")
        return group.regions
    for region in group.regions:
        if region.id == region_id:
            return (region,)
    raise RegionReferenceError(
        f"unknown region {region_id!r} in set {group.id!r}; available: "
        f"{_listed([r.id for r in group.regions])}"
    )


def _check_image(group: RegionSet, image_id: str | None) -> None:
    """Refuse a region drawn on a different image.

    Only checked when BOTH sides know their image: a set with no
    `image_id` is unbound by design (ADR 0006), and a caller that does not
    pass one is not claiming anything to contradict. Where both are known,
    a mismatch is a scientific error — the numbers would come out of the
    wrong specimen — so it is refused rather than warned about.
    """
    if image_id is None or group.image_id is None:
        return
    if group.image_id != image_id:
        raise RegionReferenceError(
            f"region set {group.id!r} was drawn on image {group.image_id!r}, not {image_id!r}"
        )


def resolve_region(
    shape: tuple[int, int],
    *,
    region: str = "",
    roi: str = "",
    sets: tuple[RegionSet, ...] = (),
    image_id: str | None = None,
) -> ResolvedRegion:
    """Resolve a region reference against an image grid.

    Exactly one of `region` and `roi` may be given; both empty means the
    whole image. Passing both is an error rather than a precedence rule,
    because a caller that sends two different scopes has a bug and
    silently honouring one of them hides it.

    * `region` — ``"set_id"`` (the union of that set's regions) or
      ``"set_id/region_id"``, resolved against `sets`.
    * `roi` — the frozen ``"r1,c1,r2,c2"`` 1-based inclusive string, so
      every existing caller's param keeps working unchanged.

    `image_id`, when given, is checked against the region set's own (see
    `_check_image`). Raises `RegionReferenceError` for an unresolvable
    reference and for a region that selects no pixels.
    """
    if region and roi:
        raise RegionReferenceError("give either a region reference or a roi rectangle, not both")
    if not region:
        rect = _clamped_rect(shape, parse_roi_param(roi))
        r1, c1, r2, c2 = rect
        return ResolvedRegion(
            rect=rect,
            mask=None,
            pixel_count=(r2 - r1 + 1) * (c2 - c1 + 1),
            provenance={
                "source": "roi" if roi else "whole-image",
                "rect": list(rect),
                "frame": dict(REFERENCE_FRAME),
                "exact_mask": False,
            },
        )

    set_id, region_id = _split_reference(region)
    group = _find_set(sets, set_id)
    _check_image(group, image_id)
    regions = _find_regions(group, region_id)

    mask = np.zeros((int(shape[0]), int(shape[1])), dtype=bool)
    for item in regions:
        mask |= rasterize(item, (int(shape[0]), int(shape[1])))
    count = int(mask.sum())
    if count == 0:
        raise RegionReferenceError(
            f"region reference {region!r} selects no pixels of this {shape[0]}x{shape[1]} image"
        )

    rect = _mask_bounds(mask)
    r1, c1, r2, c2 = rect
    # `None` iff the selection fills its own bounding box — the invariant
    # a rectangle-only consumer depends on (see the module docstring).
    exact = count != (r2 - r1 + 1) * (c2 - c1 + 1)
    return ResolvedRegion(
        rect=rect,
        mask=mask if exact else None,
        pixel_count=count,
        provenance={
            "source": "region-set",
            "set_id": group.id,
            "region_ids": [item.id for item in regions],
            "image_id": group.image_id,
            "rect": list(rect),
            "frame": dict(REFERENCE_FRAME),
            "exact_mask": exact,
        },
    )


def resolve_region_params(
    shape: tuple[int, int],
    params: dict[str, Any],
    *,
    image_id: str | None = None,
) -> ResolvedRegion:
    """`resolve_region` for a registered op, reading the session's region
    sets and the op's own ``region``/``roi`` params.

    The session read lives here rather than in each catalogue so an op
    gains region support by declaring a ``region`` param and calling this,
    with no import of `project_session` of its own.
    """
    return resolve_region(
        shape,
        region=str(params.get("region", "") or ""),
        roi=str(params.get("roi", "") or ""),
        sets=project.current().region_sets,
        image_id=image_id,
    )
