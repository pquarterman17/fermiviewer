"""POST /export — server-side full-resolution export (handoff §8).

PNG / JPEG: windowed + gamma + colormap RGB with optional baked scale
bar. TIFF-16: windowed 16-bit grayscale (no LUT, no overlays — data
export). SVG/PDF are not implemented yet (422).
"""

from __future__ import annotations

import io

import numpy as np
from fastapi import APIRouter, HTTPException, Response
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from fermiviewer.calc.export import render_rgb, render_u16, scale_bar_geometry
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")

_MEDIA = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "tiff16": "image/tiff",
}


class ExportRequest(BaseModel):
    image_id: str
    format: str = "png"  # png | jpeg | tiff16
    scale: int = Field(default=1, ge=1, le=4)
    # normalized [0,1] window against the raster min/max (the client's
    # display state); gamma as on the stage
    lo: float = 0.0
    hi: float = 1.0
    gamma: float = 1.0
    cmap: str = "gray"
    include: list[str] = []  # ["scale_bar"]


def _raster(ds: DataStruct) -> np.ndarray:
    if ds.kind is DataKind.IMAGE:
        return np.asarray(ds.data, dtype=np.float64)
    if ds.kind is DataKind.SPECTRUM_IMAGE:
        summed: np.ndarray = np.asarray(ds.data, dtype=np.float64).sum(axis=2)
        return summed
    raise HTTPException(400, "1D spectra have no raster to export")


@router.post("/export")
def export_image(req: ExportRequest) -> Response:
    if req.format in ("svg", "pdf"):
        raise HTTPException(422, f"{req.format} export not implemented yet")
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
        try:
            import tifffile
        except ImportError:  # pragma: no cover
            raise HTTPException(500, "tifffile not installed") from None
        u16 = render_u16(raster, lo, hi, req.gamma, req.scale)
        buf = io.BytesIO()
        tifffile.imwrite(buf, u16)
        return _file_response(buf.getvalue(), f"{stem}.tif", "tiff16")

    try:
        rgb = render_rgb(raster, lo, hi, req.gamma, req.cmap, req.scale)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    img = Image.fromarray(rgb, mode="RGB")

    if "scale_bar" in req.include and ds.pixel_cal.calibrated:
        bar = scale_bar_geometry(
            img.width,
            img.height,
            ds.pixel_cal.scale,
            ds.pixel_cal.units,
            req.scale,
        )
        draw = ImageDraw.Draw(img)
        draw.rectangle(
            [bar.x, bar.y, bar.x + bar.width, bar.y + bar.height],
            fill=(255, 255, 255),
        )
        draw.text(
            (bar.x, bar.y - 14),
            bar.label,
            fill=(255, 255, 255),
            stroke_width=1,
            stroke_fill=(0, 0, 0),
        )

    buf = io.BytesIO()
    if req.format == "jpeg":
        img.save(buf, format="JPEG", quality=92)
        return _file_response(buf.getvalue(), f"{stem}.jpg", "jpeg")
    img.save(buf, format="PNG")
    return _file_response(buf.getvalue(), f"{stem}.png", "png")


def _file_response(data: bytes, filename: str, fmt: str) -> Response:
    return Response(
        content=data,
        media_type=_MEDIA[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )
