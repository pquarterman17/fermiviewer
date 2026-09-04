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
    "fit",
    "raster_for_thumbnail",
    "render_thumbnail_png",
    "target_size",
]

#: ADR 0002 §2: "<= 256 px on the longest edge".
THUMBNAIL_MAX_EDGE = 256


#: Working-buffer ceiling while box-reducing, in bytes. Bounds the
#: float64 chunk `_box_reduce` materialises, so reducing a 4096x4096
#: image costs this much rather than the 134 MB the whole array would.
_REDUCE_CHUNK_BYTES = 8 << 20


def _box_reduce(raster: np.ndarray, k: int) -> np.ndarray:
    """Mean of every k x k block over the COMPLETE source, bounded memory.

    Blocks at the right and bottom edges are usually short. They are kept
    and divided by the samples they actually contain, never cropped to the
    last whole block: cropping deletes source rows outright, and no later
    resize can put them back. A 513x513 image reduced with k = 8 dropped
    row 512, so a bright final row vanished entirely; a 3 x 1024 image
    with k = 2 threw away a third of the picture and returned one row
    where two are owed.

    `np.add.reduceat` sums each block including the short final one, so
    the result is ceil(h / k) x ceil(w / k) and every input pixel
    contributes exactly once. Rows are processed a chunk at a time to keep
    the float64 working buffer near `_REDUCE_CHUNK_BYTES`.
    """
    h, w = raster.shape
    row_starts = np.arange(0, h, k)
    col_starts = np.arange(0, w, k)
    # samples per block along each axis; the final entry is the short one
    row_counts = np.diff(np.append(row_starts, h)).astype(np.float64)
    col_counts = np.diff(np.append(col_starts, w)).astype(np.float64)
    hb, wb = row_starts.size, col_starts.size

    out = np.empty((hb, wb), dtype=np.float64)
    per_row = k * w * 8  # float64 bytes one row-of-blocks needs
    chunk = max(1, _REDUCE_CHUNK_BYTES // max(per_row, 1))
    for i in range(0, hb, chunk):
        j = min(i + chunk, hb)
        lo = int(row_starts[i])
        hi = int(row_starts[j]) if j < hb else h
        block = raster[lo:hi].astype(np.float64)
        sums = np.add.reduceat(block, row_starts[i:j] - lo, axis=0)
        sums = np.add.reduceat(sums, col_starts, axis=1)
        out[i:j] = sums / (row_counts[i:j, None] * col_counts[None, :])
    return out


def decimate(raster: np.ndarray, max_edge: int | None) -> np.ndarray:
    """Area-average `raster` down toward `max_edge`, antialiased.

    Windowing is the expensive half of making a thumbnail --
    `calc.render.window_level` casts to float64 and masks, so a 4096x4096
    uint16 image costs several 134 MB temporaries and about a second.
    Reducing first avoids that.

    It must be a box AVERAGE, not point subsampling. Striding was tried
    and is wrong: it commits aliasing that no later resampling pass can
    undo. On a 512x512 checkerboard a stride of 4 samples one phase only,
    so `display_png(x, max_edge=64)` came out entirely black -- and
    entirely white for the same image rolled by a single row, where the
    true answer is a uniform mid-grey. Periodic structure is not a corner
    case here: lattice fringes and stripe contrast are the subject.

    The auto window must still be taken from the FULL raster
    (`calc.render.auto_window`) -- bounds read off a reduced copy would
    stretch the thumbnail to a different black point than the full render.
    """
    if max_edge is None:
        return raster
    h, w = raster.shape
    # Capped by the SHORTEST side too, so a very oblong image reduces by a
    # factor its short axis can actually carry. `_box_reduce` keeps partial
    # blocks, so neither dimension can round away to nothing.
    k = min(max(h, w) // max_edge, h, w)
    return _box_reduce(raster, k) if k >= 2 else raster


def target_size(h: int, w: int, max_edge: int | None) -> tuple[int, int]:
    """PNG ``(width, height)`` a thumbnail of an ``h x w`` source should be.

    Derived from the ORIGINAL extent, never from the reduced intermediate.
    `_box_reduce` rounds each axis UP, so a very oblong source lands
    thicker than its aspect ratio allows: a 9 x 4096 raster at
    ``max_edge=512`` reduces to 2 x 512, and asking only "is the longest
    edge over 512?" leaves it there — twice the thickness the source
    implies, which is 9/4096 * 512 = 1.1 rows.

    Never enlarges: a source already within `max_edge` keeps its own size,
    so a caller can name one size without first checking which is smaller.
    """
    if max_edge is None:
        return (w, h)
    longest = max(h, w)
    if longest <= max_edge:
        return (w, h)
    scale = max_edge / longest
    return (max(1, round(w * scale)), max(1, round(h * scale)))


def fit(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resample `img` to exactly `size`, or pass it through unchanged.

    Always a downsize in this module: `_box_reduce` divides by an integer
    ``k <= longest / max_edge``, so every axis of the reduced image is at
    least its `target_size` value and resampling only ever removes
    resolution here.
    """
    return img if img.size == size else img.resize(size, Image.Resampling.LANCZOS)


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
    # from the SOURCE shape, before any reduction touches it
    size = target_size(data.shape[0], data.shape[1], max_edge)
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
    fit(img, size).save(png, format="PNG")
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
