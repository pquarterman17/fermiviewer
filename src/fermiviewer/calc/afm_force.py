"""Force-curve analysis: baseline, contact point, adhesion and the elastic
modulus from Hertz / Sneddon contact mechanics.

Inputs follow io/force_common.py: Z in nm growing toward the sample,
deflection d in nm, positive for repulsion. With the spring constant k in
N/m, ``F = k·d`` is in nN, and the indentation of the sample is the Z
travel past the contact point minus the cantilever's own bending,
``δ = (Z − Z_c) − d``. Moduli come out in nN/nm² = GPa (reported in Pa).

* **Baseline** — a line fitted to deflection vs Z over the far part of
  the approach (default: the first half of its Z range), subtracted from
  both segments; it removes the deflection offset and a virtual-deflection
  tilt (optical interference, drag).
* **Contact point** — the last zero crossing of the corrected approach
  before its maximum; then refined as a free parameter of the fit.
* **Fit** — least squares in (E_r, Z_c) over the approach from below the
  contact to the fit window (maximum indentation and/or force), model
  zero before contact:

  =========  =========================================  ================
  sphere     F = 4/3 · E_r · √R · δ^3/2                 Hertz (paraboloid)
  cone       F = 2/π · E_r · tan α · δ²                  Sneddon
  pyramid    F = 0.7453 · E_r · tan α · δ²               Bilodeau, 4-sided
  flat       F = 2 · E_r · R · δ                         flat punch
  =========  =========================================  ================

  with the reduced modulus ``E_r = E / (1 − ν²)`` of the sample (the tip
  taken as rigid).
* **Adhesion** — the most negative force on the retract (pull-off), and
  the work of adhesion: the area of that attractive well against the
  tip–sample separation, in aJ (nN·nm).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.optimize import least_squares

__all__ = ["ForceAnalysis", "Tip", "analyze_curve", "fit_baseline", "find_contact",
           "contact_force"]

TipShape = Literal["sphere", "cone", "pyramid", "flat"]


@dataclass(frozen=True)
class Tip:
    shape: TipShape = "sphere"
    radius_nm: float = 20.0          # sphere radius / punch radius
    half_angle_deg: float = 20.0     # cone half-angle / pyramid face angle

    def prefactor(self) -> tuple[float, float]:
        """(c, p) with F = c · E_r · δ^p (nN, GPa, nm)."""
        if self.shape == "sphere":
            return 4.0 / 3.0 * np.sqrt(self.radius_nm), 1.5
        tan = np.tan(np.radians(self.half_angle_deg))
        if self.shape == "cone":
            return 2.0 / np.pi * tan, 2.0
        if self.shape == "pyramid":
            return 0.7453 * tan, 2.0
        return 2.0 * self.radius_nm, 1.0


def contact_force(delta: np.ndarray, e_r_gpa: float, tip: Tip) -> np.ndarray:
    c, p = tip.prefactor()
    return np.asarray(c * e_r_gpa * np.clip(delta, 0.0, None) ** p, dtype=np.float64)


def fit_baseline(z: np.ndarray, d: np.ndarray, lo: float = 0.0,
                 hi: float = 0.5) -> tuple[np.ndarray, float]:
    """Line through the approach points whose Z lies in the [lo, hi]
    fraction of the Z range from the far end: (polyfit coefficients, σ)."""
    zmin, span = float(z.min()), float(np.ptp(z))
    sel = (z >= zmin + lo * span) & (z <= zmin + hi * span)
    if sel.sum() < 3:
        raise ValueError("too few points in the baseline window")
    coef = np.polyfit(z[sel], d[sel], 1)
    sigma = float(np.std(d[sel] - np.polyval(coef, z[sel])))
    return coef, sigma


def find_contact(z: np.ndarray, d: np.ndarray) -> float:
    """Z of the last zero crossing of the corrected deflection `d` before
    its maximum (time-ordered approach)."""
    top = int(np.argmax(d))
    eps = 1e-9 * float(np.ptp(d))                # rounding left by the baseline fit
    below = np.nonzero(d[: top + 1] <= eps)[0]
    if below.size == 0:
        return float(z[0])
    i = int(below[-1])
    if i >= top:
        return float(z[top])
    d0, d1 = d[i], d[i + 1]
    t = d0 / (d0 - d1) if d1 != d0 else 0.0
    return float(z[i] + t * (z[i + 1] - z[i]))


@dataclass
class ForceAnalysis:
    baseline: tuple[float, float]       # deflection = slope·Z + offset (nm)
    noise_nm: float
    contact_z: float                    # nm (refined by the fit when it ran)
    max_force: float                    # nN, approach
    snap_in: float                      # nN, attractive dip before contact (≥ 0)
    adhesion: float                     # nN, pull-off (≥ 0), NaN without a retract
    adhesion_z: float                   # nm, where the pull-off happens
    adhesion_energy: float              # aJ
    e_r: float                          # GPa, reduced modulus
    youngs_modulus: float               # Pa
    fit_r2: float
    fit_rms: float                      # nN
    fit_points: int
    max_indentation: float              # nm, at the maximum force
    contact_slope: float                # d(deflection)/dZ at the top of the approach


def _window(z: np.ndarray, d: np.ndarray, zc: float, max_indent: float | None,
            max_force_nn: float | None, k: float) -> np.ndarray:
    delta = (z - zc) - d
    sel = np.ones(z.size, dtype=bool)
    if max_indent is not None:
        sel &= delta <= max_indent
    if max_force_nn is not None:
        sel &= k * d <= max_force_nn
    depth = float(np.max(delta[sel], initial=0.0)) if sel.any() else 0.0
    return sel & (z >= zc - max(depth, 1.0))     # and as much baseline before contact


def _fit(z: np.ndarray, d: np.ndarray, zc0: float, k: float, tip: Tip,
         sel: np.ndarray) -> tuple[float, float, np.ndarray]:
    zs, ds = z[sel], d[sel]
    f = k * ds

    def resid(x: np.ndarray) -> np.ndarray:
        return np.asarray(f - contact_force((zs - x[1]) - ds, x[0], tip))

    c, p = tip.prefactor()
    delta0 = np.clip((zs - zc0) - ds, 0, None) ** p
    e0 = float(f @ delta0 / (c * (delta0 @ delta0))) if delta0.any() else 1.0
    span = float(np.ptp(zs)) or 1.0
    res = least_squares(resid, x0=[max(e0, 1e-9), zc0], x_scale=[max(e0, 1e-6), span / 10],
                        bounds=([0.0, zs.min() - span], [np.inf, zs.max()]))
    return float(res.x[0]), float(res.x[1]), res.fun


def _adhesion(z: np.ndarray, d: np.ndarray, zc: float, k: float) -> tuple[float, float, float]:
    f = k * d
    i = int(np.argmin(f))
    if f[i] >= 0:
        return 0.0, float("nan"), 0.0
    lo = i
    while lo > 0 and f[lo - 1] < 0:
        lo -= 1
    hi = i
    while hi < f.size - 1 and f[hi + 1] < 0:
        hi += 1
    sep = (zc - z[lo:hi + 1]) + d[lo:hi + 1]   # tip–sample separation
    energy = float(abs(np.trapezoid(-f[lo:hi + 1], sep)))
    return float(-f[i]), float(z[i]), energy


def analyze_curve(z_app: np.ndarray, d_app: np.ndarray, z_ret: np.ndarray | None,
                  d_ret: np.ndarray | None, *, k: float, tip: Tip, poisson: float = 0.5,
                  baseline: tuple[float, float] = (0.0, 0.5),
                  max_indent: float | None = None, max_force: float | None = None,
                  fit: bool = True) -> ForceAnalysis:
    """Analyse one curve (deflection already in nm). `max_force` is in nN."""
    if not np.isfinite(k) or k <= 0:
        raise ValueError("a positive spring constant is needed")
    coef, sigma = fit_baseline(z_app, d_app, *baseline)
    da = d_app - np.polyval(coef, z_app)
    zc = find_contact(z_app, da)
    fa = k * da
    pre = z_app < zc
    snap = float(max(-fa[pre].min(), 0.0)) if pre.any() else 0.0

    e_r = r2 = rms = float("nan")
    n_fit = 0
    if fit:
        sel = _window(z_app, da, zc, max_indent, max_force, k)
        if sel.sum() >= 5:
            e_r, zc, resid = _fit(z_app, da, zc, k, tip, sel)
            f = fa[sel]
            ss = float(((f - f.mean()) ** 2).sum())
            r2 = 1.0 - float(resid @ resid) / ss if ss > 0 else float("nan")
            rms, n_fit = float(np.sqrt(np.mean(resid ** 2))), int(sel.sum())

    top = da >= da.max() - 0.2 * np.ptp(da)
    slope = float(np.polyfit(z_app[top], da[top], 1)[0]) if top.sum() >= 3 else float("nan")
    imax = int(np.argmax(fa))
    adh = (float("nan"), float("nan"), float("nan"))
    if z_ret is not None and d_ret is not None and z_ret.size >= 3:
        adh = _adhesion(z_ret, d_ret - np.polyval(coef, z_ret), zc, k)
    return ForceAnalysis(
        baseline=(float(coef[0]), float(coef[1])), noise_nm=sigma, contact_z=zc,
        max_force=float(fa[imax]), snap_in=snap,
        adhesion=adh[0], adhesion_z=adh[1], adhesion_energy=adh[2],
        e_r=e_r, youngs_modulus=e_r * (1.0 - poisson ** 2) * 1e9,
        fit_r2=r2, fit_rms=rms, fit_points=n_fit,
        max_indentation=float((z_app[imax] - zc) - da[imax]), contact_slope=slope,
    )
