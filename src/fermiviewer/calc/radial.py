"""Radial + azimuthal integration about a centre (ported verbatim).

Split out of ``profiles.py`` to keep that module under the 500-line
god-module ceiling. These two share the radial-binning idiom and are
used together by ``routes/imaging_ops.py``; line/box profiles and ROI
statistics stay in ``profiles.py``. Coordinates are MATLAB-style 1-based
pixel centres throughout.
"""

from __future__ import annotations

import numpy as np

from fermiviewer.calc.calibration import usable_spacing

__all__ = ["azimuthal_integrate", "radial_profile", "radial_profile_stats"]


def radial_profile(
    img: np.ndarray,
    center: tuple[float, float] | None = None,
    n_bins: int = 0,
    normalize: bool = False,
    *,
    spacing: tuple[float, float] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Radial average + max profiles about a centre — ported verbatim.

    Default centre is the pixel-centre convention ((W+1)/2, (H+1)/2) in
    1-based coords; bins span [0, max radius] (the full corner reach,
    unlike azimuthal_integrate's inscribed rMax). n_bins=0 resolves to
    floor(min(H, W)/2) — the documented MATLAB default, whose literal
    default value (0) trips its own validator (latent upstream bug).

    Returns (radii, avg_profile, max_profile); empty bins are NaN.

    Radii are in PIXELS unless `spacing` (`DataStruct.pixel_spacing`,
    ``(row, column)``) is usable, in which case the rings are drawn in
    physical space and the radii come back in its unit. A ring is a set
    of pixels at one physical distance; on anisotropic pixels a pixel
    radius describes an ellipse on the specimen, so scaling pixel radii
    afterwards puts a physically round ring into several bins.
    """
    radii, avg, mx, _std, _n = _radial_bin(img, center, n_bins, normalize, spacing)
    return radii, avg, mx


def radial_profile_stats(
    img: np.ndarray,
    center: tuple[float, float] | None = None,
    n_bins: int = 0,
    normalize: bool = False,
    *,
    spacing: tuple[float, float] | None = None,
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
    empty-bin convention. Radii as in :func:`radial_profile`.
    """
    return _radial_bin(img, center, n_bins, normalize, spacing)


def _physical_offsets(
    cx: float, cy: float, h: int, w: int, spacing: tuple[float, float] | None
) -> tuple[np.ndarray, np.ndarray, float]:
    """``(dx, dy, radius_unit)``: per-pixel offsets from the centre in the
    space the rings are drawn in, and the factor that converts a PIXEL
    radius to the reported one.

    Equal extents keep the pixel-space distance map and scale the radii
    afterwards, exactly the product callers used to form themselves, so
    square-pixel profiles are bit for bit unchanged. Unequal extents make
    the map physical, and then there is no pixel radius to scale.
    """
    dx = np.arange(1, w + 1, dtype=np.float64)[None, :] - cx
    dy = np.arange(1, h + 1, dtype=np.float64)[:, None] - cy
    sp = usable_spacing(spacing)
    if sp is None:
        return dx, dy, 1.0
    s_row, s_col = sp
    if s_row == s_col:
        return dx, dy, s_col
    return dx * s_col, dy * s_row, 1.0


def _radial_bin(
    img: np.ndarray,
    center: tuple[float, float] | None,
    n_bins: int,
    normalize: bool,
    spacing: tuple[float, float] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Shared binning core for radial_profile / radial_profile_stats."""
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    cx, cy = center if center is not None else (w / 2 + 0.5, h / 2 + 0.5)
    if n_bins <= 0:
        n_bins = min(h, w) // 2

    dx, dy, radius_unit = _physical_offsets(cx, cy, h, w, spacing)
    dist_map = np.hypot(dx, dy)

    max_radius = dist_map.max()
    bin_width = max_radius / n_bins
    radii = (np.arange(n_bins) + 0.5) * bin_width
    if radius_unit != 1.0:
        radii = radii * radius_unit

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
    *,
    spacing: tuple[float, float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Sector-masked azimuthal average — ported verbatim.

    Angles measured from +x clockwise (image-row convention), wrapped to
    [0, 360); sector_min >= sector_max selects the wrap-around wedge.
    rMax is the inscribed distance to the nearest edge (NOT the corner
    reach used by radial_profile). NaN pixels are excluded; empty bins
    are NaN. Returns (radii_calibrated, intensity).

    `spacing` (`DataStruct.pixel_spacing`, ``(row, column)``) wins over
    `pixel_size`, the column scale read as isotropic. With unequal
    extents the rings, the sector angles and rMax are all taken in
    physical space: a 45° wedge on 1:3 pixels is not the pixel-space 45°
    wedge, and the nearest edge is the nearest in the specimen's units.
    """
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    cx, cy = center if center is not None else ((w + 1) / 2, (h + 1) / 2)
    if n_bins <= 0:
        n_bins = min(h, w) // 2

    sp = usable_spacing(spacing)
    if sp is None:
        s_row = s_col = float(pixel_size)
    else:
        s_row, s_col = sp
    if s_row == s_col:
        # pixel-space rings, scaled afterwards: the port, bit for bit
        dx, dy, _ = _physical_offsets(cx, cy, h, w, None)
        r_max = max(min(cx, cy, w - cx, h - cy), 1.0)
        radius_unit = s_col
    else:
        # physical rings; inscribed reach and its one-pixel floor in the
        # same units, and nothing left to scale
        dx, dy, _ = _physical_offsets(cx, cy, h, w, (s_row, s_col))
        r_max = max(
            min(cx * s_col, cy * s_row, (w - cx) * s_col, (h - cy) * s_row),
            min(s_row, s_col),
        )
        radius_unit = 1.0
    radius = np.hypot(dx, dy)
    phi = np.degrees(np.arctan2(dy, dx))
    phi = np.where(phi < 0, phi + 360, phi)

    if sector_min == 0 and sector_max == 360:
        sector = np.ones((h, w), dtype=bool)
    elif sector_min < sector_max:
        sector = (phi >= sector_min) & (phi < sector_max)
    else:  # wrapping wedge, e.g. 300 -> 60
        sector = (phi >= sector_min) | (phi < sector_max)

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

    return centres * radius_unit, intensity
