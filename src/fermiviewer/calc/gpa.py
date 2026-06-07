"""Geometric phase analysis — W3 tranche 3 (ported verbatim).

Hÿtch-style GPA: per g-vector, Butterworth-mask the (shifted) FFT
around the spot, translate it to DC with a phase ramp, IFFT, unwrap
the phase (rows then columns), then solve G·u = −P/2π for the
displacement field and differentiate for strain.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["GpaResult", "geometric_phase_analysis"]


@dataclass(frozen=True)
class GpaResult:
    exx: np.ndarray
    eyy: np.ndarray
    exy: np.ndarray
    rotation: np.ndarray
    phase1: np.ndarray
    phase2: np.ndarray
    displacement_x: np.ndarray
    displacement_y: np.ndarray


def _extract_phase(
    f_shifted: np.ndarray,
    uu: np.ndarray,
    vv: np.ndarray,
    g: tuple[float, float],
    radius: float,
    order: float,
) -> np.ndarray:
    """Butterworth mask at g → shift to DC → IFFT → 2×1D-unwrapped phase."""
    h, w = f_shifted.shape
    r = np.hypot(uu - g[0], vv - g[1])
    mask = 1.0 / (1.0 + (r / radius) ** (2 * order))

    xx, yy = np.meshgrid(np.arange(w), np.arange(h))
    ramp = np.exp(-1j * 2 * np.pi * (g[0] * xx / w + g[1] * yy / h))
    cg = np.fft.ifft2(np.fft.ifftshift(f_shifted * mask)) * ramp

    raw = np.angle(cg)
    return np.unwrap(np.unwrap(raw, axis=1), axis=0)


def geometric_phase_analysis(
    img: np.ndarray,
    g1: tuple[float, float],
    g2: tuple[float, float],
    mask_radius: float = 0.0,
    mask_order: float = 2.0,
    pixel_size: float = 1.0,
) -> GpaResult:
    """GPA strain mapping from two non-collinear g-vectors.

    g-vectors are in FFT-pixel offsets from the (fftshifted) centre,
    (gx, gy) = (column, row) frequency index. mask_radius 0 resolves to
    min(|g1|, |g2|)/3, floored at 1.
    """
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape

    if mask_radius == 0:
        mask_radius = max(1.0, min(np.hypot(*g1), np.hypot(*g2)) / 3)

    f = np.fft.fftshift(np.fft.fft2(d))
    u_axis = np.arange(-(w // 2), -(w // 2) + w)
    v_axis = np.arange(-(h // 2), -(h // 2) + h)
    uu, vv = np.meshgrid(u_axis, v_axis)

    phase1 = _extract_phase(f, uu, vv, g1, mask_radius, mask_order)
    phase2 = _extract_phase(f, uu, vv, g2, mask_radius, mask_order)

    # normalise g to 1/pixel and invert the 2×2 system G·u = −P/2π
    g_mat = np.array(
        [[g1[0] / w, g1[1] / h], [g2[0] / w, g2[1] / h]], dtype=np.float64
    )
    det = g_mat[0, 0] * g_mat[1, 1] - g_mat[0, 1] * g_mat[1, 0]
    if abs(det) < 1e-12:
        raise ValueError("g1 and g2 are linearly dependent")
    g_inv = (
        np.array(
            [
                [g_mat[1, 1], -g_mat[0, 1]],
                [-g_mat[1, 0], g_mat[0, 0]],
            ]
        )
        / det
    )

    rhs1 = -phase1 / (2 * np.pi)
    rhs2 = -phase2 / (2 * np.pi)
    ux = (g_inv[0, 0] * rhs1 + g_inv[0, 1] * rhs2) * pixel_size
    uy = (g_inv[1, 0] * rhs1 + g_inv[1, 1] * rhs2) * pixel_size

    # MATLAB [dudx, dudy] = gradient(ux): first output is d/dcol
    dudy, dudx = np.gradient(ux)
    dvdy, dvdx = np.gradient(uy)

    return GpaResult(
        exx=dudx,
        eyy=dvdy,
        exy=0.5 * (dudy + dvdx),
        rotation=0.5 * (dvdx - dudy),
        phase1=phase1,
        phase2=phase2,
        displacement_x=ux,
        displacement_y=uy,
    )
