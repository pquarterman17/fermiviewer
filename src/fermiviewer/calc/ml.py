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

__all__ = [
    "KmeansInfo",
    "SoftmaxModel",
    "kmeans_lite",
    "softmax_predict",
    "softmax_train",
    "standardize_features",
]


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


@dataclass(frozen=True)
class SoftmaxModel:
    """Multinomial logistic-regression classifier (ported from
    imaging.ml.softmaxTrain). Standardization stats are baked in so
    softmax_predict reproduces the exact training feature space."""

    w: np.ndarray  # (F+1, C) weights, row 0 = bias
    classes: np.ndarray  # (C,) original label values, in model-output order
    mu: np.ndarray | None  # (F,) standardization means (None if not used)
    sigma: np.ndarray | None  # (F,) standardization std devs
    standardize: bool
    iters: int
    loss: float

    @property
    def num_classes(self) -> int:
        return int(self.classes.size)


def softmax_train(
    x: np.ndarray,
    y: np.ndarray,
    learn_rate: float = 0.5,
    max_iter: int = 800,
    lambda_: float = 1e-3,
    tol: float = 1e-7,
    standardize: bool = True,
) -> SoftmaxModel:
    """Softmax (multinomial logistic) classifier by batch gradient descent
    with L2 regularization — ported from imaging.ml.softmaxTrain.

    Zero weight initialization makes training deterministic (no RNG). The
    bias row is never regularized. Standardization is fitted here and baked
    into the model so predictions on new data use the identical transform.
    """
    feats = np.asarray(x, dtype=np.float64)
    n = feats.shape[0]
    labels = np.asarray(y).ravel()
    if labels.size != n:
        raise ValueError(f"x has {n} rows but y has {labels.size}.")

    # map labels to 0..C-1 (np.unique is sorted, so searchsorted is exact)
    classes = np.unique(labels)
    n_classes = classes.size
    y_idx = np.searchsorted(classes, labels)

    if standardize:
        feats_s, mu, sigma = standardize_features(feats)
    else:
        feats_s, mu, sigma = feats, None, None

    xb = np.hstack([np.ones((n, 1)), feats_s])  # bias column
    f1 = xb.shape[1]

    onehot = np.zeros((n, n_classes))
    onehot[np.arange(n), y_idx] = 1.0

    reg_mask = np.ones((f1, n_classes))
    reg_mask[0, :] = 0.0  # never regularize the bias

    w = np.zeros((f1, n_classes))
    prev_loss = np.inf
    it = 0
    loss = 0.0
    for it in range(1, max_iter + 1):  # noqa: B007 — it reported in model.iters
        scores = xb @ w
        scores = scores - scores.max(axis=1, keepdims=True)  # stability
        exp_s = np.exp(scores)
        probs = exp_s / exp_s.sum(axis=1, keepdims=True)

        log_lik = float(np.log(probs[np.arange(n), y_idx]).sum())
        loss = -log_lik / n + lambda_ / 2 * float(np.sum((reg_mask * w) ** 2))

        grad = xb.T @ (probs - onehot) / n + lambda_ * (reg_mask * w)
        w = w - learn_rate * grad

        if abs(prev_loss - loss) < tol:
            break
        prev_loss = loss

    return SoftmaxModel(
        w=w,
        classes=classes,
        mu=mu,
        sigma=sigma,
        standardize=standardize,
        iters=it,
        loss=float(loss),
    )


def softmax_predict(
    model: SoftmaxModel, x: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Predict with a softmax_train model — ported from
    imaging.ml.softmaxPredict. Returns (labels in model.classes values,
    [M, C] class posteriors aligned to model.classes order)."""
    feats = np.asarray(x, dtype=np.float64)
    if model.standardize:
        feats_s, _, _ = standardize_features(feats, mu=model.mu, sigma=model.sigma)
    else:
        feats_s = feats
    xb = np.hstack([np.ones((feats_s.shape[0], 1)), feats_s])
    scores = xb @ model.w
    scores = scores - scores.max(axis=1, keepdims=True)
    exp_s = np.exp(scores)
    probs: np.ndarray = exp_s / exp_s.sum(axis=1, keepdims=True)
    labels: np.ndarray = model.classes[np.argmax(probs, axis=1)]
    return labels, probs
