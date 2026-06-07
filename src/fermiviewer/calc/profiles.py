"""Line profiles + ROI statistics (port of lineProfile.m / rect ROI math).

Coordinates are MATLAB-style 1-based pixel centres throughout (matching
the diffraction module and the wire protocol).
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import map_coordinates

__all__ = [
    "azimuthal_integrate",
    "line_profile",
    "radial_profile",
    "roi_stats",
]


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


def radial_profile(
    img: np.ndarray,
    center: tuple[float, float] | None = None,
    n_bins: int = 0,
    normalize: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Radial average + max profiles about a centre — ported verbatim.

    Default centre is the pixel-centre convention ((W+1)/2, (H+1)/2) in
    1-based coords; bins span [0, max radius] (the full corner reach,
    unlike azimuthal_integrate's inscribed rMax). n_bins=0 resolves to
    floor(min(H, W)/2) — the documented MATLAB default, whose literal
    default value (0) trips its own validator (latent upstream bug).

    Returns (radii, avg_profile, max_profile); empty bins are NaN.
    """
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    cx, cy = center if center is not None else (w / 2 + 0.5, h / 2 + 0.5)
    if n_bins <= 0:
        n_bins = min(h, w) // 2

    cols = np.arange(1, w + 1, dtype=np.float64)[None, :]
    rows = np.arange(1, h + 1, dtype=np.float64)[:, None]
    dist_map = np.hypot(cols - cx, rows - cy)

    max_radius = dist_map.max()
    bin_width = max_radius / n_bins
    radii = (np.arange(n_bins) + 0.5) * bin_width

    idx = np.minimum((dist_map / bin_width).astype(np.int64), n_bins - 1)
    flat_idx = idx.ravel()
    flat_val = d.ravel()
    counts = np.bincount(flat_idx, minlength=n_bins).astype(np.float64)
    sums = np.bincount(flat_idx, weights=flat_val, minlength=n_bins)
    with np.errstate(invalid="ignore"):
        avg = sums / counts
    avg[counts == 0] = np.nan
    mx = np.full(n_bins, -np.inf)
    np.maximum.at(mx, flat_idx, flat_val)
    mx[counts == 0] = np.nan

    if normalize:
        for arr in (avg, mx):
            lo, hi = np.nanmin(arr), np.nanmax(arr)
            if hi > lo:
                arr -= lo
                arr /= hi - lo
            else:
                arr[:] = 0.0
    return radii, avg, mx


def azimuthal_integrate(
    img: np.ndarray,
    center: tuple[float, float] | None = None,
    n_bins: int = 0,
    sector_min: float = 0.0,
    sector_max: float = 360.0,
    pixel_size: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Sector-masked azimuthal average — ported verbatim.

    Angles measured from +x clockwise (image-row convention), wrapped to
    [0, 360); sector_min >= sector_max selects the wrap-around wedge.
    rMax is the inscribed distance to the nearest edge (NOT the corner
    reach used by radial_profile). NaN pixels are excluded; empty bins
    are NaN. Returns (radii_calibrated, intensity).
    """
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    cx, cy = center if center is not None else ((w + 1) / 2, (h + 1) / 2)
    if n_bins <= 0:
        n_bins = min(h, w) // 2

    dx = np.arange(1, w + 1, dtype=np.float64)[None, :] - cx
    dy = np.arange(1, h + 1, dtype=np.float64)[:, None] - cy
    radius = np.hypot(dx, dy)
    phi = np.degrees(np.arctan2(dy, dx))
    phi = np.where(phi < 0, phi + 360, phi)

    if sector_min == 0 and sector_max == 360:
        sector = np.ones((h, w), dtype=bool)
    elif sector_min < sector_max:
        sector = (phi >= sector_min) & (phi < sector_max)
    else:  # wrapping wedge, e.g. 300 -> 60
        sector = (phi >= sector_min) | (phi < sector_max)

    r_max = max(min(cx, cy, w - cx, h - cy), 1.0)
    bin_width = r_max / n_bins
    centres = (np.arange(n_bins) + 0.5) * bin_width

    keep = sector & ~np.isnan(d) & (radius >= 0) & (radius < r_max)
    idx = np.minimum(
        (radius[keep] / bin_width).astype(np.int64), n_bins - 1
    )
    sums = np.bincount(idx, weights=d[keep], minlength=n_bins)
    counts = np.bincount(idx, minlength=n_bins).astype(np.float64)
    with np.errstate(invalid="ignore"):
        intensity = sums / counts
    intensity[counts == 0] = np.nan

    return centres * pixel_size, intensity
