"""2D FFT display transform (port of computeFFT.m)."""

from __future__ import annotations

import numpy as np

__all__ = ["compute_fft"]


def compute_fft(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(log10(1+|F|), phase) of the centred 2D FFT."""
    f = np.fft.fftshift(np.fft.fft2(np.asarray(img, dtype=np.float64)))
    mag: np.ndarray = np.log10(1 + np.abs(f))
    phase: np.ndarray = np.angle(f)
    return mag, phase
