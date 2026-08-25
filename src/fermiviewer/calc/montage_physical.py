"""Comparison montage — tiles resampled to ONE common physical scale.

Split out of montage.py (plan item #25): that module was 230 lines and this
mode added 257, taking it to 485 against the 500-line ceiling. A file should
not grow to its limit because a feature landed near it, so the mode lives
here and composes `montage()` rather than being appended to it.

Pure library — numpy + PIL + scipy in, ndarray out. No fastapi/pydantic/routes.

Why a common scale: tiling frames imaged at different magnifications and
baking one scale bar produces a figure that LIES — a feature appears larger
in whichever sample happened to be imaged more closely. The two real Helios
corpus frames differ 78x in pixel size (3.37 vs 264 um/px), so this is not a
hypothetical. Every tile is downsampled to the COARSEST input scale, never
upsampled past its own real resolution.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw
from PIL.ImageFont import FreeTypeFont
from scipy import ndimage

from fermiviewer.calc.export import UNIT_TO_NM, ScaleBar, scale_bar_geometry

# Shared tile-rendering primitives. These stay private to montage.py rather
# than becoming public API just because this module was split out of it: the
# split is an internal reorganisation, not a new contract.
from fermiviewer.calc.montage import (
    _DEFAULT_BG,
    _DEFAULT_FONT_SIZE,
    _DEFAULT_GAP,
    _load_font,
    montage,
)

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


# ════════════════════════════════════════════════════════════════════
# Panel ordering — read a sample series as a trend, not as request order
# ════════════════════════════════════════════════════════════════════


def order_by_param_value(values: Sequence[float | str | bool | None]) -> list[int]:
    """Panel order as a permutation of INDICES into `values`, ascending by
    parameter value (plan item 29).

    Returns indices rather than reordered items so this stays a pure
    numeric/ordering primitive: the caller keeps whatever tile objects it
    has (pydantic models, dicts, ...) and this module keeps no opinion on
    them — the layering rule that keeps calc/ server-free.

    Only a genuinely numeric value (`int`/`float`) participates in the
    ordering. `bool` is EXCLUDED even though it is an `int` subclass — a
    sample flag is categorical, not a point on an ordinal scale — and so
    is a numeric-LOOKING string like "300": a parameter recorded as text
    is a label, and quietly parsing it would sort "300" against 3.37 as
    if the two came from the same scale.

    Every non-numeric or missing value keeps its original relative order
    and is placed AFTER all the numeric ones (`list.sort` is stable, so
    ties among numeric values keep request order too), which gives:

      - a request where NO value is numeric is unchanged from
        creation/request order (the pre-#29 behaviour) — every entry
        falls into the "non-numeric" bucket, which is never reordered;
      - a request mixing numeric and non-numeric values still produces a
        usable trend for the entries that have one, without crashing or
        silently dropping the rest.
    """

    def is_numeric(v: float | str | bool | None) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    numeric = [i for i, v in enumerate(values) if is_numeric(v)]
    other = [i for i, v in enumerate(values) if not is_numeric(v)]
    numeric.sort(key=lambda i: float(values[i]))  # type: ignore[arg-type]
    return numeric + other
