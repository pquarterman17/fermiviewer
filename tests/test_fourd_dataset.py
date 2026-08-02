"""Unit tests for the lazy 4D-STEM data model (calc/fourd/dataset.py).

All synthetic — a plain in-memory ndarray already satisfies the FourDHandle
protocol (`handle[y, x]` / `handle[row0:row1]` are just numpy basic
indexing), so no file I/O is needed here; see test_io_fourd_mib.py /
test_io_fourd_hspy4d.py for the real parsers.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.fourd.dataset import FourDDataset
from fermiviewer.datastruct import AxisCal

pytestmark = pytest.mark.parser


def _make_cube(
    rows: int = 3, cols: int = 4, det_h: int = 5, det_w: int = 6, seed: int = 0
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 100, size=(rows, cols, det_h, det_w)).astype(np.float64)


def _dataset(cube: np.ndarray, **kwargs: object) -> FourDDataset:
    rows, cols, det_h, det_w = cube.shape
    return FourDDataset(
        handle=cube,
        scan_shape=(rows, cols),
        det_shape=(det_h, det_w),
        scan_axes=(
            AxisCal(scale=1.0, origin=0.0, units="nm"),
            AxisCal(scale=1.0, origin=0.0, units="nm"),
        ),
        det_axes=(AxisCal(), AxisCal()),
        dtype=cube.dtype,
        metadata={"source": "synthetic"},
        **kwargs,
    )


def test_pattern_matches_direct_index() -> None:
    cube = _make_cube()
    ds = _dataset(cube)
    for y in range(cube.shape[0]):
        for x in range(cube.shape[1]):
            np.testing.assert_array_equal(ds.pattern(y, x), cube[y, x])


def test_pattern_out_of_range_raises() -> None:
    ds = _dataset(_make_cube(rows=2, cols=2))
    with pytest.raises(IndexError):
        ds.pattern(2, 0)
    with pytest.raises(IndexError):
        ds.pattern(0, -1)


def test_iter_scan_rows_block_math() -> None:
    cube = _make_cube(rows=7, cols=3, det_h=2, det_w=2)
    ds = _dataset(cube, block_rows=3)
    seen = []
    for row0, block in ds.iter_scan_rows():
        n = block.shape[0]
        np.testing.assert_array_equal(block, cube[row0 : row0 + n])
        seen.append((row0, n))
    assert seen == [(0, 3), (3, 3), (6, 1)]


def test_iter_scan_rows_explicit_block_rows_overrides_default() -> None:
    cube = _make_cube(rows=5, cols=2, det_h=2, det_w=2)
    ds = _dataset(cube, block_rows=8)
    row_starts = [row0 for row0, _ in ds.iter_scan_rows(block_rows=2)]
    assert row_starts == [0, 2, 4]


def test_nav_image_matches_full_load_reference() -> None:
    cube = _make_cube(rows=4, cols=5, det_h=6, det_w=7)
    ds = _dataset(cube, block_rows=2)
    expected = cube.sum(axis=(2, 3))
    np.testing.assert_allclose(ds.nav_image, expected)
    assert ds.nav_image.shape == (4, 5)
    # cached: second access is the identical array object, not recomputed
    assert ds.nav_image is ds.nav_image


def test_mean_pattern_matches_full_load_reference() -> None:
    cube = _make_cube(rows=4, cols=5, det_h=6, det_w=7)
    ds = _dataset(cube, block_rows=3)
    expected = cube.mean(axis=(0, 1))
    np.testing.assert_allclose(ds.mean_pattern, expected)
    assert ds.mean_pattern.shape == (6, 7)
    assert ds.mean_pattern is ds.mean_pattern


@pytest.mark.parametrize("scan_shape", [(0, 4), (3, 0), (-1, 4)])
def test_invalid_scan_shape_raises(scan_shape: tuple[int, int]) -> None:
    cube = _make_cube(rows=3, cols=4)
    with pytest.raises(ValueError, match="scan_shape"):
        FourDDataset(
            handle=cube,
            scan_shape=scan_shape,
            det_shape=(5, 6),
            scan_axes=(AxisCal(), AxisCal()),
            det_axes=(AxisCal(), AxisCal()),
            dtype=cube.dtype,
        )


@pytest.mark.parametrize("det_shape", [(0, 6), (5, 0)])
def test_invalid_det_shape_raises(det_shape: tuple[int, int]) -> None:
    cube = _make_cube()
    with pytest.raises(ValueError, match="det_shape"):
        FourDDataset(
            handle=cube,
            scan_shape=(3, 4),
            det_shape=det_shape,
            scan_axes=(AxisCal(), AxisCal()),
            det_axes=(AxisCal(), AxisCal()),
            dtype=cube.dtype,
        )


def test_wrong_axes_count_raises() -> None:
    cube = _make_cube(rows=2, cols=2)
    with pytest.raises(ValueError, match="axes"):
        FourDDataset(
            handle=cube,
            scan_shape=(2, 2),
            det_shape=(5, 6),
            scan_axes=(AxisCal(),),  # type: ignore[arg-type]
            det_axes=(AxisCal(), AxisCal()),
            dtype=cube.dtype,
        )


def test_close_calls_close_fn() -> None:
    closed = []
    ds = _dataset(_make_cube(rows=2, cols=2), close_fn=lambda: closed.append(True))
    ds.close()
    assert closed == [True]


def test_close_is_a_noop_without_close_fn() -> None:
    ds = _dataset(_make_cube(rows=2, cols=2))
    ds.close()  # must not raise


def test_double_close_invokes_close_fn_only_once() -> None:
    calls: list[None] = []
    ds = _dataset(_make_cube(rows=2, cols=2), close_fn=lambda: calls.append(None))
    ds.close()
    ds.close()
    ds.close()
    assert len(calls) == 1


def test_pattern_after_close_raises_clear_runtime_error() -> None:
    ds = _dataset(_make_cube(rows=2, cols=2), close_fn=lambda: None)
    ds.close()
    with pytest.raises(RuntimeError, match="closed"):
        ds.pattern(0, 0)


def test_iter_scan_rows_after_close_raises_clear_runtime_error() -> None:
    ds = _dataset(_make_cube(rows=2, cols=2), close_fn=lambda: None)
    ds.close()
    with pytest.raises(RuntimeError, match="closed"):
        next(ds.iter_scan_rows())


def test_uncached_nav_image_after_close_raises() -> None:
    ds = _dataset(_make_cube(rows=2, cols=2), close_fn=lambda: None)
    ds.close()
    with pytest.raises(RuntimeError, match="closed"):
        _ = ds.nav_image


def test_uncached_mean_pattern_after_close_raises() -> None:
    ds = _dataset(_make_cube(rows=2, cols=2), close_fn=lambda: None)
    ds.close()
    with pytest.raises(RuntimeError, match="closed"):
        _ = ds.mean_pattern


def test_already_cached_nav_image_survives_close() -> None:
    """Once nav_image/mean_pattern have been computed and cached, no further
    handle access is needed to read them — closing shouldn't take away
    something already in hand."""
    cube = _make_cube(rows=2, cols=2)
    ds = _dataset(cube, close_fn=lambda: None)
    expected = ds.nav_image.copy()
    ds.close()
    np.testing.assert_array_equal(ds.nav_image, expected)


def test_already_cached_mean_pattern_survives_close() -> None:
    cube = _make_cube(rows=2, cols=2)
    ds = _dataset(cube, close_fn=lambda: None)
    expected = ds.mean_pattern.copy()
    ds.close()
    np.testing.assert_array_equal(ds.mean_pattern, expected)


def test_context_manager_closes_on_exit() -> None:
    closed = []
    with _dataset(_make_cube(rows=2, cols=2), close_fn=lambda: closed.append(True)) as ds:
        assert ds.scan_shape == (2, 2)
    assert closed == [True]


def test_metadata_defaults_to_empty_dict() -> None:
    cube = _make_cube(rows=2, cols=2)
    ds = FourDDataset(
        handle=cube,
        scan_shape=(2, 2),
        det_shape=(5, 6),
        scan_axes=(AxisCal(), AxisCal()),
        det_axes=(AxisCal(), AxisCal()),
        dtype=cube.dtype,
    )
    assert ds.metadata == {}


def test_dtype_is_normalized_to_numpy_dtype() -> None:
    ds = _dataset(_make_cube(rows=2, cols=2).astype(np.uint8))
    assert ds.dtype == np.dtype(np.uint8)


# ── NaN policy: pin the same "plain sum, propagate" convention the 2D
# pipeline already uses (calc/eds_maps.py sums with no nansum anywhere) —
# a non-finite pixel poisons only the scan position / detector pixel it
# actually belongs to, never anything else. ──────────────────────────────


def test_nav_image_nan_poisons_only_its_own_scan_position() -> None:
    cube = _make_cube(rows=2, cols=2, det_h=3, det_w=3)
    cube[0, 1, 1, 1] = np.nan
    ds = _dataset(cube)
    nav = ds.nav_image
    assert np.isnan(nav[0, 1])
    for y, x in [(0, 0), (1, 0), (1, 1)]:
        assert np.isfinite(nav[y, x])
        assert nav[y, x] == pytest.approx(cube[y, x].sum())


def test_mean_pattern_nan_poisons_only_its_own_detector_pixel() -> None:
    cube = _make_cube(rows=2, cols=2, det_h=3, det_w=3)
    cube[0, 1, 2, 0] = np.nan
    ds = _dataset(cube)
    mp = ds.mean_pattern
    assert np.isnan(mp[2, 0])
    other = np.ones((3, 3), dtype=bool)
    other[2, 0] = False
    assert np.all(np.isfinite(mp[other]))


# ── degenerate but valid shapes ─────────────────────────────────────────


def test_1x1_scan_and_1x1_detector() -> None:
    cube = np.array([[[[5.0]]]])
    ds = _dataset(cube)
    assert ds.scan_shape == (1, 1)
    assert ds.det_shape == (1, 1)
    np.testing.assert_array_equal(ds.pattern(0, 0), [[5.0]])
    np.testing.assert_array_equal(ds.nav_image, [[5.0]])
    np.testing.assert_array_equal(ds.mean_pattern, [[5.0]])


@pytest.mark.parametrize("rows,cols", [(1, 5), (5, 1), (1, 1)])
def test_degenerate_scan_line_shapes(rows: int, cols: int) -> None:
    cube = _make_cube(rows=rows, cols=cols, det_h=3, det_w=3)
    ds = _dataset(cube)
    assert ds.nav_image.shape == (rows, cols)
    np.testing.assert_allclose(ds.nav_image, cube.sum(axis=(2, 3)))


@pytest.mark.parametrize(
    "dtype", [np.bool_, np.float16, np.int64, np.uint16]
)
def test_nav_image_across_dtypes_is_always_float64(dtype: np.dtype) -> None:
    rng = np.random.default_rng(0)
    if dtype is np.bool_:
        cube = rng.integers(0, 2, size=(3, 4, 5, 5)).astype(dtype)
    else:
        cube = rng.integers(0, 100, size=(3, 4, 5, 5)).astype(dtype)
    ds = _dataset(cube)
    assert ds.nav_image.dtype == np.float64
    np.testing.assert_allclose(ds.nav_image, cube.astype(np.float64).sum(axis=(2, 3)))


def test_block_rows_larger_than_scan_y_yields_one_block() -> None:
    cube = _make_cube(rows=3, cols=2, det_h=2, det_w=2)
    ds = _dataset(cube, block_rows=1000)
    blocks = list(ds.iter_scan_rows())
    assert len(blocks) == 1
    assert blocks[0][0] == 0
    assert blocks[0][1].shape[0] == 3


@pytest.mark.parametrize("block_rows", [0, -5])
def test_block_rows_zero_or_negative_is_sanitized_to_one(block_rows: int) -> None:
    ds = _dataset(_make_cube(rows=3, cols=2), block_rows=block_rows)
    assert ds.block_rows == 1
