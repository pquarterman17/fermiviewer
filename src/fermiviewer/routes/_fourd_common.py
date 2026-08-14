"""Route-layer helpers shared by the 4D-STEM route modules.

`routes/fourd.py` carries the Phase-1 surface (list/meta/nav/pattern/
mean-pattern/reshape/virtual-detector); `routes/fourd_com.py` carries the
COM-derived phase-contrast family (COM, and the DPC/iDPC work that builds
on it). Both need the same dataset lookup, the same streamed block-size
cap and the same optional-center contract, and neither can import the
other without a cycle — so those three live here, following
`routes/_arrays.py`'s precedent for a shared route-layer helper module.

These are route-layer, not `calc/`: they raise `HTTPException`, which the
pure layer must never do.
"""

from __future__ import annotations

from fastapi import HTTPException

from fermiviewer.calc.fourd.dataset import FourDDataset
from fermiviewer.session_fourd import UnknownFourDError, fourd_store

__all__ = [
    "BLOCK_BYTES_CAP",
    "block_rows_for_byte_cap",
    "get_fourd",
    "validate_optional_center",
]


def get_fourd(fourd_id: str) -> FourDDataset:
    try:
        return fourd_store.get(fourd_id)
    except UnknownFourDError:
        raise HTTPException(404, f"unknown 4D dataset id: {fourd_id}") from None


# Block size for the streamed reductions, capped by BYTES rather than rows:
# computed per-dataset from det_shape/scan_x/dtype rather than a fixed row
# count — a 4k direct-electron detector needs far fewer rows per block than
# a small Merlin frame does for the same memory ceiling. (This is a
# route-layer choice independent of FourDDataset's own default block_rows,
# which is sized for its *unweighted* nav_image/mean_pattern reductions.)
# Shared by /virtual-detector and /com — both are single-pass streamed
# reductions over the same block shape, just with a different per-pixel
# weighting, so the same cap applies unchanged.
BLOCK_BYTES_CAP = 64 * 1024 * 1024


def block_rows_for_byte_cap(
    ds4: FourDDataset, cap_bytes: int = BLOCK_BYTES_CAP
) -> int:
    scan_x = ds4.scan_shape[1]
    det_ky, det_kx = ds4.det_shape
    bytes_per_row = scan_x * det_ky * det_kx * ds4.dtype.itemsize
    if bytes_per_row <= 0:
        return ds4.scan_shape[0]
    return max(1, cap_bytes // bytes_per_row)


def validate_optional_center(
    center_ky: float | None, center_kx: float | None, det_shape: tuple[int, int]
) -> None:
    """Both-or-neither + in-bounds validation for an optional detector
    center. Shared by `/virtual-detector` and `/com` (PLAN_4DSTEM #7) —
    both accept the same null-means-auto-center contract."""
    has_center = (center_ky is not None, center_kx is not None)
    if has_center[0] != has_center[1]:
        raise HTTPException(
            422,
            "center_ky and center_kx must both be given, or both omitted "
            "for auto-center",
        )
    if all(has_center):
        assert center_ky is not None and center_kx is not None
        if not (0 <= center_ky <= det_shape[0] - 1):
            raise HTTPException(
                422,
                f"center_ky {center_ky} outside detector bounds "
                f"[0, {det_shape[0] - 1}]",
            )
        if not (0 <= center_kx <= det_shape[1] - 1):
            raise HTTPException(
                422,
                f"center_kx {center_kx} outside detector bounds "
                f"[0, {det_shape[1] - 1}]",
            )
