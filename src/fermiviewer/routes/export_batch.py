"""POST /export/batch — render many images into one ZIP download
(checklist L batch export). Split from export.py for the god-module
ceiling; reuses its renderers."""

from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from fermiviewer.calc.export import render_rgb, render_u16
from fermiviewer.routes.export import _raster, _window_bounds
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


class BatchExportRequest(BaseModel):
    image_ids: list[str]
    format: str = "png"                      # png | jpeg | tiff16
    scale: int = Field(default=1, ge=1, le=4)
    gamma: float = 1.0
    cmap: str = "gray"
    lo: float = 0.0                          # per-image normalized window
    hi: float = 1.0


@router.post("/export/batch")
def export_batch(req: BatchExportRequest) -> Response:
    if not req.image_ids:
        raise HTTPException(422, "no images given")
    if req.format not in ("png", "jpeg", "tiff16"):
        raise HTTPException(422, "format must be png, jpeg or tiff16")

    from PIL import Image

    buf = io.BytesIO()
    seen: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for iid in req.image_ids:
            try:
                ds = store.get(iid)
            except UnknownImageError:
                raise HTTPException(
                    404, f"unknown image id: {iid}") from None
            raster = _raster(ds)
            lo, hi = _window_bounds(raster, req.lo, req.hi)
            stem = store.name(iid).rsplit(".", 1)[0] or iid
            # de-dupe names inside the archive
            base = stem
            n = 1
            while stem in seen:
                n += 1
                stem = f"{base}_{n}"
            seen.add(stem)

            entry = io.BytesIO()
            if req.format == "tiff16":
                import tifffile

                tifffile.imwrite(
                    entry, render_u16(raster, lo, hi, req.gamma, req.scale)
                )
                zf.writestr(f"{stem}.tif", entry.getvalue())
            else:
                rgb = render_rgb(raster, lo, hi, req.gamma, req.cmap,
                                 req.scale)
                img = Image.fromarray(rgb, mode="RGB")
                if req.format == "jpeg":
                    img.save(entry, format="JPEG", quality=92)
                    zf.writestr(f"{stem}.jpg", entry.getvalue())
                else:
                    img.save(entry, format="PNG")
                    zf.writestr(f"{stem}.png", entry.getvalue())

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="export.zip"'
        },
    )
