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
    draw_caption_band,
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
    # circle|cross|square|none|bar — wire key is camelCase (mirrors the
    # frontend Measure.endSymbol); model_dump() emits end_symbol,
    # which calc.measure_annotations also accepts
    end_symbol: str = Field(default="none", alias="endSymbol")
    # box-profile ⊥ averaging width in image px → bakes the box outline
    width: float | None = None


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
    include: list[str] = []  # ["scale_bar", "measurements", "colorbar", "caption"]
    measures: list[WireMeasure] = []
    overlay_color: str = "#35e0c2"
    # report caption burned into a band below the figure (item WS4c); the
    # frontend composes the text (user caption + optional metadata line).
    # Rendered only when "caption" is in `include` and this is non-empty.
    caption: str | None = None
    # custom scale-bar geometry (item #33); None → auto (backward-compatible)
    scale_bar_norm_x: float | None = None
    scale_bar_norm_y: float | None = None
    scale_bar_length_phys: float | None = None
    scale_bar_thickness: int | None = None
    # tilt correction for distance/profile/polyline labels (item #34);
    # 0 → off (backward-compatible)
    tilt_angle_deg: float = 0.0
    tilt_axis: str = "Y"                    # Y | X
    tilt_geometry: str = "cross-section"    # cross-section | surface
    # scale-bar label font size in screen px (item #48); None → 20 (default)
    # multiplied by export scale so labels grow with the image
    scale_bar_font_size: int | None = Field(default=None, ge=1, le=200)
    # scale-bar bar + label colour (audit #10); None → "#ffffff" (white,
    # byte-identical to all existing exports that omit this field)
    scale_bar_color: str | None = None
    # force a unit for the scale-bar label regardless of calibration units
    # (audit #10); None → auto-derived by _bar_label (EM sub-unit step-down)
    scale_bar_unit_override: str | None = None


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
            color=req.scale_bar_color or "#ffffff",
            unit_override=req.scale_bar_unit_override,
        )

    annos: list[Annotation] = []
    if "measurements" in req.include and req.measures:
        annos = measure_annotations(
            [m.model_dump() for m in req.measures],
            raster.shape[0], raster.shape[1],
            ds.pixel_cal.scale if ds.pixel_cal.calibrated else None,
            ds.pixel_cal.units, req.scale, raster,
            tilt_angle_deg=req.tilt_angle_deg,
            tilt_axis=req.tilt_axis,
            tilt_geometry=req.tilt_geometry,
        )

    cbar = ("colorbar" in req.include, lo, hi)
    # font size: on-screen value (default 20) × export scale so labels
    # grow proportionally with the image (item #48)
    font_size = (req.scale_bar_font_size or 20) * req.scale

    want_caption = "caption" in req.include and bool(req.caption)

    if req.format == "svg":
        svg = build_svg(img, bar, annos, req.overlay_color,
                        cbar=cbar, cmap=req.cmap, font_size=font_size,
                        caption=req.caption if want_caption else None)
        return _file_response(svg.encode(), f"{stem}.svg", "svg")

    img = _bake_raster_overlays(img, bar, annos, cbar, req, font_size,
                                want_caption)
    return _encode_raster(img, req.format, stem)


def _bake_raster_overlays(
    img: Image.Image,
    bar: ScaleBar | None,
    annos: list[Annotation],
    cbar: tuple[bool, float, float],
    req: ExportRequest,
    font_size: int,
    want_caption: bool,
) -> Image.Image:
    """Bake scale bar, annotations, colorbar gutter, then caption band (in
    that order) onto the rendered RGB image; returns the final image."""
    if bar is not None:
        draw_scale_bar(img, bar, font_size=font_size)
    if annos:
        draw_annotations(img, annos, _hex_rgb(req.overlay_color))
    if cbar[0]:
        img = composite_colorbar(img, req.cmap, cbar[1], cbar[2])
    if want_caption:
        # caption spans the full width incl. the colorbar gutter (added last)
        img = draw_caption_band(img, req.caption or "", req.scale)
    return img


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
