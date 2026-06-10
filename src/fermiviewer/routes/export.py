"""POST /export — server-side full-resolution export (handoff §8).

PNG / JPEG / PDF: windowed + gamma + colormap RGB with optional baked
scale bar and measurement overlays. TIFF-16: windowed 16-bit grayscale
(no LUT, no overlays — data export). SVG: embedded full-res PNG with
TRUE VECTOR scale bar + measurement overlays.

Render helpers (PIL baking, SVG composition) live in _export_render.py
to keep this file under the 500-line god-module ceiling.
"""

from __future__ import annotations

import io
import zipfile

import numpy as np
from fastapi import APIRouter, HTTPException, Response
from PIL import Image
from pydantic import BaseModel, Field

from fermiviewer.calc.export import (
    Annotation,
    ScaleBar,
    measure_annotations,
    render_rgb,
    render_u16,
    scale_bar_geometry,
)
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.routes._export_render import (
    build_svg,
    composite_colorbar,
    draw_annotations,
    draw_scale_bar,
)
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")

_MEDIA = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "tiff16": "image/tiff",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "gif": "image/gif",
}


class WirePoint(BaseModel):
    x: float
    y: float


class WireMeasure(BaseModel):
    kind: str                  # distance|profile|angle|roi|polyline|
    pts: list[WirePoint]       #   text|arrow|box
    text: str | None = None    # annotation caption
    endSymbol: str = "none"    # circle|cross|square|none (mirrors Measure.endSymbol)


class ExportRequest(BaseModel):
    image_id: str
    format: str = "png"  # png | jpeg | tiff16 | svg | pdf
    scale: int = Field(default=1, ge=1, le=4)
    # normalized [0,1] window against the raster min/max (the client's
    # display state); gamma as on the stage
    lo: float = 0.0
    hi: float = 1.0
    gamma: float = 1.0
    cmap: str = "gray"
    include: list[str] = []  # ["scale_bar", "measurements"]
    measures: list[WireMeasure] = []
    overlay_color: str = "#35e0c2"
    # custom scale-bar geometry (item #33); None → auto (backward-compatible)
    scale_bar_norm_x: float | None = None
    scale_bar_norm_y: float | None = None
    scale_bar_length_phys: float | None = None
    scale_bar_thickness: int | None = None


def _raster(ds: DataStruct) -> np.ndarray:
    if ds.kind is DataKind.IMAGE:
        return np.asarray(ds.data, dtype=np.float64)
    if ds.kind is DataKind.SPECTRUM_IMAGE:
        summed: np.ndarray = np.asarray(ds.data, dtype=np.float64).sum(axis=2)
        return summed
    raise HTTPException(400, "1D spectra have no raster to export")


def _window_bounds(raster: np.ndarray, lo_n: float,
                   hi_n: float) -> tuple[float, float]:
    """Normalized [0,1] window → real units against the raster range."""
    finite = raster[np.isfinite(raster)]
    vmin = float(finite.min()) if finite.size else 0.0
    vmax = float(finite.max()) if finite.size else 1.0
    span = vmax - vmin if vmax > vmin else 1.0
    return vmin + lo_n * span, vmin + hi_n * span


def _hex_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    if len(c) != 6:
        return (53, 224, 194)  # default accent
    try:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
    except ValueError:
        return (53, 224, 194)


@router.post("/export")
def export_image(req: ExportRequest) -> Response:
    if req.format == "gif":
        raise HTTPException(422, "use POST /export/gif for animations")
    if req.format not in _MEDIA:
        raise HTTPException(
            422, f"unknown format '{req.format}' (have: {sorted(_MEDIA)})"
        )
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    raster = _raster(ds)
    lo, hi = _window_bounds(raster, req.lo, req.hi)

    name = store.name(req.image_id)
    stem = name.rsplit(".", 1)[0] or name

    if req.format == "tiff16":
        return _export_tiff16(raster, lo, hi, req, stem)

    try:
        rgb = render_rgb(raster, lo, hi, req.gamma, req.cmap, req.scale)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    img = Image.fromarray(rgb, mode="RGB")

    bar: ScaleBar | None = None
    if "scale_bar" in req.include and ds.pixel_cal.calibrated:
        bar = scale_bar_geometry(
            img.width, img.height,
            ds.pixel_cal.scale, ds.pixel_cal.units,
            req.scale,
            norm_x=req.scale_bar_norm_x,
            norm_y=req.scale_bar_norm_y,
            length_phys=req.scale_bar_length_phys,
            thickness=req.scale_bar_thickness,
        )

    annos: list[Annotation] = []
    if "measurements" in req.include and req.measures:
        annos = measure_annotations(
            [m.model_dump() for m in req.measures],
            raster.shape[0], raster.shape[1],
            ds.pixel_cal.scale if ds.pixel_cal.calibrated else None,
            ds.pixel_cal.units, req.scale, raster,
        )

    cbar = ("colorbar" in req.include, lo, hi)

    if req.format == "svg":
        svg = build_svg(img, bar, annos, req.overlay_color,
                        cbar=cbar, cmap=req.cmap)
        return _file_response(svg.encode(), f"{stem}.svg", "svg")

    if bar is not None:
        draw_scale_bar(img, bar)
    if annos:
        draw_annotations(img, annos, _hex_rgb(req.overlay_color))
    if cbar[0]:
        img = composite_colorbar(img, req.cmap, lo, hi)

    return _encode_raster(img, req.format, stem)


def _encode_raster(img: Image.Image, fmt: str, stem: str) -> Response:
    buf = io.BytesIO()
    if fmt == "pdf":
        img.save(buf, format="PDF", resolution=150.0)
        return _file_response(buf.getvalue(), f"{stem}.pdf", "pdf")
    if fmt == "jpeg":
        img.save(buf, format="JPEG", quality=92)
        return _file_response(buf.getvalue(), f"{stem}.jpg", "jpeg")
    img.save(buf, format="PNG")
    return _file_response(buf.getvalue(), f"{stem}.png", "png")


def _export_tiff16(raster: np.ndarray, lo: float, hi: float,
                   req: ExportRequest, stem: str) -> Response:
    try:
        import tifffile
    except ImportError:  # pragma: no cover
        raise HTTPException(500, "tifffile not installed") from None
    u16 = render_u16(raster, lo, hi, req.gamma, req.scale)
    buf = io.BytesIO()
    tifffile.imwrite(buf, u16)
    return _file_response(buf.getvalue(), f"{stem}.tif", "tiff16")


class GifRequest(BaseModel):
    image_ids: list[str]
    fps: float = Field(default=4.0, gt=0, le=60)
    scale: int = Field(default=1, ge=1, le=4)
    gamma: float = 1.0
    cmap: str = "gray"
    lo: float = 0.0   # normalized window applied per-frame
    hi: float = 1.0


@router.post("/export/gif")
def export_gif(req: GifRequest) -> Response:
    """Animate ≥2 equal-size images into a looping GIF (checklist N).
    The normalized window is applied against EACH frame's own range, so
    a time series with drifting intensity stays visible throughout."""
    if len(req.image_ids) < 2:
        raise HTTPException(422, "a GIF needs at least 2 images")
    frames: list[Image.Image] = []
    shape: tuple[int, ...] | None = None
    for iid in req.image_ids:
        try:
            ds = store.get(iid)
        except UnknownImageError:
            raise HTTPException(404, f"unknown image id: {iid}") from None
        raster = _raster(ds)
        if shape is None:
            shape = raster.shape
        elif raster.shape != shape:
            raise HTTPException(
                422,
                f"all frames must share dimensions ({store.name(iid)} is "
                f"{raster.shape}, expected {shape})",
            )
        lo, hi = _window_bounds(raster, req.lo, req.hi)
        rgb = render_rgb(raster, lo, hi, req.gamma, req.cmap, req.scale)
        frames.append(Image.fromarray(rgb, mode="RGB"))
    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True, append_images=frames[1:],
        duration=max(20, int(round(1000 / req.fps))), loop=0,
    )
    stem = store.name(req.image_ids[0]).rsplit(".", 1)[0] or "stack"
    return _file_response(buf.getvalue(), f"{stem}.gif", "gif")


class BatchExportRequest(BaseModel):
    image_ids: list[str]
    format: str = "png"
    scale: int = Field(default=1, ge=1, le=4)
    lo: float = 0.0
    hi: float = 1.0
    gamma: float = 1.0
    cmap: str = "gray"


@router.post("/export/batch")
def export_batch(req: BatchExportRequest) -> Response:
    """ZIP of individually exported images (checklist M)."""
    if not req.image_ids:
        raise HTTPException(422, "image_ids must not be empty")
    if req.format not in _MEDIA or req.format in ("gif", "svg", "pdf"):
        raise HTTPException(422, f"batch supports png/jpeg/tiff16, not {req.format!r}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for iid in req.image_ids:
            try:
                ds = store.get(iid)
            except UnknownImageError:
                raise HTTPException(404, f"unknown image id: {iid}") from None
            raster = _raster(ds)
            lo, hi = _window_bounds(raster, req.lo, req.hi)
            name = store.name(iid)
            stem = name.rsplit(".", 1)[0] or name
            if req.format == "tiff16":
                try:
                    import tifffile
                except ImportError:  # pragma: no cover
                    raise HTTPException(500, "tifffile not installed") from None
                u16 = render_u16(raster, lo, hi, req.gamma, req.scale)
                fb = io.BytesIO()
                tifffile.imwrite(fb, u16)
                zf.writestr(f"{stem}.tif", fb.getvalue())
            else:
                rgb = render_rgb(raster, lo, hi, req.gamma, req.cmap, req.scale)
                img = Image.fromarray(rgb, mode="RGB")
                fb = io.BytesIO()
                if req.format == "jpeg":
                    img.save(fb, format="JPEG", quality=92)
                    zf.writestr(f"{stem}.jpg", fb.getvalue())
                else:
                    img.save(fb, format="PNG")
                    zf.writestr(f"{stem}.png", fb.getvalue())
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="export.zip"'},
    )


def _file_response(data: bytes, filename: str, fmt: str) -> Response:
    return Response(
        content=data,
        media_type=_MEDIA[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )
