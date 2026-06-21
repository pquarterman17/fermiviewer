"""HyperSpy .hspy reader (Data-Formats #6)."""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.hspy import HspyFormatError, load_hspy
from fermiviewer.io.registry import load_auto

pytestmark = pytest.mark.parser


def _write_hspy(path, data, axes):
    """axes: list of dicts with scale/offset/units/name/navigate (array order)."""
    with h5py.File(path, "w") as f:
        exp = f.create_group("Experiments/sig")
        exp.create_dataset("data", data=data)
        for i, a in enumerate(axes):
            g = exp.create_group(f"axis-{i}")
            for k, v in a.items():
                g.attrs[k] = v
    return path


def test_hspy_image(tmp_path) -> None:
    img = np.arange(12, dtype=np.float32).reshape(3, 4)
    fp = _write_hspy(
        tmp_path / "im.hspy",
        img,
        [
            {"scale": 0.5, "offset": 0.0, "units": "nm", "name": "y", "navigate": True},
            {"scale": 0.5, "offset": 0.0, "units": "nm", "name": "x", "navigate": True},
        ],
    )
    ds = load_hspy(fp)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (3, 4)
    assert ds.pixel_cal.units == "nm"
    assert ds.pixel_cal.scale == pytest.approx(0.5)
    assert ds.metadata["parser"] == "hspy"


def test_hspy_spectrum_image_energy_last(tmp_path) -> None:
    # array order (y, x, energy) already; energy axis flagged by units
    cube = np.arange(2 * 3 * 5, dtype=np.float32).reshape(2, 3, 5)
    fp = _write_hspy(
        tmp_path / "si.hspy",
        cube,
        [
            {"scale": 1.0, "offset": 0.0, "units": "nm", "name": "y", "navigate": True},
            {"scale": 1.0, "offset": 0.0, "units": "nm", "name": "x", "navigate": True},
            {
                "scale": 0.5,
                "offset": 100.0,
                "units": "eV",
                "name": "Energy loss",
                "navigate": False,
            },
        ],
    )
    ds = load_hspy(fp)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (2, 3, 5)
    assert ds.energy_cal.units == "eV"
    assert np.allclose(ds.energy_axis[:2], [100.0, 100.5])


def test_hspy_spectrum(tmp_path) -> None:
    fp = _write_hspy(
        tmp_path / "s.hspy",
        np.arange(6, dtype=np.float32),
        [{"scale": 2.0, "offset": 50.0, "units": "eV", "name": "E", "navigate": False}],
    )
    ds = load_hspy(fp)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.n_channels == 6
    assert ds.energy_cal.scale == pytest.approx(2.0)


def test_hspy_4d_rejected(tmp_path) -> None:
    fp = _write_hspy(
        tmp_path / "4d.hspy",
        np.zeros((2, 2, 3, 3), dtype=np.float32),
        [
            {"scale": 1.0, "offset": 0.0, "units": "", "name": f"a{i}", "navigate": i < 2}
            for i in range(4)
        ],
    )
    with pytest.raises(HspyFormatError, match="4D"):
        load_hspy(fp)


def test_hspy_routes_through_load_auto(tmp_path) -> None:
    fp = _write_hspy(
        tmp_path / "a.hspy",
        np.ones((2, 2), dtype=np.float32),
        [
            {"scale": 1.0, "offset": 0.0, "units": "nm", "name": "y", "navigate": True},
            {"scale": 1.0, "offset": 0.0, "units": "nm", "name": "x", "navigate": True},
        ],
    )
    assert load_auto(fp).metadata["parser"] == "hspy"


def test_non_hdf5_hspy_raises(tmp_path) -> None:
    bad = tmp_path / "bad.hspy"
    bad.write_bytes(b"plain text not hdf5")
    with pytest.raises(HspyFormatError, match="not an HDF5"):
        load_hspy(bad)
