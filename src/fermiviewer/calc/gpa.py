"""Geometric phase analysis — W3 tranche 3 (ported verbatim).

Hÿtch-style GPA: per g-vector, Butterworth-mask the (shifted) FFT
around the spot, translate it to DC with a phase ramp, IFFT, unwrap
the phase (rows then columns), then solve G·u = −P/2π for the
displacement field and differentiate for strain.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.crofton import usable_spacing

__all__ = ["GpaResult", "geometric_phase_analysis", "gpa_mean_strain"]


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
    *,
    spacing: tuple[float, float] | None = None,
) -> GpaResult:
    """GPA strain mapping from two non-collinear g-vectors.

    g-vectors are in FFT-pixel offsets from the (fftshifted) centre,
    (gx, gy) = (column, row) frequency index. mask_radius 0 resolves to
    min(|g1|, |g2|)/3, floored at 1.

    `spacing` is the physical extent of one pixel as ``(row, column)``
    (`DataStruct.pixel_spacing`); `pixel_size` is the isotropic fallback
    for a caller with a single length, and an explicit `spacing` wins.

    STRAIN IS DIMENSIONLESS and does not depend on either. `exx` is
    ``d(u_x)/dx``, so the scale appears in the numerator and the
    denominator and cancels. Until 2026-09-02 it did not: the
    displacements were converted to physical units but the gradients were
    still taken against PIXEL indices, so every strain component came out
    multiplied by `pixel_size` -- exx was 10x too large at
    `pixel_size=10`, and only correct at the default of 1. The gradients
    now carry the physical spacing, which is what makes the cancellation
    happen.

    The two DISPLACEMENTS are lengths and do scale, but not by the same
    number when the pixels are not square: `displacement_x` is along
    COLUMNS and `displacement_y` along ROWS.
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

    # A zero, negative or non-finite `pixel_size` is not a calibration,
    # and neither the route model nor the op's `OpParam` excludes one --
    # the sibling `lattice` op in the same catalogue already falls back
    # rather than trusting it. Falling back to 1 is not a guess here:
    # strain is dimensionless, so the four maps this function is asked
    # for are CORRECT at any spacing, and dividing the gradients by zero
    # instead would turn a computable result into NaN. The displacements
    # are then in pixels, which is the honest reading of "no usable
    # scale" -- and no caller exposes them.
    s_row, s_col = (
        usable_spacing(spacing)
        or usable_spacing((pixel_size, pixel_size))
        or (1.0, 1.0)
    )

    rhs1 = -phase1 / (2 * np.pi)
    rhs2 = -phase2 / (2 * np.pi)
    # ux displaces along COLUMNS and uy along ROWS, so they take the
    # column and row extents respectively -- the same number only when
    # the pixels are square.
    ux = (g_inv[0, 0] * rhs1 + g_inv[0, 1] * rhs2) * s_col
    uy = (g_inv[1, 0] * rhs1 + g_inv[1, 1] * rhs2) * s_row

    # MATLAB [dudx, dudy] = gradient(ux): first output is d/dcol. The
    # spacings make each derivative a rate per PHYSICAL length rather
    # than per pixel, which is what leaves the strains dimensionless.
    dudy, dudx = np.gradient(ux, s_row, s_col)
    dvdy, dvdx = np.gradient(uy, s_row, s_col)

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


def gpa_mean_strain(res: GpaResult) -> dict[str, float]:
    """Field means of the four GPA maps — the aggregate block of the
    /analyze/gpa payload, lifted out of `routes/imaging_ops.py` (wave B,
    ADR 0005 §1) so the registered `gpa` op and the route report the
    same numbers."""
    maps = {
        "exx": res.exx, "eyy": res.eyy,
        "exy": res.exy, "rotation": res.rotation,
    }
    return {k: float(np.nanmean(m)) for k, m in maps.items()}
