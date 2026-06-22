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
    # publication sizing (Quick-Wins #3): when BOTH are set, the output is
    # sized to a physical width instead of an integer multiple — target pixel
    # width = width_mm/25.4 * dpi, giving a float upscale factor. dpi is also
    # embedded in the PNG/JPEG/PDF. Ignored for tiff16 (quantitative data
    # export stays integer-scale). When either is None, the integer `scale`
    # path runs unchanged (byte-identical to existing exports).
    width_mm: float | None = Field(default=None, gt=0, le=2000)
    dpi: int | None = Field(default=None, ge=72, le=1200)
    # normalized [0,1] window against the raster min/max (the client's
    # display state); gamma as on the stage
    lo: float = 0.0
    hi: float = 1.0
    gamma: float = 1.0
    cmap: str = "gray"
    include: list[str] = []  # ["scale_bar", "measurements", "colorbar", "caption"]
    measures: list[WireMeasure] = []
    overlay_color: str = "#35e0c2"
    # measurement overlay styling (mirrors the on-screen overlay size + line
    # width); multiplied by `scale` like the scale-bar font. None → legacy
    # 2 px line and small fixed label (byte-identical to older exports).
    overlay_font_size: int | None = Field(default=None, ge=1, le=200)
    overlay_line_width: float | None = Field(default=None, gt=0, le=50)
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

    # discrete grain palette (Quick-Wins #1 export half): window 0..maxid so
    # each integer label lands on its colour band, matching the stage. The
    # continuous colorbar is meaningless for labels, so it is suppressed.
    n_labels: int | None = None
    if req.cmap == "label":
        finite = raster[np.isfinite(raster)]
        n_labels = int(round(float(finite.max()))) + 1 if finite.size else 1
        lo, hi = 0.0, float(max(n_labels - 1, 1))

    name = store.name(req.image_id)
    stem = name.rsplit(".", 1)[0] or name

    if req.format == "tiff16":
        return _export_tiff16(raster, lo, hi, req, stem)

    # physical sizing (Quick-Wins #3): width_mm + dpi → float upscale factor;
    # otherwise the integer `scale` path (byte-identical to before).
    phys_mode = req.width_mm is not None and req.dpi is not None
    src_h, src_w = raster.shape

    try:
        rgb = render_rgb(
            raster, lo, hi, req.gamma, req.cmap, 1 if phys_mode else req.scale,
            n_labels=n_labels,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    img = Image.fromarray(rgb, mode="RGB")

    if phys_mode:
        target_w = max(1, round(req.width_mm / 25.4 * req.dpi))  # type: ignore[operator]
        eff_scale = target_w / src_w
        out_h = max(1, round(src_h * eff_scale))
        # nearest keeps EM pixels crisp when enlarging (matches the stage);
        # lanczos avoids aliasing when the figure is smaller than the raster
        resample = (
            Image.Resampling.NEAREST
            if eff_scale >= 1
            else Image.Resampling.LANCZOS
        )
        img = img.resize((target_w, out_h), resample)
    else:
        eff_scale = float(req.scale)
    save_dpi = req.dpi if phys_mode else None

    bar: ScaleBar | None = None
    if "scale_bar" in req.include and ds.pixel_cal.calibrated:
        bar = scale_bar_geometry(
            img.width, img.height,
            ds.pixel_cal.scale, ds.pixel_cal.units,
            eff_scale,
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
            ds.pixel_cal.units, eff_scale, raster,
            tilt_angle_deg=req.tilt_angle_deg,
            tilt_axis=req.tilt_axis,
            tilt_geometry=req.tilt_geometry,
        )

    cbar = ("colorbar" in req.include and req.cmap != "label", lo, hi)
    # font size: on-screen value (default 20) × effective scale so labels
    # grow proportionally with the image (item #48; float in physical mode)
    font_size = round((req.scale_bar_font_size or 20) * eff_scale)

    # measurement overlay styling × effective scale (mirrors on-screen size +
    # line width); None → backend legacy default (2 px line, 12 px label)
    m_lw = (max(1, round(req.overlay_line_width * eff_scale))
            if req.overlay_line_width else 2)
    m_font = (round(req.overlay_font_size * eff_scale)
              if req.overlay_font_size else None)

    want_caption = "caption" in req.include and bool(req.caption)

    if req.format == "svg":
        svg = build_svg(img, bar, annos, req.overlay_color,
                        cbar=cbar, cmap=req.cmap, font_size=font_size,
                        measure_font_size=m_font or 12, measure_line_width=m_lw,
                        caption=req.caption if want_caption else None)
        return _file_response(svg.encode(), f"{stem}.svg", "svg")

    img = _bake_raster_overlays(img, bar, annos, cbar, req, font_size,
                                want_caption, m_lw, m_font,
                                caption_scale=max(1, round(eff_scale)))
    return _encode_raster(img, req.format, stem, save_dpi)


def _bake_raster_overlays(
    img: Image.Image,
    bar: ScaleBar | None,
    annos: list[Annotation],
    cbar: tuple[bool, float, float],
    req: ExportRequest,
    font_size: int,
    want_caption: bool,
    anno_line_width: int = 2,
    anno_font_size: int | None = None,
    caption_scale: int = 1,
) -> Image.Image:
    """Bake scale bar, annotations, colorbar gutter, then caption band (in
    that order) onto the rendered RGB image; returns the final image."""
    if bar is not None:
        draw_scale_bar(img, bar, font_size=font_size)
    if annos:
        draw_annotations(img, annos, _hex_rgb(req.overlay_color),
                         line_width=anno_line_width,
                         label_font_size=anno_font_size)
    if cbar[0]:
        img = composite_colorbar(img, req.cmap, cbar[1], cbar[2])
    if want_caption:
        # caption spans the full width incl. the colorbar gutter (added last)
        img = draw_caption_band(img, req.caption or "", caption_scale)
    return img


def _encode_raster(
    img: Image.Image, fmt: str, stem: str, dpi: int | None = None
) -> Response:
    """Encode the baked image. When `dpi` is set (physical sizing, #3) it is
    embedded — PNG/JPEG pHYs/JFIF density and the PDF render resolution — so
    the figure imports at the intended physical size in Illustrator/Word."""
    buf = io.BytesIO()
    if fmt == "pdf":
        img.save(buf, format="PDF", resolution=float(dpi) if dpi else 150.0)
        return _file_response(buf.getvalue(), f"{stem}.pdf", "pdf")
    if fmt == "jpeg":
        kw = {"dpi": (dpi, dpi)} if dpi else {}
        img.save(buf, format="JPEG", quality=92, **kw)
        return _file_response(buf.getvalue(), f"{stem}.jpg", "jpeg")
    kw = {"dpi": (dpi, dpi)} if dpi else {}
    img.save(buf, format="PNG", **kw)
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
