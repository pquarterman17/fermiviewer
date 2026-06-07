"""POST /export — server-side full-resolution export (handoff §8).

PNG / JPEG / PDF: windowed + gamma + colormap RGB with optional baked
scale bar and measurement overlays. TIFF-16: windowed 16-bit grayscale
(no LUT, no overlays — data export). SVG: embedded full-res PNG with
TRUE VECTOR scale bar + measurement overlays.
"""

from __future__ import annotations

import base64
import io
from xml.sax.saxutils import escape

import numpy as np
from fastapi import APIRouter, HTTPException, Response
from PIL import Image, ImageDraw
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
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")

_MEDIA = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "tiff16": "image/tiff",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
}


class WirePoint(BaseModel):
    x: float
    y: float


class WireMeasure(BaseModel):
    kind: str                                  # distance|profile|angle|roi
    pts: list[WirePoint]


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


def _raster(ds: DataStruct) -> np.ndarray:
    if ds.kind is DataKind.IMAGE:
        return np.asarray(ds.data, dtype=np.float64)
    if ds.kind is DataKind.SPECTRUM_IMAGE:
        summed: np.ndarray = np.asarray(ds.data, dtype=np.float64).sum(axis=2)
        return summed
    raise HTTPException(400, "1D spectra have no raster to export")


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
    if req.format not in _MEDIA:
        raise HTTPException(
            422, f"unknown format '{req.format}' (have: {sorted(_MEDIA)})"
        )
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    raster = _raster(ds)

    # normalized window → real units (window_level semantics)
    finite = raster[np.isfinite(raster)]
    vmin = float(finite.min()) if finite.size else 0.0
    vmax = float(finite.max()) if finite.size else 1.0
    span = vmax - vmin if vmax > vmin else 1.0
    lo = vmin + req.lo * span
    hi = vmin + req.hi * span

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
        bar = scale_bar_geometry(img.width, img.height,
                                 ds.pixel_cal.scale, ds.pixel_cal.units,
                                 req.scale)

    annos: list[Annotation] = []
    if "measurements" in req.include and req.measures:
        annos = measure_annotations(
            [m.model_dump() for m in req.measures],
            raster.shape[0], raster.shape[1],
            ds.pixel_cal.scale if ds.pixel_cal.calibrated else None,
            ds.pixel_cal.units, req.scale, raster,
        )

    if req.format == "svg":
        svg = _build_svg(img, bar, annos, req.overlay_color)
        return _file_response(svg.encode(), f"{stem}.svg", "svg")

    if bar is not None:
        _draw_scale_bar(img, bar)
    if annos:
        _draw_annotations(img, annos, _hex_rgb(req.overlay_color))

    buf = io.BytesIO()
    if req.format == "pdf":
        img.save(buf, format="PDF", resolution=150.0)
        return _file_response(buf.getvalue(), f"{stem}.pdf", "pdf")
    if req.format == "jpeg":
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


# ── PIL raster baking ────────────────────────────────────────────────

def _draw_scale_bar(img: Image.Image, bar: ScaleBar) -> None:
    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [bar.x, bar.y, bar.x + bar.width, bar.y + bar.height],
        fill=(255, 255, 255),
    )
    draw.text((bar.x, bar.y - 14), bar.label, fill=(255, 255, 255),
              stroke_width=1, stroke_fill=(0, 0, 0))


def _dashed_line(draw: ImageDraw.ImageDraw, a: tuple[float, float],
                 b: tuple[float, float], color: tuple[int, int, int],
                 width: int, dash: float = 6.0, gap: float = 4.0) -> None:
    """PIL has no dash support — draw the segments (profile lines)."""
    total = float(np.hypot(b[0] - a[0], b[1] - a[1]))
    if total <= 0:
        return
    ux, uy = (b[0] - a[0]) / total, (b[1] - a[1]) / total
    pos = 0.0
    while pos < total:
        end = min(pos + dash, total)
        draw.line([(a[0] + ux * pos, a[1] + uy * pos),
                   (a[0] + ux * end, a[1] + uy * end)],
                  fill=color, width=width)
        pos = end + gap


def _draw_annotations(img: Image.Image, annos: list[Annotation],
                      color: tuple[int, int, int]) -> None:
    draw = ImageDraw.Draw(img)
    for an in annos:
        p = an.points
        if an.kind == "roi":
            x0 = min(p[0][0], p[1][0])
            y0 = min(p[0][1], p[1][1])
            x1 = max(p[0][0], p[1][0])
            y1 = max(p[0][1], p[1][1])
            draw.rectangle([x0, y0, x1, y1], outline=color, width=2)
        elif an.kind == "angle":
            draw.line([p[0], p[1], p[2]], fill=color, width=2)
        elif an.kind == "polyline":
            for i in range(len(p) - 1):
                _dashed_line(draw, p[i], p[i + 1], color, 2)
        elif an.dashed:
            _dashed_line(draw, p[0], p[1], color, 2)
        else:
            draw.line([p[0], p[1]], fill=color, width=2)
        draw.text(an.label_xy, an.label, fill=color,
                  stroke_width=2, stroke_fill=(0, 0, 0))


# ── SVG vector composition ───────────────────────────────────────────

def _build_svg(img: Image.Image, bar: ScaleBar | None,
               annos: list[Annotation], color: str) -> str:
    """Full-res PNG embedded as <image> + vector overlay elements."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{img.width}" height="{img.height}" '
        f'viewBox="0 0 {img.width} {img.height}">',
        f'<image width="{img.width}" height="{img.height}" '
        f'href="data:image/png;base64,{b64}"/>',
    ]
    text_attrs = ('font-family="monospace" font-size="12" '
                  'paint-order="stroke" stroke="rgba(0,0,0,0.75)" '
                  'stroke-width="3"')

    if bar is not None:
        parts.append(
            f'<rect x="{bar.x}" y="{bar.y}" width="{bar.width}" '
            f'height="{bar.height}" fill="white"/>'
        )
        parts.append(
            f'<text x="{bar.x}" y="{bar.y - 5}" fill="white" '
            f'{text_attrs}>{escape(bar.label)}</text>'
        )

    for an in annos:
        p = an.points
        if an.kind == "roi":
            x0 = min(p[0][0], p[1][0])
            y0 = min(p[0][1], p[1][1])
            w = abs(p[1][0] - p[0][0])
            h = abs(p[1][1] - p[0][1])
            parts.append(
                f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" '
                f'height="{h:.1f}" fill="none" stroke="{color}" '
                f'stroke-width="2"/>'
            )
        elif an.kind in ("angle", "polyline"):
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in p)
            dash = ' stroke-dasharray="6 4"' if an.dashed else ""
            parts.append(
                f'<polyline points="{pts}" fill="none" '
                f'stroke="{color}" stroke-width="2"{dash}/>'
            )
        else:
            dash = ' stroke-dasharray="6 4"' if an.dashed else ""
            parts.append(
                f'<line x1="{p[0][0]:.1f}" y1="{p[0][1]:.1f}" '
                f'x2="{p[1][0]:.1f}" y2="{p[1][1]:.1f}" '
                f'stroke="{color}" stroke-width="2"{dash}/>'
            )
        parts.append(
            f'<text x="{an.label_xy[0]:.1f}" y="{an.label_xy[1]:.1f}" '
            f'fill="{color}" {text_attrs}>{escape(an.label)}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _file_response(data: bytes, filename: str, fmt: str) -> Response:
    return Response(
        content=data,
        media_type=_MEDIA[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )
