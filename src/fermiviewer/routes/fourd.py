"""4D-STEM endpoints: list metadata, navigation image, single/mean pattern.

Thin adapters only — all real work (streamed reductions, lazy access) lives
in `calc/fourd/dataset.py`. Worst-case RAM per route:

  * `GET /api/fourd`             — metadata only, negligible.
  * `GET /api/fourd/{id}/meta`   — metadata only, negligible.
  * `GET /api/fourd/{id}/nav`    — streams row-blocks (see FourDDataset's
    docstring for the per-block cost) to build one `scan_shape`-sized
    float64 array, then registers it as an ordinary derived 2D image in the
    NORMAL image store — a few MB even for a large scan, never the 4D cube.
  * `GET /api/fourd/{id}/pattern`      — one det_shape array, negligible.
  * `GET /api/fourd/{id}/mean-pattern` — streams row-blocks into one
    det_shape float64 accumulator; same per-block cost as `/nav`.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException, Response

from fermiviewer.calc.fourd.dataset import FourDDataset
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.models import FourDMeta, ImageMeta
from fermiviewer.routes.images import encode_raster_u16
from fermiviewer.session import UnknownImageError
from fermiviewer.session import store as image_store
from fermiviewer.session_fourd import UnknownFourDError, fourd_store

router = APIRouter(prefix="/api")


def _get(fourd_id: str) -> FourDDataset:
    try:
        return fourd_store.get(fourd_id)
    except UnknownFourDError:
        raise HTTPException(404, f"unknown 4D dataset id: {fourd_id}") from None


@router.get("/fourd")
def list_fourd() -> list[FourDMeta]:
    return [
        FourDMeta.from_dataset(i, fourd_store.name(i), fourd_store.get(i))
        for i in fourd_store.ids()
    ]


@router.get("/fourd/{fourd_id}/meta")
def fourd_meta(fourd_id: str) -> FourDMeta:
    ds4 = _get(fourd_id)
    return FourDMeta.from_dataset(fourd_id, fourd_store.name(fourd_id), ds4)


@router.get("/fourd/{fourd_id}/nav")
def fourd_nav(fourd_id: str) -> ImageMeta:
    """The navigation image (detector-summed intensity per scan position),
    registered as a normal derived 2D image so it flows through the
    existing LUT/render/measure/export pipeline untouched.

    Idempotent: a second call returns the SAME already-registered image
    (re-registering only if the user has since closed it), rather than
    flooding the image store with a fresh derived image every call.
    """
    ds4 = _get(fourd_id)
    existing = fourd_store.nav_image_id(fourd_id)
    if existing is not None:
        try:
            return ImageMeta.from_datastruct(
                existing, image_store.name(existing), image_store.get(existing)
            )
        except UnknownImageError:
            pass  # user closed it — fall through and re-register

    name = f"nav({fourd_store.name(fourd_id)})"
    struct = DataStruct(
        data=np.ascontiguousarray(ds4.nav_image),
        kind=DataKind.IMAGE,
        axes=(ds4.scan_axes[0], ds4.scan_axes[1]),
        metadata={
            "source": name,
            "parser": "fourd-nav",
            "fourd_id": fourd_id,
        },
    )
    img_id = image_store.add_derived(struct, name, fourd_id)
    fourd_store.set_nav_image_id(fourd_id, img_id)
    return ImageMeta.from_datastruct(img_id, image_store.name(img_id), struct)


@router.get("/fourd/{fourd_id}/pattern")
def fourd_pattern(fourd_id: str, y: int, x: int) -> Response:
    """A single diffraction pattern at scan position (y, x), uint16-encoded
    the same way `/image/{id}/data16` is (see `encode_raster_u16`) —
    register-as-image-per-call would flood the store, so this returns the
    pixels directly instead."""
    ds4 = _get(fourd_id)
    try:
        dp = ds4.pattern(y, x)
    except IndexError as e:
        raise HTTPException(422, str(e)) from None
    return encode_raster_u16(np.asarray(dp, dtype=np.float64))


@router.get("/fourd/{fourd_id}/mean-pattern")
def fourd_mean_pattern(fourd_id: str) -> Response:
    """The scan-averaged diffraction pattern, uint16-encoded like `/pattern`."""
    ds4 = _get(fourd_id)
    return encode_raster_u16(np.asarray(ds4.mean_pattern, dtype=np.float64))
