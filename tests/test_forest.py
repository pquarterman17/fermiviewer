"""Random-forest classifier (Quick-Wins #8): the pure-numpy CART forest used
as the nonlinear alternative to softmax for scribble-trained grains.

Net-new code (no MATLAB golden) — tests use synthetic well-separated /
nonlinearly-separable classes and assert determinism from the seed."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.forest import forest_predict, forest_train
from fermiviewer.calc.ml import softmax_predict, softmax_train


def test_forest_separates_two_clusters() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(loc=[-3.0, -3.0], scale=0.3, size=(40, 2))
    b = rng.normal(loc=[3.0, 3.0], scale=0.3, size=(40, 2))
    x = np.vstack([a, b])
    y = np.array([1] * 40 + [2] * 40)
    model = forest_train(x, y, n_trees=32, seed=0)
    labels, probs = forest_predict(model, x)
    assert np.array_equal(model.classes, [1, 2])
    assert (labels == y).mean() == 1.0
    assert np.allclose(probs.sum(axis=1), 1.0)
    assert (probs >= 0).all() and (probs <= 1).all()


def test_forest_handles_three_classes() -> None:
    rng = np.random.default_rng(1)
    centers = [[-4.0, 0.0], [4.0, 0.0], [0.0, 5.0]]
    blobs = [rng.normal(c, 0.4, size=(30, 2)) for c in centers]
    x = np.vstack(blobs)
    y = np.array([1] * 30 + [2] * 30 + [3] * 30)
    model = forest_train(x, y, n_trees=48, seed=7)
    labels, probs = forest_predict(model, x)
    assert np.array_equal(model.classes, [1, 2, 3])
    assert (labels == y).mean() >= 0.98
    assert probs.shape == (90, 3)


def test_forest_beats_softmax_on_xor() -> None:
    # XOR / checkerboard is the canonical NON-linearly-separable problem:
    # a linear softmax boundary cannot separate it, but axis-aligned tree
    # splits can. This is the whole reason the forest classifier exists.
    rng = np.random.default_rng(2)
    n = 80
    quads = [
        (rng.normal([-2, -2], 0.3, (n, 2)), 1),
        (rng.normal([2, 2], 0.3, (n, 2)), 1),
        (rng.normal([-2, 2], 0.3, (n, 2)), 2),
        (rng.normal([2, -2], 0.3, (n, 2)), 2),
    ]
    x = np.vstack([q[0] for q in quads])
    y = np.concatenate([[q[1]] * n for q in quads])

    forest = forest_train(x, y, n_trees=64, seed=0)
    fa = (forest_predict(forest, x)[0] == y).mean()
    sm = softmax_train(x, y, max_iter=2000)
    sa = (softmax_predict(sm, x)[0] == y).mean()

    assert fa >= 0.97  # forest nails the checkerboard
    assert sa < 0.75  # linear model can't (chance ≈ 0.5)
    assert fa > sa


def test_forest_is_deterministic_from_seed() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=(60, 4))
    y = (x[:, 0] + x[:, 1] > 0).astype(int) + 1
    m1 = forest_train(x, y, n_trees=20, seed=42)
    m2 = forest_train(x, y, n_trees=20, seed=42)
    p1 = forest_predict(m1, x)[1]
    p2 = forest_predict(m2, x)[1]
    assert np.array_equal(p1, p2)
    # a different seed gives a (generally) different ensemble
    m3 = forest_train(x, y, n_trees=20, seed=43)
    assert not np.array_equal(forest_predict(m3, x)[1], p1)


def test_forest_size_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="rows"):
        forest_train(np.zeros((4, 2)), np.array([1, 2, 1]))


def test_forest_single_feature_and_pure_node() -> None:
    # one feature, a clean threshold — tree must split once and predict 1.0
    x = np.array([[0.0], [0.1], [5.0], [5.1]])
    y = np.array([1, 1, 2, 2])
    model = forest_train(x, y, n_trees=8, bootstrap=False, seed=0)
    labels, probs = forest_predict(model, np.array([[0.05], [5.05]]))
    assert list(labels) == [1, 2]
    assert probs.max(axis=1).min() > 0.9
