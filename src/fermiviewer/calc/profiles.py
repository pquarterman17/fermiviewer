"""Line-profile sampling core (port of lineProfile.m).

Coordinates are MATLAB-style 1-based pixel centres throughout (matching
the diffraction module and the wire protocol). Point/region measurement
helpers built on top of this sampling core — measure_distance, roi_stats,
box_integrate, fit_interface_width — live in calc/profile_stats.py,
split out to keep both modules comfortably under the 500-line ceiling.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import map_coordinates

__all__ = [
    "line_profile",
    "line_profile_stats",
    "polyline_profile",
]


def _perp_stack(
    arr: np.ndarray,
    x1: float, y1: float, x2: float, y2: float,
    n_lines: int, xs: np.ndarray, ys: np.ndarray, pixel_dist: float,
) -> np.ndarray:
    """n_lines bilinear samples along (x1,y1)-(x2,y2), offset by whole
    pixels perpendicular to it — shared by line_profile's width>1
    averaging and line_profile_stats' per-point spread."""
    ux, uy = (x2 - x1) / pixel_dist, (y2 - y1) / pixel_dist
    perp_x, perp_y = -uy, ux
    offsets = np.arange(n_lines, dtype=np.float64) - (n_lines - 1) / 2
    return np.stack([
        map_coordinates(
            arr, [ys + perp_y * o - 1, xs + perp_x * o - 1],
            order=1, mode="constant", cval=np.nan,
        )
        for o in offsets
    ])


def line_profile(
    img: np.ndarray,
    x1: float, y1: float, x2: float, y2: float,
    pixel_size: float = float("nan"),
    tilt_angle_deg: float = 0.0,
    tilt_axis: str = "Y",
    geometry: str = "cross-section",
    width: float = 1.0,
    reduce: str = "mean",
) -> tuple[np.ndarray, np.ndarray]:
    """Sub-pixel bilinear profile along a segment (port of lineProfile.m).

    Returns (dist, intensity); dist in pixels unless pixel_size given.
    Tilt correction stretches the in-tilt-axis component by 1/sin (cross
    sections) or 1/cos (surfaces).

    width > 1 (NEW, not in the MATLAB original) averages round(width)
    parallel lines spaced 1 px apart perpendicular to the segment,
    ignoring out-of-image samples — width=1 is bit-identical to the
    ported single-line path (goldens unchanged).

    reduce : 'mean' (default) or 'sum'.  'sum' returns the true integral
    over the box width — useful for quantitative intensity integration.
    width=1 is identical for both modes (single-sample, no averaging).
    """
    if not -90 < tilt_angle_deg < 90:
        raise ValueError("tilt_angle_deg must be in (-90, 90)")
    if reduce not in ("mean", "sum"):
        raise ValueError("reduce must be 'mean' or 'sum'")

    pixel_dist = float(np.hypot(x2 - x1, y2 - y1))
    n = max(2, int(np.ceil(pixel_dist)) + 1)
    xs = np.linspace(x1, x2, n)
    ys = np.linspace(y1, y2, n)
    arr = np.asarray(img, dtype=np.float64)

    n_lines = max(1, int(round(width)))
    if n_lines > 1:
        if pixel_dist == 0:
            raise ValueError("zero-length segment cannot have width")
        stacked = _perp_stack(arr, x1, y1, x2, y2, n_lines, xs, ys, pixel_dist)
        with np.errstate(invalid="ignore"):
            if reduce == "sum":
                # count only valid (non-NaN) samples to avoid inflating the
                # sum near edges where some rows are clipped
                valid = np.sum(np.isfinite(stacked), axis=0).astype(np.float64)
                intensity = np.where(
                    valid > 0, np.nansum(stacked, axis=0), np.nan
                )
            else:
                intensity = np.nanmean(stacked, axis=0)
    else:
        # 1-based pixel-centre coords → 0-based array indices
        intensity = map_coordinates(
            arr, [ys - 1, xs - 1],
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


def line_profile_stats(
    img: np.ndarray,
    x1: float, y1: float, x2: float, y2: float,
    pixel_size: float = float("nan"),
    tilt_angle_deg: float = 0.0,
    tilt_axis: str = "Y",
    geometry: str = "cross-section",
    width: float = 1.0,
    reduce: str = "mean",
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """line_profile, plus the per-point sem across the averaging width —
    additive sibling for the ±σ line-profile band (item 3). dist/intensity
    come from calling line_profile() directly (bit-identical). sem is
    populated ONLY for a genuine per-point average of >1 sample:
    round(width) > 1 AND reduce=='mean'. Otherwise None — width=1 draws
    one bilinear sample (no spread to estimate) and reduce='sum' plots an
    integral, not a mean — neither has an honest σ; do not invent one.
    """
    dist, intensity = line_profile(
        img, x1, y1, x2, y2,
        pixel_size=pixel_size, tilt_angle_deg=tilt_angle_deg,
        tilt_axis=tilt_axis, geometry=geometry, width=width, reduce=reduce,
    )
    n_lines = max(1, int(round(width)))
    if n_lines <= 1 or reduce != "mean":
        return dist, intensity, None

    pixel_dist = float(np.hypot(x2 - x1, y2 - y1))
    n = max(2, int(np.ceil(pixel_dist)) + 1)
    xs, ys = np.linspace(x1, x2, n), np.linspace(y1, y2, n)
    arr = np.asarray(img, dtype=np.float64)
    stacked = _perp_stack(arr, x1, y1, x2, y2, n_lines, xs, ys, pixel_dist)
    # sum/count, not np.nanmean/nanstd (those warn via `warnings`, not
    # np.errstate, on an all-NaN column — trips filterwarnings=error)
    finite = np.isfinite(stacked)
    valid = finite.sum(axis=0).astype(np.float64)
    zeroed = np.where(finite, stacked, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = zeroed.sum(axis=0) / valid
        mean_sq = (zeroed * zeroed).sum(axis=0) / valid
        var = np.maximum(mean_sq - mean * mean, 0.0)
        std = np.sqrt(var)
        sem = std / np.sqrt(valid)
    sem[valid == 0] = np.nan
    return dist, intensity, sem


def polyline_profile(
    img: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    pixel_size: float = float("nan"),
    width: float = 1.0,
    reduce: str = "mean",
) -> tuple[np.ndarray, np.ndarray]:
    """Concatenated sub-pixel profile along polyline vertices (1-based
    pixel-centre coords, NEW — no MATLAB counterpart). Distance
    accumulates across segments; duplicated joint samples are dropped.
    """
    xv = np.asarray(xs, dtype=np.float64).ravel()
    yv = np.asarray(ys, dtype=np.float64).ravel()
    if xv.size != yv.size:
        raise ValueError("xs and ys must have the same length")
    if xv.size < 2:
        raise ValueError("a polyline needs at least 2 vertices")

    ds_list: list[np.ndarray] = []
    vs_list: list[np.ndarray] = []
    total = 0.0
    for i in range(xv.size - 1):
        d, v = line_profile(
            img, xv[i], yv[i], xv[i + 1], yv[i + 1],
            pixel_size=pixel_size, width=width, reduce=reduce,
        )
        if i == 0:
            ds_list.append(d + total)
            vs_list.append(v)
        else:                       # joint sample == previous endpoint
            ds_list.append(d[1:] + total)
            vs_list.append(v[1:])
        total += float(d[-1])
    return np.concatenate(ds_list), np.concatenate(vs_list)
