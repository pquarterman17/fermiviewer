"""Synthetic-fixture tests for the SER 0x4120 (1-D spectrum) path.

CI-runnable coverage of the enhancement validated against real TIA files in
test_em_examples.py — no corpus needed.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.ser import load_ser
from fixtures.ser import write_ser_spectra


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
