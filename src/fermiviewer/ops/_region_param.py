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
from fermiviewer.calc.roi import RectRoi
from fermiviewer.ops.base import OpParam, RecordSpec, RowSpec

__all__ = ["REGION_PARAM", "ScopedRegion", "region_from_params"]

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
                row=RowSpec(width=2),
                doc="[[row, col], ...] — ONE inner ring subtracted from this part",
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
    rings = (np.asarray(holes, dtype=np.float64),) if holes else ()
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
    parts = tuple(
        Part(_shape_of(part, f"param '{name}[{i}]'"), mode=part["mode"])
        for i, part in enumerate(parts_json)
    )
    grid = (int(shape[0]), int(shape[1]))
    mask = rasterize(Region(id=name, parts=parts), grid)
    try:
        rect, exact_mask, _ = mask_and_rect(mask)
    except ValueError:
        raise ValueError(
            f"param '{name}': the geometry selects no pixels of this "
            f"{grid[0]}x{grid[1]} image"
        ) from None
    return ScopedRegion(rect, exact_mask)
