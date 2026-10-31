"""Scan distortion correction: line-to-line jitter within one scanned image,
and frame-to-frame drift across a series. Pure library.

Scanned images (STEM, SEM, AFM) are built one line at a time, so a timing
or stage disturbance displaces whole rows sideways ("jitter") within a
frame, and the field of view wanders between frames ("drift").

* :func:`estimate_line_jitter` measures, for every row, its sub-pixel
  horizontal shift against each of the K rows above it, with the
  normalised correlation of each comparison as its confidence. All those
  pairwise shifts are solved together for one offset per row by weighted
  least squares. Rows that are nearly blank (between atomic rows, say)
  correlate poorly and carry little weight, but stay tied to the rest
  through longer lags — on a lattice, the row one period above matches
  well. Weights fall off as 1/k², since a longer lag sees more genuine
  change in the structure. A small ridge term and the removal of trends
  slower than ``trend_rows`` keep slow, sample-like shear (a tilted
  lattice, a curved interface) from being "corrected": what is removed is
  the row-to-row jitter band, which includes mains-frequency wobble.
  Offsets are reported relative to their median, so the correction
  re-registers rows to each other without translating the whole image.
  On amorphous or featureless areas the estimate is uncertain at the
  ~0.5 px level; on crystalline images it is typically ~0.1–0.3 px.
* :func:`estimate_frame_drift` registers frames by sub-pixel phase
  correlation (scikit-image), first against the first frame and then
  against the mean of the aligned frames, which is far less noisy than any
  single frame. :func:`apply_frame_drift` resamples the frames and crops
  them to the region every frame covers, so no frame contributes padding.

Conventions: an offset ``d`` means the content appears ``d`` pixels further
along the axis than it should, so correction samples at ``x + d``. Frame
shifts are ``(dy, dx)`` in that sense, per frame, with the reference at 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

__all__ = [
    "FrameDrift",
    "LineJitter",
    "apply_frame_drift",
    "correct_line_jitter",
    "estimate_frame_drift",
    "estimate_line_jitter",
]


@dataclass(frozen=True)
class LineJitter:
    """Per-row horizontal offsets (px) and summary statistics."""

    offsets: np.ndarray
    rms: float
    max_abs: float


@dataclass(frozen=True)
class FrameDrift:
    """Per-frame (dy, dx) shifts (px); frame 0 of the input is the origin."""

    shifts: np.ndarray
    max_abs: float


#: Gaussian sigma (px) of the row background removed before rows are
#: compared; structure broader than this cannot locate a sub-pixel shift.
_BACKGROUND_SIGMA = 10.0


def _as_image(img: np.ndarray) -> np.ndarray:
    a = np.asarray(img, dtype=np.float64)
    if a.ndim != 2:
        raise ValueError("expected a 2-D image")
    if a.shape[0] < 3 or a.shape[1] < 8:
        raise ValueError("image too small to estimate jitter (need ≥ 3 rows, ≥ 8 columns)")
    if not np.all(np.isfinite(a)):
        # NaN/inf would poison the FFT correlation of the whole row
        finite = np.isfinite(a)
        a = np.where(finite, a, float(np.median(a[finite])) if finite.any() else 0.0)
    return a


def _pair_shifts(
    a: np.ndarray, max_lag: int, max_shift: float
) -> list[tuple[int, np.ndarray, np.ndarray]]:
    """For each lag k ≤ max_lag: the sub-pixel shift of row r's content
    relative to row r−k (positive: further right), and the normalised
    correlation at the peak, for r = k … h−1. Circular cross-correlation of
    Hann-tapered, mean-removed rows, searched within ±max_shift and refined
    by a parabola through the peak and its neighbours."""
    h, n = a.shape
    # band-pass each row: a light blur against pixel noise, minus a broad
    # blur that removes background. A smooth background correlates with
    # itself at almost any shift, so it would pass the confidence test
    # while carrying no information about where the row actually sits.
    rows = ndimage.gaussian_filter1d(a, 1.0, axis=1) - ndimage.gaussian_filter1d(
        a, _BACKGROUND_SIGMA, axis=1
    )
    rows = (rows - rows.mean(axis=1, keepdims=True)) * np.hanning(n)
    spec = np.fft.rfft(rows, axis=1)
    energy = np.sqrt(np.sum(rows * rows, axis=1))
    structure = np.clip(energy / max(float(np.median(energy)), 1e-300), 0.0, 1.0)
    lim = int(min(math.floor(max_shift), n // 2 - 1))
    lags = np.arange(-lim, lim + 1)
    out = []
    for k in range(1, min(max_lag, h - 1) + 1):
        cc = np.fft.irfft(spec[k:] * np.conj(spec[:-k]), n, axis=1)[:, lags % n]
        i = np.argmax(cc, axis=1)
        idx = np.arange(cc.shape[0])
        peak = cc[idx, i]
        lag = lags[i].astype(np.float64)
        inner = (i > 0) & (i < len(lags) - 1)
        y0 = cc[idx, np.clip(i - 1, 0, None)]
        y2 = cc[idx, np.clip(i + 1, None, len(lags) - 1)]
        denom = y0 - 2.0 * peak + y2
        # only a true (negatively curved) interior maximum is refined
        refine = inner & (denom < 0)
        lag[refine] += 0.5 * (y0 - y2)[refine] / denom[refine]
        corr = peak / np.maximum(energy[k:] * energy[:-k], 1e-300)
        # discount rows with little structure (blank rows between atomic
        # rows): their noise can still correlate by chance, but they carry
        # no information about where the row sits
        corr = corr * np.sqrt(structure[k:] * structure[:-k])
        out.append((k, lag, corr))
    return out


def _solve_offsets(
    h: int,
    pairs: list[tuple[int, np.ndarray, np.ndarray]],
    min_corr: float,
    ridge: float,
) -> np.ndarray:
    """Weighted least squares for row offsets d from pairwise shifts
    s ≈ d[r] − d[r−k]: minimise Σ w (d[r] − d[r−k] − s)² + ridge Σ d²."""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve

    diag = np.full(h, ridge)
    rhs = np.zeros(h)
    r_idx: list[np.ndarray] = []
    c_idx: list[np.ndarray] = []
    vals: list[np.ndarray] = []
    for k, shift, corr in pairs:
        w = np.where(corr >= min_corr, corr**2 / k**2, 0.0)
        r = np.arange(k, h)
        j = r - k
        np.add.at(diag, r, w)
        np.add.at(diag, j, w)
        np.add.at(rhs, r, w * shift)
        np.add.at(rhs, j, -w * shift)
        r_idx += [r, j]
        c_idx += [j, r]
        vals += [-w, -w]
    off = sparse.coo_matrix(
        (np.concatenate(vals), (np.concatenate(r_idx), np.concatenate(c_idx))), shape=(h, h)
    )
    system = (off + sparse.diags(diag)).tocsc()
    return np.asarray(spsolve(system, rhs), dtype=np.float64)


def correct_line_jitter(img: np.ndarray, offsets: np.ndarray) -> np.ndarray:
    """Resample each row at ``x + offset`` (linear interpolation). Columns
    that would sample beyond the image repeat the edge value."""
    a = np.asarray(img, dtype=np.float64)
    offsets = np.asarray(offsets, dtype=np.float64)
    if offsets.shape != (a.shape[0],):
        raise ValueError("need one offset per row")
    x = np.arange(a.shape[1], dtype=np.float64)
    out = np.empty_like(a)
    for r in range(a.shape[0]):
        out[r] = np.interp(x + offsets[r], x, a[r])
    return out


def estimate_line_jitter(
    img: np.ndarray,
    *,
    max_shift: float = 5.0,
    trend_rows: float = 20.0,
    max_lag: int = 16,
    min_corr: float = 0.3,
    iterations: int = 3,
) -> LineJitter:
    """Measure the horizontal offset of every row of a scanned image.

    ``max_shift`` bounds each row comparison (px); keep it below half the
    period of any strong horizontal lattice so a comparison cannot lock onto
    the neighbouring fringe. ``trend_rows`` is the Gaussian sigma (rows) of
    the slow trend kept as genuine structure — jitter repeating within about
    3× that many rows is removed. ``max_lag`` is how many rows above each
    row it is compared with; ``min_corr`` drops comparisons less correlated
    than that. ``iterations`` re-measures on the corrected image to refine
    offsets near the capture range (it stops early once updates fall below
    0.01 px).
    """
    if max_shift < 1:
        raise ValueError("max_shift must be at least 1 px")
    if trend_rows < 0:
        raise ValueError("trend_rows must be ≥ 0 (0 keeps no trend)")
    if max_lag < 1:
        raise ValueError("max_lag must be at least 1")
    if not 0 <= min_corr < 1:
        raise ValueError("min_corr must be in [0, 1)")
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    a = _as_image(img)
    h = a.shape[0]
    total = np.zeros(h)
    current = a
    for _ in range(iterations):
        step = _solve_offsets(h, _pair_shifts(current, max_lag, max_shift), min_corr, 0.1)
        if trend_rows > 0:
            # a steady shear is a straight line across the rows; take it out
            # exactly first, since a Gaussian trend filter mis-estimates a
            # ramp near the image edges and would leave a spurious kink there
            rows = np.arange(h, dtype=np.float64)
            step -= np.polyval(np.polyfit(rows, step, 1), rows)
            step -= ndimage.gaussian_filter1d(step, trend_rows, mode="nearest")
        step -= np.median(step)
        total += step
        current = correct_line_jitter(a, total)
        if np.max(np.abs(step)) < 0.01:
            break
    total -= np.median(total)
    return LineJitter(
        offsets=total,
        rms=float(np.sqrt(np.mean(total**2))),
        max_abs=float(np.max(np.abs(total))),
    )


# ── frame drift ─────────────────────────────────────────────────────────


def _register(ref: np.ndarray, mov: np.ndarray, upsample: int) -> np.ndarray:
    """(dy, dx) displacement of ``mov``'s content relative to ``ref``."""
    from skimage.registration import phase_cross_correlation

    win = np.outer(np.hanning(ref.shape[0]), np.hanning(ref.shape[1]))
    shift, _err, _phase = phase_cross_correlation(
        (ref - ref.mean()) * win,
        (mov - mov.mean()) * win,
        upsample_factor=upsample,
        normalization=None,
    )
    # skimage returns the shift that registers mov onto ref; the content
    # displacement is its negative
    return -np.asarray(shift, dtype=np.float64)


def _shift_frame(frame: np.ndarray, dy: float, dx: float) -> np.ndarray:
    out: np.ndarray = ndimage.shift(frame, (-dy, -dx), order=1, mode="nearest")
    return out


def estimate_frame_drift(
    frames: list[np.ndarray],
    *,
    reference: str = "mean",
    upsample: int = 20,
) -> FrameDrift:
    """Measure the drift of each frame. ``reference`` is ``"first"``
    (register every frame to frame 0) or ``"mean"`` (then re-register every
    frame to the mean of the first-pass-aligned frames). Shifts are
    reported relative to frame 0 either way."""
    if len(frames) < 2:
        raise ValueError("need at least 2 frames")
    if reference not in ("first", "mean"):
        raise ValueError("reference must be 'first' or 'mean'")
    if upsample < 1:
        raise ValueError("upsample must be at least 1")
    arrs = [_as_image(f) for f in frames]
    shape = arrs[0].shape
    if any(f.shape != shape for f in arrs):
        raise ValueError("all frames must have the same size")
    shifts = np.array([[0.0, 0.0]] + [_register(arrs[0], f, upsample) for f in arrs[1:]])
    if reference == "mean":
        mean = np.mean([_shift_frame(f, *s) for f, s in zip(arrs, shifts, strict=True)], axis=0)
        shifts = np.array([_register(mean, f, upsample) for f in arrs])
        shifts -= shifts[0]
    return FrameDrift(shifts=shifts, max_abs=float(np.max(np.abs(shifts))))


def apply_frame_drift(
    frames: list[np.ndarray],
    shifts: np.ndarray,
    *,
    crop: bool = True,
) -> tuple[list[np.ndarray], tuple[int, int, int, int]]:
    """Resample every frame onto frame 0's grid (linear interpolation).

    With ``crop`` the frames are cut to the rectangle every frame covers,
    returned as (top, bottom, left, right) in frame-0 pixels, so the
    aligned frames and their average contain no edge padding."""
    arrs = [np.asarray(f, dtype=np.float64) for f in frames]
    shifts = np.asarray(shifts, dtype=np.float64)
    if shifts.shape != (len(arrs), 2):
        raise ValueError("need one (dy, dx) shift per frame")
    h, w = arrs[0].shape
    aligned = [_shift_frame(f, dy, dx) for f, (dy, dx) in zip(arrs, shifts, strict=True)]
    if not crop:
        return aligned, (0, h, 0, w)
    # aligned[y] samples the source at y + dy, which is inside the source
    # only for 0 ≤ y + dy ≤ h − 1
    top = int(math.ceil(max(0.0, -float(shifts[:, 0].min()))))
    bottom = int(math.floor(min(float(h), h - float(shifts[:, 0].max()))))
    left = int(math.ceil(max(0.0, -float(shifts[:, 1].min()))))
    right = int(math.floor(min(float(w), w - float(shifts[:, 1].max()))))
    if bottom - top < 2 or right - left < 2:
        raise ValueError("drift is larger than the frames: no common region to crop to")
    return [a[top:bottom, left:right] for a in aligned], (top, bottom, left, right)
