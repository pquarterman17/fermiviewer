"""Radial + azimuthal integration about a centre (ported verbatim).

Split out of ``profiles.py`` to keep that module under the 500-line
god-module ceiling. These two share the radial-binning idiom and are
used together by ``routes/imaging_ops.py``; line/box profiles and ROI
statistics stay in ``profiles.py``. Coordinates are MATLAB-style 1-based
pixel centres throughout.
"""

from __future__ import annotations

import numpy as np

__all__ = ["azimuthal_integrate", "radial_profile", "radial_profile_stats"]


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
    radii, avg, mx, _std, _n = _radial_bin(img, center, n_bins, normalize)
    return radii, avg, mx


def radial_profile_stats(
    img: np.ndarray,
    center: tuple[float, float] | None = None,
    n_bins: int = 0,
    normalize: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Like radial_profile, plus the per-ring standard deviation of pixel
    values and the per-ring pixel count — additive sibling for the ±σ
    radial-profile band (ANALYSIS_PRESENTATION_PLAN item 3).

    Returns (radii, avg_profile, max_profile, std_profile, n_pixels).

    std_profile is the population standard deviation (ddof=0) of the raw
    pixel VALUES inside each ring — the ring's intensity SPREAD. That is
    NOT the same quantity as the uncertainty of the ring's average: a
    caller wanting the latter (the standard error of the mean, a much
    narrower band) divides by sqrt(n_pixels) itself — see
    routes/imaging_ops.py::analyze_radial, which does exactly that and
    documents the distinction again at the wire boundary.

    n_pixels is 0 for an empty ring (only possible for masked/NaN-heavy
    callers; radial_profile's own bin geometry always assigns every pixel
    to some ring); avg/max/std are NaN there, matching the existing
    empty-bin convention.
    """
    return _radial_bin(img, center, n_bins, normalize)


def _radial_bin(
    img: np.ndarray,
    center: tuple[float, float] | None,
    n_bins: int,
    normalize: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Shared binning core for radial_profile / radial_profile_stats."""
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
    sums_sq = np.bincount(
        flat_idx, weights=flat_val * flat_val, minlength=n_bins
    )
    with np.errstate(invalid="ignore"):
        avg = sums / counts
        mean_sq = sums_sq / counts
    avg[counts == 0] = np.nan
    # Population variance E[x^2] - E[x]^2; clamp the rare tiny negative
    # from floating-point cancellation before the sqrt.
    var = np.maximum(mean_sq - avg * avg, 0.0)
    std = np.sqrt(var)
    std[counts == 0] = np.nan
    mx = np.full(n_bins, -np.inf)
    np.maximum.at(mx, flat_idx, flat_val)
    mx[counts == 0] = np.nan

    if normalize:
        lo, hi = np.nanmin(avg), np.nanmax(avg)
        if hi > lo:
            avg -= lo
            avg /= hi - lo
            std /= hi - lo
        else:
            avg[:] = 0.0
            std[:] = 0.0
        lo, hi = np.nanmin(mx), np.nanmax(mx)
        if hi > lo:
            mx -= lo
            mx /= hi - lo
        else:
            mx[:] = 0.0

    return radii, avg, mx, std, counts


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
