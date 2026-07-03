"""Interface-trace roughness metrology (CROSS_SECTION_LAYERS items 8-12).

Rigorous statistics for a per-column interface trace ``h(x)`` (from
``calc.layers.trace_interface``), replacing the raw ``np.std(trace)``.
Distinct from :mod:`fermiviewer.calc.roughness` (2-D ISO surface parameters
on height images, ported verbatim) — this module is net-new 1-D metrology:

1. **Form removal** — a polynomial detrend separates form (tilt, substrate
   bow) from roughness. Without it a 0.5 deg residual tilt over a 1024 px
   field injects +-4.5 px of linear trend that masquerades as roughness.
2. **Robust sigma + outliers** — MAD-based sigma with iterative rejection, so
   hot pixels / contamination / curtain residue columns cannot inflate the
   result. The kept fraction is reported as a quality flag.
3. **Noise-floor subtraction** — shot-noise edge-localisation jitter is
   uncorrelated between adjacent columns while real roughness is laterally
   correlated, so the lag-1 structure function estimates the jitter power,
   which is subtracted in quadrature: sigma_w^2 = sigma_robust^2 - sigma_loc^2.
4. **Spectrum** — Hann-windowed PSD of the detrended trace plus a self-affine
   height-height correlation fit ``g(r) = 2 sigma^2 (1 - exp(-(r/xi)^{2H}))``
   (Sinha et al., Phys. Rev. B 38, 2297 (1988)) giving the correlation
   length xi and Hurst exponent H — the same language as XRR/AFM roughness.
5. **Conformality** — Pearson correlation between adjacent detrended traces:
   r ~ 1 means the upper interface replicates the lower one (conformal
   growth); r ~ 0 means independent roughness.
6. **Uncertainty** — a circular *block* bootstrap over columns (blocks ~ the
   correlation length, since laterally correlated samples make the naive
   bootstrap under-cover) gives a 95% CI on sigma_w.

All lengths are in *pixels* unless a ``pixel_size`` converts them. A TEM
cross-section projects through the foil, so sigma_w is a **lower bound** —
roughness at lateral wavelengths shorter than the foil thickness is averaged
away along the beam. Pure library: numpy/scipy only, no fastapi imports.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import curve_fit

__all__ = [
    "TraceRoughness",
    "analyze_trace",
    "clean_trace",
    "conformality",
    "hhcf",
    "hhcf_fit",
    "robust_sigma",
    "robust_sigma_w",
    "sigma_chem",
    "trace_interface",
    "trace_psd",
]

_MAD_TO_SIGMA = 1.4826  # normal-consistency factor for the MAD


def _parabolic_edge(line: np.ndarray, approx: int, window: int) -> float:
    """Sub-pixel gradient-peak edge in a 1-D profile near ``approx``.

    The cheap per-column estimator (vs the expensive erf fit): the
    |gradient| maximum within ``±window`` of ``approx``, refined by a
    3-point parabolic fit. Fast enough to run on every lateral column.
    """
    n = line.size
    lo = max(1, approx - window)
    hi = min(n - 1, approx + window + 1)
    if hi - lo < 1:
        return float(approx)
    g = np.abs(np.gradient(line))
    k = int(np.argmax(g[lo:hi])) + lo
    if k <= 0 or k >= n - 1:
        return float(k)
    y0, y1, y2 = g[k - 1], g[k], g[k + 1]
    denom = y0 - 2.0 * y1 + y2
    frac = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
    return float(k + np.clip(frac, -0.5, 0.5))


def trace_interface(
    img: np.ndarray,
    axis: str,
    interface_pos: float,
    window: int = 10,
    smooth: float = 1.0,
) -> np.ndarray:
    """Trace an interface column-by-column → its depth at each lateral pos.

    For ``axis="y"`` (horizontal layers) each column is a depth profile and
    the interface is traced across columns; ``axis="x"`` traces across rows.
    Feed the result to :func:`analyze_trace` / :func:`robust_sigma_w` for the
    roughness statistics. A light Gaussian pre-smooth suppresses per-column
    noise. Keep ``window`` at most half the gap to the nearest neighbouring
    interface, or the trace locks onto the stronger adjacent edge.
    """
    from scipy.ndimage import gaussian_filter1d

    arr = np.asarray(img, dtype=np.float64)
    lines = arr.T if axis == "y" else arr   # rows of `lines` are depth profiles
    approx = int(round(interface_pos))
    out = np.empty(lines.shape[0], dtype=np.float64)
    for j in range(lines.shape[0]):
        line = lines[j]
        if smooth > 0:
            line = gaussian_filter1d(line, smooth)
        out[j] = _parabolic_edge(line, approx, window)
    return out


@dataclass(frozen=True)
class TraceRoughness:
    """Full roughness report for one interface trace (lengths calibrated)."""

    sigma_w: float                    # detrended, robust, noise-corrected rms
    sigma_ci: tuple[float, float]     # 95% block-bootstrap CI on sigma_w
    sigma_raw: float                  # robust rms before noise subtraction
    noise_floor: float                # edge-localisation jitter estimate
    quality: float                    # fraction of columns kept (0..1)
    xi: float                         # HHCF correlation length (NaN if unfit)
    hurst: float                      # HHCF Hurst exponent (NaN if unfit)
    psd_wavelength: np.ndarray        # lateral wavelength per PSD bin
    psd_power: np.ndarray             # power spectral density
    detrended: np.ndarray             # cleaned trace residual (NaN = rejected)


def robust_sigma(x: np.ndarray) -> float:
    """MAD-based sigma estimate — immune to a few wild columns."""
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    if x.size < 2:
        return float("nan")
    med = float(np.median(x))
    return float(np.median(np.abs(x - med))) * _MAD_TO_SIGMA


def clean_trace(
    trace: np.ndarray, order: int = 2, kappa: float = 4.0, n_iter: int = 3
) -> tuple[np.ndarray, np.ndarray]:
    """Detrend + iteratively reject outlier columns.

    Fits a degree-``order`` polynomial (form: tilt + bow) to the finite
    columns, rejects residuals beyond ``kappa`` robust sigmas, and refits so a
    gross outlier cannot steer the trend it is judged against. Returns
    ``(residual, keep_mask)`` where rejected/invalid columns are NaN.
    """
    y = np.asarray(trace, dtype=np.float64)
    x = np.arange(y.size, dtype=np.float64)
    min_pts = max(order + 2, 4)
    keep = np.isfinite(y)
    if keep.sum() < min_pts:
        return np.full(y.size, np.nan), np.zeros(y.size, dtype=bool)
    for _ in range(n_iter):
        coeffs = np.polyfit(x[keep], y[keep], order)
        resid = y - np.polyval(coeffs, x)
        s = robust_sigma(resid[keep])
        if not np.isfinite(s) or s <= 0:
            break
        new_keep = np.isfinite(y) & (np.abs(resid) <= kappa * s)
        if new_keep.sum() < min_pts or bool(np.all(new_keep == keep)):
            keep = new_keep if new_keep.sum() >= min_pts else keep
            break
        keep = new_keep
    coeffs = np.polyfit(x[keep], y[keep], order)
    resid = y - np.polyval(coeffs, x)
    resid[~keep] = np.nan
    return resid, keep


def _noise_floor(resid: np.ndarray) -> float:
    """Edge-localisation jitter from the lag-1 structure function.

    Adjacent-column differences of *uncorrelated* jitter have variance
    ``2 sigma_loc^2``; laterally correlated roughness contributes little at
    lag 1 (the probe/PSF already smooths ~px scales). The median of squared
    differences (normal-consistency: median(chi^2_1) = 0.4549) keeps single
    bad columns from dominating.
    """
    v = resid[np.isfinite(resid)]
    if v.size < 3:
        return float("nan")
    d = np.diff(v)
    med_sq = float(np.median(d * d))
    return float(np.sqrt(max(med_sq / 0.4549, 0.0) / 2.0))


def _noise_corrected(resid: np.ndarray) -> tuple[float, float, float]:
    """(sigma_w, sigma_raw, noise_floor) in pixels from a cleaned residual."""
    s_raw = robust_sigma(resid)
    s_loc = _noise_floor(resid)
    if not np.isfinite(s_raw):
        return float("nan"), s_raw, s_loc
    if not np.isfinite(s_loc):
        return s_raw, s_raw, s_loc
    return float(np.sqrt(max(s_raw**2 - s_loc**2, 0.0))), s_raw, s_loc


def robust_sigma_w(trace: np.ndarray) -> float:
    """The headline sigma_w (pixels): detrended, robust, noise-corrected.

    The cheap entry point used by ``calc.layers`` for the table number;
    :func:`analyze_trace` adds spectrum/CI/quality on top.
    """
    resid, _ = clean_trace(trace)
    return _noise_corrected(resid)[0]


def trace_psd(
    resid: np.ndarray, pixel_size: float = 1.0
) -> tuple[np.ndarray, np.ndarray]:
    """Hann-windowed one-sided PSD of a detrended trace.

    NaN gaps (rejected columns) are linearly interpolated — acceptable for
    the small rejected fractions a quality flag would pass. Returns
    ``(wavelength, power)`` with the DC bin dropped; wavelength is in
    calibrated units, longest first.
    """
    y = np.asarray(resid, dtype=np.float64).copy()
    n = y.size
    good = np.isfinite(y)
    if good.sum() < 8:
        return np.empty(0), np.empty(0)
    idx = np.arange(n, dtype=np.float64)
    y[~good] = np.interp(idx[~good], idx[good], y[good])
    y -= y.mean()
    w = np.hanning(n)
    spec = np.fft.rfft(y * w)
    # one-sided Parseval: sum(power) ~ variance of the windowed trace
    power = (np.abs(spec) ** 2) * 2.0 / (n * np.sum(w**2) + np.finfo(np.float64).eps)
    if n % 2 == 0:
        power[-1] /= 2.0  # Nyquist bin is not doubled
    freq = np.fft.rfftfreq(n, d=pixel_size)
    return (1.0 / freq[1:]), power[1:]


def hhcf(resid: np.ndarray, max_lag: int) -> tuple[np.ndarray, np.ndarray]:
    """Height-height correlation g(r) = <(h(x+r) - h(x))^2> over valid pairs."""
    y = np.asarray(resid, dtype=np.float64)
    lags = np.arange(1, max_lag + 1)
    g = np.full(lags.size, np.nan)
    for i, r in enumerate(lags):
        d = y[r:] - y[:-r]
        d = d[np.isfinite(d)]
        if d.size >= 8:
            g[i] = float(np.mean(d * d))
    return lags.astype(np.float64), g


def _saff(
    r: np.ndarray, sigma: float, xi: float, hurst: float, nugget: float
) -> np.ndarray:
    return 2.0 * nugget**2 + 2.0 * sigma**2 * (
        1.0 - np.exp(-((r / xi) ** (2.0 * hurst)))
    )


def hhcf_fit(resid: np.ndarray, pixel_size: float = 1.0) -> tuple[float, float]:
    """Fit the self-affine model to the HHCF → (xi, hurst).

    ``g(r) = 2 s_n^2 + 2 sigma^2 (1 - exp(-(r/xi)^{2H}))`` — the standard
    growth-front scaling form (Sinha et al. 1988) plus a *nugget* ``s_n``:
    uncorrelated edge-localisation jitter lifts g(r) by a constant for all
    r >= 1, and without the term the fit warps H down / xi up to absorb the
    lag-1 jump. Fit over lags up to a quarter of the trace (longer lags have
    too few independent pairs). Returns calibrated ``xi``; ``(nan, nan)``
    when the trace cannot constrain the fit.
    """
    y = np.asarray(resid, dtype=np.float64)
    n_valid = int(np.isfinite(y).sum())
    max_lag = min(y.size // 4, 256)
    if n_valid < 32 or max_lag < 8:
        return float("nan"), float("nan")
    lags, g = hhcf(y, max_lag)
    ok = np.isfinite(g)
    if ok.sum() < 8:
        return float("nan"), float("nan")
    s0 = robust_sigma(y)
    if not np.isfinite(s0) or s0 <= 0:
        return float("nan"), float("nan")
    # xi seed = first crossing of the 1-1/e saturation level; then fit only
    # out to ~4 xi — beyond that g(r) is flat and an unweighted fit over a
    # long saturated tail out-votes the rise that actually encodes xi and H
    sat = 2.0 * s0**2
    crossed = lags[ok][g[ok] >= (1.0 - 1.0 / np.e) * sat]
    xi0 = float(crossed[0]) if crossed.size else float(lags[ok][-1]) / 2.0
    sel = ok & (lags <= max(4.0 * xi0, 16.0))
    if sel.sum() < 6:
        sel = ok
    n0 = _noise_floor(y)
    try:
        popt, _ = curve_fit(
            _saff,
            lags[sel],
            g[sel],
            p0=[s0, max(xi0, 1.0), 0.8, n0 if np.isfinite(n0) else 0.1],
            bounds=([1e-6, 0.5, 0.05, 0.0], [np.inf, float(y.size), 1.0, np.inf]),
            maxfev=2000,
        )
    except (RuntimeError, ValueError):
        return float("nan"), float("nan")
    return float(popt[1]) * pixel_size, float(popt[2])


def _block_bootstrap_ci(
    resid: np.ndarray, n_boot: int = 200, seed: int = 0
) -> tuple[float, float]:
    """95% CI on the noise-corrected sigma via a circular block bootstrap.

    Lateral correlation makes naive per-column resampling under-cover, so
    contiguous blocks (~n/8 columns) are resampled with wraparound.
    """
    v = resid[np.isfinite(resid)]
    n = v.size
    if n < 16:
        return float("nan"), float("nan")
    block = max(4, n // 8)
    n_blocks = int(np.ceil(n / block))
    rng = np.random.default_rng(seed)
    stats = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        take = (starts[:, None] + np.arange(block)[None, :]) % n
        stats[b] = _noise_corrected(v[take.ravel()[:n]])[0]
    stats = stats[np.isfinite(stats)]
    if stats.size < n_boot // 2:
        return float("nan"), float("nan")
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return float(lo), float(hi)


def conformality(resid_a: np.ndarray, resid_b: np.ndarray) -> float:
    """Pearson r between two detrended traces on their common valid columns.

    r ~ 1 → the upper interface replicates the lower (conformal growth);
    r ~ 0 → independent roughness. NaN when the overlap is too short.
    """
    a = np.asarray(resid_a, dtype=np.float64)
    b = np.asarray(resid_b, dtype=np.float64)
    if a.size != b.size:
        return float("nan")
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 16:
        return float("nan")
    av, bv = a[ok] - a[ok].mean(), b[ok] - b[ok].mean()
    denom = float(np.sqrt(np.sum(av**2) * np.sum(bv**2)))
    if denom <= 0:
        return float("nan")
    return float(np.sum(av * bv) / denom)


def sigma_chem(sigma_erf: float, sigma_w: float) -> float:
    """Intrinsic (chemical) diffuseness by quadrature decomposition.

    The erf width fit to the laterally *averaged* profile convolves the true
    compositional grading with the geometric waviness the averaging smears:
    ``sigma_erf^2 ~ sigma_chem^2 + sigma_w^2``. Subtracting in quadrature
    recovers the intrinsic width. NaN when inputs are missing or
    ``sigma_w >= sigma_erf`` (roughness-limited: nothing resolvable left).
    Both inputs are projection-limited — treat as an upper bound on grading.
    """
    if not (np.isfinite(sigma_erf) and np.isfinite(sigma_w)):
        return float("nan")
    if sigma_w >= sigma_erf:
        return float("nan")
    return float(np.sqrt(sigma_erf**2 - sigma_w**2))


def analyze_trace(
    trace: np.ndarray,
    pixel_size: float = 1.0,
    *,
    order: int = 2,
    kappa: float = 4.0,
    n_boot: int = 200,
) -> TraceRoughness:
    """Full roughness report for one interface trace (see module docstring)."""
    y = np.asarray(trace, dtype=np.float64)
    resid, keep = clean_trace(y, order=order, kappa=kappa)
    s_w, s_raw, s_loc = _noise_corrected(resid)
    lo, hi = _block_bootstrap_ci(resid, n_boot=n_boot)
    wavelength, power = trace_psd(resid, pixel_size)
    xi, hurst = hhcf_fit(resid, pixel_size)
    n_finite = int(np.isfinite(y).sum())
    quality = float(keep.sum() / n_finite) if n_finite else 0.0
    px = float(pixel_size)
    return TraceRoughness(
        sigma_w=s_w * px,
        sigma_ci=(lo * px, hi * px),
        sigma_raw=s_raw * px,
        noise_floor=s_loc * px if np.isfinite(s_loc) else float("nan"),
        quality=quality,
        xi=xi,
        hurst=hurst,
        psd_wavelength=wavelength,
        psd_power=power * px**2,
        detrended=resid,
    )
