"""Point/region measurement helpers built on the line-profile sampling
core: tilt-corrected distance, rect/ellipse ROI statistics, axis-aligned
box integration, and erf/sigmoid interface-width fitting. Split out of
calc/profiles.py to keep both modules comfortably under the 500-line
ceiling.

Coordinates are MATLAB-style 1-based pixel centres throughout (matching
the diffraction module and the wire protocol).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.region_mask import rasterize
from fermiviewer.calc.region_stats import STD_MATLAB, region_stats
from fermiviewer.calc.regions import Part, Region, ellipse

__all__ = [
    "DistanceResult",
    "InterfaceFit",
    "box_integrate",
    "fit_interface_width",
    "measure_distance",
    "roi_stats",
]


@dataclass(frozen=True)
class DistanceResult:
    raw_px: float
    corrected_px: float
    raw_calibrated: float | None    # None when uncalibrated
    corrected_calibrated: float | None
    unit: str                       # physical unit string, 'px' when uncalibrated
    tilt_angle_deg: float
    tilt_axis: str
    geometry: str


def measure_distance(
    x1: float, y1: float,
    x2: float, y2: float,
    pixel_size: float = float("nan"),
    pixel_unit: str = "px",
    tilt_angle_deg: float = 0.0,
    tilt_axis: str = "Y",
    geometry: str = "cross-section",
) -> DistanceResult:
    """Euclidean distance between two points with optional tilt correction.

    Port of imaging.measureDistance.m (verbatim geometry, validator, and
    correction logic).

    Formula
    -------
    Let dx = X2 - X1, dy = Y2 - Y1. When tilt_angle_deg != 0, the
    in-tilt-axis component is scaled::

        cross-section (FIB): dy *= 1/sin(theta)   (TiltAxis='Y')
        surface (plan-view):  dy *= 1/cos(theta)

    Then: corrected_px = sqrt(dx^2 + dy^2).

    Parameters
    ----------
    x1, y1 : start point (column, row) in 1-based pixel coordinates
    x2, y2 : end   point (column, row) in 1-based pixel coordinates
    pixel_size : nm (or other unit) per pixel; NaN → uncalibrated
    pixel_unit : unit label ('nm', 'um', etc.)
    tilt_angle_deg : stage tilt in degrees; must be in (-90, 90) exclusive
    tilt_axis : 'Y' (row axis, default) or 'X' (column axis)
    geometry : 'cross-section' (1/sin, default) or 'surface' (1/cos)

    Returns
    -------
    DistanceResult with raw and corrected distances in pixels and in
    calibrated units (None when uncalibrated).

    Examples
    --------
    >>> r = measure_distance(0, 0, 3, 4)          # 3-4-5 triangle
    >>> r.raw_px
    5.0
    >>> r = measure_distance(0, 0, 0, 10, tilt_angle_deg=30)  # cross-section
    >>> round(r.corrected_px, 4)   # 10 / sin(30) = 20.0
    20.0

    References
    ----------
    Goldstein et al., "Scanning Electron Microscopy and X-Ray Microanalysis",
    4th ed., Springer 2018, ch. 4 (geometric distortions).
    Giannuzzi & Stevie, "Introduction to Focused Ion Beams", Springer 2005,
    ch. 10 (cross-section metrology).
    """
    if not (-90 < tilt_angle_deg < 90):
        raise ValueError("tilt_angle_deg must be in (-90, 90) exclusive")
    axis = tilt_axis.upper()
    if axis not in ("X", "Y"):
        raise ValueError("tilt_axis must be 'X' or 'Y'")
    geom = geometry.lower().replace("-", "").replace("_", "")

    dx = float(x2 - x1)
    dy = float(y2 - y1)
    raw_px = float(np.hypot(dx, dy))

    if tilt_angle_deg != 0.0:
        if geom == "surface":
            scale = 1.0 / np.cos(np.deg2rad(tilt_angle_deg))
        else:                        # 'crosssection'
            scale = 1.0 / np.sin(np.deg2rad(tilt_angle_deg))
        if axis == "Y":
            dy *= scale
        else:
            dx *= scale
    corrected_px = float(np.hypot(dx, dy))

    calibrated = np.isfinite(pixel_size)
    raw_cal = raw_px * pixel_size if calibrated else None
    corr_cal = corrected_px * pixel_size if calibrated else None
    unit = pixel_unit if calibrated else "px"

    return DistanceResult(
        raw_px=raw_px,
        corrected_px=corrected_px,
        raw_calibrated=raw_cal,
        corrected_calibrated=corr_cal,
        unit=unit,
        tilt_angle_deg=tilt_angle_deg,
        tilt_axis=axis,
        geometry=geometry,
    )


def roi_stats(
    img: np.ndarray,
    row1: float, col1: float, row2: float, col2: float,
    pixel_size: float = float("nan"),
    shape: str = "rect",
) -> dict[str, float]:
    """Rectangle or inscribed-ellipse statistics (1-based inclusive
    bounds, clamped). shape='ellipse' keeps only pixels inside the
    ellipse inscribed in the bounding rect.

    4C-2: the geometry now comes from the canonical region contract and
    the aggregates from `calc.region_stats`, so this and the `image_stats`
    op read the same pixels the same way. The returned keys are unchanged
    apart from an added `n_finite`."""
    arr = np.asarray(img)
    if arr.ndim != 2:
        raise ValueError(f"ROI statistics need a 2-D raster, got {arr.shape}")
    h, w = arr.shape
    r1, r2 = sorted((int(round(row1)), int(round(row2))))
    c1, c2 = sorted((int(round(col1)), int(round(col2))))
    r1, r2 = max(r1, 1), min(r2, h)
    c1, c2 = max(c1, 1), min(c2, w)
    if r1 > r2 or c1 > c2:
        raise ValueError("ROI is empty after clamping to the image")
    if shape not in ("rect", "ellipse"):
        raise ValueError("shape must be 'rect' or 'ellipse'")

    mask = None
    if shape == "ellipse":
        # The 4A `ellipse` primitive was defined to match the inline
        # version this replaces — its semi-axis is the footprint
        # `(extent + 1) / 2`, i.e. the `ry = sh / 2` used here — and
        # tests/test_region_stats.py pins the two pixel-identical over
        # square, oblong and degenerate bounds. Bounds go 1-based -> the
        # contract's 0-based inclusive form.
        outline = ellipse(r1 - 1, c1 - 1, r2 - 1, c2 - 1)
        mask = rasterize(Region(id="roi", parts=(Part(outline),)), (h, w))
        if not mask.any():
            raise ValueError("elliptical ROI contains no pixels")

    # ddof=1 is MATLAB parity and stays that way (STD_MATLAB records why).
    # NOTE: mean/std/min/max are now taken over the FINITE pixels only,
    # where this used to propagate a NaN through the whole ROI. `n_finite`
    # reports how many were usable, so the difference is visible.
    return region_stats(
        arr, (r1, c1, r2, c2), mask, pixel_size=pixel_size, ddof=STD_MATLAB
    )


def box_integrate(
    img: np.ndarray,
    row1: float, col1: float, row2: float, col2: float,
    reduce: str = "sum",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    """Integrate an axis-aligned box along BOTH axes → two 1-D profiles.

    For a rectangle clamped to the image, collapse it onto each axis:

    * the **x** profile reduces over rows (one value per column) — the
      horizontal profile you read left-to-right across the box;
    * the **y** profile reduces over columns (one value per row) — the
      vertical profile you read top-to-bottom.

    ``reduce='sum'`` (default) gives the true line integral across the
    perpendicular extent — what "box integration" usually means for
    counts/EELS; ``'mean'`` averages instead, giving a magnitude that is
    independent of the box's perpendicular size.

    Bounds are 1-based inclusive (matching :func:`roi_stats`) and clamped
    to the image. Positions are returned in PIXELS, 0-based from the box
    edge (0, 1, 2, …); the caller applies any pixel-size calibration.

    Returns ``(x_pos, x_intensity, y_pos, y_intensity, clamped_rect)``
    where ``clamped_rect`` is ``(r1, c1, r2, c2)`` in 1-based pixels.

    Examples
    --------
    >>> img = np.arange(1, 13, dtype=float).reshape(3, 4)  # rows of x-ramp
    >>> x_pos, x_int, y_pos, y_int, rect = box_integrate(img, 1, 1, 3, 4)
    >>> x_int            # column sums: 1+5+9, 2+6+10, ...
    array([15., 18., 21., 24.])
    >>> y_int            # row sums: 1+2+3+4, 5+6+7+8, 9+10+11+12
    array([10., 26., 42.])
    """
    if reduce not in ("mean", "sum"):
        raise ValueError("reduce must be 'mean' or 'sum'")
    arr = np.asarray(img, dtype=np.float64)
    h, w = arr.shape
    r1, r2 = sorted((int(round(row1)), int(round(row2))))
    c1, c2 = sorted((int(round(col1)), int(round(col2))))
    r1, r2 = max(r1, 1), min(r2, h)
    c1, c2 = max(c1, 1), min(c2, w)
    if r1 > r2 or c1 > c2:
        raise ValueError("box is empty after clamping to the image")
    sel = arr[r1 - 1 : r2, c1 - 1 : c2]
    fn = np.sum if reduce == "sum" else np.mean
    x_intensity = fn(sel, axis=0)               # one value per column
    y_intensity = fn(sel, axis=1)               # one value per row
    x_pos = np.arange(sel.shape[1], dtype=np.float64)
    y_pos = np.arange(sel.shape[0], dtype=np.float64)
    return x_pos, x_intensity, y_pos, y_intensity, (r1, c1, r2, c2)


@dataclass(frozen=True)
class InterfaceFit:
    center: float
    sigma: float
    width_10_90: float
    amplitude: float
    offset: float
    r_squared: float
    x_fit: np.ndarray
    y_fit: np.ndarray
    model: str


def fit_interface_width(
    x: np.ndarray, y: np.ndarray, model: str = "erf"
) -> InterfaceFit:
    """4-parameter erf/sigmoid interface fit — ported verbatim.

    Mirrors fminsearch with Nelder-Mead (xatol/fatol 1e-10); converged
    minima agree with MATLAB to ~1e-6 on clean data (optimizer paths
    differ — golden tolerance is 1e-5, per the audit).

    10–90 % width: 2·erfinv(0.8)·σ·√2 (erf) or 2·σ·ln 9 (sigmoid).
    """
    from scipy.optimize import minimize
    from scipy.special import erf as _erf
    from scipy.special import erfinv

    xv = np.asarray(x, dtype=np.float64).ravel()
    yv = np.asarray(y, dtype=np.float64).ravel()
    if xv.size != yv.size:
        raise ValueError("x and y must have the same number of elements")
    if xv.size < 4:
        raise ValueError("at least 4 data points are required")
    if model not in ("erf", "sigmoid"):
        raise ValueError("model must be 'erf' or 'sigmoid'")

    x_range = xv.max() - xv.min()
    amp0 = yv.max() - yv.min()
    mid = xv.size // 2
    if yv[:mid].mean() > yv[mid:].mean():
        amp0 = -amp0  # falling transition
    p0 = np.array(
        [(xv.min() + xv.max()) / 2, x_range / 8, amp0, yv.min()]
    )

    if model == "erf":

        def model_fn(p: np.ndarray, t: np.ndarray) -> np.ndarray:
            out: np.ndarray = (
                p[2] / 2 * _erf((t - p[0]) / (p[1] * np.sqrt(2)))
                + p[3] + p[2] / 2
            )
            return out
    else:

        def model_fn(p: np.ndarray, t: np.ndarray) -> np.ndarray:
            out: np.ndarray = p[2] / (1 + np.exp(-(t - p[0]) / p[1])) + p[3]
            return out

    res = minimize(
        lambda p: float(((yv - model_fn(p, xv)) ** 2).sum()),
        p0,
        method="Nelder-Mead",
        options={
            "xatol": 1e-10,
            "fatol": 1e-10,
            "maxiter": 5000,
            "maxfev": 5000,
        },
    )
    p = res.x
    sigma = abs(float(p[1]))
    if model == "erf":
        width = float(2 * erfinv(0.8) * sigma * np.sqrt(2))
    else:
        width = float(2 * sigma * np.log(9))

    y_hat = model_fn(p, xv)
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    r_sq = 1.0 if ss_tot == 0 else 1 - float(((yv - y_hat) ** 2).sum()) / ss_tot

    x_fit = np.linspace(xv.min(), xv.max(), 500)
    return InterfaceFit(
        center=float(p[0]),
        sigma=sigma,
        width_10_90=width,
        amplitude=float(p[2]),
        offset=float(p[3]),
        r_squared=r_sq,
        x_fit=x_fit,
        y_fit=model_fn(p, x_fit),
        model=model,
    )
