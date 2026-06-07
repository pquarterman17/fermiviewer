"""Filtered back-projection — W4 (ported verbatim).

Frequency-domain ramp/Shepp-Logan/Hamming filtering of each projection
(zero-padded to the next power of two), then linear-interpolated
back-projection onto a square grid with the π/(2N) normalisation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["BackProjection", "back_project"]


@dataclass(frozen=True)
class BackProjection:
    reconstruction: np.ndarray
    angles: np.ndarray  # degrees
    filter: str


def _build_filter(width: int, n_pad: int, name: str) -> np.ndarray:
    """Ramp-based frequency filter of length n_pad (fft ordering)."""
    freq = np.arange(n_pad) / n_pad
    k_sym = np.where(freq > 0.5, freq - 1, freq)
    abs_k = np.abs(k_sym)
    k_max = 0.5
    if name == "ramp":
        h = abs_k
    elif name == "shepp-logan":
        arg = np.pi * abs_k / (2 * k_max)
        sinc = np.ones_like(arg)
        nz = arg > 0
        sinc[nz] = np.sin(arg[nz]) / arg[nz]
        h = abs_k * sinc
    elif name == "hamming":
        h = abs_k * (0.54 + 0.46 * np.cos(np.pi * abs_k / k_max))
    else:  # 'none' handled upstream; identity fallback like MATLAB
        h = np.ones(n_pad)
    return h / width


def back_project(
    sinogram: np.ndarray,
    angles: np.ndarray | None = None,
    filter_name: str = "ramp",
    output_size: int = 0,
) -> BackProjection:
    """Reconstruct from a (n_angles × width) sinogram.

    angles default to linspace(−70°, 70°) (typical tomography tilt
    range); output_size 0 resolves to the projection width.
    """
    sino = np.asarray(sinogram, dtype=np.float64)
    n_angles, width = sino.shape
    if angles is None:
        ang = np.linspace(-70.0, 70.0, n_angles)
    else:
        ang = np.asarray(angles, dtype=np.float64).ravel()
        if ang.size != n_angles:
            raise ValueError("angles length must match sinogram rows")
    if filter_name not in ("ramp", "shepp-logan", "hamming", "none"):
        raise ValueError(
            "filter must be ramp, shepp-logan, hamming or none"
        )
    out_size = int(output_size) if output_size else width

    if filter_name == "none":
        filt_sino = sino.copy()
    else:
        n_pad = 1 << int(np.ceil(np.log2(2 * width - 1)))
        h = _build_filter(width, n_pad, filter_name)
        padded = np.zeros((n_angles, n_pad))
        padded[:, :width] = sino
        filtered = np.real(np.fft.ifft(np.fft.fft(padded, axis=1) * h, axis=1))
        filt_sino = filtered[:, :width]

    half_out = (out_size - 1) / 2
    x_out = np.linspace(-half_out, half_out, out_size)
    xg, yg = np.meshgrid(x_out, x_out)
    half_w = (width - 1) / 2
    t_axis = np.linspace(-half_w, half_w, width)

    recon = np.zeros((out_size, out_size))
    for k in range(n_angles):
        theta = np.deg2rad(ang[k])
        t = np.clip(xg * np.cos(theta) + yg * np.sin(theta),
                    t_axis[0], t_axis[-1])
        recon += np.interp(t.ravel(), t_axis, filt_sino[k]).reshape(
            out_size, out_size
        )

    recon *= np.pi / (2 * n_angles)
    return BackProjection(
        reconstruction=recon, angles=ang, filter=filter_name
    )
