"""Edge and validation paths of calc/segment.py that the golden suite
doesn't reach: the 5-class coarse→fine Otsu search, empty-class ranges,
argument validation, and slic's degenerate-grid seeding fallbacks."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.segment import (
    distance_transform,
    label_components,
    morph_op,
    multi_otsu,
    slic,
)

pytestmark = pytest.mark.imaging


def test_multi_otsu_five_classes_separates_five_levels() -> None:
    # five tight clusters at 0/10/20/30/40 → the coarse(64)→windowed-fine
    # search must place one threshold between each adjacent pair
    rng = np.random.default_rng(0)
    levels = np.repeat(np.array([0.0, 10.0, 20.0, 30.0, 40.0]), 200)
    img = (levels + rng.normal(0, 0.3, levels.size)).reshape(20, 50)

    res = multi_otsu(img, n_classes=5)

    assert res.thresholds.shape == (4,)
    assert np.all(np.diff(res.thresholds) > 0)
    # every cluster keeps its 200 pixels → exactly 1/5 per class
    np.testing.assert_allclose(res.class_fractions, 0.2, atol=1e-12)
    assert res.label_map.min() == 1 and res.label_map.max() == 5
    # each level block maps to a single label, in ascending order
    blocks = res.label_map.ravel().reshape(5, 200)
    assert [int(np.unique(b).item()) for b in blocks] == [1, 2, 3, 4, 5]


def test_multi_otsu_empty_class_ranges_are_nan() -> None:
    # two spikes forced into three classes → the middle class has no
    # pixels: fraction 0 and a [nan, nan] range, not a crash
    img = np.concatenate([np.zeros(100), np.full(100, 100.0)]).reshape(10, 20)

    res = multi_otsu(img, n_classes=3)

    np.testing.assert_allclose(res.class_fractions, [0.5, 0.0, 0.5])
    assert np.isnan(res.class_ranges[1]).all()
    assert res.class_ranges[0][0] == 0.0 and res.class_ranges[2][1] == 100.0


def test_multi_otsu_rejects_bad_class_count() -> None:
    img = np.arange(16.0).reshape(4, 4)
    with pytest.raises(ValueError, match="n_classes"):
        multi_otsu(img, n_classes=1)
    with pytest.raises(ValueError, match="n_classes"):
        multi_otsu(img, n_classes=6)


def test_morph_op_rejects_bad_structuring_shape() -> None:
    bw = np.zeros((5, 5), dtype=bool)
    bw[2, 2] = True
    with pytest.raises(ValueError, match="shape"):
        morph_op(bw, "dilate", radius=1, shape="hex")


def test_label_components_rejects_bad_connectivity() -> None:
    with pytest.raises(ValueError, match="connectivity"):
        label_components(np.ones((3, 3), dtype=bool), connectivity=5)


def test_distance_transform_rejects_bad_metric() -> None:
    with pytest.raises(ValueError, match="metric"):
        distance_transform(np.ones((3, 3), dtype=bool), metric="euclid")


@pytest.mark.parametrize("shape", [(2, 100), (100, 2)])
def test_slic_degenerate_grid_falls_back_to_midline_seed(
    shape: tuple[int, int],
) -> None:
    # a strip thinner than half the seeding step produces an EMPTY seed
    # grid along that axis; the fallback seeds the mid-line instead of
    # returning zero superpixels, and every pixel still gets a label
    rng = np.random.default_rng(1)
    img = rng.normal(0.0, 1.0, shape)

    labels, centres = slic(img, n_superpixels=1)

    assert labels.shape == shape
    assert labels.min() >= 1
    assert (labels > 0).all()
    assert centres.shape[0] == labels.max()
