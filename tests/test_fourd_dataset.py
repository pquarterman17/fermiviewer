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
