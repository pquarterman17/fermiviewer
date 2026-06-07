"""2D FFT display transform (port of computeFFT.m)."""

from __future__ import annotations

import numpy as np

__all__ = ["compute_fft", "fft_mask_inverse"]


def compute_fft(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(log10(1+|F|), phase) of the centred 2D FFT."""
    f = np.fft.fftshift(np.fft.fft2(np.asarray(img, dtype=np.float64)))
    mag: np.ndarray = np.log10(1 + np.abs(f))
    phase: np.ndarray = np.angle(f)
    return mag, phase


def fft_mask_inverse(
    img: np.ndarray,
    masks: list[tuple[float, float, float]],
    mode: str = "pass",
) -> np.ndarray:
    """Inverse FFT through circular spectral masks (FFT mask editor).

    masks are (row, col, radius) on the fftshifted spectrum, 1-based
    like the stage's FFT display. mode 'pass' keeps only the masked
    regions (symmetrised: each mask is mirrored through DC so the
    reconstruction stays real); 'reject' suppresses them (and their
    mirrors) — e.g. periodic-noise removal.
    """
    if mode not in ("pass", "reject"):
        raise ValueError("mode must be 'pass' or 'reject'")
    if not masks:
        raise ValueError("at least one mask is required")
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    f = np.fft.fftshift(np.fft.fft2(d))

    rr = np.arange(1, h + 1, dtype=np.float64)[:, None]
    cc = np.arange(1, w + 1, dtype=np.float64)[None, :]
    # DC pixel in 1-based fftshifted coordinates
    dc_r = h // 2 + 1
    dc_c = w // 2 + 1

    sel = np.zeros((h, w), dtype=bool)
    for row, col, radius in masks:
        if radius <= 0:
            raise ValueError("mask radius must be positive")
        sel |= np.hypot(rr - row, cc - col) <= radius
        # conjugate-symmetric mirror keeps the inverse real
        m_row = 2 * dc_r - row
        m_col = 2 * dc_c - col
        sel |= np.hypot(rr - m_row, cc - m_col) <= radius

    if mode == "pass":
        sel = sel.copy()
        sel[dc_r - 1, dc_c - 1] = True  # keep the mean
        f = np.where(sel, f, 0)
    else:
        f = np.where(sel, 0, f)

    out: np.ndarray = np.real(np.fft.ifft2(np.fft.ifftshift(f)))
    return out
