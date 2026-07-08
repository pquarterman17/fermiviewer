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

pytestmark = pytest.mark.parser


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


def test_registry_unknown_extension_raises_directly(tmp_path):
    # a plain unrecognised extension hits _LOADERS.get(ext) is None directly
    # (the .xyz upload-route rejection tested elsewhere is a different layer
    # — the HTTP filter — that never reaches the registry at all)
    p = tmp_path / "mystery.xyz"
    p.write_bytes(b"whatever")
    with pytest.raises(UnsupportedFormatError, match="no parser for"):
        load_auto(p)


def test_empty_spm_falls_through_to_tiff_and_raises_tifffile_error(tmp_path):
    # .spm content-sniffs Nanoscope vs Park/JPK-TIFF; an empty file fails the
    # Nanoscope sniff (is_nanoscope needs >= 12 bytes) and falls through to
    # load_tiff, which raises tifffile's own TiffFileError rather than a
    # clean UnsupportedFormatError/ValueError. This pins today's behavior —
    # not necessarily the ideal one — so a future change is a deliberate
    # decision, not an accidental regression.
    import tifffile

    p = tmp_path / "empty.spm"
    p.write_bytes(b"")
    with pytest.raises(tifffile.TiffFileError):
        load_auto(p)


# ── header-spelling variants (legacy NanoScope III) ──────────────────


def test_lowercase_scan_size_key(tmp_path):
    # legacy files spell it `Scan size`; lookup must be case-insensitive
    p = tmp_path / "legacy.spm"
    ex = write_nanoscope(p, scan_size_key="Scan size")
    ds = load_nanoscope(p)
    assert ds.axes[1].scale == pytest.approx(ex["nm_per_px"], rel=1e-6)


def test_tilde_micron_unit(tmp_path):
    # `~m` is legacy NanoScope's 7-bit-safe spelling of µm
    p = tmp_path / "micron.spm"
    write_nanoscope(p, scan_size_value="2 2 ~m")  # 2 µm = 2000 nm over 4 px
    ds = load_nanoscope(p)
    assert ds.metadata["scan_size_nm"] == [2000.0, 2000.0]
    assert ds.axes[1].scale == pytest.approx(2000.0 / 4, rel=1e-6)


def test_single_value_square_scan_size(tmp_path):
    # legacy files often give one number for a square scan
    p = tmp_path / "square.spm"
    write_nanoscope(p, scan_size_value="500 nm")
    ds = load_nanoscope(p)
    assert ds.metadata["scan_size_nm"] == [500.0, 500.0]


# ── per-channel unit derivation (hard-scale parenthetical) ───────────


def test_channel_unit_from_hard_scale(tmp_path):
    # a non-length channel takes its unit from the `(… Arb/LSB)` hard scale,
    # not the sensitivity line (which carries a bogus placeholder unit)
    p = tmp_path / "multi.spm"
    write_nanoscope(p, extra_channel="Arb/LSB")
    chans = {c.metadata["channel"]: c for c in load_nanoscope_all(p)}
    assert chans["ZSensor"].metadata["value_unit"] == "nm"  # V/LSB → sens unit
    assert chans["Other"].metadata["value_unit"] == "Arb"  # hard-scale unit


def test_log_unit_with_nested_parens(tmp_path):
    # `log(Arb)/LSB` — the inner parens must not confuse unit extraction
    p = tmp_path / "log.spm"
    write_nanoscope(p, extra_channel="log(Arb)/LSB")
    chans = {c.metadata["channel"]: c for c in load_nanoscope_all(p)}
    assert chans["Other"].metadata["value_unit"] == "log(Arb)"


# ── robustness / error paths ─────────────────────────────────────────


def test_truncated_data_block_rejected(tmp_path):
    # a header that promises more data than the file holds must not read
    # past EOF — it should raise, like the real header-only captures
    p = tmp_path / "trunc.spm"
    write_nanoscope(p)
    p.write_bytes(p.read_bytes()[:-8])  # lop off part of the data block
    with pytest.raises(NanoscopeError, match="past end"):
        load_nanoscope(p)


def test_missing_scan_size_rejected(tmp_path):
    p = tmp_path / "noscan.spm"
    write_nanoscope(p, scan_size_value="")
    with pytest.raises(NanoscopeError, match="Scan Size"):
        load_nanoscope(p)
