"""JEOL Analysis Station parser tests: synthetic fixtures + realdata + oracle.

See ``fermiviewer/io/jeol.py``'s module docstring for the format derivation
and the license policy around the rosettasciio oracle.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.jeol import JeolFormatError, load_jeol_img, load_jeol_map, load_jeol_pts
from fixtures.minijeol import write_mini_jeol_img, write_mini_jeol_pts

pytestmark = pytest.mark.parser


# ── synthetic fixtures (CI-runnable, no real corpus needed) ──────────

def test_synthetic_img_roundtrip(tmp_path: Path) -> None:
    pixels = np.arange(64, dtype=np.uint8).reshape(8, 8)
    f = write_mini_jeol_img(tmp_path / "mini.img", pixels, scan_size_um=80.0, mag=10000)
    ds = load_jeol_img(f)

    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (8, 8)
    np.testing.assert_array_equal(ds.data, pixels)
    # scale = ScanSize / (width * 40) — see module docstring
    assert ds.pixel_size == pytest.approx(80.0 / (8 * 40))
    assert ds.pixel_unit == "um"
    assert ds.metadata["parser"] == "jeol"
    assert ds.metadata["jeol_subtype"] == "img"
    assert ds.metadata["beam_kv"] == pytest.approx(200.0)
    assert ds.metadata["magnification"] == 10000


def test_synthetic_map_element_metadata(tmp_path: Path) -> None:
    pixels = np.zeros((4, 4), dtype=np.uint8)
    pixels[1, 2] = 9
    f = write_mini_jeol_img(
        tmp_path / "mini.map", pixels, filetype="JED-2200:MAP2", map_element="Fe K"
    )
    ds = load_jeol_map(f)

    assert ds.kind is DataKind.IMAGE
    assert int(ds.data.sum()) == 9
    assert ds.metadata["jeol_subtype"] == "map"
    assert ds.metadata["map_element"] == "Fe K"
    assert ds.metadata["map_type"] == 2


def test_wrong_magic_raises_friendly_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.img"
    bad.write_bytes(b"not a jeol file" * 8)
    with pytest.raises(JeolFormatError, match="not a JEOL"):
        load_jeol_img(bad)


def _pts_word(kind: str, value: int) -> bytes:
    nibble = {"y": 0x9, "x": 0x8, "hit": 0xB}[kind]
    return struct.pack("<H", (nibble << 12) | (value & 0x0FFF))


def test_synthetic_pts_roundtrip(tmp_path: Path) -> None:
    # (y=0,x=0): two hits at channel 5; (y=0,x=2): one hit at channel 10;
    # (y=3,x=1): one hit at channel 4000.
    events = (
        _pts_word("y", 0 << 3)
        + _pts_word("x", 0 << 3)
        + _pts_word("hit", 5)
        + _pts_word("hit", 5)
        + _pts_word("x", 2 << 3)
        + _pts_word("hit", 10)
        + _pts_word("y", 3 << 3)
        + _pts_word("x", 1 << 3)
        + _pts_word("hit", 4000)
    )
    f = write_mini_jeol_pts(
        tmp_path / "mini.pts", events, width=4, height=4, coef_a=0.01, coef_b=-0.001,
        scan_size_um=40.0,
    )
    ds = load_jeol_pts(f)

    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (4, 4, 4096)
    assert int(ds.data.sum()) == 4
    assert int(ds.data[0, 0, 5]) == 2
    assert int(ds.data[0, 2, 10]) == 1
    assert int(ds.data[3, 1, 4000]) == 1
    assert ds.metadata["n_hits"] == 4

    # energy(cube_index) = CoefA * (cube_index - 96) + CoefB
    assert ds.energy_cal.scale == pytest.approx(0.01)
    axis = ds.energy_cal.axis(4096)
    assert axis[0] == pytest.approx(0.01 * (0 - 96) + (-0.001))

    assert ds.pixel_size == pytest.approx(40.0 / (4 * 40))
    assert ds.pixel_unit == "um"


def test_pts_declared_size_past_eof_raises_friendly_error(tmp_path: Path) -> None:
    events = _pts_word("y", 0) + _pts_word("x", 0) + _pts_word("hit", 1)
    f = write_mini_jeol_pts(tmp_path / "trunc.pts", events, width=2, height=2)

    # Simulate an interrupted acquisition: header still promises more event
    # bytes than the file actually contains (see InvalidFrame in the real
    # corpus — a measurement cut off mid-sweep).
    buf = bytearray(f.read_bytes())
    declared = struct.unpack_from("<I", buf, 32)[0]
    struct.pack_into("<I", buf, 32, declared + 1000)
    f.write_bytes(bytes(buf))

    with pytest.raises(JeolFormatError, match="truncated"):
        load_jeol_pts(f)


def test_pts_wrong_magic_raises_friendly_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pts"
    bad.write_bytes(b"not a jeol pts file" * 4)
    with pytest.raises(JeolFormatError, match="not a JEOL"):
        load_jeol_pts(bad)


# ── realdata (../test-data/jeol/eds/rosettasciio; skips when absent) ─

@pytest.mark.realdata
def test_real_img_pinned(jeol_examples: Path) -> None:
    f = jeol_examples / "Sample" / "00_View000" / "View000_0000000.img"
    ds = load_jeol_img(f)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (512, 512)
    assert int(ds.data.astype(np.int64).sum()) == 137518
    assert ds.pixel_size == pytest.approx(0.00869140625)
    assert ds.pixel_unit == "um"
    assert ds.metadata["instrument_name"] == "JEM-2100F(UHR)"
    assert ds.metadata["beam_kv"] == pytest.approx(200.0)
    assert ds.metadata["magnification"] == 40000


@pytest.mark.realdata
def test_real_map_pinned(jeol_examples: Path) -> None:
    f = jeol_examples / "Sample" / "00_View000" / "View000_0000001.map"
    ds = load_jeol_map(f)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (512, 512)
    assert int(ds.data.astype(np.int64).sum()) == 62728
    assert ds.metadata["map_element"] == "C K"
    assert ds.metadata["sweep_count"] == 14


@pytest.mark.realdata
def test_real_pts_pinned(jeol_examples: Path) -> None:
    f = jeol_examples / "Sample" / "00_View000" / "View000_0000006.pts"
    ds = load_jeol_pts(f)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (512, 512, 4096)
    assert int(ds.data.astype(np.int64).sum()) == 308261
    assert ds.energy_cal.scale == pytest.approx(0.00999866)
    axis = ds.energy_cal.axis(4096)
    assert axis[0] == pytest.approx(-0.9606613249999999, rel=1e-6)
    assert ds.pixel_size == pytest.approx(0.00869140625)
    assert ds.metadata["sweep_count"] == 14


@pytest.mark.realdata
def test_real_invalid_frame_pts_raises_friendly_error(jeol_examples: Path) -> None:
    base = jeol_examples / "InvalidFrame" / "Sample" / "00_Dummy-Data"
    f = base / "Dummy-Data_0000007.pts"
    if not f.is_file():
        pytest.skip("InvalidFrame corpus absent")
    with pytest.raises(JeolFormatError, match="truncated"):
        load_jeol_pts(f)


@pytest.mark.realdata
def test_real_invalid_frame_img_still_loads(jeol_examples: Path) -> None:
    # Only the interrupted .pts stream is truncated; the accompanying
    # survey image for the same acquisition is complete.
    base = jeol_examples / "InvalidFrame" / "Sample" / "00_Dummy-Data"
    f = base / "Dummy-Data_0000000.img"
    if not f.is_file():
        pytest.skip("InvalidFrame corpus absent")
    ds = load_jeol_img(f)
    assert ds.data.shape == (256, 256)
    assert int(ds.data.astype(np.int64).sum()) == 4253953


# ── oracle cross-check (rosettasciio, dev-only; module-scoped narrow import) ─

@pytest.mark.oracle
@pytest.mark.realdata
def test_real_corpus_matches_rsciio_oracle(jeol_examples: Path) -> None:
    pytest.importorskip("rsciio", reason="oracle group not installed")
    from rsciio.jeol import file_reader  # noqa: PLC0415 — oracle-only import

    view = jeol_examples / "Sample" / "00_View000"
    compared = 0
    for fn, our_loader in (
        ("View000_0000000.img", load_jeol_img),
        ("View000_0000001.map", load_jeol_map),
    ):
        f = view / fn
        ours = our_loader(f)
        theirs = file_reader(str(f))[0]
        assert list(ours.data.shape) == list(theirs["data"].shape), fn
        assert int(ours.data.astype(np.int64).sum()) == int(
            np.asarray(theirs["data"], dtype=np.int64).sum()
        ), fn
        compared += 1

    pts_f = view / "View000_0000006.pts"
    try:
        theirs_pts = file_reader(str(pts_f))[0]
    except ModuleNotFoundError:
        pytest.skip("rsciio's .pts reader needs numba (not in the dev/oracle group)")
    ours_pts = load_jeol_pts(pts_f)
    assert list(ours_pts.data.shape) == list(theirs_pts["data"].shape)
    theirs_arr = np.asarray(theirs_pts["data"])
    # Byte-for-byte match, not just totals — see jeol_pts.py's docstring.
    assert np.array_equal(
        ours_pts.data.astype(np.int64), theirs_arr.astype(np.int64)
    ), "cube mismatch vs rsciio oracle"
    compared += 1

    assert compared == 3, f"expected 3 oracle comparisons, made {compared}"
