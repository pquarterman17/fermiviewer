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

from fermiviewer.calc.raster import NoRasterError, raster_from
from fermiviewer.calc.render import auto_window, to_display
from fermiviewer.datastruct import DataKind

__all__ = [
    "THUMBNAIL_MAX_EDGE",
    "decimate",
    "display_png",
    "raster_for_thumbnail",
    "render_thumbnail_png",
    "shrink",
]

#: ADR 0002 §2: "<= 256 px on the longest edge".
THUMBNAIL_MAX_EDGE = 256


def decimate(raster: np.ndarray, max_edge: int | None) -> np.ndarray:
    """Stride-subsample `raster` to roughly twice `max_edge`.

    Windowing is the expensive half of making a thumbnail --
    `calc.render.window_level` casts to float64 and masks, so a 4096x4096
    uint16 image costs several 134 MB temporaries and about a second.
    Striding first is a view plus one small copy.

    Deliberately lands ABOVE `max_edge` (integer stride, only down to
    ~2x) so `shrink` still does a resampling pass: pure decimation
    aliases, and a survey image of a lattice is exactly the thing that
    aliases visibly.

    The auto window must still be taken from the FULL raster
    (`calc.render.auto_window`) -- bounds read off a subsample would
    stretch the thumbnail to a different black point than the full render
    whenever the stride skipped an extreme pixel.
    """
    if max_edge is None:
        return raster
    step = max(raster.shape[0], raster.shape[1]) // (2 * max_edge)
    return raster[::step, ::step] if step > 1 else raster


def shrink(img: Image.Image, max_edge: int | None) -> Image.Image:
    """Resample so the longest edge is at most `max_edge`.

    Never enlarges: asking for a 512 px thumbnail of a 256 px image
    returns the 256 px image, so a caller can name one size without first
    finding out which is smaller.
    """
    if max_edge is None:
        return img
    scale = max_edge / max(img.width, img.height)
    if scale >= 1.0:
        return img
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(size, Image.Resampling.LANCZOS)


def raster_for_thumbnail(data: np.ndarray, kind: DataKind) -> np.ndarray | None:
    """2D view of `data` for a thumbnail, or None when `kind` has no raster.

    The shape logic is `calc.raster.raster_from` (the one raster boundary);
    this wrapper keeps the None-not-raise contract the `.fvp` writer relies
    on — no `thumbs/` entry for a 1D spectrum, rather than a failed save.
    """
    try:
        return raster_from(data, kind, native=True)
    except NoRasterError:
        return None


def display_png(
    data: np.ndarray,
    *,
    rgb: bool = False,
    max_edge: int | None = None,
    lo: float | None = None,
    hi: float | None = None,
    gamma: float = 1.0,
) -> bytes:
    """8-bit PNG of a 2D raster (or an RGB composite), capped at `max_edge`.

    The one place windowing, decimation and resampling are composed, so
    `/image/{id}/render` and the `.fvp` writer cannot drift apart on what
    a rendered image looks like. `max_edge=None` returns full resolution.
    """
    if rgb:
        img = Image.fromarray(np.asarray(data), mode="RGB")
    else:
        if lo is None or hi is None:
            auto = auto_window(data)
            if auto is not None:
                lo = auto[0] if lo is None else lo
                hi = auto[1] if hi is None else hi
        img = Image.fromarray(
            to_display(decimate(data, max_edge), lo, hi, gamma), mode="L"
        )
    png = io.BytesIO()
    shrink(img, max_edge).save(png, format="PNG")
    return png.getvalue()


def render_thumbnail_png(
    data: np.ndarray, kind: DataKind, *, max_edge: int = THUMBNAIL_MAX_EDGE
) -> bytes | None:
    """An 8-bit grayscale PNG, <= `max_edge` px on the longest edge.

    None when there is nothing to render: a 1D spectrum (no raster) or an
    empty array. The caller writes no `thumbs/` entry in that case, rather
    than embedding a placeholder image.
    """
    if kind is DataKind.RGB_IMAGE:
        # colour thumbnails stay colour — no windowing, the composite's
        # uint8 pixels ARE the display values (ADR 0003 §2)
        if data.size == 0:
            return None
        return display_png(data, rgb=True, max_edge=max_edge)
    raster = raster_for_thumbnail(data, kind)
    if raster is None or raster.ndim != 2 or raster.size == 0:
        return None
    return display_png(raster, max_edge=max_edge)
