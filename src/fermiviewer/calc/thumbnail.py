"""Project thumbnails — `thumbs/<image-id>.png` (ADR 0002 §2, plan item 37).

Embedded for every image in BOTH `.fvp` payload modes, so a project browses
and reviews with its source data absent — the same reason derived images are
always embedded, one layer down.

Reuses the exact windowing `/image/{id}/render` uses
(`calc.render.to_display`, full-range auto window, gamma 1) rather than
inventing a second contrast rule; collapsing a >2D array to a raster mirrors
`routes/images.py`'s `_raster` (image as-is, spectrum_image summed over its
energy axis). A 1D spectrum has no raster and gets no thumbnail.

Pure library: numpy + PIL in, PNG bytes out. No fastapi/pydantic/routes —
this lives in `calc/`, not `routes/`, specifically so `io/project_file.py`
(which the layering guard forbids from importing `routes/`) can call it
directly while writing a `.fvp`.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from fermiviewer.calc.render import to_display
from fermiviewer.datastruct import DataKind

__all__ = ["THUMBNAIL_MAX_EDGE", "raster_for_thumbnail", "render_thumbnail_png"]

#: ADR 0002 §2: "<= 256 px on the longest edge".
THUMBNAIL_MAX_EDGE = 256


def raster_for_thumbnail(data: np.ndarray, kind: DataKind) -> np.ndarray | None:
    """2D view of `data` for a thumbnail, or None when `kind` has no raster.

    Mirrors `routes/images.py`'s `_raster`: an image is used as-is; a
    spectrum_image cube is summed over its energy (last) axis; a 1D spectrum
    has nothing to rasterize.
    """
    if kind is DataKind.IMAGE:
        return data
    if kind is DataKind.SPECTRUM_IMAGE:
        summed: np.ndarray = np.asarray(data, dtype=np.float64).sum(axis=2)
        return summed
    return None


def render_thumbnail_png(
    data: np.ndarray, kind: DataKind, *, max_edge: int = THUMBNAIL_MAX_EDGE
) -> bytes | None:
    """An 8-bit grayscale PNG, <= `max_edge` px on the longest edge.

    None when there is nothing to render: a 1D spectrum (no raster) or an
    empty array. The caller writes no `thumbs/` entry in that case, rather
    than embedding a placeholder image.
    """
    raster = raster_for_thumbnail(data, kind)
    if raster is None or raster.ndim != 2 or raster.size == 0:
        return None
    buf8 = to_display(raster)  # same auto full-range window as the render route
    img = Image.fromarray(buf8, mode="L")
    scale = max_edge / max(img.width, img.height)
    if scale < 1.0:
        size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(size, Image.Resampling.LANCZOS)
    png = io.BytesIO()
    img.save(png, format="PNG")
    return png.getvalue()
