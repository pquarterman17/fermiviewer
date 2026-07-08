"""Image filters — W3 tranche 1 (docs/w3_imaging_audit.md).

Ports of fermi-viewer +imaging filters. "Map" rows use scipy with the
exact parameter adaptation recorded in the audit; "port" rows mirror
the MATLAB algorithm line for line. Golden-tested against
tests/golden/imaging.json at rel 1e-9.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

__all__ = [
    "PlaneLevelResult",
    "apply_gaussian",
    "apply_median",
    "area_downsample",
    "bin_image",
    "butterworth_filter",
    "clahe",
    "plane_level",
    "thumbnail",
    "unsharp_mask",
]


def _matlab_round(x: np.ndarray | float) -> np.ndarray:
    """MATLAB round(): half away from zero (np.round is banker's)."""
    out: np.ndarray = np.floor(np.asarray(x, dtype=np.float64) + 0.5)
    return out


def apply_gaussian(img: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    """Gaussian blur — maps to scipy with conv2-'same' semantics.

    MATLAB builds a 2-D kernel of half-width ceil(3σ), normalizes to
    unit sum, and convolves with zero padding. The separable scipy
    filter is identical because the outer-product kernel's sum
    factorizes; the explicit radius matches MATLAB's ceil(3σ) (scipy's
    default int(3σ+0.5) truncates differently for σ < 1).
    """
    d = np.asarray(img, dtype=np.float64)
    radius = int(math.ceil(3.0 * sigma))
    out: np.ndarray = ndimage.gaussian_filter(
        d, sigma=sigma, mode="constant", cval=0.0, radius=radius
    )
    return out


def apply_median(img: np.ndarray, window_size: int = 3) -> np.ndarray:
    """Median filter — maps to scipy; replicate padding = mode='nearest'.

    Order statistic on identical windows → bit-exact vs MATLAB.
    """
    if window_size not in (3, 5, 7):
        raise ValueError("window_size must be 3, 5 or 7")
    d = np.asarray(img, dtype=np.float64)
    out: np.ndarray = ndimage.median_filter(d, size=window_size, mode="nearest")
    return out


def unsharp_mask(
    img: np.ndarray, sigma: float = 2.0, amount: float = 1.0
) -> np.ndarray:
    """img + amount·(img − blur). No clipping/rescaling (unlike skimage)."""
    d = np.asarray(img, dtype=np.float64)
    out: np.ndarray = d + amount * (d - apply_gaussian(d, sigma))
    return out


def butterworth_filter(
    img: np.ndarray,
    low_cutoff: float = 0.0,
    high_cutoff: float = 0.5,
    order: int = 2,
) -> np.ndarray:
    """Frequency-domain Butterworth bandpass — ported verbatim.

    Nonstandard normalization (intentional, matches MATLAB): the radial
    frequency grid is divided by its max so the far CORNER = 1, not the
    Nyquist edge. The high-pass DC bin is forced to 1 so the mean
    survives when low_cutoff > 0.
    """
    if not 0 < high_cutoff <= 1:
        raise ValueError("high_cutoff must be in (0, 1]")
    if low_cutoff < 0:
        raise ValueError("low_cutoff must be >= 0")
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    f = np.fft.fft2(d)

    u = np.linspace(-1.0, 1.0, w)
    v = np.linspace(-1.0, 1.0, h)
    uu, vv = np.meshgrid(u, v)
    dist = np.hypot(uu, vv)
    dist /= dist.max()

    n = 2 * order
    h_lp = 1.0 / (1.0 + (dist / high_cutoff) ** n)
    if low_cutoff > 0:
        with np.errstate(divide="ignore"):
            h_hp = 1.0 / (1.0 + (low_cutoff / dist) ** n)
        # Force DC through so the image mean survives. NB: linspace(-1,1,N)
        # only hits exactly 0 for ODD N, so for even-sized images this is a
        # no-op and DC is attenuated — this faithfully mirrors the MATLAB
        # original (same linspace), so do NOT "fix" it without re-pinning
        # the goldens.
        h_hp[dist == 0] = 1.0
    else:
        h_hp = np.ones_like(dist)

    out = np.fft.ifft2(np.fft.ifftshift(h_lp * h_hp) * f)
    return np.real(out)


def clahe(
    img: np.ndarray,
    tile_size: tuple[int, int] = (8, 8),
    clip_limit: float = 0.01,
    num_bins: int = 256,
) -> np.ndarray:
    """Contrast-limited adaptive histogram equalization — ported verbatim.

    Differs from skimage.equalize_adapthist: single uniform clip
    redistribution (excess/nBins added once), rounded-linspace tile
    edges, and tile-CENTER bilinear weights. Output is double in [0, 1].
    """
    n_r, n_c = int(tile_size[0]), int(tile_size[1])
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape

    d_min = d.min()
    d_max = d.max()
    if d_max <= d_min:
        return np.zeros((h, w))

    bin_img = np.floor((d - d_min) / (d_max - d_min) * (num_bins - 1) + 0.5)
    bin_img = np.clip(bin_img, 0, num_bins - 1).astype(np.int64)

    row_edges = _matlab_round(np.linspace(0, h, n_r + 1)).astype(np.int64)
    col_edges = _matlab_round(np.linspace(0, w, n_c + 1)).astype(np.int64)

    luts = np.zeros((num_bins, n_r, n_c))
    for i in range(n_r):
        for j in range(n_c):
            tile = bin_img[row_edges[i] : row_edges[i + 1],
                           col_edges[j] : col_edges[j + 1]]
            n_px = tile.size
            if n_px == 0:
                luts[:, i, j] = np.linspace(0, 1, num_bins)
                continue
            hist = np.bincount(tile.ravel(), minlength=num_bins).astype(
                np.float64
            )
            if clip_limit > 0:
                clip_count = max(1.0, float(_matlab_round(clip_limit * n_px)))
                excess = np.maximum(0.0, hist - clip_count).sum()
                hist = np.minimum(hist, clip_count) + excess / num_bins
            cdf = np.cumsum(hist)
            if cdf[-1] > 0:
                cdf /= cdf[-1]
            luts[:, i, j] = cdf

    # tile centres in 1-based pixel coordinates
    tile_cr = (row_edges[:-1] + row_edges[1:] + 1) / 2.0
    tile_cc = (col_edges[:-1] + col_edges[1:] + 1) / 2.0

    def bracket(
        coords: np.ndarray, centres: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        idx = np.searchsorted(centres, coords, side="right") - 1
        lo = np.clip(idx, 0, len(centres) - 1)
        hi = np.where(
            (idx < 0) | (idx >= len(centres) - 1), lo, np.minimum(idx + 1, len(centres) - 1)
        )
        wgt = np.zeros_like(coords, dtype=np.float64)
        diff = centres[hi] - centres[lo]
        inner = hi != lo
        wgt[inner] = (coords[inner] - centres[lo][inner]) / diff[inner]
        return lo, hi, wgt

    rows = np.arange(1, h + 1, dtype=np.float64)
    cols = np.arange(1, w + 1, dtype=np.float64)
    i_lo, i_hi, w_row = bracket(rows, tile_cr)
    j_lo, j_hi, w_col = bracket(cols, tile_cc)

    # gather the four bracketing LUT values for every pixel (broadcasted)
    b = bin_img
    v00 = luts[b, i_lo[:, None], j_lo[None, :]]
    v01 = luts[b, i_lo[:, None], j_hi[None, :]]
    v10 = luts[b, i_hi[:, None], j_lo[None, :]]
    v11 = luts[b, i_hi[:, None], j_hi[None, :]]
    wr = w_row[:, None]
    wc = w_col[None, :]
    out: np.ndarray = (1 - wr) * ((1 - wc) * v00 + wc * v01) + wr * (
        (1 - wc) * v10 + wc * v11
    )
    return out


def bin_image(
    img: np.ndarray, bin_size: int = 2, mode: str = "average"
) -> np.ndarray:
    """Non-overlapping block binning; trims to a divisible size."""
    if mode not in ("average", "sum"):
        raise ValueError("mode must be 'average' or 'sum'")
    b = int(bin_size)
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    hb, wb = h // b, w // b
    if hb == 0 or wb == 0:
        raise ValueError("bin_size larger than image")
    blocks = d[: hb * b, : wb * b].reshape(hb, b, wb, b)
    out: np.ndarray = (
        blocks.sum(axis=(1, 3)) if mode == "sum" else blocks.mean(axis=(1, 3))
    )
    return out


def area_downsample(img: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Area-style downsample — ported (intentional simple bin assignment).

    Integer ratios use exact block means; the general path assigns each
    input pixel to output bin ceil(idx/ratio) and averages (close to,
    but deliberately not, true area weighting — see audit).
    """
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    th = max(1, int(math.floor(target_h)))
    tw = max(1, int(math.floor(target_w)))
    if th >= h and tw >= w:
        return d.copy()

    row_ratio = h / th
    col_ratio = w / tw
    row_int = row_ratio > 0.999 and abs(row_ratio - round(row_ratio)) < 1e-6
    col_int = col_ratio > 0.999 and abs(col_ratio - round(col_ratio)) < 1e-6

    if row_int and col_int:
        rb, cb = round(row_ratio), round(col_ratio)
        blocks = d[: th * rb, : tw * cb].reshape(th, rb, tw, cb)
        fast: np.ndarray = blocks.mean(axis=(1, 3))
        return fast

    r_idx = np.minimum(th, np.ceil(np.arange(1, h + 1) / row_ratio)).astype(
        np.int64
    ) - 1
    c_idx = np.minimum(tw, np.ceil(np.arange(1, w + 1) / col_ratio)).astype(
        np.int64
    ) - 1
    lin = (r_idx[:, None] * tw + c_idx[None, :]).ravel()
    sums = np.bincount(lin, weights=d.ravel(), minlength=th * tw)
    cnts = np.bincount(lin, minlength=th * tw)
    cnts[cnts == 0] = 1
    out: np.ndarray = (sums / cnts).reshape(th, tw)
    return out


def thumbnail(img: np.ndarray, max_size: int = 256) -> np.ndarray:
    """Bilinear thumbnail on an align-corners grid — ported.

    Samples linspace(1, H, newH) × linspace(1, W, newW) (endpoints
    inclusive), which differs from skimage.resize's pixel-area grid.
    Returns float64 (the MATLAB cast-back is display-side concern).
    """
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    if max(h, w) <= max_size or h < 2 or w < 2:
        return d.copy()
    scale = max_size / max(h, w)
    new_h = max(1, int(_matlab_round(h * scale)))
    new_w = max(1, int(_matlab_round(w * scale)))
    # 0-based query coordinates for map_coordinates
    row_q = np.linspace(0.0, h - 1.0, new_h)
    col_q = np.linspace(0.0, w - 1.0, new_w)
    rr, cc = np.meshgrid(row_q, col_q, indexing="ij")
    out: np.ndarray = ndimage.map_coordinates(
        d, [rr, cc], order=1, mode="nearest"
    )
    return out


@dataclass(frozen=True)
class PlaneLevelResult:
    coeffs: np.ndarray
    leveled: np.ndarray
    surface: np.ndarray
    order: int


def _poly_design(
    x: np.ndarray, y: np.ndarray, order: int
) -> np.ndarray:
    one = np.ones_like(x)
    if order == 1:
        cols = [one, x, y]
    elif order == 2:
        cols = [one, x, y, x**2, x * y, y**2]
    elif order == 3:
        cols = [one, x, y, x**2, x * y, y**2, x**3, x**2 * y, x * y**2, y**3]
    else:
        raise ValueError("order must be 1, 2 or 3")
    return np.column_stack(cols)


def plane_level(
    img: np.ndarray, order: int = 1, mask: np.ndarray | None = None
) -> PlaneLevelResult:
    """Polynomial background removal — ported (1-based x/y coordinates).

    NaN policy (deliberate extension beyond the MATLAB reference, same
    convention as the 2026-06 grain-finding hardening / calc.trace_roughness):
    a non-finite pixel inside the active mask would otherwise poison ``lstsq``
    and NaN the coefficients — and hence the WHOLE reconstructed surface, not
    just that pixel — silently. Callers that already exclude non-finite
    pixels from ``mask`` (e.g. calc.roughness.surface_roughness) are
    unaffected; this is a backstop for direct callers.
    """
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    yy, xx = np.mgrid[1 : h + 1, 1 : w + 1].astype(np.float64)
    if mask is None:
        m = np.ones((h, w), dtype=bool)
    else:
        m = np.asarray(mask, dtype=bool)
        if m.shape != (h, w):
            raise ValueError("mask must match image shape")
        if not m.any():
            raise ValueError("mask contains no true pixels")
    if not np.all(np.isfinite(d[m])):
        raise ValueError("plane_level: masked region contains non-finite values")
    a = _poly_design(xx[m], yy[m], order)
    coeffs, *_ = np.linalg.lstsq(a, d[m], rcond=None)
    surface = (_poly_design(xx.ravel(), yy.ravel(), order) @ coeffs).reshape(
        h, w
    )
    return PlaneLevelResult(
        coeffs=coeffs, leveled=d - surface, surface=surface, order=order
    )
