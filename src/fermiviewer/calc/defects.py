"""Dislocation / defect-line density — W3 tranche 3b (ported verbatim).

Oriented derivative-of-Gaussian filtering (max response over angles),
inline single-threshold Otsu (NOT multi_otsu — different binning), test
line grid, and Ham's (1961) line-intercept density: ρ = 2N/L (2-D) or
2N/(L·t) (3-D with foil thickness).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

__all__ = ["DefectCount", "count_defect_lines"]


@dataclass(frozen=True)
class DefectCount:
    intersection_count: int
    num_test_lines: int
    total_line_length: float
    density: float
    density_unit: str
    enhanced: np.ndarray
    binary_mask: np.ndarray
    h_rows: np.ndarray  # 1-based test line positions (MATLAB convention)
    v_cols: np.ndarray


def _oriented_kernel(
    k_len: int, theta_deg: float, sigma_par: float, sigma_perp: float
) -> np.ndarray:
    """Gaussian along the defect direction × dG/dv perpendicular,
    with split positive/negative zero-mean normalization."""
    hw = k_len // 2
    coords = np.arange(-hw, hw + 1, dtype=np.float64)
    xx, yy = np.meshgrid(coords, coords)
    th = np.deg2rad(theta_deg)
    u = xx * np.cos(th) + yy * np.sin(th)
    v = -xx * np.sin(th) + yy * np.cos(th)
    g_par = np.exp(-0.5 * (u / sigma_par) ** 2)
    g_perp = -(v / sigma_perp**2) * np.exp(-0.5 * (v / sigma_perp) ** 2)
    k: np.ndarray = np.asarray(g_par * g_perp)
    pos = k[k > 0].sum()
    neg = k[k < 0].sum()
    if pos > 0 and abs(neg) > 0:
        k[k > 0] /= pos
        k[k < 0] /= abs(neg)
    return k


def _otsu_threshold(response: np.ndarray, n_bins: int = 256) -> float:
    """Inline Otsu (the countDefectLines variant — bin-centre threshold)."""
    r_min = response.min()
    r_max = response.max()
    rng = r_max - r_min
    edges = np.linspace(r_min, r_max, n_bins + 1)
    centres = (edges[:-1] + edges[1:]) / 2
    norm = (response.ravel() - r_min) / rng
    idx = np.minimum(n_bins - 1, np.floor(norm * n_bins).astype(np.int64))
    counts = np.bincount(idx, minlength=n_bins).astype(np.float64)
    prob = counts / counts.sum()
    omega = np.cumsum(prob)
    mu = np.cumsum(prob * centres)
    mu_total = mu[-1]
    w1 = omega
    w2 = 1 - omega
    safe = (w1 > 1e-10) & (w2 > 1e-10)
    var_between = np.zeros(n_bins)
    var_between[safe] = (mu_total * w1[safe] - mu[safe]) ** 2 / (
        w1[safe] * w2[safe]
    )
    return float(centres[int(np.argmax(var_between))])


def count_defect_lines(
    img: np.ndarray,
    roi: tuple[int, int, int, int] | None = None,
    direction: float | None = None,
    kernel_length: int = 15,
    grid_spacing: int = 50,
    foil_thickness: float = float("nan"),
    pixel_size: float = 1.0,
    pixel_unit: str = "px",
) -> DefectCount:
    """Count line defects via oriented filtering + line intercepts.

    roi is 1-based (r1, c1, r2, c2) inclusive (MATLAB convention);
    direction None sweeps [0, 45, 90, 135]°.
    """
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    if roi is None:
        r1, c1, r2, c2 = 1, 1, h, w
    else:
        r1 = max(1, round(roi[0]))
        c1 = max(1, round(roi[1]))
        r2 = min(h, round(roi[2]))
        c2 = min(w, round(roi[3]))
        if r2 <= r1 or c2 <= c1:
            raise ValueError("invalid ROI")
    patch = d[r1 - 1 : r2, c1 - 1 : c2]
    roi_h, roi_w = patch.shape

    k_len = kernel_length + (kernel_length % 2 == 0)
    sigma = k_len / 6
    angles = [0.0, 45.0, 90.0, 135.0] if direction is None else [direction]

    response = np.zeros((roi_h, roi_w))
    for theta in angles:
        k = _oriented_kernel(k_len, theta, sigma * 2, sigma)
        filtered = signal.convolve2d(patch, k, mode="same", boundary="fill")
        response = np.maximum(response, np.abs(filtered))

    if response.max() <= response.min():
        mask = np.zeros((roi_h, roi_w), dtype=bool)
    else:
        mask = response >= _otsu_threshold(response)

    gap = int(grid_spacing)
    h_rows = np.arange(gap, roi_h, gap, dtype=np.int64)  # 1-based, ≤ roiH-1
    if h_rows.size == 0:
        h_rows = np.array([round(roi_h / 2)], dtype=np.int64)
    v_cols = np.arange(gap, roi_w, gap, dtype=np.int64)
    if v_cols.size == 0:
        v_cols = np.array([round(roi_w / 2)], dtype=np.int64)

    n_hits = 0
    for r in h_rows:
        n_hits += int((np.diff(mask[r - 1, :].astype(np.int8)) == 1).sum())
    for c in v_cols:
        n_hits += int((np.diff(mask[:, c - 1].astype(np.int8)) == 1).sum())

    total_len = (
        h_rows.size * roi_w * pixel_size + v_cols.size * roi_h * pixel_size
    )
    rho_2d = 2 * n_hits / total_len if total_len > 0 else 0.0
    if np.isfinite(foil_thickness) and foil_thickness > 0:
        density = 2 * n_hits / (total_len * foil_thickness)
        density_unit = f"lines/{pixel_unit}^3"
    else:
        density = rho_2d
        density_unit = f"lines/{pixel_unit}^2"

    return DefectCount(
        intersection_count=n_hits,
        num_test_lines=int(h_rows.size + v_cols.size),
        total_line_length=float(total_len),
        density=float(density),
        density_unit=density_unit,
        enhanced=response,
        binary_mask=mask,
        h_rows=h_rows,
        v_cols=v_cols,
    )
