"""Image endpoints: open, metadata, render, histogram (handoff §8)."""

from __future__ import annotations

import io

import numpy as np
from fastapi import APIRouter, HTTPException, Response
from PIL import Image

from fermiviewer.calc.render import histogram, to_display, to_uint16_norm
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.io.registry import UnsupportedFormatError
from fermiviewer.models import ImageMeta, OpenRequest
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _get(img_id: str) -> DataStruct:
    try:
        return store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None


def _raster(ds: DataStruct) -> np.ndarray:
    """2D view of any kind: image as-is; SI cube summed over energy."""
    if ds.kind is DataKind.IMAGE:
        return ds.data
    if ds.kind is DataKind.SPECTRUM_IMAGE:
        summed: np.ndarray = np.asarray(ds.data, dtype=np.float64).sum(axis=2)
        return summed
    raise HTTPException(400, "1D spectra have no raster — use the spectrum endpoints")


@router.post("/session/open")
def session_open(req: OpenRequest) -> list[ImageMeta]:
    try:
        opened = store.open_paths(req.paths)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except UnsupportedFormatError as e:
        raise HTTPException(415, str(e)) from None
    except ValueError as e:  # parser format errors
        raise HTTPException(422, str(e)) from None
    return [ImageMeta.from_datastruct(i, store.name(i), ds) for i, ds in opened]


@router.get("/session/images")
def session_images() -> list[ImageMeta]:
    return [
        ImageMeta.from_datastruct(i, store.name(i), store.get(i)) for i in store.ids()
    ]


@router.delete("/image/{img_id}")
def close_image(img_id: str) -> dict[str, str]:
    _get(img_id)
    store.close(img_id)
    return {"status": "closed"}


@router.get("/image/{img_id}/meta")
def image_meta(img_id: str) -> ImageMeta:
    return ImageMeta.from_datastruct(img_id, store.name(img_id), _get(img_id))


@router.get("/image/{img_id}/render")
def image_render(
    img_id: str,
    lo: float | None = None,
    hi: float | None = None,
    gamma: float = 1.0,
) -> Response:
    """Windowed 8-bit grayscale PNG. (Client-side WebGL LUT supersedes
    this for interactive contrast; this is the simple/export path.)"""
    raster = _raster(_get(img_id))
    buf8 = to_display(raster, lo, hi, gamma)
    png = io.BytesIO()
    Image.fromarray(buf8, mode="L").save(png, format="PNG")
    return Response(content=png.getvalue(), media_type="image/png")


@router.get("/image/{img_id}/data16")
def image_data16(img_id: str) -> Response:
    """Full-range-normalized uint16 raster, little-endian, row-major.

    Feeds the client-side WebGL window/level/gamma/LUT shader (handoff
    section-13 render path). Real values reconstruct from X-Min/X-Max.
    """
    raster = _raster(_get(img_id))
    u16, vmin, vmax = to_uint16_norm(raster)
    return Response(
        content=u16.astype("<u2").tobytes(),
        media_type="application/octet-stream",
        headers={
            "X-Shape": f"{raster.shape[0]},{raster.shape[1]}",
            "X-Min": repr(vmin),
            "X-Max": repr(vmax),
        },
    )


@router.get("/image/{img_id}/spectrum")
def image_spectrum(img_id: str) -> dict[str, object]:
    """Sum spectrum (SI cubes) or the spectrum itself (1D) for the
    EELS/EDS workshop plots."""
    ds = _get(img_id)
    if ds.kind is DataKind.IMAGE:
        raise HTTPException(400, "2D images have no spectral axis")
    energy = ds.energy_axis
    counts = ds.sum_spectrum()
    return {
        "energy": energy.tolist(),
        "counts": np.asarray(counts, dtype=np.float64).tolist(),
        "units": ds.energy_cal.units,
    }


@router.get("/image/{img_id}/histogram")
def image_histogram(img_id: str, bins: int = 256) -> dict[str, list[float]]:
    if not 2 <= bins <= 4096:
        raise HTTPException(422, "bins must be in [2, 4096]")
    centers, counts = histogram(_raster(_get(img_id)), bins)
    return {"bins": centers.tolist(), "counts": counts.tolist()}
