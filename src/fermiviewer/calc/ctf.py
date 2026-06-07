"""CTF (contrast transfer function) defocus estimation — W4 (verbatim).

Radially averaged power spectrum → grid search over defocus candidates
maximising the dot-product with sin²(χ) → Nelder-Mead refinement.
Wavelength uses the MATLAB-pinned 12.2643/√(V + 0.97845e−6 V²) form.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

__all__ = ["CtfResult", "estimate_ctf"]


@dataclass(frozen=True)
class CtfResult:
    defocus: float  # Angstroms
    defocus_nm: float
    radial_freq: np.ndarray  # 1/A
    radial_power: np.ndarray
    ctf_fit: np.ndarray  # fitted |CTF|² on the radial axis
    r_squared: float
    voltage_kv: float
    cs_mm: float
    lambda_a: float


def _wavelength_a(voltage_kv: float) -> float:
    v = voltage_kv * 1e3
    return float(12.2643 / np.sqrt(v + 0.97845e-6 * v**2))


def estimate_ctf(
    img: np.ndarray,
    voltage_kv: float = 200.0,
    cs_mm: float = 1.2,
    pixel_size: float = 1.0,
    n_rings: int = 10,
) -> CtfResult:
    """Estimate defocus from Thon rings (pixel_size in Å/px)."""
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    lam = _wavelength_a(voltage_kv)
    cs = cs_mm * 1e7  # mm → Å

    ps = np.abs(np.fft.fftshift(np.fft.fft2(d))) ** 2

    du = 1 / (w * pixel_size)
    dv = 1 / (h * pixel_size)
    u_axis = np.arange(-(w // 2), -(w // 2) + w) * du
    v_axis = np.arange(-(h // 2), -(h // 2) + h) * dv
    ku, kv = np.meshgrid(u_axis, v_axis)
    k2d = np.hypot(ku, kv)

    k_max = min(np.abs(u_axis).max(), np.abs(v_axis).max())
    n_bins = max(64, min(512, min(h, w) // 2))
    edges = np.linspace(0, k_max, n_bins + 1)
    centres = (edges[:-1] + edges[1:]) / 2

    # histc semantics: [e_i, e_{i+1}); ONLY exact top-edge values absorb
    # into the last bin — frequencies beyond kMax (the spectrum corners)
    # are excluded entirely, not clamped
    k_flat = k2d.ravel()
    idx = np.searchsorted(edges, k_flat, side="right") - 1
    idx[k_flat == edges[-1]] = n_bins - 1
    valid = (idx >= 0) & (idx < n_bins)
    sums = np.bincount(idx[valid], weights=ps.ravel()[valid], minlength=n_bins)
    counts = np.bincount(idx[valid], minlength=n_bins).astype(np.float64)
    non_empty = counts > 0
    freq = centres[non_empty]
    rad_pow = sums[non_empty] / counts[non_empty]
    rad_pow_n = rad_pow / rad_pow.max() if rad_pow.max() > 0 else rad_pow

    k2 = freq**2
    k4 = freq**4

    def neg_corr(df: float) -> float:
        chi = np.pi * lam * k2 * df - 0.5 * np.pi * cs * lam**3 * k4
        return float(-(np.sin(chi) ** 2 * rad_pow_n).sum())

    k_first = k_max / (n_rings + 1)
    df_min = max(100.0, 0.5 / (lam * k_max**2))
    df_max = 1.5 / (lam * k_first**2)
    candidates = np.linspace(df_min, df_max, 200)
    df_init = candidates[int(np.argmin([neg_corr(df) for df in candidates]))]

    res = minimize(
        lambda p: neg_corr(p[0]),
        np.array([df_init]),
        method="Nelder-Mead",
        options={"xatol": 1.0, "fatol": 1e-6, "maxfev": 500},
    )
    df_fit = float(np.clip(res.x[0], df_min * 0.5, df_max * 1.5))

    chi = np.pi * lam * k2 * df_fit - 0.5 * np.pi * cs * lam**3 * k4
    ctf_sq = np.sin(chi) ** 2
    ss_tot = float(((rad_pow_n - rad_pow_n.mean()) ** 2).sum())
    r_sq = 1 - float(((rad_pow_n - ctf_sq) ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0

    return CtfResult(
        defocus=df_fit,
        defocus_nm=df_fit / 10,
        radial_freq=freq,
        radial_power=rad_pow,
        ctf_fit=ctf_sq,
        r_squared=r_sq,
        voltage_kv=voltage_kv,
        cs_mm=cs_mm,
        lambda_a=lam,
    )
