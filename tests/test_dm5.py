"""DM5 (GMS 3.5+ HDF5) parser tests — synthetic fixtures only.

No public DM5 sample file exists (verified 2026-08-01 — see io/dm5.py's
module docstring for the documented + ASSUMED layout this reader is built
from). No @pytest.mark.realdata test for the same reason.

No @pytest.mark.oracle test either: rosettasciio 0.14.0 (the project's dev
oracle) has no DM5 reader — its DigitalMicrograph plugin only registers the
.dm3/.dm4 extensions (verified via `rsciio.IO_PLUGINS`; no plugin in that
registry lists a "dm5" extension). Add an oracle test once rsciio gains DM5
support or a real corpus file becomes available.
"""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.dm5 import DM5FormatError, load_dm5
from fermiviewer.io.registry import load_auto
from fixtures.minidm5 import write_dm5, write_dm5_spectrum_image

pytestmark = pytest.mark.parser


# ── image ────────────────────────────────────────────────────────────

def test_dm5_image_calibration_and_orientation(tmp_path) -> None:
    w, h = 6, 4
    img = np.arange(w * h, dtype=np.uint16).reshape(h, w)  # HDF5-order (h, w)
    fp = write_dm5(
        tmp_path / "img.dm5",
        img,
        cal=[
            {"scale": 0.2, "origin": 0, "units": "nm"},  # DM dim0 = x (fastest)
            {"scale": 0.3, "origin": 1, "units": "nm"},  # DM dim1 = y
        ],
    )
    ds = load_dm5(fp)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (h, w)
    np.testing.assert_array_equal(ds.data, img)
    assert ds.pixel_size == pytest.approx(0.2)  # x/width calibration <- dim0
    assert ds.pixel_unit == "nm"
    assert ds.axes[0].scale == pytest.approx(0.3)  # y axis <- dim1
    assert ds.axes[0].origin == pytest.approx(1.0)
    assert ds.metadata["parser"] == "dm5"
    assert ds.metadata["dm_version"] == 5
    assert ds.metadata["bit_depth"] == 16


def test_dm5_spectrum(tmp_path) -> None:
    n, zlp_ch = 32, 10
    counts = np.round(1000 * np.exp(-((np.arange(n) - zlp_ch) ** 2) / 8)) + 1
    fp = write_dm5(
        tmp_path / "spec.dm5",
        counts,
        cal=[{"scale": 0.05, "origin": zlp_ch, "units": "eV"}],
    )
    ds = load_dm5(fp)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.n_channels == n
    assert ds.energy_cal.units == "eV"
    assert ds.energy_axis[int(np.argmax(ds.data))] == pytest.approx(0.0)


# ── spectrum image — position-encoded to catch axis-order bugs ────────
# (same technique as tests/test_dm_contract.py: v(x, y, e) = x + 10y + 100e,
# so a wrong transpose changes VALUES, not just the shape.)

def _encode(x: int, y: int, e: int) -> int:
    return x + 10 * y + 100 * e


def _expected_cube(nx: int, ny: int, ne: int) -> np.ndarray:
    out = np.zeros((ny, nx, ne), dtype=np.int64)
    for e in range(ne):
        for y in range(ny):
            for x in range(nx):
                out[y, x, e] = _encode(x, y, e)
    return out


def test_dm5_spectrum_image_energy_last_default(tmp_path) -> None:
    nx, ny, ne = 4, 3, 5
    cube = _expected_cube(nx, ny, ne)
    fp = write_dm5_spectrum_image(
        tmp_path / "elast.dm5",
        cube,
        y_cal={"scale": 0.5, "origin": 0, "units": "nm"},
        x_cal={"scale": 0.5, "origin": 0, "units": "nm"},
        e_cal={"scale": 0.05, "origin": 40, "units": "eV"},
        e_dm_index=2,
    )
    ds = load_dm5(fp)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (ny, nx, ne)
    np.testing.assert_array_equal(ds.data, cube)
    assert ds.energy_axis[0] == pytest.approx(-2.0)  # (0 - 40) x 0.05
    assert ds.energy_cal.units == "eV"
    assert ds.pixel_size == pytest.approx(0.5)


def test_dm5_spectrum_image_energy_first_units_detected(tmp_path) -> None:
    # Energy at DM dimension 0 (not the default-last position) — must be
    # detected via Units, not assumed by position.
    nx, ny, ne = 4, 3, 5
    cube = _expected_cube(nx, ny, ne)
    fp = write_dm5_spectrum_image(
        tmp_path / "efirst.dm5",
        cube,
        y_cal={"scale": 0.5, "origin": 0, "units": "nm"},
        x_cal={"scale": 0.5, "origin": 0, "units": "nm"},
        e_cal={"scale": 0.05, "origin": 40, "units": "eV"},
        e_dm_index=0,
    )
    ds = load_dm5(fp)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (ny, nx, ne)
    np.testing.assert_array_equal(ds.data, cube)
    assert ds.energy_axis[0] == pytest.approx(-2.0)


def test_dm5_no_energy_units_falls_back_to_last(tmp_path) -> None:
    nx, ny, ne = 4, 3, 5
    cube = _expected_cube(nx, ny, ne)
    fp = write_dm5_spectrum_image(
        tmp_path / "nounits.dm5",
        cube,
        y_cal={"scale": 0.5, "origin": 0, "units": "nm"},
        x_cal={"scale": 0.5, "origin": 0, "units": "nm"},
        e_cal={"scale": 1.0, "origin": 0, "units": ""},
        e_dm_index=2,
    )
    ds = load_dm5(fp)
    assert ds.n_channels == ne
    assert ds.data[1, 2, 3] == _encode(2, 1, 3)


# ── image selection: extras warning + boolean-mask skip ───────────────

def test_dm5_extra_images_warns_and_uses_first(tmp_path) -> None:
    a = np.arange(6, dtype=np.uint16).reshape(2, 3)
    b = np.full((2, 3), 9, dtype=np.uint16)
    fp = write_dm5(
        tmp_path / "extras.dm5",
        a,
        cal=[{"units": "nm"}, {"units": "nm"}],
        extra_images=[b],
    )
    with pytest.warns(UserWarning, match="extra images"):
        ds = load_dm5(fp)
    np.testing.assert_array_equal(ds.data, a)


def test_dm5_boolean_mask_entry_skipped(tmp_path) -> None:
    mask = np.zeros((2, 3), dtype=bool)
    real = np.arange(6, dtype=np.uint16).reshape(2, 3) + 1
    fp = write_dm5(tmp_path / "mask.dm5", mask, cal=[{"units": "nm"}, {"units": "nm"}])
    with h5py.File(fp, "a") as f:
        entry = f["ImageList"].create_group("1")
        entry.create_group("ImageData").create_dataset("Data", data=real)
    ds = load_dm5(fp)
    np.testing.assert_array_equal(ds.data, real)


def test_dm5_all_boolean_falls_back_to_largest(tmp_path) -> None:
    small_mask = np.zeros((2, 2), dtype=bool)
    big_mask = np.ones((4, 4), dtype=bool)
    fp = write_dm5(
        tmp_path / "allbool.dm5",
        small_mask,
        cal=[{"units": "nm"}, {"units": "nm"}],
        extra_images=[big_mask],
    )
    ds = load_dm5(fp)
    assert ds.data.shape == (4, 4)


# ── metadata harvest ────────────────────────────────────────────────

def test_dm5_image_tags_and_display_info(tmp_path) -> None:
    img = np.ones((2, 2), dtype=np.uint16)
    fp = write_dm5(
        tmp_path / "tags.dm5",
        img,
        cal=[{"units": "nm"}, {"units": "nm"}],
        image_tags={
            "Microscope Info": {"Voltage": 200000.0, "Name": "Titan"},
            "Session": "abc123",
        },
        brightness={"origin": 0, "scale": 2.0, "units": "counts"},
        display={"LowLimit": 0.0, "HighLimit": 4095.0, "Gamma": 1.2, "IsInverted": 1},
    )
    ds = load_dm5(fp)
    tags = ds.metadata["image_tags"]
    assert tags["Microscope Info.Voltage"] == pytest.approx(200000.0)
    assert tags["Microscope Info.Name"] == "Titan"
    assert tags["Session"] == "abc123"
    assert ds.metadata["intensity_scale"] == pytest.approx(2.0)
    assert ds.metadata["intensity_units"] == "counts"
    assert ds.metadata["display_high"] == pytest.approx(4095.0)
    assert ds.metadata["display_gamma"] == pytest.approx(1.2)
    assert ds.metadata["display_inverted"] is True


def test_dm5_no_image_tags_yields_empty_dict(tmp_path) -> None:
    img = np.ones((2, 2), dtype=np.uint16)
    fp = write_dm5(tmp_path / "notags.dm5", img, cal=[{"units": "nm"}, {"units": "nm"}])
    ds = load_dm5(fp)
    assert ds.metadata["image_tags"] == {}


# ── registry + error paths ───────────────────────────────────────────

def test_dm5_routes_through_load_auto(tmp_path) -> None:
    img = np.ones((2, 3), dtype=np.uint16)
    fp = write_dm5(tmp_path / "auto.dm5", img, cal=[{"units": "nm"}, {"units": "nm"}])
    ds = load_auto(fp)
    assert ds.kind is DataKind.IMAGE
    assert ds.metadata["parser"] == "dm5"


def test_dm5_non_hdf5_raises(tmp_path) -> None:
    bad = tmp_path / "bad.dm5"
    bad.write_bytes(b"not an hdf5 file at all")
    with pytest.raises(DM5FormatError, match="not an HDF5"):
        load_dm5(bad)


def test_dm5_missing_imagelist_raises(tmp_path) -> None:
    fp = tmp_path / "noimglist.dm5"
    with h5py.File(fp, "w") as f:
        f.create_group("SomethingElse")
    with pytest.raises(DM5FormatError, match="no /ImageList"):
        load_dm5(fp)


def test_dm5_empty_imagelist_raises(tmp_path) -> None:
    fp = tmp_path / "emptylist.dm5"
    with h5py.File(fp, "w") as f:
        f.create_group("ImageList")
    with pytest.raises(DM5FormatError, match="no usable image"):
        load_dm5(fp)


# ── degenerate 2-D spectra (mirrors dm.py) ───────────────────────────

def test_1xn_energy_axis_loads_as_a_spectrum(tmp_path) -> None:
    """DM5 keeps DM's tag names, so the same 1xN-EELS-as-an-image trap
    applies; the readers must agree. See test_dm_contract.py for the .dm4
    twin and test_dm_golden.py for the corpus file that hit it."""
    counts = np.arange(1, 17, dtype=np.uint16)
    f = write_dm5(
        tmp_path / "line.dm5",
        counts.reshape(1, 16),      # array (rows, cols) = (1, 16)
        cal=[{"scale": 0.5, "origin": -20.0, "units": "eV"},  # DM dim 0 = cols
             {"scale": 1.0, "origin": 0.0, "units": ""}],
    )
    ds = load_dm5(f)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.data.shape == (16,)
    assert ds.metadata["squeezed_from_shape"] == [1, 16]
    assert ds.energy_cal.units == "eV"
    assert ds.energy_cal.scale == pytest.approx(0.5)
    np.testing.assert_array_equal(ds.data, counts)


def test_nx1_energy_axis_loads_as_a_spectrum(tmp_path) -> None:
    counts = np.arange(1, 9, dtype=np.uint16)
    f = write_dm5(
        tmp_path / "col.dm5",
        counts.reshape(8, 1),       # array (rows, cols) = (8, 1)
        cal=[{"scale": 1.0, "origin": 0.0, "units": ""},
             {"scale": 0.25, "origin": 0.0, "units": "eV"}],  # DM dim 1 = rows
    )
    ds = load_dm5(f)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.data.shape == (8,)
    assert ds.energy_cal.scale == pytest.approx(0.25)


def test_1xn_length_axis_stays_an_image(tmp_path) -> None:
    f = write_dm5(
        tmp_path / "row.dm5",
        np.arange(1, 17, dtype=np.uint16).reshape(1, 16),
        cal=[{"scale": 0.5, "origin": 0.0, "units": "nm"},
             {"scale": 0.5, "origin": 0.0, "units": "nm"}],
    )
    ds = load_dm5(f)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (1, 16)
