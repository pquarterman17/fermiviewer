"""Image endpoints: open, upload, metadata, render, histogram (handoff §8)."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Response, UploadFile
from PIL import Image
from pydantic import BaseModel

from fermiviewer.calc.render import histogram, to_display, to_uint16_norm
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.io.registry import (
    UnsupportedFormatError,
    load_auto,
    supported_extensions,
)
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
    from fermiviewer.routes.calibration import auto_apply_calibration

    for i, ds in opened:
        auto_apply_calibration(i, ds)
    return [
        ImageMeta.from_datastruct(i, store.name(i), store.get(i))
        for i, _ in opened
    ]


@router.post("/session/upload")
async def session_upload(files: list[UploadFile]) -> list[ImageMeta]:
    """Open files sent by the browser's native picker.

    The SPA can't hand the server a filesystem path, so the picker
    uploads bytes (a memcpy on localhost); each file is staged to a
    temp file under its original name so extension dispatch and
    content sniffers behave exactly like /session/open.
    """
    if not files:
        raise HTTPException(422, "no files in upload")
    metas: list[ImageMeta] = []
    with tempfile.TemporaryDirectory(prefix="fv_upload_") as tmp:
        for up in files:
            name = Path(up.filename or "upload").name  # strip any path
            staged = Path(tmp) / name
            staged.write_bytes(await up.read())
            try:
                ds = load_auto(staged)
            except UnsupportedFormatError as e:
                raise HTTPException(415, str(e)) from None
            except ValueError as e:
                raise HTTPException(422, f"{name}: {e}") from None
            # don't leak the vanishing temp path as the source
            ds.metadata["source"] = name
            img_id = store.add_parsed(ds, name)
            from fermiviewer.routes.calibration import (
                auto_apply_calibration,
            )

            auto_apply_calibration(img_id, ds)
            metas.append(
                ImageMeta.from_datastruct(img_id, name, store.get(img_id))
            )
    return metas


class OpenRawRequest(BaseModel):
    path: str
    width: int
    height: int
    bit_depth: int = 16
    byte_order: str = "little"
    header_bytes: int = 0


@router.post("/session/open-raw")
def session_open_raw(req: OpenRawRequest) -> ImageMeta:
    """Headerless binary import with explicit geometry (checklist L —
    the RAW dialog flow; load_auto can't infer .raw dimensions)."""
    from fermiviewer.io.images import load_raw

    try:
        ds = load_raw(req.path, req.width, req.height,
                      bit_depth=req.bit_depth, byte_order=req.byte_order,
                      header_bytes=req.header_bytes)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    name = Path(req.path).name
    img_id = store.add_parsed(ds, name)
    return ImageMeta.from_datastruct(img_id, name, store.get(img_id))


class RenameRequest(BaseModel):
    name: str


@router.post("/image/{img_id}/rename")
def image_rename(img_id: str, req: RenameRequest) -> ImageMeta:
    if not req.name.strip():
        raise HTTPException(422, "name cannot be empty")
    try:
        store.rename(img_id, req.name.strip())
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    return ImageMeta.from_datastruct(img_id, store.name(img_id),
                                     store.get(img_id))


@router.post("/image/{img_id}/explode")
def image_explode(img_id: str) -> list[ImageMeta]:
    """Register every slice of a 3D cube as its own derived image
    (checklist K multi-frame stacks: the filmstrip becomes the frame
    navigator, and align/MIP/GIF then operate on the frames)."""
    ds = _get(img_id)
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise HTTPException(400, "only 3D cubes can be exploded")
    n = int(ds.data.shape[2])
    if n > 256:
        raise HTTPException(
            422, f"cube has {n} slices — explode is capped at 256"
        )
    name = store.name(img_id)
    stem = name.rsplit(".", 1)[0] or name
    metas: list[ImageMeta] = []
    for k in range(n):
        frame = np.ascontiguousarray(
            np.asarray(ds.data[:, :, k], dtype=np.float64)
        )
        derived = DataStruct(
            data=frame,
            kind=DataKind.IMAGE,
            axes=(ds.axes[0], ds.axes[1]),
            metadata={
                "source": f"frame {k + 1} of {name}",
                "parser": "derived",
                "frame_index": k + 1,
            },
        )
        fid = store.add_derived(derived, f"{stem}[{k + 1}]", img_id)
        metas.append(
            ImageMeta.from_datastruct(fid, store.name(fid), derived)
        )
    return metas


class MetadataPatch(BaseModel):
    updates: dict[str, str | float | int | bool]


@router.post("/image/{img_id}/metadata")
def image_metadata_update(img_id: str, req: MetadataPatch) -> ImageMeta:
    """Edit/add metadata entries (checklist K metadata editor)."""
    ds = _get(img_id)
    for k, v in req.updates.items():
        if not k.strip():
            raise HTTPException(422, "metadata keys cannot be empty")
        ds.metadata[k.strip()] = v
    return ImageMeta.from_datastruct(img_id, store.name(img_id), ds)


@router.get("/session/supported-extensions")
def session_supported_extensions() -> dict[str, list[str]]:
    """Extension list for the picker's accept filter."""
    return {"extensions": list(supported_extensions())}


@router.get("/session/launch-dir")
def session_launch_dir() -> dict[str, object]:
    """The folder the app was launched from plus its supported images, so
    the SPA can default the Open dialog there (CLI `fermiviewer <dir>`).

    Returns ``{"dir": null, "files": []}`` when no launch dir is set
    (installed app / server started without one) or it holds no supported
    files — the frontend then falls back to the OS-native picker.
    """
    from fermiviewer import launch

    d = launch.launch_dir()
    if d is None or not d.is_dir():
        return {"dir": None, "files": []}
    exts = set(supported_extensions())
    files: list[dict[str, str]] = []
    try:
        entries = sorted(d.iterdir(), key=lambda q: q.name.lower())
    except OSError:  # unreadable directory — treat as empty
        return {"dir": str(d), "files": [], "truncated": False}
    for p in entries:
        if p.suffix.lower() not in exts:
            continue
        try:
            is_file = p.is_file()  # can raise on OneDrive cloud-only files
        except OSError:
            continue  # skip the unreadable entry, keep the rest
        if is_file:
            files.append({"name": p.name, "path": str(p)})
    return {"dir": str(d), "files": files[:500], "truncated": len(files) > 500}


@router.get("/session/images")
def session_images() -> list[ImageMeta]:
    return [
        ImageMeta.from_datastruct(i, store.name(i), store.get(i)) for i in store.ids()
    ]


@router.delete("/image/{img_id}")
def close_image(img_id: str) -> dict[str, str]:
    _get(img_id)
    store.close(img_id)
    evict_level_cache(img_id)
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
def image_data16(img_id: str, frame: int | None = None) -> Response:
    """Full-range-normalized uint16 raster, little-endian, row-major.

    Feeds the client-side WebGL window/level/gamma/LUT shader (handoff
    section-13 render path). Real values reconstruct from X-Min/X-Max.

    For spectrum_image (3D stack) kinds, the optional `frame` query param
    selects a channel (0-based). Without frame, falls back to the energy sum.
    The response header X-N-Frames reports the total frame count so the
    client can build the stepper without a separate metadata call.
    """
    ds = _get(img_id)
    n_frames: int | None = None
    if ds.kind is DataKind.SPECTRUM_IMAGE:
        n_frames = int(ds.data.shape[2])
        if frame is not None:
            clamped = max(0, min(n_frames - 1, frame))
            raster = np.ascontiguousarray(
                np.asarray(ds.data[:, :, clamped], dtype=np.float64)
            )
        else:
            raster = np.asarray(ds.data, dtype=np.float64).sum(axis=2)
    else:
        raster = _raster(ds)
    u16, vmin, vmax = to_uint16_norm(raster)
    extra: dict[str, str] = {}
    if n_frames is not None:
        extra["X-N-Frames"] = str(n_frames)
    return Response(
        content=u16.astype("<u2").tobytes(),
        media_type="application/octet-stream",
        headers={
            "X-Shape": f"{raster.shape[0]},{raster.shape[1]}",
            "X-Min": repr(vmin),
            "X-Max": repr(vmax),
            **extra,
        },
    )


_TILE_SIZE = 256
_LEVEL_CACHE: dict[tuple[str, int], np.ndarray] = {}


def evict_level_cache(img_id: str) -> None:
    """Drop every cached pyramid level for `img_id` — called wherever an
    image leaves the session store so a closed image's full-res rasters
    (up to ~64 entries, ~1 GB worst case) aren't retained after close."""
    for key in [k for k in _LEVEL_CACHE if k[0] == img_id]:
        del _LEVEL_CACHE[key]


def clear_level_cache() -> None:
    """Drop the whole pyramid cache — called when the store is wholesale
    replaced (session/workspace load), since every id it might reference
    is about to be gone."""
    _LEVEL_CACHE.clear()


def _pyramid_level(img_id: str, z: int) -> np.ndarray:
    """8-bit full-range display raster downscaled 2^z by block mean."""
    key = (img_id, z)
    cached = _LEVEL_CACHE.get(key)
    if cached is not None:
        return cached
    raster = _raster(_get(img_id))
    buf8 = to_display(raster)
    if z > 0:
        f = 1 << z
        h, w = buf8.shape
        hb, wb = max(1, h // f), max(1, w // f)
        buf8 = (
            buf8[: hb * f, : wb * f]
            .reshape(hb, f, wb, f)
            .mean(axis=(1, 3))
            .astype(np.uint8)
        )
    # tiny cache: a handful of levels per open image
    if len(_LEVEL_CACHE) > 64:
        _LEVEL_CACHE.clear()
    _LEVEL_CACHE[key] = buf8
    return buf8


@router.get("/image/{img_id}/tile-info")
def tile_info(img_id: str) -> dict[str, int]:
    raster = _raster(_get(img_id))
    h, w = raster.shape
    levels = 1
    while (max(h, w) >> (levels - 1)) > _TILE_SIZE:
        levels += 1
    return {
        "tile_size": _TILE_SIZE,
        "levels": levels,
        "width": int(w),
        "height": int(h),
    }


@router.get("/image/{img_id}/tile")
def image_tile(img_id: str, z: int = 0, x: int = 0, y: int = 0) -> Response:
    """PNG tile (x, y) of pyramid level z (downscale 2^z) — handoff §8.

    Edge tiles are cropped; out-of-range tiles are 404.
    """
    if z < 0 or z > 12 or x < 0 or y < 0:
        raise HTTPException(422, "z/x/y out of range")
    level = _pyramid_level(img_id, z)
    h, w = level.shape
    r0, c0 = y * _TILE_SIZE, x * _TILE_SIZE
    if r0 >= h or c0 >= w:
        raise HTTPException(404, "tile outside image")
    tile = level[r0 : r0 + _TILE_SIZE, c0 : c0 + _TILE_SIZE]
    png = io.BytesIO()
    Image.fromarray(tile, mode="L").save(png, format="PNG")
    return Response(content=png.getvalue(), media_type="image/png")


@router.get("/image/{img_id}/spectrum")
def image_spectrum(
    img_id: str,
    row0: int | None = None,
    col0: int | None = None,
    row1: int | None = None,
    col1: int | None = None,
) -> dict[str, object]:
    """Sum spectrum (SI cubes) or the spectrum itself (1D) for the
    EELS/EDS workshop plots. Optional 1-based inclusive rect → the
    region-summed spectrum (SI explorer: pixel/ROI spectra)."""
    ds = _get(img_id)
    if ds.kind is DataKind.IMAGE:
        raise HTTPException(400, "2D images have no spectral axis")
    energy = ds.energy_axis
    region = None
    if ds.kind is DataKind.SPECTRUM_IMAGE and None not in (
        row0, col0, row1, col1
    ):
        h, w, _ = ds.data.shape
        assert row0 is not None and row1 is not None
        assert col0 is not None and col1 is not None
        r0, r1 = sorted((row0, row1))
        c0, c1 = sorted((col0, col1))
        r0, c0 = max(r0, 1), max(c0, 1)
        r1, c1 = min(r1, h), min(c1, w)
        if r0 > r1 or c0 > c1:
            raise HTTPException(422, "region is empty after clamping")
        cube = np.asarray(ds.data, dtype=np.float64)
        counts = cube[r0 - 1:r1, c0 - 1:c1, :].sum(axis=(0, 1))
        region = [r0, c0, r1, c1]
    else:
        counts = ds.sum_spectrum()
    return {
        "energy": energy.tolist(),
        "counts": np.asarray(counts, dtype=np.float64).tolist(),
        "units": ds.energy_cal.units,
        "region": region,
    }


@router.get("/image/{img_id}/histogram")
def image_histogram(img_id: str, bins: int = 256) -> dict[str, list[float]]:
    if not 2 <= bins <= 4096:
        raise HTTPException(422, "bins must be in [2, 4096]")
    centers, counts = histogram(_raster(_get(img_id)), bins)
    return {"bins": centers.tolist(), "counts": counts.tolist()}
