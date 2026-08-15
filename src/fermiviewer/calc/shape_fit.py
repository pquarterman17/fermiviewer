"""Direct least-squares circle/ellipse fits on contour points
(SHAPE_ANALYSIS_PLAN Tier-2 item #5) -- geometry for pores, core-shell
shells, and the PLAN_4DSTEM #10 Bragg-disk-detection runway.

`calc/diffraction_calib.py` ALREADY fits ellipses -- to diffraction rings,
via the Halir-Flusser (1998) direct least-squares conic fit. This module
REUSES that fit rather than re-deriving it: `fit_ellipse` below is a thin
wrapper around `diffraction_calib.fit_ellipse` that adds the RMS residual
this module's contract requires. A second, independent ellipse fit in the
same codebase would drift from the first under maintenance -- see that
module's docstring and `SHAPE_ANALYSIS_PLAN.md` item #5, which calls this
out explicitly. No extraction was needed: `diffraction_calib.fit_ellipse`
is already a plain, importable pure function, so this module imports it
rather than moving code around (contrast `calc/eds_absorption.py`, which
WAS an extraction, done because the shared math was landlocked inside
another function's loop body with no importable name of its own).

Circle fit: Kasa's algebraic least-squares circle fit -- the circle
analogue of the ellipse's direct/algebraic (as opposed to iterative
geometric) approach: minimize the ALGEBRAIC residual of
`x^2 + y^2 + D x + E y + F = 0` in `(D, E, F)`, a LINEAR least-squares
problem with a closed-form solution (no Gauss-Newton, no initial guess).
Kasa, I. (1976). "A circle fitting procedure and its error analysis."
IEEE Transactions on Instrumentation and Measurement, IM-25(1), 8-14.
https://doi.org/10.1109/TIM.1976.6312298

Coordinate convention: every point is `(row, col)` -- `row -> y`,
`col -> x` -- exactly like `diffraction_calib.py` and `calc/atoms.py`'s
peak positions. Every length/coordinate this module returns (`cy, cx, r,
a, b`, and `rms`) is in the SAME units and origin convention as the input
points: PIXELS, 0- or 1-based depending on what the caller passed in --
this module does no origin shifting of its own. `routes/shape_id.py`'s
`/analyze/fit-shape` contract is 1-based; that convention lives at the
route layer, not here.

RMS residual: both fits report a RADIAL residual -- for each input point,
the (signed) difference between its measured distance from the fitted
center and the fitted boundary's radius at that point's polar angle, RMS
over all points. This is the same radial-residual convention
`diffraction_calib.undistort_radii` already uses (via `EllipseFit.
radius_at`), not a full orthogonal (nearest-point-on-boundary) residual,
which needs iterative projection and is unnecessary precision for a
"how noisy was this fit" summary number.

PURE: numpy only, plus `calc.diffraction_calib` (itself pure). No
fastapi/pydantic/routes imports -- enforced by tests/test_repo_integrity.py
for every module under calc/.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.diffraction_calib import EllipseFit
from fermiviewer.calc.diffraction_calib import fit_ellipse as _fit_ellipse_conic

__all__ = ["CircleFit", "EllipseFitResult", "fit_circle", "fit_ellipse"]


@dataclass(frozen=True)
class CircleFit:
    """Fitted circle: center `(cy, cx)` and radius `r`, px, plus the RMS
    radial residual (module docstring), same units/origin as the input."""

    cy: float
    cx: float
    r: float
    rms: float


@dataclass(frozen=True)
class EllipseFitResult:
    """Fitted ellipse: center `(cy, cx)`, semi-axes `a >= b` (px), major-
    axis angle `theta_rad` (rad, from +col/x toward +row/y -- same
    convention as `diffraction_calib.EllipseFit`), plus the RMS radial
    residual, same units/origin as the input."""

    cy: float
    cx: float
    a: float
    b: float
    theta_rad: float
    rms: float


def fit_circle(points_rc: np.ndarray) -> CircleFit:
    """Kasa algebraic least-squares circle fit (module docstring).

    Needs >= 3 DISTINCT `(row, col)` points; raises `ValueError` for too
    few points, fewer than 3 distinct locations among them (checked
    explicitly -- `np.linalg.lstsq` silently returns a minimum-norm
    solution for a rank-deficient design matrix instead of raising, so
    relying on it alone to catch "not enough real information" is not
    safe), or a non-positive squared radius from the fitted `(D, E, F)`.
    NEARLY collinear (but still >= 3 distinct) points do NOT raise -- the
    algebraic system stays full rank and solvable -- but they DO produce
    a large `rms`, the known Kasa-fit bias toward a poor circle from a
    short/straight arc; that large residual is the intended signal a
    caller should check for rather than treat a "successful" fit at
    face value.
    """
    pts = np.asarray(points_rc, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 3:
        raise ValueError("need >= 3 (row, col) points to fit a circle")
    if np.unique(pts, axis=0).shape[0] < 3:
        raise ValueError("need >= 3 DISTINCT (row, col) points to fit a circle")
    y = pts[:, 0]
    x = pts[:, 1]

    design = np.column_stack([x, y, np.ones_like(x)])
    rhs = -(x**2 + y**2)
    try:
        solution, *_ = np.linalg.lstsq(design, rhs, rcond=None)
    except np.linalg.LinAlgError as e:  # pragma: no cover - degenerate input
        raise ValueError(f"circle fit failed: {e}") from None
    d_coef, e_coef, f_coef = solution
    cx = -d_coef / 2.0
    cy = -e_coef / 2.0
    r2 = cx * cx + cy * cy - f_coef
    if not np.isfinite(r2) or r2 <= 0:
        raise ValueError("degenerate circle fit (points may be collinear)")
    r = float(np.sqrt(r2))

    resid = np.hypot(x - cx, y - cy) - r
    rms = float(np.sqrt(np.mean(resid**2)))
    return CircleFit(cy=float(cy), cx=float(cx), r=r, rms=rms)


def _ellipse_rms(pts: np.ndarray, ellipse: EllipseFit) -> float:
    """Radial residual RMS (module docstring) using
    `diffraction_calib.EllipseFit.radius_at`, the same helper
    `undistort_radii` already relies on for this exact quantity."""
    dy = pts[:, 0] - ellipse.center_row
    dx = pts[:, 1] - ellipse.center_col
    r_meas = np.hypot(dy, dx)
    phi = np.arctan2(dy, dx)
    r_pred = ellipse.radius_at(phi)
    resid = r_meas - r_pred
    finite = np.isfinite(resid)
    if not finite.any():
        return float("nan")
    return float(np.sqrt(np.mean(resid[finite] ** 2)))


def fit_ellipse(points_rc: np.ndarray) -> EllipseFitResult:
    """Ellipse fit via `diffraction_calib.fit_ellipse` (module docstring),
    plus the RMS radial residual.

    Needs >= 5 non-degenerate `(row, col)` points; raises `ValueError`
    otherwise (propagated from `diffraction_calib.fit_ellipse`, which
    already validates this).
    """
    pts = np.asarray(points_rc, dtype=np.float64)
    ellipse = _fit_ellipse_conic(pts)
    rms = _ellipse_rms(pts, ellipse)
    return EllipseFitResult(
        cy=ellipse.center_row,
        cx=ellipse.center_col,
        a=ellipse.a,
        b=ellipse.b,
        theta_rad=ellipse.theta,
        rms=rms,
    )
