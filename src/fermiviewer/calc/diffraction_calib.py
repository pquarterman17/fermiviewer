"""Diffraction calibration — elliptical-distortion fit + camera constant.

Diffraction #1. Post-specimen lenses distort SAED/NBED rings into ellipses, so
raw spot radii give systematically wrong d-spacings (and wrong strain). This
pure module fits an ellipse to a known-standard ring, un-distorts radii to the
equivalent circle, and anchors the camera constant ``C = R·d`` (px·Å) from a
ring of known d-spacing.

Conventions: points are 1-based ``(row, col)`` like the rest of
``diffraction.py``; the default beam centre is ``floor(H/2)+1`` — the SAME
convention ``index_spots`` uses (NOT the ``H/2+0.5`` *simulate* offset, a
separate calibrated code path that this module must not touch). The ellipse fit
is the in-house Halir–Flušser direct least-squares method (numpy/scipy only —
no new dep, Apache-clean).

Kept out of ``diffraction.py`` (already 446 lines) to respect the 500-line
ceiling. Pure layer: numpy/stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "EllipseFit",
    "beam_center",
    "camera_constant",
    "detect_ring_points",
    "fit_ellipse",
    "undistort_radii",
]


def beam_center(img_size: tuple[int, int]) -> tuple[float, float]:
    """The 1-based beam centre ``(row, col)`` = ``floor(H/2)+1`` — matching
    ``index_spots`` (do not use the simulate ``H/2+0.5`` convention here)."""
    return (img_size[0] // 2 + 1, img_size[1] // 2 + 1)


@dataclass(frozen=True)
class EllipseFit:
    """Fitted ellipse in image coords. ``a >= b`` are the semi-axes (px),
    ``theta`` the major-axis angle (rad, measured from the +col/x axis toward
    +row/y). Centre is 1-based ``(row, col)``."""

    center_row: float
    center_col: float
    a: float
    b: float
    theta: float

    @property
    def eccentricity(self) -> float:
        if self.a <= 0:
            return 0.0
        return float(np.sqrt(max(0.0, 1.0 - (self.b / self.a) ** 2)))

    @property
    def mean_radius(self) -> float:
        """Area-preserving equivalent circular radius ``sqrt(a·b)``."""
        return float(np.sqrt(self.a * self.b))

    def radius_at(self, phi: np.ndarray | float) -> np.ndarray:
        """Ellipse radius at polar angle(s) ``phi`` (rad, image frame)."""
        p = np.asarray(phi, dtype=np.float64) - self.theta
        denom = np.sqrt((self.b * np.cos(p)) ** 2 + (self.a * np.sin(p)) ** 2)
        out: np.ndarray = np.divide(
            self.a * self.b, denom, out=np.full_like(np.asarray(p, float), np.nan),
            where=denom != 0,
        )
        return out


def fit_ellipse(points_rc: np.ndarray) -> EllipseFit:
    """Direct least-squares ellipse fit (Halir–Flušser) to ``(row, col)``
    points. Needs ≥5 non-degenerate points. Raises ValueError otherwise."""
    pts = np.asarray(points_rc, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 5 or pts.shape[1] != 2:
        raise ValueError("need ≥5 (row, col) points to fit an ellipse")
    y = pts[:, 0]  # row → y
    x = pts[:, 1]  # col → x
    mx, my = x.mean(), y.mean()
    xs, ys = x - mx, y - my  # centre for numerical stability

    d1 = np.column_stack([xs * xs, xs * ys, ys * ys])
    d2 = np.column_stack([xs, ys, np.ones_like(xs)])
    s1 = d1.T @ d1
    s2 = d1.T @ d2
    s3 = d2.T @ d2
    try:
        t = -np.linalg.solve(s3, s2.T)
    except np.linalg.LinAlgError as e:  # pragma: no cover - degenerate input
        raise ValueError(f"ellipse fit failed: {e}") from None
    m = s1 + s2 @ t
    # Halir–Flušser: C^-1 M, where C is the 4ac−b²=1 constraint matrix, has the
    # closed form of permuting/halving M's rows (no explicit inverse needed)
    c_inv_m = np.vstack([m[2] / 2.0, -m[1], m[0] / 2.0])
    eigvecs = np.linalg.eig(c_inv_m)[1]
    cond = 4.0 * eigvecs[0] * eigvecs[2] - eigvecs[1] ** 2
    valid = np.where(cond > 0)[0]
    if valid.size == 0:
        raise ValueError("no elliptical solution (points may be collinear)")
    a1 = np.real(eigvecs[:, valid[0]])
    a2 = t @ a1
    coeffs = np.concatenate([a1, a2])  # [A, B, C, D, E, F] in centred coords
    return _conic_to_ellipse(coeffs, mx, my)


def _conic_to_ellipse(coeffs: np.ndarray, mx: float, my: float) -> EllipseFit:
    """Geometric params of A x²+B xy+C y²+D x+E y+F=0 (centred coords), with
    the centre shifted back by (mx, my)."""
    a_, b_, c_, d_, e_, f_ = coeffs
    a33 = np.array([[a_, b_ / 2.0], [b_ / 2.0, c_]])
    center = np.linalg.solve(a33, [-d_ / 2.0, -e_ / 2.0])  # (xc, yc) centred
    xc, yc = float(center[0]), float(center[1])
    f0 = a_ * xc * xc + b_ * xc * yc + c_ * yc * yc + d_ * xc + e_ * yc + f_
    mu, vecs = np.linalg.eigh(a33)  # ascending eigenvalues
    with np.errstate(invalid="ignore"):
        axes = np.sqrt(-f0 / mu)
    if not np.all(np.isfinite(axes)):
        raise ValueError("degenerate conic (not an ellipse)")
    # smaller mu → larger axis; major axis = axes[0], its eigenvector = vecs[:,0]
    major_i = int(np.argmax(axes))
    a_axis = float(axes[major_i])
    b_axis = float(axes[1 - major_i])
    vx, vy = vecs[0, major_i], vecs[1, major_i]
    theta = float(np.arctan2(vy, vx))
    return EllipseFit(
        center_row=yc + my,
        center_col=xc + mx,
        a=a_axis,
        b=b_axis,
        theta=theta,
    )


def detect_ring_points(
    img: np.ndarray,
    center_rc: tuple[float, float] | None = None,
    r_min: float = 5.0,
    r_max: float | None = None,
    n_angles: int = 180,
) -> np.ndarray:
    """Sample the dominant ring as ``(row, col)`` points: along ``n_angles``
    rays from the centre, take the radius of peak intensity in ``[r_min,
    r_max]``. Returns an (n_angles, 2) array (rays hitting no signal dropped)."""
    arr = np.asarray(img, dtype=np.float64)
    h, w = arr.shape[:2]
    cr, cc = center_rc if center_rc is not None else beam_center((h, w))
    cr -= 1.0  # to 0-based for sampling
    cc -= 1.0
    if r_max is None:
        r_max = 0.95 * min(cr, cc, h - 1 - cr, w - 1 - cc)
    if r_max <= r_min:
        return np.empty((0, 2))
    radii = np.arange(r_min, r_max, 1.0)
    pts: list[tuple[float, float]] = []
    for ang in np.linspace(0.0, 2.0 * np.pi, n_angles, endpoint=False):
        rr = cr + radii * np.sin(ang)
        cc_ = cc + radii * np.cos(ang)
        ri = np.round(rr).astype(int)
        ci = np.round(cc_).astype(int)
        inside = (ri >= 0) & (ri < h) & (ci >= 0) & (ci < w)
        if not inside.any():
            continue
        prof = np.full(radii.shape, -np.inf)
        prof[inside] = arr[ri[inside], ci[inside]]
        best = int(np.argmax(prof))
        if np.isfinite(prof[best]):
            pts.append((rr[best] + 1.0, cc_[best] + 1.0))  # back to 1-based
    return np.asarray(pts, dtype=np.float64) if pts else np.empty((0, 2))


def undistort_radii(
    points_rc: np.ndarray, ellipse: EllipseFit
) -> np.ndarray:
    """Map each point's measured radius (from the ellipse centre) to its
    equivalent-circle radius, scaling by ``mean_radius / ellipse_radius(φ)`` so
    every point on the fitted ring collapses to ``mean_radius``."""
    pts = np.asarray(points_rc, dtype=np.float64)
    dy = pts[:, 0] - ellipse.center_row
    dx = pts[:, 1] - ellipse.center_col
    r_meas = np.hypot(dy, dx)
    phi = np.arctan2(dy, dx)
    r_ell = ellipse.radius_at(phi)
    out: np.ndarray = np.where(
        np.isfinite(r_ell) & (r_ell > 0), r_meas * ellipse.mean_radius / r_ell, r_meas
    )
    return out


def camera_constant(d_known_ang: float, r_corrected_px: float) -> float:
    """Camera constant ``C = R·d`` (px·Å) from a standard ring of known
    d-spacing: any other ring's d-spacing is then ``d = C / R``."""
    if d_known_ang <= 0 or not np.isfinite(r_corrected_px):
        return float("nan")
    return float(r_corrected_px * d_known_ang)
