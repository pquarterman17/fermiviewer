"""MRC2014 parser tests: endianness (machine stamp), MODE table, extended
header offset, and dimension guards — via a synthetic fixture (no committed
MRC corpus exercises big-endian files or these edge cases)."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.mrc import load_mrc
from fixtures.minimrc import write_mini_mrc

pytestmark = pytest.mark.parser


def _grid(ny: int, nx: int) -> np.ndarray:
    """Position-encoded (ny, nx) grid: value(y, x) = x + 10*y."""
    return np.array([[x + 10 * y for x in range(nx)] for y in range(ny)], dtype=np.uint16)


def test_little_and_big_endian_decode_identically(tmp_path) -> None:
    grid = _grid(4, 6)
    fle = write_mini_mrc(tmp_path / "le.mrc", grid, mode=6, endian="little")
    fbe = write_mini_mrc(tmp_path / "be.mrc", grid, mode=6, endian="big")

    ds_le = load_mrc(fle)
    ds_be = load_mrc(fbe)

    assert ds_le.kind is DataKind.IMAGE
    np.testing.assert_array_equal(ds_le.data, grid)
    np.testing.assert_array_equal(ds_be.data, grid)
    np.testing.assert_array_equal(ds_le.data, ds_be.data)
    assert ds_le.metadata["mrc_byte_order"] == "little"
    assert ds_be.metadata["mrc_byte_order"] == "big"


def test_unrecognized_machine_stamp_defaults_to_little_endian(tmp_path) -> None:
    grid = _grid(3, 3)
    f = write_mini_mrc(
        tmp_path / "junkstamp.mrc", grid, mode=6, endian="little", machst=b"\x00\x00\x00\x00"
    )
    ds = load_mrc(f)
    np.testing.assert_array_equal(ds.data, grid)
    assert ds.metadata["mrc_byte_order"] == "little"


def test_invalid_dims_raise(tmp_path) -> None:
    grid = _grid(2, 2)
    f_zero = write_mini_mrc(tmp_path / "zero.mrc", grid, nx=0)
    with pytest.raises(ValueError, match="invalid MRC dimensions"):
        load_mrc(f_zero)

    f_neg = write_mini_mrc(tmp_path / "neg.mrc", grid, ny=-1)
    with pytest.raises(ValueError, match="invalid MRC dimensions"):
        load_mrc(f_neg)


def test_unsupported_mode_raises(tmp_path) -> None:
    grid = _grid(2, 2)
    f = write_mini_mrc(tmp_path / "badmode.mrc", grid, mode=6, header_mode=99)
    with pytest.raises(ValueError, match="unsupported MRC MODE 99"):
        load_mrc(f)


def test_nsymbt_extended_header_offset_honored(tmp_path) -> None:
    grid = _grid(3, 5)
    f = write_mini_mrc(tmp_path / "ext.mrc", grid, mode=6, nsymbt=128)
    ds = load_mrc(f)
    np.testing.assert_array_equal(ds.data, grid)


def test_non_square_orientation(tmp_path) -> None:
    ny, nx = 3, 5
    grid = _grid(ny, nx)
    f = write_mini_mrc(tmp_path / "rect.mrc", grid, mode=6)
    ds = load_mrc(f)
    assert ds.data.shape == (ny, nx)
    assert ds.data[0, 0] == 0
    assert ds.data[2, 4] == 4 + 10 * 2
    assert ds.data[1, 3] == 3 + 10 * 1


def test_1x1(tmp_path) -> None:
    grid = np.array([[42]], dtype=np.uint16)
    f = write_mini_mrc(tmp_path / "one.mrc", grid, mode=6)
    ds = load_mrc(f)
    assert ds.data.shape == (1, 1)
    assert ds.data[0, 0] == 42


def test_float32_mode_be_and_le(tmp_path) -> None:
    # MODE 2 (float32) is common for reconstructed volumes — check both
    # endians round-trip through a non-integer dtype too.
    grid = np.array([[1.5, -2.25], [3.0, 0.125]], dtype=np.float32)
    fle = write_mini_mrc(tmp_path / "f32le.mrc", grid, mode=2, endian="little")
    fbe = write_mini_mrc(tmp_path / "f32be.mrc", grid, mode=2, endian="big")
    np.testing.assert_array_equal(load_mrc(fle).data, grid)
    np.testing.assert_array_equal(load_mrc(fbe).data, grid)
