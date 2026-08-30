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

**A reference with slashes is disambiguated, not guessed.** Ids are
free-form non-empty strings, so a slash can appear on either side of
``"set_id/region_id"``. Rather than picking a separator — which only
decides which side is silently crippled — every split is tried and only
the readings that name something existing are kept. Several resolving is
refused as ambiguous, because two readings can cover different pixels and
answering with either is a wrong answer, not an arbitrary one.

App layer on purpose, for the same reason as `result_capture.py`: naming a
region by id requires the server-carried session, so this cannot live in
the pure `calc/`/`io/`/`ops/` layers. The geometry itself stays pure — the
rasterization is `calc.region_mask`'s and is not duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from fermiviewer.calc.region_mask import mask_and_rect, rasterize
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


def _listed(ids: list[str]) -> str:
    """Ids for an error message, truncated so a large project's exception
    stays readable."""
    if not ids:
        return "none"
    shown = ", ".join(repr(i) for i in ids[:_MAX_LISTED_IDS])
    extra = len(ids) - _MAX_LISTED_IDS
    return f"{shown}, +{extra} more" if extra > 0 else shown


def _candidate_parses(reference: str) -> list[tuple[str, str | None]]:
    """Every way `reference` could split into ``(set_id, region_id)``.

    The schema constrains both ids only to be non-empty strings, so a
    slash is ordinary data and can legitimately appear on EITHER side.
    That makes the reference ambiguous in general, and picking a side is
    not a fix: splitting on the last separator silently privileges the
    set id and leaves a region id containing a slash permanently
    unreachable, while splitting on the first does the reverse. So every
    split is offered here and `_resolve_reference` keeps only the ones
    that name something that actually exists.

    The whole string is always a candidate on its own — a bare set id.
    A split with an empty half never is: an id cannot be empty, so
    ``"s1/"`` can only be a set literally named ``"s1/"``.
    """
    parses: list[tuple[str, str | None]] = [(reference, None)]
    for index, char in enumerate(reference):
        if char == "/" and 0 < index < len(reference) - 1:
            parses.append((reference[:index], reference[index + 1 :]))
    return parses


def _resolve_reference(
    sets: tuple[RegionSet, ...], reference: str
) -> tuple[RegionSet, str | None]:
    """The one reading of `reference` that names something that exists.

    Refuses rather than guesses when several readings resolve. Two sets
    — one called ``"a/b"``, one called ``"a"`` holding a region ``"b/r1"``
    — make ``"a/b/r1"`` genuinely mean two different selections, and
    answering with either would report a number for a region the caller
    may not have asked for. That silent wrong answer is the failure this
    function exists to prevent; a refusal the user can fix by renaming is
    the lesser cost.
    """
    # First occurrence wins, matching the linear scan this replaced;
    # `load_regions` enforces id uniqueness, but a direct caller may not.
    by_id: dict[str, RegionSet] = {}
    for entry in sets:
        by_id.setdefault(entry.id, entry)

    viable: list[tuple[RegionSet, str | None]] = []
    set_hits: list[tuple[RegionSet, str]] = []
    for set_id, region_id in _candidate_parses(reference):
        group = by_id.get(set_id)
        if group is None:
            continue
        if region_id is None:
            viable.append((group, None))
        elif any(region.id == region_id for region in group.regions):
            viable.append((group, region_id))
        else:
            set_hits.append((group, region_id))

    if len(viable) > 1:
        readings = "; ".join(
            f"set {g.id!r}" + ("" if rid is None else f" region {rid!r}")
            for g, rid in viable
        )
        raise RegionReferenceError(
            f"region reference {reference!r} is ambiguous — ids may contain "
            f"'/', and this names more than one existing target ({readings}). "
            "Rename one of them to reference either unambiguously"
        )
    if viable:
        return viable[0]

    if set_hits:
        group, region_id = set_hits[0]
        raise RegionReferenceError(
            f"unknown region {region_id!r} in set {group.id!r}; available: "
            f"{_listed([r.id for r in group.regions])}"
        )
    leading = reference.split("/", 1)[0] or reference
    raise RegionReferenceError(
        f"unknown region set {leading!r}; available: "
        f"{_listed([g.id for g in sets])}"
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

    group, region_id = _resolve_reference(sets, region)
    _check_image(group, image_id)
    regions = _find_regions(group, region_id)

    mask = np.zeros((int(shape[0]), int(shape[1])), dtype=bool)
    for item in regions:
        mask |= rasterize(item, (int(shape[0]), int(shape[1])))
    try:
        # The `mask is None` invariant lives in calc.region_mask, shared
        # with the inline-geometry op param so the rule has one definition.
        rect, exact_mask, count = mask_and_rect(mask)
    except ValueError:
        raise RegionReferenceError(
            f"region reference {region!r} selects no pixels of this "
            f"{shape[0]}x{shape[1]} image"
        ) from None
    exact = exact_mask is not None
    return ResolvedRegion(
        rect=rect,
        mask=exact_mask,
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
