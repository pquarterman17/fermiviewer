"""Shared HDF5 helpers (Data-Formats #1) — the walker, attr decoding,
largest-dataset picker, and the offset/scale → AxisCal conversion."""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from fermiviewer.io.hdf5_common import (
    HDF5_MAGIC,
    attr_float,
    attr_str,
    axiscal_from_offset_scale,
    is_hdf5,
    iter_datasets,
    largest_dataset,
)

pytestmark = pytest.mark.parser


def test_is_hdf5_recognizes_signature() -> None:
    assert is_hdf5(HDF5_MAGIC)
    assert is_hdf5(HDF5_MAGIC + b"more bytes")
    assert not is_hdf5(b"II*\x00")  # TIFF
    assert not is_hdf5(b"")


def test_iter_datasets_walks_nested_groups(tmp_path) -> None:
    fp = tmp_path / "tree.h5"
    with h5py.File(fp, "w") as f:
        f.create_dataset("top", data=np.zeros((2, 2)))
        g = f.create_group("group/sub")
        g.create_dataset("inner", data=np.ones((3,)))
    with h5py.File(fp, "r") as f:
        # dataset handles are only valid while the file is open — read shapes here
        shapes = {path: ds.shape for path, ds in iter_datasets(f)}
    assert set(shapes) == {"/top", "/group/sub/inner"}
    assert shapes["/top"] == (2, 2)
    assert shapes["/group/sub/inner"] == (3,)


def test_largest_dataset_picks_biggest_numeric_in_ndim_range(tmp_path) -> None:
    fp = tmp_path / "pick.h5"
    with h5py.File(fp, "w") as f:
        f.create_dataset("small", data=np.zeros((4, 4)))
        f.create_dataset("big", data=np.zeros((32, 32)))
        f.create_dataset("huge4d", data=np.zeros((8, 8, 8, 8)))  # ndim 4, excluded
        f.create_dataset("text", data=np.array([b"a", b"b"]))  # non-numeric
    with h5py.File(fp, "r") as f:
        path, ds = largest_dataset(f, min_ndim=1, max_ndim=3)
        shape = ds.shape  # read while the file is open
    assert path == "/big"  # huge4d is out of ndim range; text is non-numeric
    assert shape == (32, 32)


def test_largest_dataset_none_when_nothing_qualifies(tmp_path) -> None:
    fp = tmp_path / "empty.h5"
    with h5py.File(fp, "w") as f:
        f.create_dataset("only4d", data=np.zeros((2, 2, 2, 2)))
    with h5py.File(fp, "r") as f:
        assert largest_dataset(f, max_ndim=3) is None


def test_attr_decoding(tmp_path) -> None:
    fp = tmp_path / "attrs.h5"
    with h5py.File(fp, "w") as f:
        d = f.create_dataset("d", data=np.zeros(2))
        d.attrs["units"] = "nm"  # str
        d.attrs["units_b"] = np.bytes_(b"eV")  # bytes
        d.attrs["scale"] = 0.25
        d.attrs["scale_arr"] = np.array([1.5])  # 1-elem array → scalar
    with h5py.File(fp, "r") as f:
        d = f["d"]
        assert attr_str(d, "units") == "nm"
        assert attr_str(d, "units_b") == "eV"
        assert attr_str(d, "missing", "fallback") == "fallback"
        assert attr_float(d, "scale") == 0.25
        assert attr_float(d, "scale_arr") == 1.5
        assert np.isnan(attr_float(d, "missing"))


def test_axiscal_from_offset_scale_converts_convention() -> None:
    # HDF5 value = index*scale + offset  →  (index − origin)*scale, origin=−off/scale
    cal = axiscal_from_offset_scale(offset=100.0, scale=0.5, units="eV")
    assert cal.scale == 0.5
    assert cal.origin == -200.0  # −100/0.5
    assert cal.units == "eV"
    # index 0 → 100 eV, index 2 → 101 eV
    assert np.allclose(cal.axis(3), [100.0, 100.5, 101.0])


def test_axiscal_zero_scale_is_uncalibrated() -> None:
    cal = axiscal_from_offset_scale(offset=5.0, scale=0.0, units="nm")
    assert not cal.calibrated
    assert np.allclose(cal.axis(3), [0, 1, 2])  # falls back to indices
