"""Bruker Nanoscope AFM parser: identification, calibration, registry route."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.nanoscope import (
    NanoscopeError,
    is_nanoscope,
    load_nanoscope,
    load_nanoscope_all,
)
from fermiviewer.io.registry import UnsupportedFormatError, load_auto, supported_extensions
from fixtures.nanoscope import write_nanoscope


@pytest.fixture
def spm(tmp_path):
    p = tmp_path / "scan.spm"
    return p, write_nanoscope(p)


def test_kind_and_shape(spm):
    p, ex = spm
    ds = load_nanoscope(p)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (ex["ny"], ex["nx"])


def test_lateral_calibration(spm):
    p, ex = spm
    ds = load_nanoscope(p)
    assert ds.axes[0].units == "nm" and ds.axes[1].units == "nm"
    assert ds.axes[1].scale == pytest.approx(ex["nm_per_px"], rel=1e-6)
    assert ds.axes[0].scale == pytest.approx(ex["nm_per_px"], rel=1e-6)
    assert ds.pixel_unit == "nm"


def test_z_height_calibration(spm):
    p, ex = spm
    ds = load_nanoscope(p)
    # top-left pixel = 1 LSB → 0.1 nm; full array matches LSB × z_scale
    assert float(ds.data[0, 0]) == pytest.approx(ex["expected_top_left_nm"], rel=1e-6)
    np.testing.assert_allclose(ds.data, ex["expected_data_nm"], rtol=1e-6)


def test_row_order_flipped(spm):
    # file stores bottom-to-top; loader must flipud so [0,0] is the top-left
    p, ex = spm
    ds = load_nanoscope(p)
    assert float(ds.data[0, 0]) < float(ds.data[-1, 0])


def test_metadata(spm):
    p, ex = spm
    ds = load_nanoscope(p)
    assert ds.metadata["parser"] == "nanoscope"
    assert ds.metadata["channel"] == ex["channel"]
    assert ds.metadata["value_unit"] == ex["value_unit"]
    assert ds.metadata["z_scale_per_lsb"] == pytest.approx(ex["z_scale_nm_per_lsb"])
    assert ds.metadata["scan_size_nm"] == [100.0, 100.0]


def test_single_channel_all(spm):
    p, _ = spm
    assert len(load_nanoscope_all(p)) == 1


def test_sniffer_accepts_and_rejects(spm):
    p, _ = spm
    assert is_nanoscope(p.read_bytes())
    assert not is_nanoscope(b"II\x2a\x00rest-is-tiff")  # Park/TIFF .spm
    assert not is_nanoscope(b"random bytes here")


def test_registry_routes_spm(spm):
    p, ex = spm
    ds = load_auto(p)  # routed via content sniff, not the extension map
    assert ds.metadata["parser"] == "nanoscope"
    assert ds.data.shape == (ex["ny"], ex["nx"])
    assert ".spm" in supported_extensions()


def test_registry_routes_numeric_extension(tmp_path):
    p = tmp_path / "capture.000"
    write_nanoscope(p)
    ds = load_auto(p)
    assert ds.metadata["parser"] == "nanoscope"


def test_force_file_rejected(tmp_path):
    p = tmp_path / "force.spm"
    p.write_bytes(b"\\*Force file list\r\n\\*File list end\r\n\x1a")
    with pytest.raises(NanoscopeError, match="force"):
        load_nanoscope(p)


def test_non_nanoscope_numeric_extension(tmp_path):
    p = tmp_path / "mystery.123"
    p.write_bytes(b"not a nanoscope file at all")
    with pytest.raises(UnsupportedFormatError):
        load_auto(p)
