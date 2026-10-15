"""Height measurements of features on a height map: a step between two
terraces, and the heights and volumes of segmented particles or grains.

* :func:`step_height` — fits ONE tilted plane shared by both terraces
  plus an offset for the upper one (z = a·x + b·y + c + h·upper), so the
  sample tilt cannot leak into the step the way a difference of two
  terrace means does. Terraces are found by Otsu and refined against the
  fit; pixels near the step edge are left out.
* :func:`region_heights` — per labelled region: maximum and mean height,
  height and volume above the region's local base (the lowest height on
  the ring of pixels just outside it — the substrate it sits on), and
  volume above zero (meaningful after Fix Zero).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from skimage.filters import threshold_otsu

__all__ = [
    "RegionHeights", "StepEvidence", "StepHeight", "region_heights",
    "step_height", "step_height_evidence",
]


@dataclass(frozen=True)
class StepHeight:
    height: float           # upper − lower terrace, z units
    lower_std: float        # residual rms on each terrace
    upper_std: float
    n_lower: int
    n_upper: int
    upper_fraction: float


@dataclass(frozen=True)
class StepEvidence:
    """Fit evidence used to audit a step-height result.

    ``terraces`` is 0 outside the fitted samples, 1 for the lower terrace,
    and 2 for the upper terrace.  The profile follows ``axis`` in increasing
    image-coordinate order, which gives ``signed_height`` an unambiguous
    direction without changing the historical positive ``height`` result.
    """

    result: StepHeight
    signed_height: float
    axis: str
    position: np.ndarray
    measured: np.ndarray
    fitted: np.ndarray
    residual: np.ndarray
    upper_fraction_profile: np.ndarray
    terraces: np.ndarray
    slope_x: float
    slope_y: float
    fit_rms: float


def _shrink(mask: np.ndarray, edge: int) -> np.ndarray:
    """`mask` eroded by `edge` pixels. Edge 0 must mean no erosion: SciPy
    reads iterations=0 as "erode until nothing changes", which empties it."""
    if edge <= 0:
        return mask
    return np.asarray(ndimage.binary_erosion(mask, iterations=edge, border_value=1))


def _fit_step(
    d: np.ndarray, finite: np.ndarray, upper: np.ndarray, edge: int, n_iter: int,
) -> StepEvidence | None:
    """Refine one initial terrace split; None if a terrace vanishes.
    Returns the result and its residual rms (to compare starts)."""
    yy, xx = np.mgrid[0:d.shape[0], 0:d.shape[1]].astype(np.float64)
    cx = cy = c0 = h = 0.0
    used_lo = used_hi = finite
    for _ in range(n_iter):
        used_hi = finite & _shrink(upper, edge)
        used_lo = finite & _shrink(finite & ~upper, edge)
        if used_lo.sum() < 4 or used_hi.sum() < 4:
            return None
        used = used_lo | used_hi
        a = np.column_stack([xx[used], yy[used], np.ones(int(used.sum())),
                             used_hi[used].astype(np.float64)])
        cx, cy, c0, h = np.linalg.lstsq(a, d[used], rcond=None)[0]
        r = d - (cx * xx + cy * yy + c0)
        new_upper = finite & (np.abs(r - h) < np.abs(r))     # nearer the offset level
        if np.array_equal(new_upper, upper):
            break
        upper = new_upper
    base = cx * xx + cy * yy + c0
    lo_res = d[used_lo] - base[used_lo]
    hi_res = d[used_hi] - base[used_hi] - h
    # the offset class is the upper terrace when h > 0, the lower one if not
    hi, lo = (hi_res, lo_res) if h >= 0 else (lo_res, hi_res)
    frac = float(upper.sum() / finite.sum())
    rms = float(np.sqrt((np.concatenate([lo, hi]) ** 2).mean()))
    result = StepHeight(
        height=float(abs(h)), lower_std=float(lo.std()), upper_std=float(hi.std()),
        n_lower=int(lo.size), n_upper=int(hi.size),
        upper_fraction=frac if h >= 0 else 1.0 - frac,
    )
    semantic_upper = upper if h >= 0 else finite & ~upper
    terraces = np.zeros(d.shape, dtype=np.uint8)
    terraces[used_lo if h >= 0 else used_hi] = 1
    terraces[used_hi if h >= 0 else used_lo] = 2
    fitted_surface = base + h * upper
    # Pick the profile direction in which terrace occupancy varies most.
    row_fraction = semantic_upper.mean(axis=1)
    col_fraction = semantic_upper.mean(axis=0)
    axis = "y" if np.ptp(row_fraction) >= np.ptp(col_fraction) else "x"
    reduce_axis = 1 if axis == "y" else 0
    measured = np.nanmedian(np.where(finite, d, np.nan), axis=reduce_axis)
    fitted = np.nanmedian(np.where(finite, fitted_surface, np.nan), axis=reduce_axis)
    residual = np.nanmedian(np.where(finite, d - fitted_surface, np.nan), axis=reduce_axis)
    profile_upper = row_fraction if axis == "y" else col_fraction
    edge_n = max(1, profile_upper.size // 4)
    direction = float(np.nanmean(profile_upper[-edge_n:]) - np.nanmean(profile_upper[:edge_n]))
    signed = result.height if direction >= 0 else -result.height
    return StepEvidence(
        result=result, signed_height=signed, axis=axis,
        position=np.arange(measured.size, dtype=np.float64), measured=measured,
        fitted=fitted, residual=residual, upper_fraction_profile=profile_upper,
        terraces=terraces, slope_x=float(cx), slope_y=float(cy), fit_rms=rms,
    )


def step_height_evidence(
    z: np.ndarray,
    edge: int = 2,
    n_iter: int = 6,
    initial_upper: np.ndarray | None = None,
) -> StepEvidence:
    """Height of the step between the two terraces in `z` (e.g. a
    rectangle drawn across one step edge).

    Two starting splits are refined and the better fit kept: Otsu on the
    raw heights (right when the step dominates the tilt) and Otsu after
    removing the tilt estimated from the MEDIAN pixel-to-pixel slope along
    each axis — robust to the step, which only a few differences cross
    (a least-squares plane would absorb part of the step as tilt)."""
    d = np.asarray(z, dtype=np.float64)
    if d.ndim != 2:
        raise ValueError("expected a 2-D height map")
    finite = np.isfinite(d)
    if int(finite.sum()) < 16:
        raise ValueError("too few finite pixels for a step")
    if np.ptp(d[finite]) == 0:
        raise ValueError("the region is flat: no step to measure")
    yy, xx = np.mgrid[0:d.shape[0], 0:d.shape[1]].astype(np.float64)
    sx, sy = (np.diff(d, axis=ax) for ax in (1, 0))
    slope_x = float(np.median(sx[np.isfinite(sx)])) if np.isfinite(sx).any() else 0.0
    slope_y = float(np.median(sy[np.isfinite(sy)])) if np.isfinite(sy).any() else 0.0
    detrended = d - slope_x * xx - slope_y * yy
    best: StepEvidence | None = None
    starts = (d, detrended) if initial_upper is None else ()
    for start in starts:
        vals = start[finite]
        if np.ptp(vals) == 0:
            continue
        fit = _fit_step(d, finite, finite & (start > threshold_otsu(vals)), edge, n_iter)
        if fit is not None and (best is None or fit.fit_rms < best.fit_rms):
            best = fit
    if initial_upper is not None:
        supplied = np.asarray(initial_upper, dtype=bool)
        if supplied.shape != d.shape:
            raise ValueError("manual terrace split differs from the height-map shape")
        best = _fit_step(d, finite, finite & supplied, edge, n_iter)
    if best is None:
        raise ValueError("one terrace is too small — draw the region across the step")
    return best


def step_height(z: np.ndarray, edge: int = 2, n_iter: int = 6) -> StepHeight:
    """Return the fitted magnitude; see :func:`step_height_evidence` for diagnostics."""
    return step_height_evidence(z, edge=edge, n_iter=n_iter).result


@dataclass(frozen=True)
class RegionHeights:
    max_height: np.ndarray       # per region (index 0 = label 1)
    mean_height: np.ndarray
    base: np.ndarray             # local base level
    height_above_base: np.ndarray
    volume_above_base: np.ndarray    # z·area units; NaN without a pixel area
    volume_above_zero: np.ndarray


def region_heights(
    labels: np.ndarray, z: np.ndarray, pixel_area: float = float("nan"),
) -> RegionHeights:
    """Heights and volumes of each labelled region (labels 1..n; 0 = none)."""
    lab = np.asarray(labels, dtype=np.int64)
    d = np.asarray(z, dtype=np.float64)
    if lab.shape != d.shape:
        raise ValueError("labels and height map differ in shape")
    n = int(lab.max()) if lab.size else 0
    out = {k: np.full(n, np.nan) for k in
           ("max", "mean", "base", "above", "vol_base", "vol_zero")}
    area = float(pixel_area) if np.isfinite(pixel_area) and pixel_area > 0 else float("nan")
    for k, sl in enumerate(ndimage.find_objects(np.maximum(lab, 0)), start=1):
        if sl is None:
            continue
        # grow the box by one pixel so the ring around the region fits
        grown = tuple(slice(max(s.start - 1, 0), s.stop + 1) for s in sl)
        sel = lab[grown] == k
        zz = d[grown]
        inside = sel & np.isfinite(zz)
        if not inside.any():
            continue
        ring = ndimage.binary_dilation(sel) & ~sel & np.isfinite(zz) & (lab[grown] == 0)
        if not ring.any():                           # touching other regions only
            ring = ndimage.binary_dilation(sel) & ~sel & np.isfinite(zz)
        vals = zz[inside]
        base = float(zz[ring].min()) if ring.any() else float(vals.min())
        i = k - 1
        out["max"][i] = vals.max()
        out["mean"][i] = vals.mean()
        out["base"][i] = base
        out["above"][i] = vals.max() - base
        out["vol_base"][i] = np.clip(vals - base, 0, None).sum() * area
        out["vol_zero"][i] = vals.sum() * area
    return RegionHeights(out["max"], out["mean"], out["base"], out["above"],
                         out["vol_base"], out["vol_zero"])
