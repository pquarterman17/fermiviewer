"""Synthetic-fixture tests for the SER 0x4120 (1-D spectrum) path.

CI-runnable coverage of the enhancement validated against real TIA files in
test_em_examples.py — no corpus needed.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.ser import load_ser
from fixtures.ser import write_ser_spectra

pytestmark = pytest.mark.parser


def test_single_spectrum(tmp_path):
    p = tmp_path / "one.ser"
    ex = write_ser_spectra(p, scan_dims=[], n_channels=8)
    ds = load_ser(p)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.data.shape == (8,)
    assert int(np.asarray(ds.data, float).sum()) == ex["total"]


def test_line_profile(tmp_path):
    p = tmp_path / "line.ser"
    ex = write_ser_spectra(p, scan_dims=[5], n_channels=4)
    ds = load_ser(p)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (1, 5, 4)  # line profile → (1, N, energy)
    assert int(np.asarray(ds.data, float).sum()) == ex["total"]


def test_spectrum_image(tmp_path):
    p = tmp_path / "si.ser"
    ex = write_ser_spectra(p, scan_dims=[2, 3], n_channels=4)
    ds = load_ser(p)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (2, 3, 4)
    assert int(np.asarray(ds.data, float).sum()) == ex["total"]


def test_energy_calibration(tmp_path):
    p = tmp_path / "cal.ser"
    ex = write_ser_spectra(
        p, scan_dims=[3], n_channels=6, cal_offset=-20.0, cal_delta=0.2, cal_element=0
    )
    ds = load_ser(p)
    assert ds.energy_cal.units == "eV"
    assert ds.energy_cal.scale == pytest.approx(0.2, rel=1e-9)
    # value at channel 0 must equal the SER calibration offset
    assert ds.energy_axis[0] == pytest.approx(ex["energy0"], abs=1e-9)
    assert ds.energy_axis[0] == pytest.approx(-20.0, abs=1e-9)


def test_spectrum_image_arrangement(tmp_path):
    # element k, channel c holds k*100+c → verify the (ny, nx, E) placement
    p = tmp_path / "arrange.ser"
    write_ser_spectra(p, scan_dims=[2, 3], n_channels=4)
    ds = load_ser(p)
    cube = np.asarray(ds.data)
    # element index = iy*nx + ix; channel 0 of each element is k*100
    assert cube[0, 0, 0] == 0        # element 0
    assert cube[0, 1, 0] == 100      # element 1
    assert cube[1, 0, 0] == 300      # element 3 = row 1, col 0
    assert cube[1, 2, 1] == 501      # element 5, channel 1


def test_wide_offset_version(tmp_path):
    # version >= 0x0220 → 8-byte offset-array entries instead of 4-byte
    p = tmp_path / "wide.ser"
    ex = write_ser_spectra(p, scan_dims=[2, 3], n_channels=4, version=0x0220)
    ds = load_ser(p)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (2, 3, 4)
    assert int(np.asarray(ds.data, float).sum()) == ex["total"]


def test_truncated_spectrum_zero_pads(tmp_path):
    p = tmp_path / "full.ser"
    write_ser_spectra(p, scan_dims=[], n_channels=100)
    raw = p.read_bytes()
    short = tmp_path / "short.ser"
    short.write_bytes(raw[:-40])  # cut off the last ~10 uint32 channels
    with pytest.warns(UserWarning, match="zero-padding"):
        ds = load_ser(short)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.data.shape == (100,)
    assert ds.data[50] == 50    # untouched
    assert ds.data[99] == 0     # chopped off → zero-padded


def test_zero_length_spectrum_raises(tmp_path):
    p = tmp_path / "zerolen.ser"
    write_ser_spectra(p, scan_dims=[], n_channels=0)
    with pytest.raises(ValueError, match="invalid SER spectrum length"):
        load_ser(p)


def test_no_valid_elements_raises(tmp_path):
    p = tmp_path / "novalid.ser"
    write_ser_spectra(p, scan_dims=[], n_channels=4, valid_elements=0)
    with pytest.raises(ValueError, match="no valid data elements"):
        load_ser(p)


def test_unknown_channel_dtype_raises(tmp_path):
    p = tmp_path / "baddtype.ser"
    write_ser_spectra(p, scan_dims=[], n_channels=4, channel_dtype_code=99)
    with pytest.raises(ValueError, match="unsupported SER DataType 99"):
        load_ser(p)


def test_wrong_magic_raises(tmp_path):
    # >= 30 bytes so it clears the length guard and reaches the magic check
    p = tmp_path / "badmagic.ser"
    p.write_bytes(b"NOTASERFILEATALL" + b"\x00" * 20)
    with pytest.raises(ValueError, match="not a TIA SER"):
        load_ser(p)


def test_unknown_data_type_id_raises(tmp_path):
    p = tmp_path / "unknowntype.ser"
    write_ser_spectra(p, scan_dims=[], n_channels=4)
    raw = bytearray(p.read_bytes())
    raw[6:10] = struct.pack("<I", 0x9999)  # DataTypeID field
    p.write_bytes(bytes(raw))
    with pytest.raises(ValueError, match="unsupported SER DataTypeID"):
        load_ser(p)
