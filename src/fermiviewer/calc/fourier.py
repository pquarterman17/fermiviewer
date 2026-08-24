"""2D FFT display transform (port of computeFFT.m)."""

from __future__ import annotations

import numpy as np

__all__ = ["compute_fft", "fft_mask_inverse", "local_fft_region"]


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


def local_fft_region(
    img: np.ndarray, rect: tuple[float, float, float, float]
) -> np.ndarray:
    """The sub-raster a local FFT runs on — the (r0, c0, r1, c1) 1-based
    inclusive corner rect, sorted and clamped to the image, with the ≥5 px
    minimum a meaningful FFT needs. Lifted out of `routes/measure.py`
    (wave B, ADR 0005 §1) so the registered `fft` op and the HTTP route
    share this arithmetic. Not `calc.roi.extract_rect_roi`: the semantics
    differ (float corners, and a too-small region is an error, never a
    clamp-to-something)."""
    d = np.asarray(img)
    h, w = d.shape
    r0, r1 = sorted((int(rect[0]), int(rect[2])))
    c0, c1 = sorted((int(rect[1]), int(rect[3])))
    r0, c0 = max(r0, 1), max(c0, 1)
    r1, c1 = min(r1, h), min(c1, w)
    if r1 - r0 < 4 or c1 - c0 < 4:
        raise ValueError("FFT region too small (≥5 px)")
    return d[r0 - 1 : r1, c0 - 1 : c1]
