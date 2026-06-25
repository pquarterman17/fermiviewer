"""BCF parser tests: SFS contract (synthetic) + golden corpus + realdata."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.bcf import load_bcf
from fermiviewer.io.sfs import SFSError, SfsFile
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
