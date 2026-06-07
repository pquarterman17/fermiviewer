"""Atom-column analysis — W4 item 15 (ported verbatim).

detect → sub-pixel Gaussian fit (hand-rolled ridge-regularised LM, kept
verbatim so convergence paths — and goldens — match MATLAB) → lattice
basis from nearest-neighbour direction histograms → per-column strain
from displacement-gradient plane fits. Positions are (x, y) = (col,
row), 1-based, throughout (the MATLAB convention).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

from fermiviewer.calc.ml import kmeans_lite, standardize_features

__all__ = [
    "ColumnDetection",
    "ColumnFit",
    "LatticeVectors",
    "PairStrain",
    "assign_sublattice",
    "detect_columns",
    "find_lattice_vectors",
    "fit_gaussian_2d",
    "peak_pair_strain",
]


# ── detection ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ColumnDetection:
    positions: np.ndarray  # (n, 2) (x, y), 1-based
    intensities: np.ndarray
    polarity: str


def detect_columns(
    img: np.ndarray,
    sigma: float = 2.0,
    threshold: float = 0.2,
    min_separation: float = 8.0,
    polarity: str = "bright",
    max_columns: int = 20000,
) -> ColumnDetection:
    """Local-maxima column detection with replicate-pad smoothing.

    Replicate padding (not zero-pad) avoids artificial bright rims on
    dark-polarity images — a documented MATLAB-side choice.
    """
    if polarity not in ("bright", "dark"):
        raise ValueError("polarity must be 'bright' or 'dark'")
    work = np.asarray(img, dtype=np.float64)
    if polarity == "dark":
        work = -work

    hw = int(np.ceil(3 * sigma))
    ax = np.arange(-hw, hw + 1, dtype=np.float64)
    xx, yy = np.meshgrid(ax, ax)
    kernel = np.exp(-0.5 * (xx**2 + yy**2) / sigma**2)
    kernel /= kernel.sum()
    padded = np.pad(work, hw, mode="edge")
    smoothed = signal.convolve2d(padded, kernel, mode="valid")

    # 8-connected local maxima (>= every neighbour)
    p = np.full(
        (smoothed.shape[0] + 2, smoothed.shape[1] + 2), -np.inf
    )
    p[1:-1, 1:-1] = smoothed
    is_max = np.ones(smoothed.shape, dtype=bool)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            is_max &= (
                smoothed
                >= p[1 + dr : p.shape[0] - 1 + dr,
                     1 + dc : p.shape[1] - 1 + dc]
            )

    lo, hi = smoothed.min(), smoothed.max()
    if hi <= lo:
        return ColumnDetection(np.zeros((0, 2)), np.zeros(0), polarity)
    is_max &= smoothed >= lo + threshold * (hi - lo)

    # candidates in MATLAB find() column-major order
    cols, rows = np.nonzero(is_max.T)
    if rows.size == 0:
        return ColumnDetection(np.zeros((0, 2)), np.zeros(0), polarity)
    intens = smoothed[rows, cols]
    order = np.argsort(-intens, kind="stable")
    rows, cols, intens = rows[order], cols[order], intens[order]

    min_sep2 = min_separation**2
    acc_r: list[int] = []
    acc_c: list[int] = []
    keep: list[int] = []
    for i in range(rows.size):
        if acc_r:
            ar = np.asarray(acc_r)
            ac = np.asarray(acc_c)
            if ((ar - rows[i]) ** 2 + (ac - cols[i]) ** 2 < min_sep2).any():
                continue
        acc_r.append(int(rows[i]))
        acc_c.append(int(cols[i]))
        keep.append(i)
        if len(acc_r) >= max_columns:
            break

    return ColumnDetection(
        positions=np.column_stack(
            [cols[keep] + 1, rows[keep] + 1]
        ).astype(np.float64),
        intensities=intens[keep],
        polarity=polarity,
    )


# ── sub-pixel Gaussian fitting (verbatim LM) ──────────────────────────


@dataclass(frozen=True)
class ColumnFit:
    positions: np.ndarray  # (n, 2) (x, y)
    amplitude: np.ndarray
    sigma: np.ndarray  # (n, 2)
    theta: np.ndarray
    background: np.ndarray
    rsquared: np.ndarray
    converged: np.ndarray


def _gauss_model(
    p: np.ndarray, x: np.ndarray, y: np.ndarray
) -> np.ndarray | None:
    a, x0, y0, sx, sy, th, bg = p
    if not (sx > 0 and sy > 0 and np.isfinite(a) and np.isfinite(x0)
            and np.isfinite(y0)):
        return None
    ct, st = np.cos(th), np.sin(th)
    dx = x - x0
    dy = y - y0
    xr = ct * dx + st * dy
    yr = -st * dx + ct * dy
    out: np.ndarray = bg + a * np.exp(
        -0.5 * (xr**2 / sx**2 + yr**2 / sy**2)
    )
    return out


def _num_jacobian(
    p: np.ndarray, x: np.ndarray, y: np.ndarray
) -> np.ndarray | None:
    f0 = _gauss_model(p, x, y)
    if f0 is None:
        return None
    j = np.zeros((x.size, p.size))
    step = np.maximum(np.abs(p) * 1e-4, 1e-6)
    for col in range(p.size):
        pp = p.copy()
        pp[col] += step[col]
        fj = _gauss_model(pp, x, y)
        if fj is None:
            return None
        j[:, col] = (fj - f0) / step[col]
    return j


def _clamp_params(p: np.ndarray) -> np.ndarray:
    p = p.copy()
    p[3] = max(abs(p[3]), 0.3)
    p[4] = max(abs(p[4]), 0.3)
    if not np.isfinite(p[5]):
        p[5] = 0.0
    return p


def _lm_fit(
    p: np.ndarray, xv: np.ndarray, yv: np.ndarray, zv: np.ndarray,
    max_iter: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Ridge-regularised Levenberg-Marquardt — ported step for step."""
    lam = 1e-2
    f = _gauss_model(p, xv, yv)
    assert f is not None
    err = zv - f
    cost = float(err @ err)
    for _ in range(max_iter):
        j = _num_jacobian(p, xv, yv)
        if j is None:
            break
        jtj = j.T @ j
        jte = j.T @ err
        ridge = 1e-9 * max(float(np.diag(jtj).max()), 1.0)
        step_taken = False
        small_step = False
        for _tries in range(6):
            h = jtj + lam * np.diag(np.diag(jtj)) + ridge * np.eye(p.size)
            dp = np.linalg.solve(h, jte)
            p_new = _clamp_params(p + dp)
            f_new = _gauss_model(p_new, xv, yv)
            if f_new is not None:
                err_new = zv - f_new
                cost_new = float(err_new @ err_new)
                if cost_new < cost:
                    small_step = (cost - cost_new) < 1e-6 * cost
                    p, err, cost = p_new, err_new, cost_new
                    lam = max(lam / 3, 1e-9)
                    step_taken = True
                    break
            lam = min(lam * 4, 1e9)
        if not step_taken or small_step:
            break
    return p, err


def fit_gaussian_2d(
    img: np.ndarray,
    seeds: np.ndarray,
    win_radius: int = 6,
    polarity: str = "bright",
    max_iter: int = 40,
) -> ColumnFit:
    """Refine seed positions with per-column 7-parameter Gaussian fits."""
    work = np.asarray(img, dtype=np.float64)
    if polarity == "dark":
        work = -work
    h, w = work.shape
    s = np.asarray(seeds, dtype=np.float64)
    n = s.shape[0]
    r = int(win_radius)

    positions = s.copy()
    amplitude = np.zeros(n)
    sigma = np.zeros((n, 2))
    theta = np.zeros(n)
    background = np.zeros(n)
    rsquared = np.zeros(n)
    converged = np.zeros(n, dtype=bool)

    for k in range(n):
        sx0, sy0 = s[k]
        c0 = int(np.floor(sx0 + 0.5))
        r0 = int(np.floor(sy0 + 0.5))
        c_lo, c_hi = max(1, c0 - r), min(w, c0 + r)
        r_lo, r_hi = max(1, r0 - r), min(h, r0 + r)
        if (c_hi - c_lo) < 2 or (r_hi - r_lo) < 2:
            continue

        xx, yy = np.meshgrid(
            np.arange(c_lo, c_hi + 1, dtype=np.float64),
            np.arange(r_lo, r_hi + 1, dtype=np.float64),
        )
        z = work[r_lo - 1 : r_hi, c_lo - 1 : c_hi]
        xv, yv, zv = xx.ravel(), yy.ravel(), z.ravel()

        bg0 = zv.min()
        amp0 = zv.max() - bg0
        if amp0 <= 0:
            continue
        p0 = np.array(
            [amp0, sx0, sy0, max(1.0, r / 3), max(1.0, r / 3), 0.0, bg0]
        )
        p, err = _lm_fit(p0, xv, yv, zv, max_iter)

        in_win = (
            c_lo - 0.5 <= p[1] <= c_hi + 0.5
            and r_lo - 0.5 <= p[2] <= r_hi + 0.5
        )
        ss_tot = float(((zv - zv.mean()) ** 2).sum())
        r2 = 1.0 if ss_tot <= 0 else 1 - float(err @ err) / ss_tot

        if in_win and np.isfinite(p[1]) and np.isfinite(p[2]):
            positions[k] = (p[1], p[2])
            converged[k] = True
        amplitude[k] = p[0]
        sigma[k] = (abs(p[3]), abs(p[4]))
        theta[k] = p[5]
        background[k] = p[6]
        rsquared[k] = r2

    return ColumnFit(
        positions=positions,
        amplitude=amplitude,
        sigma=sigma,
        theta=theta,
        background=background,
        rsquared=rsquared,
        converged=converged,
    )


# ── lattice basis ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class LatticeVectors:
    a1: np.ndarray
    a2: np.ndarray
    origin: np.ndarray
    spacing: float
    valid: bool


def _ang_diff(a: np.ndarray, b: float) -> np.ndarray:
    """Smallest signed angle difference mod π (directions fold 180°)."""
    out: np.ndarray = np.mod(a - b + np.pi / 2, np.pi) - np.pi / 2
    return out


def find_lattice_vectors(
    positions: np.ndarray,
    neighbors: int = 6,
    min_angle_deg: float = 15.0,
    max_sample: int = 400,
) -> LatticeVectors:
    """Lattice basis from nearest-neighbour direction histograms."""
    pos = np.asarray(positions, dtype=np.float64)
    n = pos.shape[0]
    invalid = LatticeVectors(
        np.full(2, np.nan), np.full(2, np.nan), np.full(2, np.nan),
        np.nan, False,
    )
    if n < 4:
        return invalid

    ctr = pos.mean(axis=0)
    origin = pos[int(np.argmin(((pos - ctr) ** 2).sum(axis=1)))]

    m = min(n, max_sample)
    q = pos[:m]
    d2 = np.maximum(
        (q**2).sum(1)[:, None] - 2 * q @ pos.T + (pos**2).sum(1)[None, :],
        0,
    )
    vecs = []
    nn_dist = np.zeros(m)
    for i in range(m):
        order = np.argsort(d2[i], kind="stable")[1:]  # drop self
        kk = min(neighbors, order.size)
        if kk < 1:
            continue
        nn_dist[i] = np.sqrt(d2[i, order[0]])
        vecs.extend(pos[order[:kk]] - q[i])
    v = np.asarray(vecs)
    if v.shape[0] < 3:
        return invalid

    spacing = float(np.median(nn_dist[nn_dist > 0]))
    length = np.hypot(v[:, 0], v[:, 1])
    v = v[(length > 0.3 * spacing) & (length < 1.8 * spacing)]
    if v.shape[0] < 3:
        return invalid
    flip = (v[:, 0] < 0) | ((np.abs(v[:, 0]) < 1e-9) & (v[:, 1] < 0))
    v[flip] = -v[flip]
    ang = np.arctan2(v[:, 1], v[:, 0])

    edges = np.linspace(-np.pi / 2, np.pi / 2, 37)
    hist, _ = np.histogram(ang, bins=edges)
    b1 = int(np.argmax(hist))
    c1 = (edges[b1] + edges[b1 + 1]) / 2
    tol = np.deg2rad(12)
    sel1 = np.abs(_ang_diff(ang, c1)) <= tol
    if sel1.sum() < 2:
        return invalid
    a1 = v[sel1].mean(axis=0)

    far = np.abs(_ang_diff(ang, c1)) > np.deg2rad(min_angle_deg)
    if far.sum() < 2:
        return invalid
    hist2, _ = np.histogram(ang[far], bins=edges)
    b2 = int(np.argmax(hist2))
    c2 = (edges[b2] + edges[b2 + 1]) / 2
    sel2 = far & (np.abs(_ang_diff(ang, c2)) <= tol)
    if sel2.sum() < 2:
        return invalid
    a2 = v[sel2].mean(axis=0)

    if abs(a1[0] * a2[1] - a1[1] * a2[0]) < 1e-6 * spacing**2:
        return invalid
    return LatticeVectors(a1=a1, a2=a2, origin=origin, spacing=spacing,
                          valid=True)


# ── sublattice assignment ─────────────────────────────────────────────


def assign_sublattice(
    features: np.ndarray, k: int, seed: int = 0
) -> np.ndarray:
    """Cluster columns into k sublattices; label 1 = brightest (by the
    first feature column), making labels stable across RNG draws when
    the clusters are separable."""
    feats = np.asarray(features, dtype=np.float64)
    if feats.ndim == 1:
        feats = feats[:, None]
    n = feats.shape[0]
    if k == 1 or n == 0:
        return np.ones(n, dtype=np.int64)
    z, _, _ = standardize_features(feats)
    raw, _, _ = kmeans_lite(z, k, seed=seed)
    primary = feats[:, 0]
    means = np.array([primary[raw == c + 1].mean() if (raw == c + 1).any()
                      else -np.inf for c in range(k)])
    rank = np.argsort(-means, kind="stable")
    remap = np.empty(k, dtype=np.int64)
    remap[rank] = np.arange(1, k + 1)
    out: np.ndarray = remap[raw - 1]
    return out


# ── peak-pair strain ──────────────────────────────────────────────────


@dataclass(frozen=True)
class PairStrain:
    exx: np.ndarray
    eyy: np.ndarray
    exy: np.ndarray
    rotation: np.ndarray
    displacement: np.ndarray
    indices: np.ndarray
    ref_vectors: np.ndarray
    origin: np.ndarray
    valid: bool


def peak_pair_strain(
    positions: np.ndarray,
    ref_vectors: np.ndarray | None = None,
    origin: np.ndarray | None = None,
    neighbors: int = 8,
) -> PairStrain:
    """Per-column strain from displacement gradients vs the ideal lattice."""
    pos = np.asarray(positions, dtype=np.float64)
    n = pos.shape[0]
    nanv = np.full(n, np.nan)
    invalid = PairStrain(
        nanv, nanv.copy(), nanv.copy(), nanv.copy(),
        np.full((n, 2), np.nan), np.full((n, 2), np.nan),
        np.full((2, 2), np.nan), np.full(2, np.nan), False,
    )
    if n < 4:
        return invalid

    if ref_vectors is not None and origin is not None:
        ref_v = np.asarray(ref_vectors, dtype=np.float64)
        org = np.asarray(origin, dtype=np.float64).ravel()
    else:
        lv = find_lattice_vectors(pos)
        if not lv.valid:
            return invalid
        ref_v = np.array([lv.a1, lv.a2])
        org = lv.origin
    b = ref_v.T  # columns a1, a2
    if abs(np.linalg.det(b)) < 1e-9:
        return invalid

    frac = np.linalg.solve(b, (pos - org).T)
    idx = np.round(frac)
    ideal = org + (b @ idx).T
    u = pos - ideal

    d2 = np.maximum(
        (ideal**2).sum(1)[:, None]
        - 2 * ideal @ ideal.T
        + (ideal**2).sum(1)[None, :],
        0,
    )
    exx = nanv.copy()
    eyy = nanv.copy()
    exy = nanv.copy()
    rot = nanv.copy()
    for i in range(n):
        order = np.argsort(d2[i], kind="stable")
        kk = min(neighbors + 1, order.size)  # include self
        nb = order[:kk]
        if kk < 4:
            continue
        dx = ideal[nb, 0] - ideal[i, 0]
        dy = ideal[nb, 1] - ideal[i, 1]
        a = np.column_stack([np.ones(kk), dx, dy])
        gx, *_ = np.linalg.lstsq(a, u[nb, 0], rcond=None)
        gy, *_ = np.linalg.lstsq(a, u[nb, 1], rcond=None)
        exx[i] = gx[1]
        eyy[i] = gy[2]
        exy[i] = 0.5 * (gx[2] + gy[1])
        rot[i] = 0.5 * (gy[1] - gx[2])

    return PairStrain(
        exx=exx, eyy=eyy, exy=exy, rotation=rot,
        displacement=u, indices=idx.T,
        ref_vectors=ref_v, origin=org, valid=True,
    )
