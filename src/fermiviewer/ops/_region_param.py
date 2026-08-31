"""A region as an op PARAMETER — canonical geometry, carried inline.

An op cannot resolve a region by name. `ops/registry.py` states the rule
its `inputs` channel already follows: auxiliary things arrive
already-resolved because "the caller owns the session store, so the pure
layer never looks an id up". A region reference is an id, so an op that
called `region_resolve` would be reaching into global session state — and
`tests/test_repo_integrity.py`'s pure-layer guard would NOT catch it,
since `FORBIDDEN_IN_PURE` names the server stack, not session coupling.

So an op takes the GEOMETRY, not a reference: `REGION_PARAM` is the
canonical form (ADR 0006's shapes) as an ordinary list-shaped `OpParam`,
validated by the same machinery every other param uses. That needs no
change to `run()`, and it keeps the property ADR 0005 depends on — an
op's params are its complete reproduction key. A recipe carrying inline
geometry replays identically on a machine with no project at all.

**How a NAMED region reaches an op later.** The recipe runner owns the
session, so it can resolve a symbolic reference and substitute the
resolved geometry into this param before dispatch. The op still never
sees an id, `run()` still never changes, and the recorded params still
carry the resolved values `result_capture` requires. That is why this
param is the whole mechanism rather than a stopgap: naming is a caller
concern, and geometry is the contract.

Datasets could not work this way — an auxiliary image is too large and
not JSON, which is exactly why `inputs` is a separate channel. Geometry
is small and JSON-native, so it belongs in params.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.region_mask import mask_and_rect, rasterize
from fermiviewer.calc.regions import (
    REGION_KINDS,
    REGION_MODES,
    Part,
    Region,
    Shape,
)
from fermiviewer.calc.roi import RectRoi, roi_slices
from fermiviewer.ops._envelopes import output
from fermiviewer.ops._parsing import parse_roi_param
from fermiviewer.ops.base import OpParam, RecordSpec, RingsSpec, RowSpec

__all__ = [
    "REGION_PARAM",
    "ScopedRegion",
    "region_from_params",
    "region_output",
    "scope_from_params",
]

#: One region, as an ordered list of parts in canonical coordinates —
#: 0-based `(row, col)`, float, INCLUSIVE bounds (`calc/regions.py`).
#:
#: Order is significant, exactly as it is for `Region`: parts apply left
#: to right, so an `include` after an `exclude` puts pixels back. An empty
#: list means "not scoped", which is why the default is `[]` rather than a
#: required param — every op adopting this stays backward compatible.
REGION_PARAM = OpParam(
    ptype=list,
    default=[],
    record=RecordSpec(
        fields={
            "kind": OpParam(str, choices=REGION_KINDS, doc="rect|ellipse|circle|polygon"),
            "mode": OpParam(
                str, "include", choices=REGION_MODES, doc="include | exclude"
            ),
            "bounds": OpParam(
                ptype=list,
                default=[],
                row=RowSpec(width=4),
                doc="one [r0, c0, r1, c1], 0-based INCLUSIVE — rect/ellipse/circle",
            ),
            "outline": OpParam(
                ptype=list,
                default=[],
                row=RowSpec(width=2),
                doc="[[row, col], ...] ring, closed implicitly — polygon only",
            ),
            "holes": OpParam(
                ptype=list,
                default=[],
                rings=RingsSpec(width=2),
                doc="[[[row, col], ...], ...] — inner RINGS subtracted from "
                "this part; `Shape.holes` is a sequence, so a region with two "
                "holes has to be writable here",
            ),
            "group": OpParam(
                int,
                0,
                minimum=0,
                doc="which region this part belongs to. Parts sharing a group "
                "are ONE region evaluated in order; groups are then unioned, "
                "exactly as a whole-set reference unions a RegionSet's "
                "regions. Default 0 = one region, the common case",
            ),
        }
    ),
    doc=(
        "region geometry in canonical 0-based inclusive (row, col) form; "
        "parts apply in order, empty = whole image. Mutually exclusive "
        "with roi"
    ),
)


class ScopedRegion(tuple):
    """``(rect, mask)`` — the same pairing `region_resolve.ResolvedRegion`
    hands out, so `calc.raster.masked_sum_spectrum` and
    `calc.region_stats.region_stats` consume it unchanged.

    `rect` is 1-based inclusive; `mask` is a full-image boolean array, or
    ``None`` when the selection fills `rect` exactly (ADR 0007 §3, shared
    with the named-region path through `calc.region_mask.mask_and_rect`).
    """

    __slots__ = ()

    def __new__(cls, rect: RectRoi, mask: np.ndarray | None) -> ScopedRegion:
        return super().__new__(cls, (rect, mask))

    @property
    def rect(self) -> RectRoi:
        return self[0]  # type: ignore[no-any-return]

    @property
    def mask(self) -> np.ndarray | None:
        return self[1]  # type: ignore[no-any-return]


def _shape_of(part: dict[str, Any], where: str) -> Shape:
    """One coerced record as a canonical `Shape`.

    `bounds` and `outline` are XOR by kind, and saying which is missing
    beats letting `Shape.__post_init__` report the generic invariant: the
    caller wrote JSON and needs to know which field to add.
    """
    kind = part["kind"]
    bounds, outline, holes = part["bounds"], part["outline"], part["holes"]
    rings = tuple(np.asarray(ring, dtype=np.float64) for ring in holes)
    if kind == "polygon":
        if not outline:
            raise ValueError(f"{where}: a polygon needs 'outline'")
        if bounds:
            raise ValueError(f"{where}: a polygon takes 'outline', not 'bounds'")
        return Shape(
            kind=kind, outline=np.asarray(outline, dtype=np.float64), holes=rings
        )
    if not bounds:
        raise ValueError(f"{where}: a {kind} needs 'bounds' as one [r0, c0, r1, c1]")
    if outline:
        raise ValueError(f"{where}: a {kind} takes 'bounds', not 'outline'")
    if len(bounds) != 1:
        raise ValueError(f"{where}: a {kind} takes exactly one bounds row")
    r0, c0, r1, c1 = bounds[0]
    return Shape(kind=kind, bounds=(r0, c0, r1, c1), holes=rings)


def region_from_params(
    params: dict[str, Any], shape: tuple[int, int], *, name: str = "region"
) -> ScopedRegion | None:
    """The op's `region` param as ``(rect, mask)``, or ``None`` if unscoped.

    Raises `ValueError` — which the catalogues' existing
    ``except (ValueError, TypeError)`` handlers already map to 422 — for
    geometry that is malformed or that selects no pixel of this image. An
    empty selection is refused rather than widened to the whole image, for
    the same reason everywhere else in 4C: a mis-drawn region must not
    silently become a full-image analysis.
    """
    parts_json = params.get(name) or []
    if not parts_json:
        return None
    grouped: dict[int, list[Part]] = {}
    for i, part in enumerate(parts_json):
        grouped.setdefault(int(part["group"]), []).append(
            Part(_shape_of(part, f"param '{name}[{i}]'"), mode=part["mode"])
        )
    grid = (int(shape[0]), int(shape[1]))
    # Each group is rasterized as its own Region and the results UNIONED —
    # not flattened into one parts list. A RegionSet's regions are
    # independent, so one region's `exclude` must not subtract from
    # another's pixels; flattening makes it, which silently changes the
    # answer for any whole-set reference whose regions overlap.
    mask = np.zeros(grid, dtype=bool)
    for group, parts in sorted(grouped.items()):
        mask |= rasterize(Region(id=f"{name}[{group}]", parts=tuple(parts)), grid)
    try:
        rect, exact_mask, _ = mask_and_rect(mask)
    except ValueError:
        raise ValueError(
            f"param '{name}': the geometry selects no pixels of this "
            f"{grid[0]}x{grid[1]} image"
        ) from None
    return ScopedRegion(rect, exact_mask)


def scope_from_params(
    params: dict[str, Any],
    shape: tuple[int, int],
    *,
    roi: str = "roi",
    region: str = "region",
) -> ScopedRegion | None:
    """The op's scope from EITHER the frozen `roi` string or `region`
    geometry, as the same ``(rect, mask)`` pair — or ``None`` for the whole
    image.

    An op that already had a rectangle keeps it: the legacy string still
    parses and still clamps through `calc.roi.roi_slices`, so its rect is
    the one `extract_rect_roi` would have used and the answer does not
    move. Only the mask is new, and for a rectangle it is ``None``.

    Passing BOTH raises, per ADR 0007 §5: two scopes is a caller bug, and
    a precedence rule would hide it behind a plausible number.
    """
    rect = parse_roi_param(params[roi]) if roi in params else None
    geometry = params.get(region) or []
    if rect is not None and geometry:
        raise ValueError(f"give either '{roi}' or '{region}', not both")
    if geometry:
        return region_from_params(params, shape, name=region)
    if rect is None:
        return None
    # Clamp through the shared helper so the REPORTED rect is the one the
    # crop actually used — an out-of-bounds corner would otherwise be
    # recorded as asked for rather than as applied.
    rows, cols = roi_slices(shape, rect)
    return ScopedRegion((rows.start + 1, cols.start + 1, rows.stop, cols.stop), None)


#: How much of the analysis a region actually constrained. Labels are always
#: exact; a neighbourhood-based method still reads the bounding box, and
#: saying so is cheaper than a reader assuming the stronger claim
#: (`calc/region_segment.py` carries the reasoning).
LABEL_CONTEXT_EXACT = "exact-mask"
LABEL_CONTEXT_BBOX = "bounding-box"
#: The algorithm read the SELECTED pixels, but through a neighbourhood, so
#: the region's own edge acted as an image edge. Weaker than `exact-mask`
#: (the answer depends on the region's shape, not only on which pixels it
#: chose) and stronger than `bounding-box` (nothing outside the mask was
#: read at all). `particles`/`efd_similarity` with `use_watershed` are the
#: case: the polarity fill makes the boundary background, so basins near
#: it differ from the ones the same pixels would produce unscoped.
LABEL_CONTEXT_MASKED_NEIGHBOURHOOD = "masked-neighbourhood"


def region_output(
    scoped: ScopedRegion,
    *,
    label_context: str | None = None,
    clipped: bool | None = None,
) -> dict[str, Any]:
    """The `region` provenance envelope, one spelling for every consumer.

    Mirrors `sum_spectrum`'s table from 4C-1 — same columns, same
    `position_convention`, same `exact_mask` meaning (False = the rect IS
    the selection, ADR 0007 §3) — so a reader who has learned one
    region-scoped result can read them all.
    """
    data: dict[str, Any] = {
        "columns": ["row0", "col0", "row1", "col1"],
        "units": ["px", "px", "px", "px"],
        "position_convention": "1-based, inclusive, clamped",
        "exact_mask": scoped.mask is not None,
        "rows": [list(scoped.rect)],
    }
    if label_context is not None:
        data["label_context"] = label_context
    if clipped is not None:
        # True when the mask actually removed a LABELLED pixel — the
        # signal that features in this result were cut by the boundary
        # and renumbered, rather than merely selected
        data["region_clipped"] = clipped
    return output("table", "region", data)
