"""Labeled-tile montage (port of +fermiViewer/+visualization/executeMontage.m).

Pure library — numpy + PIL + scipy in, ndarray out.  No fastapi/pydantic/routes.

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

Physical-scale mode (plan item #25 — comparison montage)
----------------------------------------------------------
``montage()`` above tiles frames pixel-for-pixel, which is correct for
same-scale stacks but MISLEADING for a cross-sample comparison panel: two
real Helios corpus frames can differ by tens of times in µm-per-pixel, and
tiling them without resampling makes whichever one was imaged at higher
magnification look like it has the bigger feature. ``montage_physical_scale``
resamples every tile to one common physical scale FIRST (chosen as the
coarsest — largest µm/px — among the inputs, so no tile is upsampled beyond
its real resolution), then reuses ``montage()`` for the actual tiling/
labeling, then bakes exactly ONE scale bar for the whole panel (a per-tile
bar would defeat the point, since every tile now shares a scale). Bar
geometry reuses ``calc.export.scale_bar_geometry`` — the same function the
/export route uses — rather than inventing new bar sizing rules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont
from scipy import ndimage

from fermiviewer.calc.export import UNIT_TO_NM, ScaleBar, scale_bar_geometry

__all__ = ["PhysicalMontageResult", "montage", "montage_physical_scale"]

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


# ════════════════════════════════════════════════════════════════════
# Physical-scale mode — comparison montage with ONE shared scale bar
# ════════════════════════════════════════════════════════════════════


def _hex_luma(color: str) -> int:
    """Perceptual grayscale value [0, 255] for a "#rrggbb" hex string.

    The montage canvas is single-channel float data, not RGB, so a bar
    "colour" can only be baked as an intensity. Falls back to 255 (white,
    matching ScaleBar's own default) on any parse failure.
    """
    c = color.lstrip("#")
    if len(c) == 6:
        try:
            r, g, b = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
            return int(round(0.299 * r + 0.587 * g + 0.114 * b))
        except ValueError:
            pass
    return 255


def _text_width(label: str, font: FreeTypeFont | None) -> int:
    """Measured render width in px — NOT a `len(label) * const` guess.

    A montage canvas can be much narrower than a full export (small test
    tiles, a 2-image comparison), so a guessed width can overshoot the
    canvas and drag the bake crop into a NEIGHBOURING tile's pixels. Actual
    font metrics keep the crop (and therefore the bake) confined to the
    bar's own footprint regardless of canvas size.
    """
    if not label:
        return 0
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    length = probe.textlength(label, font=font) if font is not None else probe.textlength(label)
    return int(math.ceil(length))


def _bake_scale_bar(
    canvas: np.ndarray,
    bar: ScaleBar,
    font_size: int = _DEFAULT_FONT_SIZE,
) -> None:
    """Bake the ONE panel-wide scale bar (rect + label) into `canvas`.

    Mirrors routes/_export_render.draw_scale_bar's geometry and colour
    conventions (label sits above the bar; bar.color picks the intensity) —
    reimplemented here rather than imported, because calc/ may not import
    the routes package (layering guard). Uses the same normalise/
    denormalise round-trip as `_bake_label` above so the bar reads
    correctly against any data range, not just [0, 1].
    """
    lo, hi = float(canvas.min()), float(canvas.max())
    data_range = hi - lo if hi > lo else 1.0
    font = _load_font(font_size)
    text_w = _text_width(bar.label, font)

    y0 = max(0, bar.y - (font_size + 4))
    y1 = min(canvas.shape[0], bar.y + bar.height)
    x0 = max(0, bar.x)
    x1 = min(canvas.shape[1], bar.x + max(bar.width, text_w))
    if y1 <= y0 or x1 <= x0:
        return  # geometry degenerates against a tiny canvas — nothing to bake

    crop = canvas[y0:y1, x0:x1]
    norm = np.clip((crop - lo) / data_range * 255, 0, 255).astype(np.uint8)
    pil_img = Image.fromarray(norm, mode="L")
    draw = ImageDraw.Draw(pil_img)

    rel_x, rel_y = bar.x - x0, bar.y - y0
    fill = _hex_luma(bar.color)
    stroke = 0 if fill > 127 else 255  # contrasting outline either way
    draw.rectangle([rel_x, rel_y, rel_x + bar.width, rel_y + bar.height], fill=fill)
    label_y = rel_y - font_size - 2
    if font is not None:
        draw.text((rel_x, label_y), bar.label, fill=fill, font=font,
                  stroke_width=1, stroke_fill=stroke)
    else:
        draw.text((rel_x, label_y), bar.label, fill=fill,
                  stroke_width=1, stroke_fill=stroke)

    result = np.asarray(pil_img, dtype=np.float64) / 255.0 * data_range + lo
    canvas[y0:y1, x0:x1] = result


@dataclass(frozen=True)
class PhysicalMontageResult:
    """Output of `montage_physical_scale`.

    `pixel_size`/`pixel_unit` describe the canvas itself (every tile was
    resampled to this one scale before tiling) — the caller registers the
    derived image with this calibration, not any single input tile's.
    """

    canvas: np.ndarray
    pixel_size: float
    pixel_unit: str
    scale_bar: ScaleBar


def montage_physical_scale(
    frames: list[np.ndarray],
    pixel_sizes: list[float],
    pixel_units: list[str],
    labels: list[str] | None = None,
    cols: int | None = None,
    gap: int = _DEFAULT_GAP,
    bg: float = _DEFAULT_BG,
    font_size: int = _DEFAULT_FONT_SIZE,
    bar_color: str = "#ffffff",
    resample_order: int = 1,
) -> PhysicalMontageResult:
    """Tile *frames* at ONE common physical scale, with ONE shared scale bar.

    A cross-sample comparison panel is misleading unless every tile is at
    the same µm-per-output-pixel: otherwise a feature imaged at higher
    magnification simply looks bigger, and a single scale bar baked
    afterwards would be correct for some tiles and wrong for the rest. This
    function resamples every tile to a common scale FIRST, then delegates
    the actual grid/label layout to `montage()`, then bakes exactly one
    scale bar onto the finished canvas.

    The common scale is the COARSEST input (largest physical size per
    pixel, converted to a shared nm basis via `calc.export.UNIT_TO_NM`) —
    every other tile is therefore downsampled, never upsampled beyond its
    own real resolution. `pixel_sizes`/`pixel_units` are each per-SOURCE-
    pixel, matching `DataStruct.pixel_cal` (assumed isotropic: x == y).

    Parameters
    ----------
    frames:
        List of 2-D float64 arrays (H×W), one per tile, in native/source
        resolution (pre-resample).
    pixel_sizes:
        Physical size of one SOURCE pixel, one value per frame. Must be
        finite and > 0 — an uncalibrated tile has no defined physical
        scale and the caller must reject it before calling this function
        (see routes/montage_compare.py's 422 handling).
    pixel_units:
        Unit string per frame (e.g. "nm", "µm"); must be a key of
        `calc.export.UNIT_TO_NM`.
    labels:
        Optional per-tile text, passed through to `montage()` unchanged.
    cols, gap, bg, font_size:
        Passed through to `montage()`.
    bar_color:
        Hex colour for the single scale bar (default white); baked as a
        grayscale intensity since the canvas is single-channel.
    resample_order:
        scipy.ndimage.zoom spline order (0 = nearest, 1 = bilinear
        default). Downsampling with order 1 anti-aliases mildly; order 0
        keeps hard pixel edges if that is preferred for label-like data.

    Returns
    -------
    PhysicalMontageResult
        The baked canvas plus the common pixel_size/pixel_unit/scale_bar.

    Raises
    ------
    ValueError
        If list lengths mismatch, a pixel size is non-finite/non-positive,
        or a pixel unit is not in `calc.export.UNIT_TO_NM`. Also propagates
        any ValueError `montage()` itself raises (empty frames, etc).

    Examples
    --------
    >>> import numpy as np
    >>> from fermiviewer.calc.montage import montage_physical_scale
    >>> fine = np.ones((80, 80))      # 1.0 unit/px  -> 40x40 physical units
    >>> coarse = np.ones((20, 20))    # 4.0 unit/px  -> 80x80 physical units
    >>> res = montage_physical_scale(
    ...     [fine, coarse], [1.0, 4.0], ["um", "um"], cols=2,
    ... )
    >>> res.pixel_size, res.pixel_unit   # coarsest of the two wins
    (4.0, 'um')
    """
    n = len(frames)
    if len(pixel_sizes) != n:
        raise ValueError(
            f"montage_physical_scale: pixel_sizes length ({len(pixel_sizes)}) "
            f"must equal number of frames ({n})"
        )
    if len(pixel_units) != n:
        raise ValueError(
            f"montage_physical_scale: pixel_units length ({len(pixel_units)}) "
            f"must equal number of frames ({n})"
        )

    nm_per_px: list[float] = []
    for i, (ps, pu) in enumerate(zip(pixel_sizes, pixel_units, strict=True)):
        if not np.isfinite(ps) or ps <= 0:
            raise ValueError(
                f"montage_physical_scale: tile {i} has no valid pixel size "
                f"(got {ps!r}) — a common physical scale is undefined"
            )
        factor = UNIT_TO_NM.get(pu)
        if factor is None:
            raise ValueError(
                f"montage_physical_scale: tile {i} has unknown pixel unit "
                f"'{pu}' (known: {sorted(UNIT_TO_NM)})"
            )
        nm_per_px.append(ps * factor)

    target_idx = int(np.argmax(nm_per_px))
    target_nm = nm_per_px[target_idx]
    target_pixel_size = pixel_sizes[target_idx]
    target_unit = pixel_units[target_idx]

    resampled: list[np.ndarray] = []
    for frame, nm in zip(frames, nm_per_px, strict=True):
        arr = np.asarray(frame, dtype=np.float64)
        factor = nm / target_nm  # <= 1.0: every tile shrinks or stays put
        if math.isclose(factor, 1.0, rel_tol=1e-9):
            resampled.append(arr)
        else:
            resampled.append(ndimage.zoom(arr, factor, order=resample_order))

    canvas = montage(
        resampled, cols=cols, labels=labels, gap=gap, bg=bg, font_size=font_size
    )

    bar = scale_bar_geometry(
        canvas.shape[1], canvas.shape[0], target_pixel_size, target_unit,
        scale=1.0, color=bar_color,
    )
    _bake_scale_bar(canvas, bar, font_size=font_size)

    return PhysicalMontageResult(
        canvas=canvas,
        pixel_size=target_pixel_size,
        pixel_unit=target_unit,
        scale_bar=bar,
    )
