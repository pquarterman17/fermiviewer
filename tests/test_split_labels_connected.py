"""split_labels_connected — the O(N) relabel behind grain segmentation
must reproduce the per-label full-image loop it replaced, label for label."""

from __future__ import annotations

import time

import numpy as np
import pytest

from fermiviewer.calc.segment import label_components, split_labels_connected


def _reference(labels: np.ndarray, min_area: int, connectivity: int):
    """The original implementation: one full-image labelling per label."""
    out = np.zeros(labels.shape, dtype=np.int64)
    g = 0
    for lab in np.unique(labels):
        if lab == 0:
            continue
        cc, ncc = label_components(labels == lab, connectivity)
        for j in range(1, ncc + 1):
            comp = cc == j
            if comp.sum() >= min_area:
                g += 1
                out[comp] = g
    return out, g


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("connectivity", [4, 8])
@pytest.mark.parametrize("min_area", [1, 3])
def test_matches_reference(seed: int, connectivity: int, min_area: int) -> None:
    rng = np.random.default_rng(seed)
    n_labels = int(rng.integers(2, 9))
    labels = rng.integers(0, n_labels, size=(23, 31))
    if seed % 2:
        labels = labels * 7 - 3  # sparse / negative label values
    got, n = split_labels_connected(labels, min_area, connectivity)
    want, n_want = _reference(labels, min_area, connectivity)
    assert n == n_want
    np.testing.assert_array_equal(got, want)


def test_empty_and_all_background() -> None:
    out, n = split_labels_connected(np.zeros((4, 5), dtype=int), 1)
    assert n == 0 and not out.any()
    out, n = split_labels_connected(np.zeros((0, 0), dtype=int), 1)
    assert n == 0 and out.shape == (0, 0)


def test_many_labels_is_fast() -> None:
    # ~65k tiny labels on a 1024² field took minutes with the per-label loop
    tile = np.arange(256 * 256).reshape(256, 256) + 1
    labels = np.kron(tile, np.ones((4, 4), dtype=np.int64))
    t0 = time.perf_counter()
    out, n = split_labels_connected(labels, 1)
    assert time.perf_counter() - t0 < 15.0
    assert n == 256 * 256
    assert out[0, 0] == 1 and out[-1, -1] == n


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("min_area", [1, 4])
def test_region_stats_matches_full_mask_reference(seed: int, min_area: int) -> None:
    """region_stats measures each region in its bounding box; it must give
    exactly what the per-label full-image masks gave."""
    from fermiviewer.calc.particles import region_stats

    rng = np.random.default_rng(seed)
    labels, _ = split_labels_connected(rng.integers(0, 5, size=(19, 27)), 1)
    labels[labels == 3] = 0  # a gap in the id sequence
    img = rng.normal(size=labels.shape)
    regions, renumbered, n = region_stats(labels, img, min_area=min_area)
    kept = 0
    for k in range(1, int(labels.max()) + 1):
        sel = labels == k
        if sel.sum() < min_area or not sel.any():
            continue
        kept += 1
        r = regions[kept - 1]
        rs, cs = np.nonzero(sel)
        assert r.area == int(sel.sum())
        assert r.centroid == (float(rs.mean()) + 1, float(cs.mean()) + 1)
        assert r.bbox == (rs.min() + 1, cs.min() + 1, rs.max() + 1, cs.max() + 1)
        assert r.mean_intensity == float(img[sel].mean())
        assert (renumbered[sel] == kept).all()
    assert n == kept == len(regions)
    assert int(renumbered.max()) == n
    assert (renumbered[labels == 0] == 0).all()
