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


# ── calibration: CELLA / MX, per MRC2014 ─────────────────────────────

def test_pixel_size_divides_cella_by_grid_sampling(tmp_path) -> None:
    """MRC2014 divides the cell length by MX, the grid sampling — not by NX,
    the image width. A map that does not cover exactly one cell (a cropped
    sub-volume) has MX != NX, and dividing by NX is then wrong by the crop
    factor. rosettasciio uses `Xlen / MX` for the same reason."""
    grid = np.arange(64, dtype=np.uint16).reshape(8, 8)
    f = write_mini_mrc(tmp_path / "cropped.mrc", grid, mode=6,
                       cella_x=32.0, mxyz=(16, 16, 1))
    ds = load_mrc(f)
    assert ds.pixel_unit == "A"
    assert ds.pixel_size == pytest.approx(2.0)   # 32 / MX(16), NOT 32 / NX(8)


def test_pixel_size_falls_back_to_nx_when_grid_sampling_absent(tmp_path) -> None:
    """Plain microscopy writers leave MX at 0; NX is then the only divisor."""
    grid = np.arange(64, dtype=np.uint16).reshape(8, 8)
    f = write_mini_mrc(tmp_path / "nomx.mrc", grid, mode=6, cella_x=32.0)
    ds = load_mrc(f)
    assert ds.pixel_size == pytest.approx(4.0)   # 32 / NX(8)


def test_pixel_size_per_axis(tmp_path) -> None:
    """CELLA_Y/MY calibrates the row axis independently of the column axis."""
    grid = np.arange(32, dtype=np.uint16).reshape(4, 8)   # ny=4, nx=8
    f = write_mini_mrc(tmp_path / "rect.mrc", grid, mode=6,
                       cella_x=16.0, cella_y=40.0, mxyz=(8, 4, 1))
    ds = load_mrc(f)
    assert ds.axes[1].scale == pytest.approx(2.0)   # x: 16 / 8
    assert ds.axes[0].scale == pytest.approx(10.0)  # y: 40 / 4


def test_missing_cella_y_assumes_square_pixels(tmp_path) -> None:
    """CELLA_Y is routinely left at 0; square pixels beat a half-calibration."""
    grid = np.arange(64, dtype=np.uint16).reshape(8, 8)
    f = write_mini_mrc(tmp_path / "sq.mrc", grid, mode=6, cella_x=32.0)
    ds = load_mrc(f)
    assert ds.axes[0].scale == pytest.approx(ds.axes[1].scale)
    assert ds.axes[0].units == "A"


def test_uncalibrated_when_cella_is_zero(tmp_path) -> None:
    grid = np.arange(64, dtype=np.uint16).reshape(8, 8)
    ds = load_mrc(write_mini_mrc(tmp_path / "nocal.mrc", grid, mode=6))
    assert not ds.axes[0].calibrated and not ds.axes[1].calibrated
