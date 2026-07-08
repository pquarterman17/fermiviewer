"""BCF parser tests: SFS contract (synthetic) + golden corpus + realdata."""

from __future__ import annotations

import zlib
from pathlib import Path

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.bcf import load_bcf
from fermiviewer.io.sfs import SFSError, SfsFile, decompress_if_aacs
from fixtures.minisfs import write_mini_sfs_bcf

pytestmark = pytest.mark.parser

REL = 1e-9


# ── SFS container contract (synthetic, CI-runnable) ──────────────────

def _xml(n_chan: int, pad_bytes: int) -> bytes:
    counts = ",".join(str(v) for v in range(1, n_chan + 1))
    pad = "PADDING-" * (pad_bytes // 8)
    return (
        f'<ClassInstance Type="TRTSpectrumHeader">'
        f"<CalibAbs>-0.5</CalibAbs><CalibLin>0.01</CalibLin></ClassInstance>"
        f"<ChCount>{n_chan}</ChCount><!-- {pad} --><Channels>{counts}</Channels>"
    ).encode()


def test_multichunk_pointer_table_shuffled(tmp_path) -> None:
    # ~170 kB at 512-byte chunks → 3-chunk pointer table; the sum
    # spectrum sits at the END of the payload, in the last data chunks.
    f = write_mini_sfs_bcf(tmp_path / "multi.bcf", _xml(48, 170_000), chunk_size=512)
    ds = load_bcf(f)
    assert ds.kind is DataKind.SPECTRUM
    np.testing.assert_array_equal(ds.data, np.arange(1, 49))
    assert ds.energy_axis[0] == pytest.approx(-0.5)
    assert ds.energy_axis[1] - ds.energy_axis[0] == pytest.approx(0.01)


def test_corrupt_chain_raises_cleanly(tmp_path) -> None:
    f = write_mini_sfs_bcf(
        tmp_path / "bad.bcf", _xml(8, 170_000), chunk_size=512, break_table_at=1
    )
    with pytest.raises(SFSError, match="out of bounds"):
        load_bcf(f)


def test_non_sfs_rejected(tmp_path) -> None:
    bad = tmp_path / "no.bcf"
    bad.write_bytes(b"NotToday-not-an-sfs" * 30)
    with pytest.raises(SFSError, match="not a Bruker"):
        SfsFile(bad.read_bytes(), source=str(bad))


def test_data_chunk_out_of_bounds_raises(tmp_path) -> None:
    # distinct from test_corrupt_chain_raises_cleanly: that corrupts the
    # pointer-TABLE chain header; this corrupts a data-chunk index recorded
    # *inside* a (structurally intact) pointer table.
    f = write_mini_sfs_bcf(
        tmp_path / "baddata.bcf", _xml(48, 170_000), chunk_size=512,
        corrupt_data_ptr_at=0,
    )
    with pytest.raises(SFSError, match="data chunk .* out of bounds"):
        load_bcf(f)


def _wrap_aacs(payload: bytes) -> bytes:
    """AACS-block-compress a payload (see decompress_if_aacs): 128-byte
    header (magic + n_blocks at 12:16) then one [size(4) + pad(12) + zlib
    bytes] block."""
    comp = zlib.compress(payload)
    header = bytearray(128)
    header[0:4] = b"AACS"
    header[12:16] = (1).to_bytes(4, "little")
    block = len(comp).to_bytes(4, "little") + b"\x00" * 12 + comp
    return bytes(header) + block


def test_decompress_if_aacs_unit() -> None:
    payload = b"<xml>plain HeaderData content</xml>"
    assert decompress_if_aacs(_wrap_aacs(payload)) == payload
    assert decompress_if_aacs(payload) == payload  # passthrough (no AACS magic)


def test_aacs_compressed_header_data_loads(tmp_path) -> None:
    # current fixture (write_mini_sfs_bcf) always wrote xml_bytes uncompressed;
    # here the HeaderData *entry payload itself* is an AACS zlib block, as
    # real Esprit files sometimes store it.
    xml = _xml(8, 0)
    f = write_mini_sfs_bcf(tmp_path / "aacs.bcf", _wrap_aacs(xml), chunk_size=512)
    ds = load_bcf(f)
    assert ds.kind is DataKind.SPECTRUM
    np.testing.assert_array_equal(ds.data, np.arange(1, 9))


def test_missing_header_data_raises(tmp_path) -> None:
    f = write_mini_sfs_bcf(
        tmp_path / "noheader.bcf", _xml(4, 0), header_name="EDSDatabase/SomethingElse"
    )
    with pytest.raises(ValueError, match="no EDSDatabase/HeaderData"):
        load_bcf(f)


def test_no_image_no_spectrum_raises(tmp_path) -> None:
    # header entry exists but has neither a ChCount/Channels spectrum nor
    # any TRTImageData block — nothing plottable at all.
    f = write_mini_sfs_bcf(tmp_path / "bare.bcf", b"<Root></Root>")
    with pytest.raises(ValueError, match="no SEM image and no EDS spectrum"):
        load_bcf(f)


def test_zero_channel_cube_silently_skipped(tmp_path, monkeypatch) -> None:
    # A cube whose raw header reports height=0 (h*w*n_chan*4 == 0) is a
    # distinct skip path from the over-cap skip: no metadata["cube_skipped"]
    # message is set (nothing to report — there's no cube-shaped data at
    # all), and the header sum spectrum is used instead. Building a second
    # real SFS-internal file (EDSDatabase/SpectrumData0) would require
    # multi-entry tree support the fixture doesn't have, so this monkeypatches
    # SfsFile.find/.read for just that one path — the same technique the
    # realdata cap tests use for decode_cube.
    f = write_mini_sfs_bcf(tmp_path / "zerochan.bcf", _xml(4, 0))

    sentinel = object()
    real_find, real_read = SfsFile.find, SfsFile.read

    def fake_find(self, target):
        if target == "EDSDatabase/SpectrumData0":
            return sentinel
        return real_find(self, target)

    def fake_read(self, entry):
        if entry is sentinel:
            # raw cube header: height=0, width=5 (little-endian int32 pair)
            return (0).to_bytes(4, "little", signed=True) + (5).to_bytes(
                4, "little", signed=True
            )
        return real_read(self, entry)

    monkeypatch.setattr(SfsFile, "find", fake_find)
    monkeypatch.setattr(SfsFile, "read", fake_read)

    ds = load_bcf(f)
    assert ds.kind is DataKind.SPECTRUM
    assert "cube_skipped" not in ds.metadata
    np.testing.assert_array_equal(ds.data, np.arange(1, 5))


# ── golden corpus (committed BCF vectors in ../fermi-viewer) ─────────

@pytest.mark.golden
def test_committed_bcf_matches_matlab(golden, ml_datasets: Path) -> None:
    entries = golden("parsers_committed")["bcf"]
    assert entries, "no BCF entries in golden"

    for e in entries:
        f = ml_datasets / "BCF" / e["file"]
        if e["file"] == "Fig4b_EDSmap_Bruker.bcf" and not f.is_file():
            continue  # local-only real map — covered by the realdata test
        ds = load_bcf(f)

        has_cube = bool(e.get("cubeTotal"))
        if has_cube:
            assert ds.kind is DataKind.SPECTRUM_IMAGE, e["file"]
            assert list(ds.data.shape) == e["cubeSize"], e["file"]
            assert str(ds.data.dtype) == e["cubeClass"], e["file"]
            total = float(np.asarray(ds.data, dtype=np.float64).sum())
            assert total == pytest.approx(e["cubeTotal"], rel=REL), e["file"]
            # cube column-sum == MATLAB's (cube-superseded) sum spectrum
            assert ds.sum_spectrum().sum() == pytest.approx(
                e["sumSpectrumTotal"], rel=REL
            ), e["file"]
        else:
            assert "sum_spectrum" in ds.metadata or ds.kind is DataKind.SPECTRUM, e["file"]
            ss = (
                ds.metadata["sum_spectrum"]
                if "sum_spectrum" in ds.metadata
                else ds.data
            )
            assert float(np.sum(ss)) == pytest.approx(
                e["sumSpectrumTotal"], rel=REL
            ), e["file"]

        if isinstance(e.get("calibAbs"), (int, float)):
            assert ds.metadata["calib_abs"] == pytest.approx(e["calibAbs"], rel=1e-12)
            assert ds.metadata["calib_lin"] == pytest.approx(e["calibLin"], rel=1e-12)
        gold_elems = e["elements"][0] if e.get("elements") else []
        if gold_elems:
            assert ds.metadata["elements"] == gold_elems, e["file"]


@pytest.mark.golden
@pytest.mark.realdata
def test_real_esprit_map_default_cap_loads(
    golden, ml_datasets: Path, monkeypatch
) -> None:
    """Default 5 GB cap (parity with importBCF 5b32222) keeps the real
    512x512x4096 cube (~4.3 GB dense) — the old 1.5 GB cap silently dropped
    it, leaving a black EDS panel. We assert the *cap decision* (load vs
    skip) without paying for the full pure-Python decode here; decoder
    correctness on real data is covered by the small-cube golden corpus."""
    f = ml_datasets / "BCF" / "Fig4b_EDSmap_Bruker.bcf"
    if not f.is_file():
        pytest.skip("real Esprit map absent — run fetch script")

    sentinel = np.zeros((2, 2, 4096), dtype=np.uint16)
    monkeypatch.setattr("fermiviewer.io.bcf.decode_cube", lambda *a, **k: sentinel)

    ds = load_bcf(f)  # default cap -> 4.3 GB est <= 5 GB -> load branch
    assert "cube_skipped" not in ds.metadata
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data is sentinel


@pytest.mark.golden
@pytest.mark.realdata
def test_real_esprit_map_small_cap_skips(golden, ml_datasets: Path) -> None:
    """Explicit small-cap guard: the size guard still skips the dense cube
    and falls back cleanly to the SEM survey image + header sum spectrum."""
    f = ml_datasets / "BCF" / "Fig4b_EDSmap_Bruker.bcf"
    if not f.is_file():
        pytest.skip("real Esprit map absent — run fetch script")

    ds = load_bcf(f, max_cube_bytes=1e8)  # 4.3 GB est > cap -> skip
    assert "cube_skipped" in ds.metadata
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (512, 512)
    assert ds.metadata["n_channels"] == 4096
    # the embedded header spectrum is truncated (2048 of 4096 channels);
    # the energy axis matches its length — same behaviour as MATLAB's
    # extractEDSData min() truncation
    assert len(ds.metadata["energy_axis"]) == len(ds.metadata["sum_spectrum"])
    assert ds.metadata["energy_axis"][0] == pytest.approx(ds.metadata["calib_abs"])
