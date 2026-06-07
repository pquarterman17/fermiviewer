"""Line profiles + ROI statistics (port of lineProfile.m / rect ROI math).

Coordinates are MATLAB-style 1-based pixel centres throughout (matching
the diffraction module and the wire protocol).
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import map_coordinates

__all__ = ["line_profile", "roi_stats"]


def line_profile(
    img: np.ndarray,
    x1: float, y1: float, x2: float, y2: float,
    pixel_size: float = float("nan"),
    tilt_angle_deg: float = 0.0,
    tilt_axis: str = "Y",
    geometry: str = "cross-section",
) -> tuple[np.ndarray, np.ndarray]:
    """Sub-pixel bilinear profile along a segment (port of lineProfile.m).

    Returns (dist, intensity); dist in pixels unless pixel_size given.
    Tilt correction stretches the in-tilt-axis component by 1/sin (cross
    sections) or 1/cos (surfaces).
    """
    if not -90 < tilt_angle_deg < 90:
        raise ValueError("tilt_angle_deg must be in (-90, 90)")

    pixel_dist = float(np.hypot(x2 - x1, y2 - y1))
    n = max(2, int(np.ceil(pixel_dist)) + 1)
    xs = np.linspace(x1, x2, n)
    ys = np.linspace(y1, y2, n)
    # 1-based pixel-centre coords → 0-based array indices
    intensity = map_coordinates(
        np.asarray(img, dtype=np.float64), [ys - 1, xs - 1],
        order=1, mode="constant", cval=np.nan,
    )

    dx, dy = x2 - x1, y2 - y1
    if tilt_angle_deg != 0:
        if geometry.lower().replace("-", "").replace("_", "") == "surface":
            scale = 1 / np.cos(np.deg2rad(tilt_angle_deg))
        else:
            scale = 1 / np.sin(np.deg2rad(tilt_angle_deg))
        if tilt_axis.upper() == "Y":
            dy *= scale
        else:
            dx *= scale

    dist = np.linspace(0, float(np.hypot(dx, dy)), n)
    if np.isfinite(pixel_size):
        dist = dist * pixel_size
    return dist, intensity


def roi_stats(
    img: np.ndarray,
    row1: float, col1: float, row2: float, col2: float,
    pixel_size: float = float("nan"),
) -> dict[str, float]:
    """Rectangle statistics (1-based inclusive bounds, clamped)."""
    arr = np.asarray(img, dtype=np.float64)
    h, w = arr.shape
    r1, r2 = sorted((int(round(row1)), int(round(row2))))
    c1, c2 = sorted((int(round(col1)), int(round(col2))))
    r1, r2 = max(r1, 1), min(r2, h)
    c1, c2 = max(c1, 1), min(c2, w)
    if r1 > r2 or c1 > c2:
        raise ValueError("ROI is empty after clamping to the image")
    sel = arr[r1 - 1 : r2, c1 - 1 : c2]
    area_px = float(sel.size)
    area = area_px * pixel_size**2 if np.isfinite(pixel_size) else area_px
    return {
        "mean": float(sel.mean()),
        "std": float(sel.std(ddof=0)),
        "min": float(sel.min()),
        "max": float(sel.max()),
        "n_pixels": area_px,
        "area": area,
    }
