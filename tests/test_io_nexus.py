"""NeXus + generic-HDF5 reader and the shared-HDF5 dispatch hub
(Data-Formats #5)."""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.nexus import NexusFormatError, load_hdf5_auto, load_nexus
from fermiviewer.io.registry import load_auto
from fixtures.miniemd import write_ncem_emd

pytestmark = pytest.mark.parser


def _write_nxdata(path, signal, axes):
    """axes: list of (name, values, units); '.' means no axis dataset."""
    with h5py.File(path, "w") as f:
        f.attrs["default"] = "entry"
        entry = f.create_group("entry")
        entry.attrs["NX_class"] = "NXentry"
        entry.attrs["default"] = "data"
        data = entry.create_group("data")
        data.attrs["NX_class"] = "NXdata"
        data.attrs["signal"] = "sig"
        data.attrs["axes"] = [a[0] for a in axes]
        data.create_dataset("sig", data=signal)
        for name, vals, units in axes:
            if name == ".":
                continue
            d = data.create_dataset(name, data=np.asarray(vals))
            d.attrs["units"] = units
    return path


def test_nexus_image_with_axes(tmp_path) -> None:
    img = np.arange(12, dtype=np.float32).reshape(3, 4)
    fp = _write_nxdata(
        tmp_path / "im.nxs",
        img,
        [("y", np.arange(3) * 0.5, "nm"), ("x", np.arange(4) * 0.5, "nm")],
    )
    ds = load_nexus(fp)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (3, 4)
    assert ds.pixel_cal.units == "nm"
    assert ds.pixel_cal.scale == pytest.approx(0.5)
    assert ds.metadata["nexus_signal"] == "sig"


def test_nexus_spectrum_image_energy_last(tmp_path) -> None:
    cube = np.arange(2 * 3 * 5, dtype=np.float32).reshape(2, 3, 5)
    fp = _write_nxdata(
        tmp_path / "si.nxs",
        cube,
        [
            ("y", np.arange(2) * 1.0, "nm"),
            ("x", np.arange(3) * 1.0, "nm"),
            ("E", np.arange(5) * 0.5 + 100.0, "eV"),
        ],
    )
    ds = load_nexus(fp)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (2, 3, 5)
    assert ds.energy_cal.units == "eV"
    assert np.allclose(ds.energy_axis[:2], [100.0, 100.5])


def test_generic_hdf5_fallback_uncalibrated(tmp_path) -> None:
    fp = tmp_path / "plain.h5"
    with h5py.File(fp, "w") as f:
        f.create_dataset("random/blob", data=np.ones((6, 7), dtype=np.float32))
        f.create_dataset("tiny", data=np.zeros((2,)))
    ds = load_nexus(fp)  # no NeXus markers → largest dataset
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (6, 7)
    assert ds.metadata["calibration"] == "none"
    assert ds.metadata["dataset_path"] == "/random/blob"


def test_hub_routes_emd_under_shared_extension(tmp_path) -> None:
    # an EMD payload written with a generic .h5 extension must still route to EMD
    img = np.arange(6, dtype=np.float32).reshape(2, 3)
    fp = write_ncem_emd(
        tmp_path / "secret.h5",
        img,
        [(np.arange(2) * 1.0, "y", "nm"), (np.arange(3) * 1.0, "x", "nm")],
    )
    ds = load_hdf5_auto(fp)
    assert ds.metadata["parser"] == "emd"
    # and through the registry
    assert load_auto(fp).metadata["parser"] == "emd"


def test_nxs_routes_through_load_auto(tmp_path) -> None:
    fp = _write_nxdata(
        tmp_path / "a.nxs",
        np.ones((4, 4), dtype=np.float32),
        [("y", np.arange(4) * 1.0, "nm"), ("x", np.arange(4) * 1.0, "nm")],
    )
    assert load_auto(fp).metadata["parser"] == "nexus"


def test_non_hdf5_raises(tmp_path) -> None:
    bad = tmp_path / "bad.h5"
    bad.write_bytes(b"not hdf5")
    with pytest.raises(NexusFormatError, match="not an HDF5"):
        load_hdf5_auto(bad)


def test_load_nexus_non_hdf5_raises(tmp_path) -> None:
    # load_nexus has its own not-HDF5 guard, distinct from load_hdf5_auto's
    bad = tmp_path / "bad.nxs"
    bad.write_bytes(b"not hdf5 content")
    with pytest.raises(NexusFormatError, match="not an HDF5/NeXus"):
        load_nexus(bad)


def test_no_plottable_dataset_raises(tmp_path) -> None:
    fp = tmp_path / "novalid.h5"
    with h5py.File(fp, "w") as f:
        f.create_dataset("scalar", data=5)                       # 0-d
        f.create_dataset("text", data=b"hello")                   # non-numeric
        f.create_dataset("toobig", data=np.zeros((2, 2, 2, 2), dtype=np.float32))  # 4-D
    with pytest.raises(NexusFormatError, match="no plottable"):
        load_nexus(fp)


def test_nxdata_4d_signal_raises(tmp_path) -> None:
    sig = np.zeros((2, 2, 2, 2), dtype=np.float32)
    fp = _write_nxdata(
        tmp_path / "4d.nxs",
        sig,
        [(n, np.arange(2), "") for n in ("a", "b", "c", "d")],
    )
    with pytest.raises(NexusFormatError, match="4D"):
        load_nexus(fp)


def test_axes_dot_placeholder_normalizes(tmp_path) -> None:
    # NeXus uses "." in @axes to mean "no axis dataset for this dimension"
    img = np.arange(12, dtype=np.float32).reshape(3, 4)
    fp = _write_nxdata(
        tmp_path / "dotaxis.nxs",
        img,
        [(".", None, ""), ("x", np.arange(4) * 0.5, "nm")],
    )
    ds = load_nexus(fp)
    assert ds.kind is DataKind.IMAGE
    assert ds.axes[0].units == ""
    assert ds.axes[0].scale == pytest.approx(1.0)
    assert ds.axes[1].units == "nm"
    assert ds.axes[1].scale == pytest.approx(0.5)
