"""Scanning-probe (AFM/SPM) levelling and scan-artefact correction.

A raster-scanned height map carries artefacts an electron image does not:
every scan line has its own offset or tilt (drift, feedback), the sample sits
on a tilted plane, and the feedback occasionally "jumps" for a line or two
(scars). These are the corrections every AFM tool applies first, in the
Gwyddion sense of the names:

* :func:`level_plane` — polynomial background (reuses ``filters.plane_level``)
  fitted only to the base surface when ``fit_percentile`` < 100, so
  particles do not tilt the fit.
* :func:`level_rows` — per-scan-line correction: mean, median, median of
  differences (row-to-row offset that ignores features) or a per-row
  polynomial.
* :func:`remove_scars` — 1-to-``max_width``-row streaks that stand out from
  the rows above and below, replaced by interpolation.
* :func:`level_three_point` — the plane through three picked points.
* :func:`zero_level` — shift so the minimum / mean / median is zero.

All functions keep NaN pixels as NaN and never let them into a fit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.filters import plane_level

__all__ = [
    "ROW_METHODS",
    "ZERO_MODES",
    "ScarResult",
    "base_mask",
    "level_plane",
    "level_rows",
    "level_three_point",
    "remove_scars",
    "zero_level",
]

ROW_METHODS = ("median", "mean", "mdiff", "poly")
ZERO_MODES = ("min", "mean", "median")


def _as_float(img: np.ndarray) -> np.ndarray:
    d = np.asarray(img, dtype=np.float64)
    if d.ndim != 2:
        raise ValueError("expected a 2-D height map")
    return d


def base_mask(d: np.ndarray, fit_percentile: float = 100.0) -> np.ndarray:
    """Finite pixels at or below the `fit_percentile` height: the base
    surface a levelling fit should see. 100 keeps every finite pixel;
    e.g. 60 ignores the tallest 40 % (particles, islands)."""
    if not 0 < fit_percentile <= 100:
        raise ValueError("fit percentile must be in (0, 100]")
    finite = np.isfinite(d)
    if not finite.any():
        raise ValueError("image has no finite pixels")
    if fit_percentile >= 100:
        return np.asarray(finite, dtype=bool)
    cut = float(np.percentile(d[finite], fit_percentile))
    return np.asarray(finite & (d <= cut), dtype=bool)


def level_plane(img: np.ndarray, order: int = 1, fit_percentile: float = 100.0) -> np.ndarray:
    """Subtract a polynomial surface (order 1–3) fitted to the base pixels.

    With `fit_percentile` < 100 the fit is iterated: fit, keep the pixels
    whose height ABOVE that fit is at or below the percentile, refit. Cutting
    on raw height instead would keep only the low side of a tilted sample
    and bias the very tilt being removed."""
    d = _as_float(img)
    finite = base_mask(d, 100.0)
    need = {1: 3, 2: 6, 3: 10}.get(order, 3)
    filled = np.where(finite, d, 0.0)                # masked out; keeps lstsq finite
    mask = finite
    for _ in range(1 if fit_percentile >= 100 else 4):
        if int(mask.sum()) < need:
            raise ValueError("too few pixels to fit the background")
        surface = plane_level(filled, order=order, mask=mask).surface
        if fit_percentile >= 100:
            break
        mask = base_mask(np.where(finite, d - surface, np.nan), fit_percentile)
    return np.where(finite, d - surface, np.nan)


def _row_stat(row: np.ndarray, m: np.ndarray, how: str) -> float:
    vals = row[m]
    if vals.size == 0:
        vals = row[np.isfinite(row)]
    if vals.size == 0:
        return 0.0
    return float(np.median(vals) if how == "median" else np.mean(vals))


def level_rows(
    img: np.ndarray, method: str = "median", order: int = 1,
    fit_percentile: float = 100.0,
) -> np.ndarray:
    """Per-scan-line levelling (rows are scan lines).

    * ``median`` / ``mean`` — subtract each line's median / mean.
    * ``mdiff`` — align each line to the previous one by the median of
      their pixel-wise difference, so a particle crossing a line does not
      pull its offset; the result keeps the image's overall mean.
    * ``poly`` — subtract a polynomial of `order` (1–3) fitted along each line.
    """
    if method not in ROW_METHODS:
        raise ValueError(f"row method must be one of {ROW_METHODS}")
    d = _as_float(img)
    # judge "base" against each line's own median, so line offsets do not
    # decide which pixels count as features (an all-NaN line has no median
    # and stays NaN; np.nanmedian would warn on it)
    finite = np.isfinite(d)
    row_med = np.array([np.median(d[r][finite[r]]) if finite[r].any() else 0.0
                        for r in range(d.shape[0])])
    mask = base_mask(np.where(finite, d - row_med[:, None], np.nan), fit_percentile)
    out = d.copy()
    h, w = d.shape
    if method in ("median", "mean"):
        for r in range(h):
            out[r] -= _row_stat(d[r], mask[r], method)
    elif method == "mdiff":
        shift = np.zeros(h)
        for r in range(1, h):
            both = mask[r] & mask[r - 1]
            if not both.any():
                both = np.isfinite(d[r]) & np.isfinite(d[r - 1])
            step = float(np.median(d[r][both] - d[r - 1][both])) if both.any() else 0.0
            shift[r] = shift[r - 1] + step
        out -= (shift - shift.mean())[:, None]
    else:
        if not 1 <= order <= 3:
            raise ValueError("row polynomial order must be 1, 2 or 3")
        x = np.linspace(-1.0, 1.0, w)
        for r in range(h):
            m = mask[r] if mask[r].sum() > order else np.isfinite(d[r])
            if m.sum() <= order:
                continue
            coef = np.polyfit(x[m], d[r][m], order)
            out[r] -= np.polyval(coef, x)
    return out


@dataclass(frozen=True)
class ScarResult:
    corrected: np.ndarray
    scar_mask: np.ndarray       # pixels that were replaced

    @property
    def n_pixels(self) -> int:
        return int(self.scar_mask.sum())


def remove_scars(
    img: np.ndarray, threshold: float = 3.0, max_width: int = 2, min_length: int = 8,
) -> ScarResult:
    """Find and repair scars: runs of 1–`max_width` scan lines that sit
    above (or below) BOTH the line before and the line after by more than
    `threshold` × the robust spread of line-to-line differences, over at
    least `min_length` consecutive pixels. Each scar pixel is replaced by
    linear interpolation between the bounding lines."""
    if threshold <= 0 or max_width < 1 or min_length < 1:
        raise ValueError("threshold must be > 0, max width and min length ≥ 1")
    d = _as_float(img)
    h, w = d.shape
    diffs = np.diff(d, axis=0)
    diffs = diffs[np.isfinite(diffs)]
    if diffs.size == 0:
        return ScarResult(d.copy(), np.zeros_like(d, dtype=bool))
    sigma = 1.4826 * float(np.median(np.abs(diffs - np.median(diffs))))
    if sigma == 0:
        sigma = float(np.std(diffs)) or 1.0
    t = threshold * sigma
    out = d.copy()
    scars = np.zeros((h, w), dtype=bool)
    for width in range(1, max_width + 1):
        for top in range(1, h - width):
            above, below = out[top - 1], out[top + width]
            block = out[top:top + width]
            up = (block - above > t) & (block - below > t)
            dn = (above - block > t) & (below - block > t)
            hit = np.all(up, axis=0) | np.all(dn, axis=0)
            hit &= ~np.any(scars[top:top + width], axis=0)
            hit = _long_runs(hit, min_length)
            if not hit.any():
                continue
            for k in range(width):
                f = (k + 1) / (width + 1)
                out[top + k, hit] = (1 - f) * above[hit] + f * below[hit]
                scars[top + k, hit] = True
    return ScarResult(out, scars)


def _long_runs(flags: np.ndarray, min_len: int) -> np.ndarray:
    """Keep only runs of True at least `min_len` long."""
    if min_len <= 1 or not flags.any():
        return flags
    out = np.zeros_like(flags)
    padded = np.concatenate([[False], flags, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    for start, stop in zip(edges[::2], edges[1::2], strict=True):
        if stop - start >= min_len:
            out[start:stop] = True
    return out


def level_three_point(img: np.ndarray, points: list[tuple[float, float]]) -> np.ndarray:
    """Subtract the plane through three (row, col) points. A point's height
    is its pixel's, or — if that pixel is NaN — the mean of the finite
    pixels around it."""
    d = _as_float(img)
    if len(points) != 3:
        raise ValueError("three-point levelling needs exactly 3 points")
    h, w = d.shape
    rows, cols, zs = [], [], []
    for r, c in points:
        ri, ci = int(round(r)), int(round(c))
        if not (0 <= ri < h and 0 <= ci < w):
            raise ValueError(f"point ({r}, {c}) is outside the image")
        z = d[ri, ci]
        if not np.isfinite(z):
            patch = d[max(ri - 1, 0):ri + 2, max(ci - 1, 0):ci + 2]
            patch = patch[np.isfinite(patch)]
            if patch.size == 0:
                raise ValueError(f"point ({r}, {c}) has no finite height")
            z = patch.mean()
        rows.append(ri)
        cols.append(ci)
        zs.append(float(z))
    a = np.column_stack([np.ones(3), cols, rows]).astype(np.float64)
    if abs(np.linalg.det(a)) < 1e-9:
        raise ValueError("the three points are on one line")
    c0, cx, cy = np.linalg.solve(a, np.array(zs))
    yy, xx = np.mgrid[0:h, 0:w]
    return np.asarray(d - (c0 + cx * xx + cy * yy), dtype=np.float64)


def zero_level(img: np.ndarray, mode: str = "min") -> np.ndarray:
    """Shift heights so the minimum / mean / median (finite pixels) is 0."""
    if mode not in ZERO_MODES:
        raise ValueError(f"zero mode must be one of {ZERO_MODES}")
    d = _as_float(img)
    finite = d[np.isfinite(d)]
    if finite.size == 0:
        raise ValueError("image has no finite pixels")
    if mode == "min":
        ref = float(finite.min())
    elif mode == "mean":
        ref = float(finite.mean())
    else:
        ref = float(np.median(finite))
    return d - ref
