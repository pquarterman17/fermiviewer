"""Texture & noise analysis — W3 tranche 2 (docs/w3_imaging_audit.md).

structure_tensor ports the MATLAB np.gradient + Gaussian-window +
closed-form-eigenvalue formulation (skimage uses Sobel gradients by
default, which diverge). noise_estimate ports the MAD-Laplacian and
block-variance-mode heuristics with their calibrated constants.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

from fermiviewer.calc.filters import apply_gaussian

__all__ = [
    "NoiseEstimate",
    "StructureTensor",
    "TemplateMatches",
    "noise_estimate",
    "structure_tensor",
    "template_match",
]


@dataclass(frozen=True)
class StructureTensor:
    orientation: np.ndarray
    coherence: np.ndarray
    lambda1: np.ndarray
    lambda2: np.ndarray
    energy: np.ndarray


def structure_tensor(
    img: np.ndarray, sigma: float = 3.0, gradient_sigma: float = 0.0
) -> StructureTensor:
    """Gradient structure tensor with closed-form 2×2 eigendecomposition.

    Gradients use the np.gradient central-difference convention
    (= MATLAB gradient); tensor components are smoothed with the same
    truncated Gaussian as imaging.applyGaussian.
    """
    d = np.asarray(img, dtype=np.float64)
    if gradient_sigma > 0:
        d = apply_gaussian(d, gradient_sigma)

    # np.gradient returns [d/drow, d/dcol] = [Iy, Ix] in MATLAB terms
    grads = np.gradient(d)
    iy: np.ndarray = np.asarray(grads[0])
    ix: np.ndarray = np.asarray(grads[1])

    jxx = apply_gaussian(ix * ix, sigma)
    jxy = apply_gaussian(ix * iy, sigma)
    jyy = apply_gaussian(iy * iy, sigma)

    trace2 = (jxx + jyy) / 2
    diff2 = (jxx - jyy) / 2
    rad = np.sqrt(diff2**2 + jxy**2)
    lambda1 = trace2 + rad
    lambda2 = trace2 - rad

    orientation = 0.5 * np.arctan2(2 * jxy, jxx - jyy)
    energy = lambda1 + lambda2
    eps = np.finfo(np.float64).eps
    coherence = ((lambda1 - lambda2) / (energy + eps)) ** 2

    return StructureTensor(
        orientation=orientation,
        coherence=coherence,
        lambda1=lambda1,
        lambda2=lambda2,
        energy=energy,
    )


@dataclass(frozen=True)
class NoiseEstimate:
    sigma: float
    snr_db: float
    snr_linear: float
    noise_type: str
    method: str


_LAPLACIAN = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)
_BLOCK = 16


def _sigma_mad(d: np.ndarray) -> float:
    """MAD of the Laplacian response. 0.6745 converts MAD→σ for Gaussian
    noise; √20 corrects for the kernel energy (Σ K² = 20)."""
    response = signal.convolve2d(d, _LAPLACIAN, mode="valid")
    return float(np.median(np.abs(response)) / 0.6745 / np.sqrt(20))


def _block_stats(d: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """(σ from block-variance mode, block means, block variances)."""
    h, w = d.shape
    n_row, n_col = h // _BLOCK, w // _BLOCK
    if n_row < 1 or n_col < 1:
        return (
            float(np.std(d, ddof=1)),
            np.array([d.mean()]),
            np.array([np.var(d, ddof=1)]),
        )

    blocks = (
        d[: n_row * _BLOCK, : n_col * _BLOCK]
        .reshape(n_row, _BLOCK, n_col, _BLOCK)
        .transpose(0, 2, 1, 3)
        .reshape(n_row * n_col, _BLOCK * _BLOCK)
    )
    means = blocks.mean(axis=1)
    variances = blocks.var(axis=1, ddof=1)

    # mode of block variances via histogram — flat blocks → noise floor
    n_bins = min(50, variances.size)
    v_min, v_max = variances.min(), variances.max()
    if v_max <= v_min:
        return float(np.sqrt(max(v_min, 0.0))), means, variances
    edges = np.linspace(v_min, v_max, n_bins + 1)
    # histc semantics: [e_i, e_{i+1}) bins; exact-max values dropped
    idx = np.searchsorted(edges, variances, side="right") - 1
    counts = np.bincount(idx[(idx >= 0) & (idx < n_bins)], minlength=n_bins)
    mode_bin = int(np.argmax(counts))
    noise_var = (edges[mode_bin] + edges[mode_bin + 1]) / 2
    return float(np.sqrt(max(noise_var, 0.0))), means, variances


def _classify(means: np.ndarray, variances: np.ndarray) -> str:
    """Poisson vs Gaussian via var-vs-mean regression (ported rules)."""
    if means.size < 4:
        return "unknown"
    valid = means > 0
    if valid.sum() < 4:
        return "unknown"
    x = means[valid]
    y = variances[valid]
    n = x.size
    sx, sy = x.sum(), y.sum()
    sxx, sxy = (x * x).sum(), (x * y).sum()
    denom = n * sxx - sx**2
    if abs(denom) < np.finfo(np.float64).eps:
        return "unknown"
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    y_fit = slope * x + intercept
    ss_tot = ((y - y.mean()) ** 2).sum()
    ss_res = ((y - y_fit) ** 2).sum()
    if ss_tot < np.finfo(np.float64).eps:
        return "gaussian"
    r2 = 1 - ss_res / ss_tot
    if r2 > 0.6 and slope > 0:
        return "poisson"
    if r2 < 0.4:
        return "gaussian"
    if 0.4 <= r2 <= 0.6:
        return "mixed"
    return "unknown"


def noise_estimate(img: np.ndarray, method: str = "mad") -> NoiseEstimate:
    """Noise σ + SNR + Gaussian/Poisson classification — ported verbatim."""
    if method not in ("mad", "localvar", "both"):
        raise ValueError("method must be 'mad', 'localvar' or 'both'")
    d = np.asarray(img, dtype=np.float64)

    sigma_lv, means, variances = _block_stats(d)
    if method == "mad":
        sigma = _sigma_mad(d)
    elif method == "localvar":
        sigma = sigma_lv
    else:
        sigma = (_sigma_mad(d) + sigma_lv) / 2

    if not np.isfinite(sigma) or sigma < 0:
        sigma = 0.0

    signal_level = float(d.mean())
    if sigma > 0 and signal_level > 0:
        snr_linear = signal_level / sigma
        snr_db = 20 * np.log10(snr_linear)
    elif sigma == 0:
        snr_linear = np.inf
        snr_db = np.inf
    else:
        snr_linear = np.nan
        snr_db = np.nan

    return NoiseEstimate(
        sigma=sigma,
        snr_db=float(snr_db),
        snr_linear=float(snr_linear),
        noise_type=_classify(means, variances),
        method=method,
    )


@dataclass(frozen=True)
class TemplateMatches:
    locations: np.ndarray  # (n, 2) 1-based (row, col) match CENTRES
    scores: np.ndarray
    ncc_map: np.ndarray
    n_matches: int
    threshold: float


def _ncc_map(d: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Centre-embedded NCC map (corrected valid-lag FFT correlation)."""
    img_h, img_w = d.shape
    tmpl_h, tmpl_w = t.shape
    eps = np.finfo(np.float64).eps

    tz = t - t.mean()
    tmpl_std = float(np.std(tz, ddof=1))  # N-1 (the upstream quirk)
    if tmpl_std < eps:
        tmpl_std = eps
    n_tmpl = t.size

    padded = np.zeros((img_h, img_w))
    padded[:tmpl_h, :tmpl_w] = tz
    xcorr = np.real(
        np.fft.ifft2(np.fft.fft2(d) * np.conj(np.fft.fft2(padded)))
    )
    # valid (non-wrapped) lags: template top-left at rows 0..H-h
    valid_h = img_h - tmpl_h + 1
    valid_w = img_w - tmpl_w + 1
    xcorr_valid = xcorr[:valid_h, :valid_w]

    # sliding-window stats via integral images (population N variance)
    cum = np.zeros((img_h + 1, img_w + 1))
    cum_sq = np.zeros((img_h + 1, img_w + 1))
    cum[1:, 1:] = d.cumsum(axis=0).cumsum(axis=1)
    cum_sq[1:, 1:] = (d**2).cumsum(axis=0).cumsum(axis=1)

    def box(c: np.ndarray) -> np.ndarray:
        out: np.ndarray = (
            c[tmpl_h : img_h + 1, tmpl_w : img_w + 1]
            - c[:valid_h, tmpl_w : img_w + 1]
            - c[tmpl_h : img_h + 1, :valid_w]
            + c[:valid_h, :valid_w]
        )
        return out

    local_sum = box(cum)
    local_var = np.maximum(
        box(cum_sq) / n_tmpl - (local_sum / n_tmpl) ** 2, 0.0
    )
    denom = np.sqrt(local_var) * (tmpl_std * n_tmpl)
    denom[denom < eps] = eps
    ncc_valid = np.clip(xcorr_valid / denom, -1.0, 1.0)

    # embed so ncc_map[r, c] = NCC with the template CENTRED at (r, c)
    half_r = tmpl_h // 2
    half_c = tmpl_w // 2
    ncc_map = np.zeros((img_h, img_w))
    n_rows = min(valid_h, img_h - half_r)
    n_cols = min(valid_w, img_w - half_c)
    ncc_map[half_r : half_r + n_rows, half_c : half_c + n_cols] = ncc_valid[
        :n_rows, :n_cols
    ]
    return ncc_map


def _grid_nms(
    cand_r: np.ndarray,
    cand_c: np.ndarray,
    min_dist: float,
    max_keep: int,
) -> list[int]:
    """Greedy grid NMS over pre-sorted candidates; returns kept indices."""
    cell = max(1.0, min_dist)
    min_d2 = min_dist**2
    grid: dict[tuple[int, int], list[int]] = {}
    kept_idx: list[int] = []
    kept_r: list[int] = []
    kept_c: list[int] = []
    for i in range(cand_r.size):
        if len(kept_idx) >= max_keep:
            break
        r = int(cand_r[i])
        c = int(cand_c[i])
        gr = int(r // cell)
        gc = int(c // cell)
        too_close = False
        for dgr in (-1, 0, 1):
            for dgc in (-1, 0, 1):
                for j in grid.get((gr + dgr, gc + dgc), ()):
                    if (r - kept_r[j]) ** 2 + (c - kept_c[j]) ** 2 < min_d2:
                        too_close = True
                        break
                if too_close:
                    break
            if too_close:
                break
        if too_close:
            continue
        grid.setdefault((gr, gc), []).append(len(kept_r))
        kept_r.append(r)
        kept_c.append(c)
        kept_idx.append(i)
    return kept_idx


def template_match(
    img: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.7,
    max_matches: int = 100,
    min_distance: float = 0.0,
) -> TemplateMatches:
    """FFT-based normalized cross-correlation matching — ported verbatim
    from the PR-#23-corrected MATLAB (valid lags 0..H-h, top-left pad).

    Preserves the upstream normalization quirk: template std uses N-1
    while the sliding-window std uses N, so perfect matches score
    ~0.99, not 1.0. min_distance 0 resolves to max(template dims).
    """
    d = np.asarray(img, dtype=np.float64)
    t = np.asarray(template, dtype=np.float64)
    if t.shape[0] >= d.shape[0] or t.shape[1] >= d.shape[1]:
        raise ValueError("template must be strictly smaller than image")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be in [0, 1]")
    min_dist = min_distance if min_distance > 0 else max(t.shape)

    ncc_map = _ncc_map(d, t)
    above = ncc_map >= threshold
    if not above.any():
        return TemplateMatches(
            locations=np.zeros((0, 2)),
            scores=np.zeros(0),
            ncc_map=ncc_map,
            n_matches=0,
            threshold=threshold,
        )

    # candidates in MATLAB find() column-major order, stable-sorted desc
    cand_c, cand_r = np.nonzero(above.T)
    cand_scores = ncc_map[cand_r, cand_c]
    order = np.argsort(-cand_scores, kind="stable")
    cand_r, cand_c, cand_scores = (
        cand_r[order],
        cand_c[order],
        cand_scores[order],
    )

    kept = _grid_nms(cand_r, cand_c, min_dist, max_matches)
    locations = np.column_stack(
        [cand_r[kept] + 1, cand_c[kept] + 1]
    ).astype(np.float64)
    return TemplateMatches(
        locations=locations,
        scores=cand_scores[kept],
        ncc_map=ncc_map,
        n_matches=len(kept),
        threshold=threshold,
    )
