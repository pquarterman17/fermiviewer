"""2D FFT display transform (port of computeFFT.m)."""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.calibration import (
    is_reciprocal_unit,
    reciprocal_spacing,
    usable_spacing,
)
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

__all__ = [
    "compute_fft",
    "fft_axes",
    "fft_datastruct",
    "fft_mask_inverse",
    "local_fft_region",
]


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


def fft_axes(source: DataStruct, shape: tuple[int, ...]) -> tuple[AxisCal, AxisCal]:
    """Calibration of the centred FFT of `source` computed over an
    ``(H, W)`` raster: ``1 / (N * s)`` per pixel in ``1 / unit`` along each
    axis, with the origin at DC (index ``N // 2``, where `compute_fft`'s
    fftshift puts it), so `AxisCal.axis` reads as spatial frequency.

    FFT space is not real space, so the parent's nm never carry over; but
    the parent's per-axis pixel size is exactly what fixes the frequency
    grid, and dropping it is how a 2:1 source came back with a square
    reciprocal grid. Uncalibrated when the source has no usable per-axis
    spacing, or is itself reciprocal (an FFT of an FFT has no calibration
    this function can state).
    """
    if source.kind is DataKind.SPECTRUM:
        return AxisCal(), AxisCal()
    sp = usable_spacing(source.pixel_spacing)
    unit = source.pixel_unit
    if sp is None or not unit or is_reciprocal_unit(unit):
        return AxisCal(), AxisCal()
    r_row, r_col = reciprocal_spacing(shape, sp)
    recip = f"1/{unit}"
    return (
        AxisCal(scale=r_row, origin=float(int(shape[0]) // 2), units=recip),
        AxisCal(scale=r_col, origin=float(int(shape[1]) // 2), units=recip),
    )


def fft_datastruct(
    mag: np.ndarray, source: DataStruct, metadata: dict[str, Any]
) -> DataStruct:
    """The derived image a log-magnitude FFT registers as, built ONCE for
    the route and the `fft` op (ADR 0005 §1) so the two cannot disagree on
    its calibration. `metadata` is the caller's provenance; the source's
    real-space per-axis pixel size and unit are recorded beside it so the
    reciprocal axes can be traced back to what they were derived from."""
    data = np.ascontiguousarray(mag)
    axes = fft_axes(source, data.shape)
    meta = dict(metadata)
    if axes[0].calibrated:
        s_row, s_col = source.pixel_spacing
        meta["source_pixel_spacing"] = [float(s_row), float(s_col)]
        meta["source_pixel_unit"] = source.pixel_unit
    return DataStruct(data=data, kind=DataKind.IMAGE, axes=axes, metadata=meta)
