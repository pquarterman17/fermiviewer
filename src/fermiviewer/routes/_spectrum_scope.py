"""How `GET /image/{id}/spectrum` decides which pixels it sums — 4C-1.

Split out of `routes/images.py` when adding the named-region path pushed
that module past the 500-line guard. It is one cohesive decision — the
route asks "which pixels?" and gets back the counts plus what to report
about them — so it moves as a unit rather than being trimmed in place.

**Why the resolution happens here and not in the `sum_spectrum` op.**
`ops/registry.py` states the rule: auxiliary inputs reach an op as
already-resolved `DataStruct`s because "the caller owns the session
store, so the pure layer never looks an id up". A region reference is an
id, so resolving it belongs on this side of that line. The op keeps its
1-based corner params and stays reproducible from its params alone.
"""

from __future__ import annotations

import numpy as np
from fastapi import HTTPException

from fermiviewer.calc.raster import masked_sum_spectrum, region_sum_spectrum
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.project_session import project
from fermiviewer.region_resolve import resolve_region

__all__ = ["ScopedSpectrum", "scoped_spectrum"]


class ScopedSpectrum(tuple):
    """``(counts, region, exact_mask)``.

    `region` is the 1-based inclusive bounding rect, or ``None`` for a
    whole-cube sum — unchanged from before 4C-1, so an existing client
    keeps reading the field it always read. `exact_mask` says whether the
    summed pixels are NARROWER than that rect, which is the only new
    thing a client has to learn to read a region-scoped answer correctly.
    """

    __slots__ = ()

    def __new__(
        cls, counts: np.ndarray, region: list[int] | None, exact_mask: bool
    ) -> ScopedSpectrum:
        return super().__new__(cls, (counts, region, exact_mask))


def scoped_spectrum(
    ds: DataStruct,
    img_id: str,
    *,
    row0: int | None,
    col0: int | None,
    row1: int | None,
    col1: int | None,
    region_ref: str,
) -> ScopedSpectrum:
    """Sum `ds` over the scope the caller asked for.

    Exactly one scope may be given: the legacy 1-based inclusive rect, or
    `region_ref` (``"set_id"`` or ``"set_id/region_id"``) summed over its
    EXACT mask. Both together is a 422 rather than a precedence rule — a
    caller sending two scopes has a bug, and honouring one would hide it.

    A scope on a 1D spectrum is ignored, as it always has been: that
    behaviour predates 4C and changing it here would break clients that
    pass a rect unconditionally.
    """
    corners = None not in (row0, col0, row1, col1)
    if corners and region_ref:
        raise HTTPException(
            422, "give either row0/col0/row1/col1 or region_ref, not both"
        )
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        return ScopedSpectrum(ds.sum_spectrum(), None, False)

    if region_ref:
        grid = (int(ds.data.shape[0]), int(ds.data.shape[1]))
        try:
            resolved = resolve_region(
                grid,
                region=region_ref,
                sets=project.current().region_sets,
                image_id=img_id,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        counts = masked_sum_spectrum(ds.data, resolved.rect, resolved.mask)
        return ScopedSpectrum(counts, list(resolved.rect), resolved.is_exact)

    if corners:
        assert row0 is not None and row1 is not None
        assert col0 is not None and col1 is not None
        # clamp → slice → sum lives in calc (wave D, ADR 0005 §1 — shared
        # with the registered op)
        try:
            counts, rect = region_sum_spectrum(ds.data, row0, col0, row1, col1)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return ScopedSpectrum(counts, list(rect), False)

    return ScopedSpectrum(ds.sum_spectrum(), None, False)
