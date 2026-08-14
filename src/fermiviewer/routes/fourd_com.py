"""COM-derived phase-contrast endpoints for 4D-STEM (PLAN_4DSTEM #7-#9).

Split out of `routes/fourd.py`, which carries the Phase-1 surface
(list/meta/nav/pattern/mean-pattern/reshape/virtual-detector) and was at
430 of its 500-line ceiling with the DPC (#8) and iDPC (#9) routes still
to land. The two modules share their dataset lookup, streamed block-size
cap and optional-center contract via `routes/_fourd_common.py`.

Thin adapters only — all real work lives in `calc/fourd/`.

RAM: `POST /api/fourd/{id}/com` streams row-blocks under the same
`block_rows_for_byte_cap` cap `/virtual-detector` uses, once, into two
scan-shaped maps (COMy, COMx), each registered as an ordinary derived 2D
image the same way `/nav` does. A null center costs one extra whole-cube
pass via `ds4.mean_pattern` (cached after first use) to seed an auto
center; an explicit center never touches `ds4.mean_pattern` at all.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel

from fermiviewer.calc.fourd.com import com_maps, resolve_center
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.routes._arrays import value_error_as_422
from fermiviewer.routes._fourd_common import (
    block_rows_for_byte_cap,
    get_fourd,
    validate_optional_center,
)
from fermiviewer.session import store as image_store
from fermiviewer.session_fourd import fourd_store

router = APIRouter(prefix="/api")


class ComRequest(BaseModel):
    """Descan reference center in 0-based ``(ky, kx)`` float pixels (see
    `calc/fourd/geometry.py`). A null ``center_ky``/``center_kx`` pair
    auto-seeds from ``pattern_center(mean_pattern)`` — the SAME auto-center
    policy `/virtual-detector` uses. The policy itself lives in
    `calc.fourd.resolve_center` (this route does no math); the route calls
    it explicitly so it can RECORD the resolved center on both maps."""

    center_ky: float | None = None
    center_kx: float | None = None
    name: str | None = None


class ComMapsResponse(BaseModel):
    """Both derived maps from one `/com` call, each an ordinary registered
    2D image (own id, own metadata) — this wrapper is just the pair."""

    comy: ImageMeta
    comx: ImageMeta


@router.post("/fourd/{fourd_id}/com")
def fourd_com(fourd_id: str, req: ComRequest) -> ComMapsResponse:
    """Per-probe center-of-mass shift maps — the basis for DPC/iDPC
    (PLAN_4DSTEM #8/#9). Registers COMy and COMx as two ordinary derived 2D
    images through the same `add_derived` path `/nav` and
    `/virtual-detector` use, so they inherit LUT/measure/export for free
    (same always-register convention as `/virtual-detector`: each call is a
    distinct analysis, not deduplicated like `/nav`).

    All center-resolution policy (caller-supplied vs.
    ``pattern_center(mean_pattern)`` auto-seed) lives in
    `calc.fourd.com.com_maps` — this route only validates the request,
    streams the cube once, and registers the two results. See the module
    docstring for the RAM budget.
    """
    ds4 = get_fourd(fourd_id)
    validate_optional_center(req.center_ky, req.center_kx, ds4.det_shape)

    # Resolve the center BEFORE computing so the maps can record the descan
    # reference they were actually measured against — on the auto path
    # `req.center_ky`/`kx` are null, and a stored null would lose it (the
    # /virtual-detector route resolves-then-records for the same reason).
    if req.center_ky is not None and req.center_kx is not None:
        cy, cx = req.center_ky, req.center_kx
    else:
        # only the auto-center path pays for a (possibly first-touch,
        # whole-cube) mean_pattern access — an explicit center never does.
        with value_error_as_422():
            cy, cx = resolve_center(None, ds4.mean_pattern)

    block_rows = block_rows_for_byte_cap(ds4)
    with value_error_as_422():
        com_y, com_x = com_maps(
            ds4.iter_scan_rows(block_rows=block_rows), center=(cy, cx)
        )

    base_name = fourd_store.name(fourd_id)

    def _register(map_arr: np.ndarray, axis: str, label: str) -> ImageMeta:
        name = f"{req.name} ({label})" if req.name else f"{label}({base_name})"
        struct = DataStruct(
            data=np.ascontiguousarray(map_arr),
            kind=DataKind.IMAGE,
            axes=(ds4.scan_axes[0], ds4.scan_axes[1]),
            metadata={
                "source": name,
                "parser": "fourd-com",
                "analysis": axis,
                "fourd_id": fourd_id,
                "center_ky": float(cy),
                "center_kx": float(cx),
            },
        )
        img_id = image_store.add_derived(struct, name, fourd_id)
        return ImageMeta.from_datastruct(img_id, image_store.name(img_id), struct)

    return ComMapsResponse(
        comy=_register(com_y, "com_y", "COMy"),
        comx=_register(com_x, "com_x", "COMx"),
    )
