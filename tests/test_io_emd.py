"""EMD reader (Data-Formats #2) — Velox + NCEM flavors, axis calibration,
energy-last reorder, 4D rejection, and registry wiring."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.emd import EMDFormatError, load_emd
from fermiviewer.io.registry import load_auto
from fixtures.miniemd import write_ncem_emd, write_velox_emd

pytestmark = pytest.mark.parser


# ── NCEM / Berkeley flavor ───────────────────────────────────────────


def test_ncem_image_with_calibrated_axes(tmp_path) -> None:
    img = np.arange(12, dtype=np.float32).reshape(3, 4)  # (y, x)
    y = (np.arange(3) * 0.5, "y", "nm")
    x = (np.arange(4) * 0.5, "x", "nm")
    fp = write_ncem_emd(tmp_path / "img.emd", img, [y, x])
    ds = load_emd(fp)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (3, 4)
    assert np.array_equal(ds.data, img)
    assert ds.metadata["emd_flavor"] == "ncem"
    assert ds.pixel_cal.units == "nm"
    assert ds.pixel_cal.scale == pytest.approx(0.5)


def test_ncem_spectrum_image_moves_energy_last(tmp_path) -> None:
    # store as (energy, y, x) → loader must reorder to (y, x, energy)
    cube = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)
    e = (np.arange(2) * 1.0 + 100.0, "energy", "eV")  # dim1 = energy
    yax = (np.arange(3) * 0.5, "y", "nm")  # dim2
    xax = (np.arange(4) * 0.5, "x", "nm")  # dim3
    fp = write_ncem_emd(tmp_path / "si.emd", cube, [e, yax, xax])
    ds = load_emd(fp)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (3, 4, 2)  # (y, x, energy)
    assert ds.energy_cal.units == "eV"
    # energy axis: index 0 → 100 eV, index 1 → 101 eV
    assert np.allclose(ds.energy_axis, [100.0, 101.0])


def test_ncem_spectrum(tmp_path) -> None:
    spec = np.arange(8, dtype=np.float32)
    fp = write_ncem_emd(
        tmp_path / "s.emd", spec, [(np.arange(8) * 2.0, "E", "eV")]
    )
    ds = load_emd(fp)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.n_channels == 8
    assert ds.energy_cal.scale == pytest.approx(2.0)


def test_ncem_4d_rejected(tmp_path) -> None:
    cube4 = np.zeros((2, 2, 3, 3), dtype=np.float32)
    dims = [
        (np.arange(2), "kx", "1/nm"),
        (np.arange(2), "ky", "1/nm"),
        (np.arange(3), "y", "nm"),
        (np.arange(3), "x", "nm"),
    ]
    fp = write_ncem_emd(tmp_path / "4d.emd", cube4, dims)
    with pytest.raises(EMDFormatError, match="4D"):
        load_emd(fp)


# ── Velox flavor ─────────────────────────────────────────────────────


def test_velox_image_first_frame_and_pixel_size(tmp_path) -> None:
    # [H, W, frames]; loader takes frame 0 and converts metres → nm
    stack = np.zeros((5, 6, 3), dtype=np.uint16)
    stack[..., 0] = 7  # frame 0 distinct
    stack[..., 1] = 9
    fp = write_velox_emd(tmp_path / "v.emd", stack, pixel_size_m=2e-10)
    ds = load_emd(fp)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (5, 6)
    assert (ds.data == 7).all()  # first frame
    assert ds.metadata["emd_flavor"] == "velox"
    assert ds.metadata["n_frames"] == 3
    # 2e-10 m → 0.2 nm
    assert ds.pixel_cal.units == "nm"
    assert ds.pixel_cal.scale == pytest.approx(0.2)
    # acquisition metadata harvested
    assert "Optics.AccelerationVoltage" in ds.metadata["image_tags"]


def test_velox_2d_image_without_frames(tmp_path) -> None:
    img = np.ones((4, 4), dtype=np.uint16)
    fp = write_velox_emd(tmp_path / "v2.emd", img)
    ds = load_emd(fp)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (4, 4)


# ── registry + error paths ───────────────────────────────────────────


def test_emd_routes_through_load_auto(tmp_path) -> None:
    img = np.arange(6, dtype=np.float32).reshape(2, 3)
    fp = write_ncem_emd(
        tmp_path / "auto.emd",
        img,
        [(np.arange(2) * 1.0, "y", "nm"), (np.arange(3) * 1.0, "x", "nm")],
    )
    ds = load_auto(fp)
    assert ds.kind is DataKind.IMAGE
    assert ds.metadata["parser"] == "emd"


def test_non_hdf5_emd_raises(tmp_path) -> None:
    bad = tmp_path / "bad.emd"
    bad.write_bytes(b"not an hdf5 file at all")
    with pytest.raises(EMDFormatError, match="not an HDF5"):
        load_emd(bad)
