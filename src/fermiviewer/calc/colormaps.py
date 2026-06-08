"""Colormap LUTs — Python mirror of frontend/src/lib/colormaps.ts.

Keep the stop tables in sync with the TypeScript side: the export
pipeline bakes the same colormap the user sees on the WebGL stage.
"""

from __future__ import annotations

import numpy as np

__all__ = ["COLORMAP_NAMES", "build_lut"]

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
    """256×3 uint8 LUT, linearly interpolated between the stops."""
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
