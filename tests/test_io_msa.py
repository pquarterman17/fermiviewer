"""EMSA/MAS .msa spectrum reader (Data-Formats #7)."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.msa import MSAFormatError, load_msa
from fermiviewer.io.registry import load_auto

pytestmark = pytest.mark.parser

_Y_ONLY = """#FORMAT      : EMSA/MAS Spectral Data File
#VERSION     : 1.0
#TITLE       : test spectrum
#NPOINTS     : 5
#XUNITS      : eV
#YUNITS      : counts
#XPERCHAN    : 10.0
#OFFSET      : 100.0
#DATATYPE    : Y
#SPECTRUM    :
12.0
15.0
9.0, 7.0, 4.0
#ENDOFDATA   :
"""

_XY = """#FORMAT   : EMSA/MAS Spectral Data File
#TITLE    : xy spectrum
#XUNITS   : eV
#DATATYPE : XY
#SPECTRUM :
200.0, 3.0
205.0, 8.0
210.0, 5.0
#ENDOFDATA
"""


def test_y_only_spectrum_with_calibration(tmp_path) -> None:
    fp = tmp_path / "s.msa"
    fp.write_text(_Y_ONLY)
    ds = load_msa(fp)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.n_channels == 5
    assert np.array_equal(ds.data, [12, 15, 9, 7, 4])  # multi-value rows flatten
    # x = OFFSET + index*XPERCHAN → 100, 110, 120 ...
    assert ds.energy_cal.units == "eV"
    assert np.allclose(ds.energy_axis[:3], [100.0, 110.0, 120.0])
    assert ds.metadata["parser"] == "msa"
    assert ds.metadata["msa_title"] == "test spectrum"


def test_xy_derives_scale_from_x_column(tmp_path) -> None:
    fp = tmp_path / "xy.msa"
    fp.write_text(_XY)
    ds = load_msa(fp)
    assert ds.kind is DataKind.SPECTRUM
    assert np.array_equal(ds.data, [3, 8, 5])  # the Y column
    # derived: scale = 205-200 = 5, offset 200 → 200, 205, 210
    assert ds.energy_cal.scale == pytest.approx(5.0)
    assert np.allclose(ds.energy_axis, [200.0, 205.0, 210.0])


def test_routes_through_load_auto(tmp_path) -> None:
    fp = tmp_path / "auto.msa"
    fp.write_text(_Y_ONLY)
    ds = load_auto(fp)
    assert ds.kind is DataKind.SPECTRUM


def test_empty_and_non_emsa_raise(tmp_path) -> None:
    bad = tmp_path / "bad.msa"
    bad.write_text("just some text with no header markers")
    with pytest.raises(MSAFormatError):
        load_msa(bad)

    nodata = tmp_path / "nodata.msa"
    nodata.write_text("#FORMAT : EMSA/MAS Spectral Data File\n#SPECTRUM :\n")
    with pytest.raises(MSAFormatError, match="no spectrum data"):
        load_msa(nodata)
