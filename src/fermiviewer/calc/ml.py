"""Toolbox-free ML primitives — W4 item 15 (ported).

kmeans_lite mirrors the MATLAB algorithm (k-means++ seeding, Lloyd
iterations, empty-cluster reseed, multi-start by inertia) but uses
numpy's RNG — MATLAB twister sequences are not reproducible here, so
goldens built on it must be RNG-robust (well-separated clusters whose
converged partition is unique).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["KmeansInfo", "kmeans_lite", "standardize_features"]


def standardize_features(
    x: np.ndarray,
    mu: np.ndarray | None = None,
    sigma: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-score each feature column; returns (z, mu, sigma) so the same
    transform can be re-applied to new data. Zero-variance columns get
    sigma 1 (pass through centred)."""
    d = np.asarray(x, dtype=np.float64)
    m = d.mean(axis=0) if mu is None else np.asarray(mu, dtype=np.float64)
    if sigma is None:
        s = d.std(axis=0, ddof=1)
    else:
        s = np.asarray(sigma, dtype=np.float64)
    s = np.where((~np.isfinite(s)) | (s == 0), 1.0, s)
    z: np.ndarray = (d - m) / s
    return z, m, s


@dataclass(frozen=True)
class KmeansInfo:
    inertia: float
    iters: int
    k: int


def _pairwise_sq(x: np.ndarray, c: np.ndarray) -> np.ndarray:
    d: np.ndarray = (
        (x**2).sum(axis=1)[:, None]
        + (c**2).sum(axis=1)[None, :]
        - 2 * x @ c.T
    )
    out: np.ndarray = np.maximum(d, 0.0)
    return out


def _kmeanspp_init(
    x: np.ndarray, k: int, rng: np.random.Generator
) -> np.ndarray:
    n = x.shape[0]
    c = np.empty((k, x.shape[1]))
    c[0] = x[rng.integers(n)]
    for j in range(1, k):
        d2 = _pairwise_sq(x, c[:j]).min(axis=1)
        total = d2.sum()
        if total <= 0:
            c[j] = x[rng.integers(n)]
            continue
        r = rng.random() * total
        c[j] = x[np.searchsorted(np.cumsum(d2), r)]
    return c


def kmeans_lite(
    x: np.ndarray,
    k: int,
    max_iter: int = 100,
    tol: float = 1e-4,
    seed: int = 0,
    replicates: int = 1,
) -> tuple[np.ndarray, np.ndarray, KmeansInfo]:
    """Lloyd k-means with k-means++ seeding; labels are 1-based like
    MATLAB. Best of `replicates` runs by inertia."""
    d = np.asarray(x, dtype=np.float64)
    n = d.shape[0]
    best_inertia = np.inf
    best_labels = np.ones(n, dtype=np.int64)
    best_centers = d[:1].copy()
    best_iters = 0

    for rep in range(replicates):
        rng = np.random.default_rng(seed + rep)
        c = _kmeanspp_init(d, k, rng)
        prev = c.copy()
        it = 0
        for it in range(1, max_iter + 1):  # noqa: B007 — it reported in info
            lab = np.argmin(_pairwise_sq(d, c), axis=1)
            for j in range(k):
                m = lab == j
                if m.any():
                    c[j] = d[m].mean(axis=0)
                else:
                    c[j] = d[rng.integers(n)]  # empty cluster reseed
            if np.abs(c - prev).max() < tol:
                break
            prev = c.copy()

        dist = _pairwise_sq(d, c)
        lab = np.argmin(dist, axis=1)
        inertia = float(dist[np.arange(n), lab].sum())
        if inertia < best_inertia:
            best_inertia = inertia
            best_labels = lab + 1  # 1-based
            best_centers = c.copy()
            best_iters = it

    return (
        best_labels,
        best_centers,
        KmeansInfo(inertia=best_inertia, iters=best_iters, k=k),
    )
