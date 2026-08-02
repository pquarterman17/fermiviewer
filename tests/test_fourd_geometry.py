"""Pure-math tests for 4D-STEM reciprocal-space geometry + streamed
virtual-detector reduction (calc/fourd/geometry.py, calc/fourd/virtual.py).

No corpus, no server, no golden marker — hand-checkable synthetic grids
and cubes only.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest

from fermiviewer.calc.fourd.geometry import aperture_mask, pattern_center, radial_coverage
from fermiviewer.calc.fourd.virtual import (
    abf_mask,
    adf_mask,
    bf_mask,
    com_shift_maps,
    virtual_detector,
)

# ════════════════════════════════════════════════════════════════════
# aperture_mask
# ════════════════════════════════════════════════════════════════════


def test_aperture_mask_circle_plus_shape() -> None:
    # On a 5x5 grid centered at (2,2), r<=1.0 keeps only the 4 orthogonal
    # neighbors (dist 1.0) plus the center — diagonals sit at sqrt(2)~1.414.
    mask = aperture_mask((5, 5), (2.0, 2.0), 0.0, 1.0, shape="circle")
    expected = np.zeros((5, 5), dtype=bool)
    for r, c in [(2, 2), (1, 2), (3, 2), (2, 1), (2, 3)]:
        expected[r, c] = True
    np.testing.assert_array_equal(mask, expected)


def test_aperture_mask_annulus_diagonal_ring() -> None:
    # inner=1.2 excludes the orthogonal neighbors (dist 1.0); outer=1.5
    # includes the diagonal neighbors (dist sqrt(2)~1.414) only.
    mask = aperture_mask((5, 5), (2.0, 2.0), 1.2, 1.5, shape="annulus")
    expected = np.zeros((5, 5), dtype=bool)
    for r, c in [(1, 1), (1, 3), (3, 1), (3, 3)]:
        expected[r, c] = True
    np.testing.assert_array_equal(mask, expected)


def test_aperture_mask_circle_edge_inclusion() -> None:
    # distance exactly == outer_r must be included (<=, not <).
    mask = aperture_mask((5, 5), (2.0, 2.0), 0.0, 1.0, shape="circle")
    assert bool(mask[1, 2])  # dist == 1.0 exactly


def test_aperture_mask_annulus_edge_inclusion() -> None:
    # distance exactly == inner_r or == outer_r must both be included.
    mask = aperture_mask((5, 5), (2.0, 2.0), 1.0, 1.4142135623730951, shape="annulus")
    assert bool(mask[1, 2])  # dist == inner_r == 1.0
    assert bool(mask[1, 1])  # dist == outer_r == sqrt(2)


def test_aperture_mask_off_center_and_nonsquare() -> None:
    det_shape = (6, 4)
    mask = aperture_mask(det_shape, (1.0, 3.0), 0.0, 0.5, shape="circle")
    expected = np.zeros(det_shape, dtype=bool)
    expected[1, 3] = True
    np.testing.assert_array_equal(mask, expected)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(inner_r=0.0, outer_r=1.0, shape="triangle"),
        dict(inner_r=-1.0, outer_r=1.0, shape="circle"),
        dict(inner_r=0.0, outer_r=-1.0, shape="circle"),
        dict(inner_r=2.0, outer_r=1.0, shape="annulus"),
        dict(inner_r=1.0, outer_r=1.0, shape="annulus"),
    ],
)
def test_aperture_mask_validation_errors(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        aperture_mask(
            (5, 5), (2.0, 2.0), kwargs["inner_r"], kwargs["outer_r"], shape=kwargs["shape"]
        )


# ════════════════════════════════════════════════════════════════════
# pattern_center
# ════════════════════════════════════════════════════════════════════


def test_pattern_center_centroid_off_center_gaussian() -> None:
    h, w = 41, 41
    true_cy, true_cx = 15.3, 22.7
    y = np.arange(h, dtype=np.float64)[:, None]
    x = np.arange(w, dtype=np.float64)[None, :]
    sigma = 4.0
    dp = np.exp(-((y - true_cy) ** 2 + (x - true_cx) ** 2) / (2 * sigma**2))
    cy, cx = pattern_center(dp, method="centroid")
    assert abs(cy - true_cy) < 0.1
    assert abs(cx - true_cx) < 0.1


def test_pattern_center_max() -> None:
    dp = np.zeros((10, 10))
    dp[3, 7] = 5.0
    cy, cx = pattern_center(dp, method="max")
    assert (cy, cx) == (3.0, 7.0)


def test_pattern_center_all_zero_falls_back_to_geometric_center() -> None:
    dp = np.zeros((10, 6))
    assert pattern_center(dp, method="centroid") == (4.5, 2.5)
    assert pattern_center(dp, method="max") == (4.5, 2.5)


def test_pattern_center_all_nan_falls_back_to_geometric_center() -> None:
    dp = np.full((8, 8), np.nan)
    assert pattern_center(dp, method="centroid") == (3.5, 3.5)
    assert pattern_center(dp, method="max") == (3.5, 3.5)


def test_pattern_center_invalid_method() -> None:
    with pytest.raises(ValueError):
        pattern_center(np.zeros((4, 4)), method="bogus")


def test_pattern_center_requires_2d() -> None:
    with pytest.raises(ValueError):
        pattern_center(np.zeros((4, 4, 4)))
    with pytest.raises(ValueError):
        pattern_center(np.zeros((0, 4)))


# ════════════════════════════════════════════════════════════════════
# radial_coverage
# ════════════════════════════════════════════════════════════════════


def test_radial_coverage_bin_sums_equal_total_pixels() -> None:
    det_shape = (16, 20)
    center = (7.3, 9.8)
    radii, counts = radial_coverage(det_shape, center, n_bins=10)
    assert radii.shape == counts.shape == (10,)
    assert counts.sum() == det_shape[0] * det_shape[1]


def test_radial_coverage_matches_full_circle_mask_count() -> None:
    det_shape = (12, 9)
    center = (5.0, 4.0)
    _radii, counts = radial_coverage(det_shape, center, n_bins=6)
    ky = np.arange(det_shape[0], dtype=np.float64)[:, None]
    kx = np.arange(det_shape[1], dtype=np.float64)[None, :]
    max_r = float(np.hypot(ky - center[0], kx - center[1]).max())
    full_mask = aperture_mask(det_shape, center, 0.0, max_r, shape="circle")
    assert counts.sum() == full_mask.sum()


def test_radial_coverage_default_n_bins_resolves_positive() -> None:
    det_shape = (10, 10)
    radii, counts = radial_coverage(det_shape, (4.5, 4.5))
    n_bins = max(min(det_shape) // 2, 1)
    assert radii.shape[0] == counts.shape[0] == n_bins
    assert counts.sum() == 100


def test_radial_coverage_1x1_detector_degenerate_max_radius() -> None:
    """A 1x1 detector centered on its only pixel has max_radius == 0 — the
    explicit degenerate branch, not a division by zero."""
    radii, counts = radial_coverage((1, 1), (0.0, 0.0))
    assert counts.sum() == 1
    assert counts[0] == 1
    assert np.all(np.isfinite(radii))


# ════════════════════════════════════════════════════════════════════
# virtual_detector — streaming vs dense, block-size invariance
# ════════════════════════════════════════════════════════════════════


def _stream_blocks(cube: np.ndarray, block_rows: int) -> Iterator[tuple[int, np.ndarray]]:
    scan_y = cube.shape[0]
    row = 0
    while row < scan_y:
        n = min(block_rows, scan_y - row)
        yield row, cube[row : row + n]
        row += n


@pytest.fixture()
def synthetic_cube() -> np.ndarray:
    rng = np.random.default_rng(42)
    scan_y, scan_x, det_ky, det_kx = 7, 5, 9, 9
    return rng.uniform(0, 100, size=(scan_y, scan_x, det_ky, det_kx)).astype(np.float32)


def test_virtual_detector_matches_dense_across_block_sizes(synthetic_cube: np.ndarray) -> None:
    cube = synthetic_cube
    center = (4.0, 4.0)
    mask = bf_mask(cube.shape[2:], center, 2.5)
    dense = np.tensordot(cube.astype(np.float64), mask.astype(np.float64), axes=([2, 3], [0, 1]))

    for block_rows in (1, 3, cube.shape[0]):
        result = virtual_detector(_stream_blocks(cube, block_rows), mask)
        np.testing.assert_array_equal(result, dense)


def test_virtual_detector_empty_blocks_returns_empty() -> None:
    result = virtual_detector(iter(()), np.ones((3, 3), dtype=bool))
    assert result.shape == (0, 0)


def test_virtual_detector_out_dtype() -> None:
    cube = np.ones((2, 2, 3, 3))
    mask = np.ones((3, 3), dtype=bool)
    result = virtual_detector([(0, cube)], mask, out_dtype=np.float32)
    assert result.dtype == np.float32
    np.testing.assert_allclose(result, 9.0)


def test_virtual_detector_ignores_nan_outside_the_mask() -> None:
    """Bug-hunt regression: a dead/masked detector pixel with NaN sitting
    OUTSIDE the aperture (mask weight exactly 0 there) must never poison
    the result via IEEE 754's `0 * nan == nan` — only a non-finite pixel
    genuinely inside the mask should ever propagate."""
    det_shape = (11, 11)
    center = (5.0, 5.0)
    mask = aperture_mask(det_shape, center, 0.0, 1.0, shape="circle")
    assert not mask[0, 0]  # corner is well outside the small center disk

    pattern = np.full(det_shape, 10.0)
    pattern[0, 0] = np.nan
    cube = pattern[None, None, :, :]

    result = virtual_detector([(0, cube)], mask)
    expected = pattern[mask].sum()  # NaN corner pixel excluded by the mask
    np.testing.assert_allclose(result, [[expected]])
    assert np.isfinite(result).all()


def test_virtual_detector_still_propagates_nan_inside_the_mask() -> None:
    """The flip side of the fix above: a non-finite pixel that IS inside
    the aperture must still poison that scan position's result — this
    isn't nansum, it's specifically "zero weight can't matter"."""
    det_shape = (11, 11)
    center = (5.0, 5.0)
    mask = aperture_mask(det_shape, center, 0.0, 1.0, shape="circle")
    assert mask[5, 5]  # dead center is inside the disk

    pattern = np.full(det_shape, 10.0)
    pattern[5, 5] = np.nan
    cube = pattern[None, None, :, :]

    result = virtual_detector([(0, cube)], mask)
    assert np.isnan(result[0, 0])


def test_virtual_detector_soft_mask_zero_weight_ignores_nan() -> None:
    """Same guarantee for a non-boolean (soft-edged) mask: exact 0.0 weight
    pixels are excluded regardless of value, per the module's documented
    "used as-is as per-pixel weights" contract for float masks."""
    soft_mask = np.array([[0.0, 0.5], [0.0, 1.0]])
    pattern = np.array([[np.nan, 2.0], [np.nan, 4.0]])
    cube = pattern[None, None, :, :]
    result = virtual_detector([(0, cube)], soft_mask)
    expected = 0.5 * 2.0 + 1.0 * 4.0
    np.testing.assert_allclose(result, [[expected]])


# ════════════════════════════════════════════════════════════════════
# BF / ADF physics — hand-computed centered-disk vs scattered-ring cube
# ════════════════════════════════════════════════════════════════════


def test_bf_bright_adf_dark_for_disk_vs_ring_patterns() -> None:
    det_shape = (11, 11)
    center = (5.0, 5.0)
    ky = np.arange(11, dtype=np.float64)[:, None]
    kx = np.arange(11, dtype=np.float64)[None, :]
    dist = np.hypot(ky - center[0], kx - center[1])

    # probe 0: unscattered — intensity concentrated in a small central disk
    disk_pattern = (dist <= 2.0).astype(np.float64)
    # probe 1: strongly scattered — intensity in an outer ring, none centered
    ring_pattern = ((dist >= 4.0) & (dist <= 5.0)).astype(np.float64)
    cube = np.stack([disk_pattern, ring_pattern])[:, None, :, :]  # (scan_y=2, scan_x=1, 11, 11)

    bf = bf_mask(det_shape, center, 2.5)  # fully contains the disk, none of the ring
    adf = adf_mask(det_shape, center, 3.5, 5.5)  # fully contains the ring, none of the disk

    bf_map = virtual_detector([(0, cube)], bf)
    adf_map = virtual_detector([(0, cube)], adf)

    assert bf_map[0, 0] == disk_pattern.sum() > 0
    assert bf_map[1, 0] == 0.0
    assert adf_map[0, 0] == 0.0
    assert adf_map[1, 0] == ring_pattern.sum() > 0


def test_bf_mask_matches_circle_aperture() -> None:
    det_shape, center = (9, 9), (4.0, 4.0)
    np.testing.assert_array_equal(
        bf_mask(det_shape, center, 3.0),
        aperture_mask(det_shape, center, 0.0, 3.0, shape="circle"),
    )


def test_adf_mask_matches_annulus_aperture() -> None:
    det_shape, center = (9, 9), (4.0, 4.0)
    np.testing.assert_array_equal(
        adf_mask(det_shape, center, 2.0, 4.0),
        aperture_mask(det_shape, center, 2.0, 4.0, shape="annulus"),
    )


def test_abf_mask_matches_annulus_aperture() -> None:
    det_shape, center = (9, 9), (4.0, 4.0)
    np.testing.assert_array_equal(
        abf_mask(det_shape, center, 1.0, 2.0),
        aperture_mask(det_shape, center, 1.0, 2.0, shape="annulus"),
    )


# ════════════════════════════════════════════════════════════════════
# com_shift_maps (stretch goal)
# ════════════════════════════════════════════════════════════════════


def test_com_shift_maps_tracks_known_shift() -> None:
    center = (10.0, 10.0)
    ky = np.arange(21, dtype=np.float64)[:, None]
    kx = np.arange(21, dtype=np.float64)[None, :]

    def shifted_disk(dy: float, dx: float) -> np.ndarray:
        dist = np.hypot(ky - (center[0] + dy), kx - (center[1] + dx))
        return (dist <= 2.0).astype(np.float64)

    shifts = [(0.0, 0.0), (2.0, -1.0), (-3.0, 4.0)]
    cube = np.stack([shifted_disk(dy, dx) for dy, dx in shifts])[:, None, :, :]

    com_y, com_x = com_shift_maps([(0, cube)], center)
    for i, (dy, dx) in enumerate(shifts):
        assert abs(com_y[i, 0] - dy) < 0.05
        assert abs(com_x[i, 0] - dx) < 0.05


def test_com_shift_maps_zero_intensity_returns_zero_shift() -> None:
    cube = np.zeros((1, 1, 5, 5))
    com_y, com_x = com_shift_maps([(0, cube)], (2.0, 2.0))
    assert com_y[0, 0] == 0.0
    assert com_x[0, 0] == 0.0


def test_com_shift_maps_block_size_invariance() -> None:
    det_shape = (15, 15)
    center = (7.0, 7.0)
    rng = np.random.default_rng(7)
    scan_y, scan_x = 6, 3
    cube = rng.uniform(0, 1, size=(scan_y, scan_x, *det_shape))

    dense_y, dense_x = com_shift_maps([(0, cube)], center)
    for block_rows in (1, 4, scan_y):
        y, x = com_shift_maps(_stream_blocks(cube, block_rows), center)
        np.testing.assert_array_equal(y, dense_y)
        np.testing.assert_array_equal(x, dense_x)
