"""Colormap LUTs — Python mirror of frontend/src/lib/colormaps.ts.

Keep the stop tables in sync with the TypeScript side: the export
pipeline bakes the same colormap the user sees on the WebGL stage.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = ["COLORMAP_NAMES", "build_label_lut", "build_lut", "label_color"]

_STOPS: dict[str, list[tuple[int, int, int]]] = {
    "gray": [(0, 0, 0), (255, 255, 255)],
    "invert": [(255, 255, 255), (0, 0, 0)],
    "viridis": [
        (68, 1, 84), (72, 40, 120), (62, 74, 137), (49, 104, 142),
        (38, 130, 142), (31, 158, 137), (53, 183, 121), (109, 205, 89),
        (180, 222, 44), (253, 231, 37),
    ],
    "inferno": [
        (0, 0, 4), (27, 12, 65), (74, 12, 107), (120, 28, 109),
        (165, 44, 96), (207, 68, 70), (237, 105, 37), (251, 155, 6),
        (247, 209, 61), (252, 255, 164),
    ],
    "fire": [
        (0, 0, 0), (120, 0, 0), (230, 60, 0), (255, 150, 0),
        (255, 230, 100), (255, 255, 255),
    ],
    "ice": [
        (0, 0, 0), (0, 40, 110), (0, 110, 190), (60, 180, 230),
        (180, 235, 255), (255, 255, 255),
    ],
    # diverging blue-white-red (strain / difference maps) — keep in
    # sync with frontend lib/colormaps.ts
    "redblue": [
        (25, 60, 180), (120, 160, 230), (245, 245, 245),
        (230, 120, 100), (180, 25, 35),
    ],
}

COLORMAP_NAMES = tuple(_STOPS)


def build_lut(name: str) -> np.ndarray:
    """256×3 uint8 LUT, linearly interpolated between the stops.

    The discrete grain/label palette ("label") has no stops; it falls
    through to a default 24-band cycle (mirrors buildLut("label") in
    lib/colormaps.ts). Use build_label_lut directly for an exact band
    count.
    """
    if name == "label":
        return build_label_lut(24)
    stops = _STOPS.get(name)
    if stops is None:
        raise ValueError(f"unknown colormap '{name}' (have: {COLORMAP_NAMES})")
    arr = np.asarray(stops, dtype=np.float64)
    n = arr.shape[0] - 1
    t = np.linspace(0, n, 256)
    k = np.minimum(n - 1, np.floor(t).astype(np.int64))
    f = (t - k)[:, None]
    out = arr[k] * (1 - f) + arr[k + 1] * f
    return np.asarray(out + 0.5, dtype=np.uint8)


def _round_half_up(x: float) -> int:
    """Match JS Math.round (round half toward +∞), not banker's rounding."""
    return math.floor(x + 0.5)


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """HSV → 8-bit RGB; mirror of hsvToRgb() in lib/colormaps.ts."""
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if h < 60:
        r, g, b = c, x, 0.0
    elif h < 120:
        r, g, b = x, c, 0.0
    elif h < 180:
        r, g, b = 0.0, c, x
    elif h < 240:
        r, g, b = 0.0, x, c
    elif h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (
        _round_half_up((r + m) * 255),
        _round_half_up((g + m) * 255),
        _round_half_up((b + m) * 255),
    )


def label_color(k: int) -> tuple[int, int, int]:
    """Distinct flat colour for integer label id `k` (0 = black grain
    boundary/background; ≥1 = golden-angle-spaced hue). Mirror of
    labelColor() in lib/colormaps.ts."""
    if k <= 0:
        return (0, 0, 0)
    hue = ((k - 1) * 137.508) % 360         # golden angle → max separation
    val = 0.78 + 0.2 * (((k - 1) % 3) / 2)  # nudge value so cycles differ
    return _hsv_to_rgb(hue, 0.7, val)


def build_label_lut(n_labels: int) -> np.ndarray:
    """256×3 uint8 LUT of flat per-label colour bands (raster values are
    integer ids in 0..n_labels-1). LUT index i maps back to label
    k = round(t·maxLabel) so each id lands on its band — mirror of
    buildLabelLut() in lib/colormaps.ts."""
    max_label = max(1, math.floor(n_labels) - 1)
    out = np.empty((256, 3), dtype=np.uint8)
    for i in range(256):
        out[i] = label_color(_round_half_up((i / 255) * max_label))
    return out
