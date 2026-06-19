"""Labeled-tile montage (port of +fermiViewer/+visualization/executeMontage.m).

Pure library — numpy + PIL in, ndarray out.  No fastapi/pydantic/routes.

Reference
---------
executeMontage.m (fermi-viewer, +fermiViewer/+visualization/):
  tile order left-to-right, top-to-bottom; step = round(maxDim*(1-overlap));
  output canvas uses averaged overlap regions (weight accumulator).

Deviation from MATLAB
---------------------
The MATLAB function is called with a fixed *nCols* argument.  This port adds
an *auto* mode: when *cols* is None it chooses cols = ceil(sqrt(n)) so the
grid is approximately square — the conventional choice for contact-sheet
montages.  Labels are an optional layer not present in the original (the MATLAB
version writes a figure title; here they are baked per-tile at the top-left
corner so the flat image carries its own annotation).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont

__all__ = ["montage"]

_DEFAULT_GAP = 4        # pixels of solid-bg gap between tiles (no overlap)
_DEFAULT_BG = 0.0       # float background fill (same units as input data)
_DEFAULT_FONT_SIZE = 14  # label font size in pixels


def _load_font(size: int) -> FreeTypeFont | None:
    """Load JetBrains Mono from the vendored TTF asset; fall back to None."""
    try:
        from fermiviewer.assets.fonts import jetbrains_mono_regular
        ttf: Path = jetbrains_mono_regular()
        return ImageFont.truetype(str(ttf), size=size)
    except Exception:  # noqa: BLE001
        return None


def _bake_label(
    canvas: np.ndarray,
    label: str,
    y0: int,
    x0: int,
    tile_h: int,
    tile_w: int,
    font_size: int = _DEFAULT_FONT_SIZE,
) -> None:
    """Render *label* into *canvas* at the top-left corner of the tile region.

    Uses PIL to draw white text with a 1-px black stroke so labels remain
    legible on both bright and dark tiles.  Operates in-place on a
    float64 canvas (values normalised to [0, 1] or raw counts — text is
    baked at the data maximum so it is always visible).
    """
    # Work on a small crop so PIL round-trips are cheap
    margin = font_size + 4
    y_end = min(y0 + margin * 2, y0 + tile_h)
    x_end = min(x0 + margin * 6, x0 + tile_w)
    crop = canvas[y0:y_end, x0:x_end]

    lo, hi = float(canvas.min()), float(canvas.max())
    data_range = hi - lo if hi > lo else 1.0

    # Normalise crop to uint8 for PIL
    norm = np.clip((crop - lo) / data_range * 255, 0, 255).astype(np.uint8)
    pil_img = Image.fromarray(norm, mode="L")
    draw = ImageDraw.Draw(pil_img)
    font = _load_font(font_size)
    txt_fill = 255   # white
    stroke_fill = 0  # black

    if font is not None:
        draw.text(
            (2, 2), label, fill=txt_fill, font=font,
            stroke_width=1, stroke_fill=stroke_fill,
        )
    else:
        draw.text((2, 2), label, fill=txt_fill,
                  stroke_width=1, stroke_fill=stroke_fill)

    # Write back: rescale the modified uint8 tile to original data range
    result = np.asarray(pil_img, dtype=np.float64) / 255.0 * data_range + lo
    canvas[y0:y_end, x0:x_end] = result


def montage(
    frames: list[np.ndarray],
    cols: int | None = None,
    labels: list[str] | None = None,
    gap: int = _DEFAULT_GAP,
    bg: float = _DEFAULT_BG,
    overlap: float = 0.0,
    font_size: int = _DEFAULT_FONT_SIZE,
) -> np.ndarray:
    """Arrange *frames* into a grid and return the composite ndarray.

    Mirrors executeMontage.m (verbatim layout arithmetic):
      - step_y = round(max_h * (1 - overlap))   [executeMontage.m line 18]
      - step_x = round(max_w * (1 - overlap))   [executeMontage.m line 19]
      - nRows  = ceil(nImgs / nCols)             [executeMontage.m line 10]
      - overlapping regions are averaged via a weight accumulator
        (executeMontage.m lines 34-39)

    When *overlap* == 0 (default) and *gap* > 0 each tile occupies its own
    non-overlapping cell with a *gap*-pixel background border.  *overlap* and
    *gap* are mutually exclusive: if overlap > 0, gap is ignored.

    Parameters
    ----------
    frames:
        List of 2-D float64 arrays (H×W).  Mixed sizes are handled; each tile
        is padded to (max_h × max_w) with *bg*.
    cols:
        Number of grid columns.  None → ceil(sqrt(n)).
    labels:
        Optional per-tile text.  None → no labels baked.  Length must equal
        len(frames) if provided.
    gap:
        Gap in pixels between tiles when overlap == 0 (default 4).
    bg:
        Background fill value (default 0.0).
    overlap:
        Fractional overlap [0, 1) between tiles, matching the executeMontage.m
        *overlap* argument.  0 means no overlap.
    font_size:
        Label font size in pixels (default 14).

    Returns
    -------
    np.ndarray
        Float64 composite, shape (out_h, out_w).

    Raises
    ------
    ValueError
        If *frames* is empty, *cols* < 1, or *labels* length mismatches.

    Examples
    --------
    >>> import numpy as np
    >>> from fermiviewer.calc.montage import montage
    >>> frames = [np.full((64, 64), float(i)) for i in range(6)]
    >>> out = montage(frames, cols=3)
    >>> out.shape  # 2 rows × 3 cols × 64 px + 4 px gaps
    (132, 204)
    """
    if not frames:
        raise ValueError("montage: frames list is empty")
    n = len(frames)
    if cols is None:
        cols = math.ceil(math.sqrt(n))
    if cols < 1:
        raise ValueError(f"montage: cols must be ≥ 1, got {cols}")
    if labels is not None and len(labels) != n:
        raise ValueError(
            f"montage: labels length ({len(labels)}) must equal "
            f"number of frames ({n})"
        )
    if not 0.0 <= overlap < 1.0:
        raise ValueError(f"montage: overlap must be in [0, 1), got {overlap}")

    rows = math.ceil(n / cols)

    # Tile canvas size: pad all frames to the same footprint
    max_h = max(int(np.asarray(f).shape[0]) for f in frames)
    max_w = max(int(np.asarray(f).shape[1]) for f in frames)

    if overlap > 0.0:
        # executeMontage.m layout (verbatim)
        step_y = round(max_h * (1 - overlap))
        step_x = round(max_w * (1 - overlap))
        gap = 0  # gap is unused in overlap mode
    else:
        step_y = max_h + gap
        step_x = max_w + gap

    out_h = (rows - 1) * step_y + max_h
    out_w = (cols - 1) * step_x + max_w

    canvas = np.full((out_h, out_w), bg, dtype=np.float64)
    weight = np.zeros((out_h, out_w), dtype=np.float64)

    for ti, frame in enumerate(frames):
        row_idx = ti // cols
        col_idx = ti % cols
        y0 = row_idx * step_y
        x0 = col_idx * step_x
        tile = np.asarray(frame, dtype=np.float64)
        th, tw = tile.shape
        y_end = min(out_h, y0 + th)
        x_end = min(out_w, x0 + tw)
        rh = y_end - y0
        rw = x_end - x0
        canvas[y0:y_end, x0:x_end] += tile[:rh, :rw]
        weight[y0:y_end, x0:x_end] += 1.0

        if labels is not None:
            # Labels baked after all tiles are placed (so we work on final
            # normalised values); defer to a second pass below.
            pass

    # Normalise overlap regions (executeMontage.m lines 38-39)
    mask = weight > 0
    canvas[mask] /= weight[mask]
    # Pixels that received no tile keep the bg fill (weight == 0 stays bg)

    # Second pass: bake labels onto the finalised canvas
    if labels is not None:
        for ti, (label, frame) in enumerate(zip(labels, frames, strict=True)):
            row_idx = ti // cols
            col_idx = ti % cols
            y0 = row_idx * step_y
            x0 = col_idx * step_x
            tile = np.asarray(frame)
            th = min(tile.shape[0], out_h - y0)
            tw = min(tile.shape[1], out_w - x0)
            if th > 0 and tw > 0:
                _bake_label(
                    canvas, label, y0, x0, th, tw, font_size=font_size
                )

    return canvas
