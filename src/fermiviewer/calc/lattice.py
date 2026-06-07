"""Lattice measurement from FFT spot picks — W3 tranche 3 (verbatim).

Two reciprocal-space spot positions (1-based, fftshifted FFT pixel
coordinates) → reciprocal vectors → real-space lattice parameters.
The floor(N/2)+1 centre convention is a pinned do-not-"fix" item.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["LatticeResult", "lattice_measure"]


@dataclass(frozen=True)
class LatticeResult:
    g1: tuple[float, float]  # (gx, gy) in 1/unit
    g2: tuple[float, float]
    a1: tuple[float, float]  # real-space vectors (x, y) in unit
    a2: tuple[float, float]
    a: float
    b: float
    gamma_deg: float
    d_spacing1: float
    d_spacing2: float
    unit_cell_area: float
    cell_vertices: np.ndarray  # 4×2 parallelogram from origin


def lattice_measure(
    spot1: tuple[float, float],
    spot2: tuple[float, float],
    img_size: tuple[int, int],
    pixel_size: float = 1.0,
) -> LatticeResult:
    """Spots are (row, col), 1-based, on the fftshifted FFT of an
    img_size = (rows, cols) image; pixel_size is the REAL-space
    calibration (unit/px)."""
    n_rows, n_cols = int(img_size[0]), int(img_size[1])
    # MATLAB fftshift places DC at floor(N/2)+1 (do-not-"fix")
    center_row = n_rows // 2 + 1
    center_col = n_cols // 2 + 1

    dr1 = spot1[0] - center_row
    dc1 = spot1[1] - center_col
    dr2 = spot2[0] - center_row
    dc2 = spot2[1] - center_col

    g1 = np.array(
        [dc1 / (n_cols * pixel_size), dr1 / (n_rows * pixel_size)]
    )
    g2 = np.array(
        [dc2 / (n_cols * pixel_size), dr2 / (n_rows * pixel_size)]
    )

    n1 = float(np.hypot(*g1))
    n2 = float(np.hypot(*g2))
    if n1 == 0 or n2 == 0:
        raise ValueError("spot coincides with the FFT centre")

    g_mat = np.array([g1, g2])
    det = float(np.linalg.det(g_mat))
    if abs(det) < np.finfo(np.float64).eps * max(n1, n2) ** 2:
        raise ValueError("reciprocal vectors are (nearly) collinear")

    a_mat = np.linalg.inv(g_mat).T  # rows are real-space vectors
    a1 = a_mat[0]
    a2 = a_mat[1]
    a_mag = float(np.hypot(*a1))
    b_mag = float(np.hypot(*a2))
    cos_gamma = float(np.clip(np.dot(a1, a2) / (a_mag * b_mag), -1, 1))

    return LatticeResult(
        g1=(float(g1[0]), float(g1[1])),
        g2=(float(g2[0]), float(g2[1])),
        a1=(float(a1[0]), float(a1[1])),
        a2=(float(a2[0]), float(a2[1])),
        a=a_mag,
        b=b_mag,
        gamma_deg=float(np.degrees(np.arccos(cos_gamma))),
        d_spacing1=1.0 / n1,
        d_spacing2=1.0 / n2,
        unit_cell_area=float(abs(a1[0] * a2[1] - a1[1] * a2[0])),
        cell_vertices=np.array([[0, 0], a1, a1 + a2, a2], dtype=np.float64),
    )
