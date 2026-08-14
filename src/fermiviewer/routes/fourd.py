"""4D-STEM endpoints: list metadata, navigation image, single/mean pattern,
virtual-detector imaging.

Thin adapters only — all real work (streamed reductions, lazy access) lives
in `calc/fourd/dataset.py` and `calc/fourd/virtual.py`/`geometry.py`.
Worst-case RAM per route:

  * `GET /api/fourd`             — metadata only, negligible.
  * `GET /api/fourd/{id}/meta`   — metadata only, negligible.
  * `GET /api/fourd/{id}/nav`    — streams row-blocks (see FourDDataset's
    docstring for the per-block cost) to build one `scan_shape`-sized
    float64 array, then registers it as an ordinary derived 2D image in the
    NORMAL image store — a few MB even for a large scan, never the 4D cube.
  * `GET /api/fourd/{id}/pattern`      — one det_shape array, negligible.
  * `GET /api/fourd/{id}/mean-pattern` — streams row-blocks into one
    det_shape float64 accumulator; same per-block cost as `/nav`.
  * `POST /api/fourd/{id}/virtual-detector` — streams row-blocks (capped at
    ~64 MB per in-flight block, see `_block_rows_for_byte_cap`) into a
    reciprocal-space-aperture reduction, then registers the resulting
    scan-shaped map the same way `/nav` does. A null center additionally
    streams the whole cube ONCE MORE via `ds4.mean_pattern` (cached after
    first use) to seed an auto center — same per-block cost, an extra pass.
  * `POST /api/fourd/{id}/com` — same `_block_rows_for_byte_cap` cap as
    `/virtual-detector`, streamed once through `calc.fourd.com.com_maps`
    into two scan-shaped maps (COMy, COMx), each registered the same way
    `/nav` does. A null center likewise costs one extra whole-cube pass via
    `ds4.mean_pattern` (cached after first use) to seed an auto center; an
    explicit center never touches `ds4.mean_pattern` at all.

NOTE naming: `routes/imaging_ops.py` has an UNRELATED `/analyze/vdf`
endpoint (2D FFT-aperture masking of a single already-2D image). This
module's virtual-detector endpoint is a completely different operation
(reciprocal-space aperture integrated over every probe position of a 4D
scan) and is deliberately never abbreviated "vdf" anywhere in its route
path, calc functions, or tests, to avoid colliding with that name.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from fermiviewer.calc.fourd.com import com_maps
from fermiviewer.calc.fourd.dataset import FourDDataset
from fermiviewer.calc.fourd.geometry import aperture_mask, pattern_center
from fermiviewer.calc.fourd.virtual import virtual_detector
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.io.fourd.mib import load_mib
from fermiviewer.models import FourDMeta, ImageMeta
from fermiviewer.routes._arrays import value_error_as_422
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


@router.delete("/fourd/{fourd_id}")
def close_fourd(fourd_id: str) -> dict[str, str]:
    """Close a 4D dataset and release its file handle.

    Mirrors `routes.images.close_image` exactly: same 404-on-unknown-id
    semantics (so a second delete on an already-closed id 404s rather than
    silently no-opping) and the same `{"status": "closed"}` response shape.

    IMPORTANT: nav images and virtual-detector maps already derived from
    this dataset are ORDINARY images registered in the separate
    `image_store` (see `session_fourd.FourDStore`'s module docstring — the
    two stores are never merged). Closing the 4D dataset here does not
    touch them; they stay open and usable, keyed only by their own image
    id, until the user closes them individually.
    """
    _get(fourd_id)
    fourd_store.close(fourd_id)
    return {"status": "closed"}


class ReshapeRequest(BaseModel):
    rows: int
    cols: int


@router.post("/fourd/{fourd_id}/reshape")
def fourd_reshape(fourd_id: str, req: ReshapeRequest) -> FourDMeta:
    """Re-raster a headerless acquisition to `(rows, cols)` (PLAN_4DSTEM #14).

    Merlin `.mib` records frames back to back and nothing about the scan that
    produced them, so the parser defaults to a 1xN line-scan and every such
    dataset opens as a 10-px nav strip. This is the only way to tell it what
    the acquisition actually was.

    The file is RE-OPENED under the new shape rather than the existing
    dataset being mutated: the scan shape reaches into the handle's frame
    indexing, the cached nav image and the cached mean pattern, and a partial
    update would leave a dataset that disagrees with itself. Re-opening keeps
    the same 4D id, so the workshop's selection and probe survive; the old
    memmap is released by the store.

    422 when `rows * cols` does not equal the frame count, or when the
    format states its own raster — re-rastering a file that records its scan
    axes would be inviting the user to contradict the acquisition.
    """
    ds4 = _get(fourd_id)
    if ds4.metadata.get("scan_shape_from_file", True):
        raise HTTPException(
            422,
            f"{fourd_store.name(fourd_id)} records its own scan shape "
            f"{list(ds4.scan_shape)}; it cannot be re-rastered",
        )
    path = fourd_store.source_path(fourd_id) or ds4.metadata.get("source")
    if not path:
        raise HTTPException(422, "dataset has no source file to re-open")
    if req.rows <= 0 or req.cols <= 0:
        raise HTTPException(
            422, f"scan shape must be positive, got ({req.rows}, {req.cols})"
        )
    n_frames = ds4.scan_shape[0] * ds4.scan_shape[1]
    if req.rows * req.cols != n_frames:
        raise HTTPException(
            422,
            f"scan shape ({req.rows}, {req.cols}) = {req.rows * req.cols} "
            f"probe positions does not match {n_frames} frames in the file",
        )

    try:
        reshaped = load_mib(str(path), scan_shape=(req.rows, req.cols))
    except (OSError, ValueError) as exc:
        raise HTTPException(422, f"re-opening {path}: {exc}") from None
    fourd_store.replace(fourd_id, reshaped)
    return FourDMeta.from_dataset(fourd_id, fourd_store.name(fourd_id), reshaped)


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


# ── virtual-detector imaging (PLAN_4DSTEM #5) ──────────────────────────

# One in-flight (rows, scan_x, det_ky, det_kx) block capped at ~64 MB,
# computed per-dataset from det_shape/scan_x/dtype rather than a fixed row
# count — a 4k direct-electron detector needs far fewer rows per block than
# a small Merlin frame does for the same memory ceiling. (This is a
# route-layer choice independent of FourDDataset's own default block_rows,
# which is sized for its *unweighted* nav_image/mean_pattern reductions.)
# Shared by /virtual-detector and /com — both are single-pass streamed
# reductions over the same block shape, just with a different per-pixel
# weighting, so the same cap applies unchanged.
_BLOCK_BYTES_CAP = 64 * 1024 * 1024


def _block_rows_for_byte_cap(ds4: FourDDataset, cap_bytes: int = _BLOCK_BYTES_CAP) -> int:
    scan_x = ds4.scan_shape[1]
    det_ky, det_kx = ds4.det_shape
    bytes_per_row = scan_x * det_ky * det_kx * ds4.dtype.itemsize
    if bytes_per_row <= 0:
        return ds4.scan_shape[0]
    return max(1, cap_bytes // bytes_per_row)


def _validate_optional_center(
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


class VirtualDetectorRequest(BaseModel):
    """Reciprocal-space aperture over ``det_shape``, ``center`` in 0-based
    ``(ky, kx)`` float pixels (see `calc/fourd/geometry.py`). A null
    ``center_ky``/``center_kx`` pair auto-seeds from
    ``pattern_center(mean_pattern)``. ``inner_r`` is accepted but ignored
    for ``shape="circle"`` (matching `geometry.aperture_mask`'s own
    signature), so a client need not special-case it."""

    center_ky: float | None = None
    center_kx: float | None = None
    inner_r: float
    outer_r: float
    shape: Literal["circle", "annulus"]
    name: str | None = None


def _validate_virtual_detector_request(
    req: VirtualDetectorRequest, det_shape: tuple[int, int]
) -> None:
    if req.outer_r <= 0:
        raise HTTPException(422, "outer_r must be > 0")
    if req.shape == "annulus" and not (0 <= req.inner_r < req.outer_r):
        raise HTTPException(422, "annulus requires 0 <= inner_r < outer_r")
    _validate_optional_center(req.center_ky, req.center_kx, det_shape)


@router.post("/fourd/{fourd_id}/virtual-detector")
def fourd_virtual_detector(fourd_id: str, req: VirtualDetectorRequest) -> ImageMeta:
    """Integrate a reciprocal-space aperture over every probe position,
    producing an ordinary 2D scan-shaped image (BF/ADF/ABF-style virtual
    detector imaging) registered as a normal derived image — same
    idempotent-free, always-register convention as `/nav` (repeat calls
    with different parameters are different analyses, so each gets its own
    derived image; unlike `/nav` there is no single canonical result to
    de-duplicate against).

    See the module docstring for the RAM budget and the `/analyze/vdf`
    naming-collision note (this endpoint is NEVER abbreviated "vdf").
    """
    ds4 = _get(fourd_id)
    _validate_virtual_detector_request(req, ds4.det_shape)

    if req.center_ky is None or req.center_kx is None:
        cy, cx = pattern_center(ds4.mean_pattern)
    else:
        cy, cx = req.center_ky, req.center_kx

    # inner_r is documented as ignored for "circle", but aperture_mask
    # validates radii >= 0 unconditionally — force a safe value rather than
    # let an out-of-range-but-unused inner_r 422 a circle request.
    mask_inner_r = 0.0 if req.shape == "circle" else req.inner_r
    with value_error_as_422():
        mask = aperture_mask(
            ds4.det_shape, (cy, cx), mask_inner_r, req.outer_r, shape=req.shape
        )

    block_rows = _block_rows_for_byte_cap(ds4)
    map_arr = virtual_detector(ds4.iter_scan_rows(block_rows=block_rows), mask)

    base_name = fourd_store.name(fourd_id)
    name = req.name or f"vd({base_name}, r={req.inner_r:g}-{req.outer_r:g})"
    struct = DataStruct(
        data=np.ascontiguousarray(map_arr),
        kind=DataKind.IMAGE,
        axes=(ds4.scan_axes[0], ds4.scan_axes[1]),
        metadata={
            "source": name,
            "parser": "fourd-virtual-detector",
            "analysis": "virtual_detector",
            "fourd_id": fourd_id,
            "center_ky": float(cy),
            "center_kx": float(cx),
            "inner_r": float(req.inner_r),
            "outer_r": float(req.outer_r),
            "shape": req.shape,
        },
    )
    img_id = image_store.add_derived(struct, name, fourd_id)
    return ImageMeta.from_datastruct(img_id, image_store.name(img_id), struct)


# ── per-probe center-of-mass (PLAN_4DSTEM #7) ──────────────────────────


class ComRequest(BaseModel):
    """Descan reference center in 0-based ``(ky, kx)`` float pixels (see
    `calc/fourd/geometry.py`). A null ``center_ky``/``center_kx`` pair
    auto-seeds from ``pattern_center(mean_pattern)`` — the SAME auto-center
    policy `/virtual-detector` uses, resolved inside
    `calc.fourd.com.com_maps` rather than here (this route does no math)."""

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
    ds4 = _get(fourd_id)
    _validate_optional_center(req.center_ky, req.center_kx, ds4.det_shape)

    center: tuple[float, float] | None = None
    mean_pattern: np.ndarray | None = None
    if req.center_ky is not None and req.center_kx is not None:
        center = (req.center_ky, req.center_kx)
    else:
        # only the auto-center path pays for a (possibly first-touch,
        # whole-cube) mean_pattern access — an explicit center never does.
        mean_pattern = ds4.mean_pattern

    block_rows = _block_rows_for_byte_cap(ds4)
    with value_error_as_422():
        com_y, com_x = com_maps(
            ds4.iter_scan_rows(block_rows=block_rows),
            center=center,
            mean_pattern=mean_pattern,
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
                "center_ky": req.center_ky,
                "center_kx": req.center_kx,
            },
        )
        img_id = image_store.add_derived(struct, name, fourd_id)
        return ImageMeta.from_datastruct(img_id, image_store.name(img_id), struct)

    return ComMapsResponse(
        comy=_register(com_y, "com_y", "COMy"),
        comx=_register(com_x, "com_x", "COMx"),
    )
