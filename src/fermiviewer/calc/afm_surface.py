"""Areal surface texture of a height map (ISO 25178 names) and the
spectra, correlation and histograms behind it.

Everything works on a levelled height map ``z`` with physical pixel
spacing ``(dy, dx)``. Parameters that mix heights with lateral distances
(slopes, developed area, the 2-D spectrum) need both in ONE length unit:
callers pass ``z_to_lateral`` — the factor that converts a height into the
lateral unit (e.g. 1e3 for heights in µm on an nm grid), or NaN when the
two are not both known lengths, in which case those parameters are NaN
rather than a number in mixed units.

* :func:`areal_parameters` — Sa, Sq, Ssk, Sku, Sp, Sv, Sz (height);
  Sdq, Sdr (hybrid); Sal, Str (spatial, from the ACF); Std (texture
  direction, from the angular spectrum).
* :func:`psd_2d` / :func:`radial_psd` — Hann-windowed 2-D power spectral
  density normalised so it integrates to the height variance (the 2-D
  form of ``trace_roughness.trace_psd``), and its radial average.
* :func:`acf_2d` — normalised autocorrelation with NaN-aware pair counts.
* :func:`height_histogram`, :func:`slope_histogram`.

Angles follow the screen: measured from +x (right), counter-clockwise
as seen on the image (row index grows downward).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

__all__ = [
    "ArealParameters",
    "acf_2d",
    "areal_parameters",
    "height_histogram",
    "psd_2d",
    "radial_psd",
    "slope_histogram",
]

ACF_THRESHOLD = 0.2          # ISO 25178-3 default `s` for Sal / Str


def _finite(z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    d = np.asarray(z, dtype=np.float64)
    if d.ndim != 2:
        raise ValueError("expected a 2-D height map")
    m = np.isfinite(d)
    if int(m.sum()) < 4:
        raise ValueError("too few finite pixels")
    return d, m


def _centred(d: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Mean-removed heights with NaN pixels set to 0 (no contribution)."""
    return np.where(m, d - d[m].mean(), 0.0)


def _gradients(d: np.ndarray, dy: float, dx: float, k: float) -> tuple[np.ndarray, np.ndarray]:
    """dz/dy, dz/dx with z in lateral units (NaN where a neighbour is NaN)."""
    g = np.gradient(d * k, dy, dx)
    return np.asarray(g[0]), np.asarray(g[1])


# ── spectra and correlation ───────────────────────────────────────────


def psd_2d(
    z: np.ndarray, dy: float = 1.0, dx: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Centred 2-D PSD density and its frequency axes ``(psd, fy, fx)``.

    Hann-windowed and window-compensated: ``psd.sum() * dfx * dfy`` is the
    variance of the (finite) heights, the same normalisation
    ``trace_roughness.trace_psd`` uses in 1-D. Units: height² · length².
    """
    d, m = _finite(z)
    n, w = d.shape
    win = np.outer(np.hanning(n), np.hanning(w)) if min(n, w) > 2 else np.ones_like(d)
    win = win * m
    c = _centred(d, m)
    spec = np.fft.fftshift(np.fft.fft2(c * win))
    norm = float((win**2).sum())
    if norm <= 0:
        raise ValueError("too few finite pixels")
    psd = np.abs(spec) ** 2 * dx * dy / norm
    fy = np.fft.fftshift(np.fft.fftfreq(n, d=dy))
    fx = np.fft.fftshift(np.fft.fftfreq(w, d=dx))
    return psd, fy, fx


def radial_psd(
    psd: np.ndarray, fy: np.ndarray, fx: np.ndarray, n_bins: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Azimuthal average of a 2-D PSD → ``(spatial frequency, PSD)``,
    DC dropped. Bins are the coarser of the two frequency steps wide."""
    ff = np.hypot(*np.meshgrid(fy, fx, indexing="ij"))
    step = max(abs(fy[1] - fy[0]) if fy.size > 1 else 0, abs(fx[1] - fx[0]) if fx.size > 1 else 0)
    if step <= 0:
        return np.empty(0), np.empty(0)
    f_max = min(np.abs(fy).max(), np.abs(fx).max())
    nb = n_bins or max(int(f_max / step), 1)
    edges = np.linspace(0.5 * step, f_max, nb + 1)
    idx = np.digitize(ff.ravel(), edges) - 1
    ok = (idx >= 0) & (idx < nb)
    sums = np.bincount(idx[ok], weights=psd.ravel()[ok], minlength=nb)
    counts = np.bincount(idx[ok], minlength=nb)
    keep = counts > 0
    centres = 0.5 * (edges[:-1] + edges[1:])
    return centres[keep], sums[keep] / counts[keep]


def acf_2d(z: np.ndarray) -> np.ndarray:
    """Centred, normalised autocorrelation (1 at zero lag). Each lag is
    averaged over the pixel pairs that are both finite, so NaN pixels and
    the image edge do not bias it toward zero."""
    d, m = _finite(z)
    n, w = d.shape
    c = _centred(d, m)
    shape = (2 * n - 1, 2 * w - 1)
    fc = np.fft.rfft2(c, shape)
    fm = np.fft.rfft2(m.astype(np.float64), shape)
    num = np.fft.irfft2(fc * np.conj(fc), shape)
    cnt = np.fft.irfft2(fm * np.conj(fm), shape)
    cnt = np.rint(cnt)
    with np.errstate(invalid="ignore", divide="ignore"):
        acf = np.where(cnt >= 1, num / np.maximum(cnt, 1), np.nan)
    acf = np.fft.fftshift(acf)
    var = acf[n - 1, w - 1]
    if not np.isfinite(var) or var <= 0:
        return np.zeros(shape)
    return np.asarray(acf / var, dtype=np.float64)


def _decay_lengths(
    acf: np.ndarray, dy: float, dx: float, s: float, n_angles: int = 180,
) -> tuple[np.ndarray, np.ndarray]:
    """Distance from zero lag at which the ACF first drops to `s`, along
    each of `n_angles` directions over 180°. NaN where it never does
    within the lag range. Rays are marched in physical units, so
    non-square pixels are handled."""
    cy, cx = (acf.shape[0] - 1) / 2, (acf.shape[1] - 1) / 2
    theta = np.linspace(0, np.pi, n_angles, endpoint=False)
    r_max = min(cy * dy, cx * dx) * 0.5          # lags beyond ~half have few pairs
    step = min(dy, dx) / 2
    radii = np.arange(step, r_max + step, step)
    rows = cy - np.outer(np.sin(theta), radii) / dy      # screen CCW: up is −row
    cols = cx + np.outer(np.cos(theta), radii) / dx
    vals = ndimage.map_coordinates(np.nan_to_num(acf, nan=0.0), [rows, cols], order=1)
    out = np.full(n_angles, np.nan)
    for i, v in enumerate(vals):
        below = np.flatnonzero(v <= s)
        if below.size:
            j = below[0]
            if j == 0:
                out[i] = radii[0]
            else:                                         # interpolate the crossing
                f = (v[j - 1] - s) / (v[j - 1] - v[j])
                out[i] = radii[j - 1] + f * (radii[j] - radii[j - 1])
    return theta, out


def _texture_direction(psd: np.ndarray, fy: np.ndarray, fx: np.ndarray) -> float:
    """Lay direction in degrees [0, 180): the angular spectrum's peak
    direction is ACROSS the lay, so the lay is 90° from it."""
    ffy, ffx = np.meshgrid(fy, fx, indexing="ij")
    ff = np.hypot(ffy, ffx)
    f_lo = 2 * max(abs(fy[1] - fy[0]), abs(fx[1] - fx[0]))   # drop DC and the window's leak
    ok = ff > f_lo
    if not ok.any():
        return float("nan")
    ang = np.degrees(np.arctan2(-ffy[ok], ffx[ok])) % 180.0      # screen CCW
    w = psd[ok]
    hist = np.bincount(np.rint(ang).astype(int) % 180, weights=w, minlength=180)
    hist = ndimage.uniform_filter1d(hist, 5, mode="wrap")
    if hist.max() <= 0:
        return float("nan")
    # refine the peak bin: power-weighted circular mean of the doubled
    # angles (an axis, not a vector) within ±15° of it
    peak = float(np.argmax(hist))
    near = np.abs((ang - peak + 90.0) % 180.0 - 90.0) <= 15.0
    a2 = np.radians(2 * ang[near])
    mean = 0.5 * np.degrees(np.arctan2((w[near] * np.sin(a2)).sum(), (w[near] * np.cos(a2)).sum()))
    return float(round(mean + 90.0, 6) % 180.0)


# ── histograms ────────────────────────────────────────────────────────


def height_histogram(z: np.ndarray, bins: int = 128) -> tuple[np.ndarray, np.ndarray]:
    """``(bin centres, % of pixels)`` over the finite heights."""
    d, m = _finite(z)
    counts, edges = np.histogram(d[m], bins=bins)
    return 0.5 * (edges[:-1] + edges[1:]), 100.0 * counts / counts.sum()


def slope_histogram(
    z: np.ndarray, dy: float, dx: float, z_to_lateral: float, bins: int = 90,
) -> tuple[np.ndarray, np.ndarray]:
    """``(slope angle in degrees, % of pixels)``; empty when heights and
    lateral distances do not share a length unit."""
    d, _ = _finite(z)
    if not np.isfinite(z_to_lateral):
        return np.empty(0), np.empty(0)
    gy, gx = _gradients(d, dy, dx, z_to_lateral)
    ang = np.degrees(np.arctan(np.hypot(gx, gy)))
    ang = ang[np.isfinite(ang)]
    if ang.size == 0:
        return np.empty(0), np.empty(0)
    counts, edges = np.histogram(ang, bins=bins, range=(0.0, 90.0))
    return 0.5 * (edges[:-1] + edges[1:]), 100.0 * counts / counts.sum()


# ── ISO 25178 parameters ──────────────────────────────────────────────


@dataclass(frozen=True)
class ArealParameters:
    sa: float
    sq: float
    ssk: float
    sku: float
    sp: float
    sv: float
    sz: float
    sdq: float           # rms gradient (dimensionless)
    sdr: float           # developed interfacial area ratio, %
    sal: float           # autocorrelation length (lateral unit)
    str_: float          # texture aspect ratio, 0..1
    std: float           # texture direction, degrees
    n_pixels: int


def areal_parameters(
    z: np.ndarray, dy: float = 1.0, dx: float = 1.0, z_to_lateral: float = float("nan"),
    s: float = ACF_THRESHOLD,
) -> ArealParameters:
    """ISO 25178-2 field parameters of a levelled height map (heights are
    taken about their mean, so levelling is the caller's choice)."""
    d, m = _finite(z)
    zc = d[m] - d[m].mean()
    sq = float(np.sqrt(np.mean(zc**2)))
    sp, sv = float(zc.max()), float(-zc.min())

    nan = float("nan")
    sdq = sdr = nan
    if np.isfinite(z_to_lateral):
        gy, gx = _gradients(d, dy, dx, z_to_lateral)
        g2 = gx**2 + gy**2
        g2 = g2[np.isfinite(g2)]
        if g2.size:
            sdq = float(np.sqrt(g2.mean()))
            sdr = float(100.0 * (np.sqrt(1.0 + g2).mean() - 1.0))

    sal = str_ = nan
    if sq > 0:
        _, lengths = _decay_lengths(acf_2d(d), dy, dx, s)
        found = lengths[np.isfinite(lengths)]
        if found.size:
            sal = float(found.min())
            # a direction that never decays has an unbounded length: Str → 0
            str_ = float(found.min() / found.max()) if found.size == lengths.size else 0.0
    std = nan
    if sq > 0:
        psd, fy, fx = psd_2d(d, dy, dx)
        std = _texture_direction(psd, fy, fx)

    return ArealParameters(
        sa=float(np.mean(np.abs(zc))), sq=sq,
        ssk=float(np.mean(zc**3) / sq**3) if sq > 0 else 0.0,
        sku=float(np.mean(zc**4) / sq**4) if sq > 0 else 0.0,
        sp=sp, sv=sv, sz=sp + sv, sdq=sdq, sdr=sdr, sal=sal, str_=str_, std=std,
        n_pixels=int(m.sum()),
    )
