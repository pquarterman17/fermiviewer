"""Modern grain segmentation (watershed / RAG / orientation) + the
upgraded boundary metrics. These carry NO MATLAB-parity obligation, so
they validate against deterministic synthetic fixtures rather than goldens.
The ported k-means path keeps its golden in test_atoms_grains.py.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from skimage.filters import gaussian

from fermiviewer.calc.grains import (
    astm_grain_size_number,
    enforce_connected_grains,
    grain_stats,
    segment_watershed,
    split_grain,
)
from fermiviewer.calc.segment import label_components

pytestmark = pytest.mark.imaging


@pytest.fixture
def striped() -> np.ndarray:
    """Whole-field tiling: three vertical bands of distinct intensity with
    soft boundaries — a clean 3-grain target for gradient & RAG modes."""
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :30] = 0.2
    img[:, 30:60] = 0.6
    img[:, 60:] = 1.0
    return gaussian(img, sigma=1.0)


def test_gradient_watershed_recovers_bands(striped) -> None:
    seg = segment_watershed(striped, method="gradient", granularity=0.05, min_area=50)
    assert seg.method == "gradient"
    assert seg.n_grains == 3


def test_rag_recovers_bands() -> None:
    # sharp intensity steps (what diffraction-contrast grains look like) so
    # superpixels don't chain-merge across a soft transition
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :30] = 0.2
    img[:, 30:60] = 0.6
    img[:, 60:] = 1.0
    seg = segment_watershed(
        img, method="rag", n_superpixels=200, merge_threshold=0.2, min_area=50
    )
    assert seg.n_grains == 3


def test_orientation_splits_two_lattices() -> None:
    yy, xx = np.mgrid[0:80, 0:80]
    left = np.sin(xx * 0.8)   # vertical fringes
    right = np.sin(yy * 0.8)  # horizontal fringes
    img = np.where(xx < 40, left, right).astype(np.float64)
    seg = segment_watershed(
        img, method="orientation", granularity=0.04,
        orientation_sigma=2.0, min_area=100,
    )
    assert seg.n_grains == 2


def test_unknown_method_raises(striped) -> None:
    with pytest.raises(ValueError):
        segment_watershed(striped, method="nonsense")


def test_crofton_perimeter_of_a_disk() -> None:
    yy, xx = np.mgrid[0:100, 0:100]
    r = 20.0
    disk = ((xx - 50) ** 2 + (yy - 50) ** 2) <= r**2
    labels = disk.astype(np.int64)
    gs = grain_stats(labels, disk.astype(np.float64), pixel_size=1.0)
    # true perimeter 2πr ≈ 125.7; Crofton estimate within a few percent —
    # and FAR from the naive boundary-pixel count this replaces
    assert gs.perimeter_crofton_px[0] == pytest.approx(2 * math.pi * r, rel=0.05)


def test_triple_junction_count() -> None:
    labels = np.zeros((80, 80), dtype=np.int64)
    labels[:40, :40] = 1
    labels[:40, 40:] = 2
    labels[40:, :40] = 3
    labels[40:, 40:] = 4
    gs = grain_stats(labels, labels.astype(np.float64))
    assert gs.n_triple_junctions == 1
    assert gs.n_grains == 4


def test_boundary_network_length() -> None:
    # three equal strips tiling a 10×30 field → 2 internal boundaries × 10
    labels = np.zeros((10, 30), dtype=np.int64)
    labels[:, :10] = 1
    labels[:, 10:20] = 2
    labels[:, 20:] = 3
    gs = grain_stats(labels, np.zeros((10, 30)))
    assert gs.boundary_network_px == 20.0  # not the inflated perim-sum/2 (~55)
    # a single grain has no shared boundaries
    one = np.ones((10, 10), dtype=np.int64)
    assert grain_stats(one, np.zeros((10, 10))).boundary_network_px == 0.0


def test_split_grain_labels_stay_connected() -> None:
    # a field with an isolated tiny basin the old code would orphan into a
    # second, disconnected piece sharing grain_id
    img = np.ones((50, 50)) * 0.5
    img[5:20, 5:20] = 0.01
    img[25, 25] = 0.005
    img[5:20, 30:45] = 0.01
    img[30:45, 5:45] = 0.01
    img[21:24, :] = 1.0
    labels = np.zeros((50, 50), dtype=np.int64)
    labels[1:49, 1:49] = 1
    out = split_grain(labels, img, grain_id=1, granularity=1e-7)
    for v in np.unique(out):
        if v > 0:
            _, ncc = label_components(out == v, 8)
            assert ncc == 1, f"label {v} disconnected ({ncc} components)"


def test_enforce_connected_splits_disconnected_label() -> None:
    # mimics merging two non-adjacent grains into one label
    labels = np.zeros((10, 30), dtype=np.int64)
    labels[:, :10] = 1
    labels[:, 20:] = 1  # same id, spatially separate
    labels[:, 10:20] = 2
    out = enforce_connected_grains(labels)
    assert out[0, 0] != out[0, 25]  # the two pieces become distinct grains
    for v in np.unique(out):
        if v > 0:
            _, ncc = label_components(out == v, 8)
            assert ncc == 1


def test_segment_watershed_rejects_tiny_image() -> None:
    with pytest.raises(ValueError):
        segment_watershed(np.array([[0.5, 0.6, 0.7]]), method="orientation")


def test_astm_grain_size_number() -> None:
    # 50 µm mean diameter → 0.05 mm → G = -6.6439·log2(0.05) - 3.298
    expected = -6.6439 * math.log2(0.05) - 3.298
    assert astm_grain_size_number(50.0, "um") == pytest.approx(expected, rel=1e-9)
    assert astm_grain_size_number(50.0, "µm") == pytest.approx(expected, rel=1e-9)
    # unknown unit / non-positive diameter → NaN
    assert math.isnan(astm_grain_size_number(50.0, "furlong"))
    assert math.isnan(astm_grain_size_number(0.0, "nm"))
