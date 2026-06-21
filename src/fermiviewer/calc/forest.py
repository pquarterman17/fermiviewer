"""Toolbox-free random-forest classifier — Quick-Wins #8.

A small CART random forest in pure numpy, offered as a nonlinear alternative
to the linear `softmax` classifier for scribble-trained grain segmentation
(calc.grains_trained). Grain textures in the multi-scale feature stack are
rarely linearly separable; a forest learns axis-aligned nonlinear boundaries.

This is NET-NEW (not ported from MATLAB), so it has no frozen golden: it is
made deterministic with numpy's seeded Generator (one stream per tree, seed +
tree index) and tested against synthetic well-separated classes. The public
surface — `forest_train` / `forest_predict` returning ``(labels, probs)`` —
deliberately mirrors `softmax_train` / `softmax_predict` so grains_trained can
dispatch on a single ``classifier`` field.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = [
    "DecisionTree",
    "RandomForestModel",
    "forest_predict",
    "forest_train",
]


@dataclass(frozen=True)
class DecisionTree:
    """One CART tree as flat parallel arrays (cache-friendly + lets prediction
    route an entire pixel batch down a level at a time). ``feature[n] == -1``
    marks a leaf; ``value[n]`` is that node's class-probability vector."""

    feature: np.ndarray  # (nodes,) int split-feature index, -1 = leaf
    threshold: np.ndarray  # (nodes,) float split threshold (x <= thr → left)
    left: np.ndarray  # (nodes,) int child index, -1 = none
    right: np.ndarray  # (nodes,) int child index, -1 = none
    value: np.ndarray  # (nodes, C) class probabilities (used at leaves)


@dataclass(frozen=True)
class RandomForestModel:
    """A bagged ensemble of `DecisionTree`s. ``classes`` holds the original
    label values in model-output (column) order, identical to SoftmaxModel."""

    trees: tuple[DecisionTree, ...]
    classes: np.ndarray  # (C,) original label values, in model-output order
    n_features: int
    classifier: str = "forest"

    @property
    def num_classes(self) -> int:
        return int(self.classes.size)


def _best_split(
    x: np.ndarray,
    y: np.ndarray,
    n_classes: int,
    feat_idx: np.ndarray,
    min_leaf: int,
) -> tuple[float, int, float] | None:
    """Best (lowest weighted-Gini) threshold split over a feature subset.

    For each candidate feature the rows are sorted once and cumulative class
    counts give every threshold's left/right Gini in one vectorized pass —
    the standard O(n log n + n·C) CART split, not an O(n²) scan.
    """
    n = x.shape[0]
    best: tuple[float, int, float] | None = None
    for f in feat_idx:
        col = x[:, f]
        order = np.argsort(col, kind="stable")
        sc = col[order]
        sy = y[order]
        onehot = np.zeros((n, n_classes))
        onehot[np.arange(n), sy] = 1.0
        cum = np.cumsum(onehot, axis=0)  # left counts incl. row i
        total = cum[-1]
        left_n = np.arange(1, n)  # split between row i and i+1 → left size i+1
        left_counts = cum[:-1]
        right_counts = total - left_counts
        right_n = n - left_n
        gl = 1.0 - (left_counts**2).sum(1) / np.maximum(left_n, 1) ** 2
        gr = 1.0 - (right_counts**2).sum(1) / np.maximum(right_n, 1) ** 2
        weighted = (left_n * gl + right_n * gr) / n
        # only between distinct values and respecting the leaf-size floor
        valid = (sc[:-1] != sc[1:]) & (left_n >= min_leaf) & (right_n >= min_leaf)
        if not valid.any():
            continue
        weighted = np.where(valid, weighted, np.inf)
        i = int(np.argmin(weighted))
        score = float(weighted[i])
        if best is None or score < best[0]:
            thr = float((sc[i] + sc[i + 1]) / 2.0)
            best = (score, int(f), thr)
    return best


def _grow_tree(
    x: np.ndarray,
    y: np.ndarray,
    n_classes: int,
    rng: np.random.Generator,
    max_depth: int,
    min_leaf: int,
    max_features: int,
) -> DecisionTree:
    n_feat = x.shape[1]
    feats: list[int] = []
    thresh: list[float] = []
    left: list[int] = []
    right: list[int] = []
    value: list[np.ndarray] = []

    def _alloc(counts: np.ndarray) -> int:
        total = counts.sum()
        value.append(counts / total if total else counts.astype(float))
        feats.append(-1)
        thresh.append(0.0)
        left.append(-1)
        right.append(-1)
        return len(feats) - 1

    def _build(idx: np.ndarray, depth: int) -> int:
        counts = np.bincount(y[idx], minlength=n_classes).astype(float)
        nid = _alloc(counts)  # tentatively a leaf
        pure = int((counts > 0).sum()) <= 1
        if pure or depth >= max_depth or idx.size < 2 * min_leaf:
            return nid
        fsub = (
            rng.choice(n_feat, size=max_features, replace=False)
            if max_features < n_feat
            else np.arange(n_feat)
        )
        split = _best_split(x[idx], y[idx], n_classes, fsub, min_leaf)
        if split is None:
            return nid
        _, f, thr = split
        go_left = x[idx, f] <= thr
        li, ri = idx[go_left], idx[~go_left]
        if li.size < min_leaf or ri.size < min_leaf:
            return nid
        lc = _build(li, depth + 1)
        rc = _build(ri, depth + 1)
        feats[nid] = f  # promote leaf → internal node
        thresh[nid] = thr
        left[nid] = lc
        right[nid] = rc
        return nid

    _build(np.arange(x.shape[0]), 0)
    return DecisionTree(
        feature=np.array(feats, dtype=np.int64),
        threshold=np.array(thresh, dtype=np.float64),
        left=np.array(left, dtype=np.int64),
        right=np.array(right, dtype=np.int64),
        value=np.vstack(value),
    )


def forest_train(
    x: np.ndarray,
    y: np.ndarray,
    n_trees: int = 64,
    max_depth: int = 14,
    min_leaf: int = 1,
    max_features: int | None = None,
    seed: int = 0,
    bootstrap: bool = True,
) -> RandomForestModel:
    """Fit a bagged CART forest. Labels map to 0..C-1 internally; predictions
    come back in the original ``y`` values. ``max_features`` defaults to
    ``round(sqrt(F))`` (the classification rule of thumb). Each tree draws its
    own bootstrap sample and feature subsets from ``default_rng(seed + t)``, so
    the whole model is reproducible from ``seed`` alone."""
    feats = np.asarray(x, dtype=np.float64)
    labels = np.asarray(y).ravel()
    if labels.size != feats.shape[0]:
        raise ValueError(
            f"x has {feats.shape[0]} rows but y has {labels.size}."
        )
    classes = np.unique(labels)
    n_classes = classes.size
    y_idx = np.searchsorted(classes, labels)
    n, n_feat = feats.shape
    mf = max_features or max(1, int(round(math.sqrt(n_feat))))
    mf = min(mf, n_feat)

    trees: list[DecisionTree] = []
    for t in range(n_trees):
        rng = np.random.default_rng(seed + t)
        samp = rng.integers(0, n, size=n) if bootstrap else np.arange(n)
        trees.append(
            _grow_tree(
                feats[samp], y_idx[samp], n_classes, rng, max_depth, min_leaf, mf
            )
        )
    return RandomForestModel(
        trees=tuple(trees), classes=classes, n_features=n_feat
    )


def _tree_proba(tree: DecisionTree, x: np.ndarray) -> np.ndarray:
    """Route every row of x to its leaf, level by level (depth-bounded loop),
    and return the leaf class-probability vectors. Leaf rows are masked out of
    the gather so a leaf's ``feature == -1`` never indexes out of range."""
    m = x.shape[0]
    node = np.zeros(m, dtype=np.int64)
    rows = np.arange(m)
    for _ in range(tree.feature.shape[0]):  # ≥ depth; early-breaks at leaves
        f = tree.feature[node]
        is_leaf = f < 0
        if bool(is_leaf.all()):
            break
        safe_f = np.where(is_leaf, 0, f)
        go_left = x[rows, safe_f] <= tree.threshold[node]
        nxt = np.where(go_left, tree.left[node], tree.right[node])
        node = np.where(is_leaf, node, nxt)
    return tree.value[node]


def forest_predict(
    model: RandomForestModel, x: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Predict with a forest — same contract as `softmax_predict`: returns
    ``(labels in model.classes values, [M, C] mean class probabilities)``.
    Probabilities are the average of the per-tree leaf distributions (soft
    vote), so confidence reflects tree agreement."""
    feats = np.asarray(x, dtype=np.float64)
    proba = np.zeros((feats.shape[0], model.num_classes))
    for tree in model.trees:
        proba += _tree_proba(tree, feats)
    proba /= len(model.trees)
    labels: np.ndarray = model.classes[np.argmax(proba, axis=1)]
    return labels, proba
