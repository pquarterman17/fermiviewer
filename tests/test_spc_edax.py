"""EDAX .spc EDS-spectrum reader (Data-Formats #7 remainder)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.registry import load_auto
from fermiviewer.io.spc_edax import SpcFormatError, is_edax_spc, load_spc_edax
from fixtures.minispc import write_mini_spc_edax

pytestmark = pytest.mark.parser


def test_synthetic_header_round_trips(tmp_path: Path) -> None:
    counts = [0, 1, 2, 3, 40, 500, 12]
    fp = write_mini_spc_edax(
        tmp_path / "s.spc",
        counts,
        version=0.70,
        ev_per_chan=10,
        start_energy=0.0,
        live_time=12.5,
        kv=20.0,
        det_reso=130.0,
        elevation=35.0,
        azimuth=0.0,
        tilt=0.0,
        n_elem=2,
    )
    ds = load_spc_edax(fp)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.n_channels == len(counts)
    assert np.array_equal(ds.data, counts)
    assert ds.metadata["parser"] == "spc_edax"
    assert ds.metadata["spc_version"] == pytest.approx(0.70, abs=1e-4)
    assert ds.metadata["live_time_s"] == pytest.approx(12.5, abs=1e-4)
    assert ds.metadata["beam_kv"] == pytest.approx(20.0)
    assert ds.metadata["n_elements"] == 2
    # 10 eV/channel = 0.01 keV/channel, starting at 0 keV
    assert ds.energy_cal.units == "keV"
    assert ds.energy_cal.scale == pytest.approx(0.01)
    assert np.allclose(ds.energy_axis[:3], [0.0, 0.01, 0.02])


def test_nonzero_start_energy_offsets_axis(tmp_path: Path) -> None:
    fp = write_mini_spc_edax(
        tmp_path / "offset.spc", [5, 6, 7, 8], ev_per_chan=20, start_energy=1.0
    )
    ds = load_spc_edax(fp)
    assert ds.energy_axis[0] == pytest.approx(1.0)
    assert ds.energy_cal.scale == pytest.approx(0.02)
    assert np.allclose(ds.energy_axis, [1.0, 1.02, 1.04, 1.06])


def test_all_zero_counts_load(tmp_path: Path) -> None:
    # all-zero counts must NOT be treated as "no data" (falsy-value trap)
    fp = write_mini_spc_edax(tmp_path / "zero.spc", [0, 0, 0, 0, 0])
    ds = load_spc_edax(fp)
    assert ds.n_channels == 5
    assert np.all(np.asarray(ds.data) == 0)


def test_routes_through_load_auto(tmp_path: Path) -> None:
    fp = write_mini_spc_edax(tmp_path / "auto.spc", [1, 2, 3])
    ds = load_auto(fp)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.metadata["parser"] == "spc_edax"


def test_too_short_raises(tmp_path: Path) -> None:
    fp = tmp_path / "tiny.spc"
    fp.write_bytes(b"\x00" * 10)
    with pytest.raises(SpcFormatError, match="too small|too short"):
        load_spc_edax(fp)
    assert not is_edax_spc(fp.read_bytes())


def test_bad_geometry_raises(tmp_path: Path) -> None:
    fp = write_mini_spc_edax(tmp_path / "bad.spc", [1, 2, 3])
    buf = bytearray(fp.read_bytes())
    # corrupt numPts (offset 32, int16) to something absurd — geometry no
    # longer fits inside the file
    import struct

    struct.pack_into("<h", buf, 32, 30000)
    fp.write_bytes(bytes(buf))
    with pytest.raises(SpcFormatError, match="unrecognised .spc header"):
        load_spc_edax(fp)


def test_grams_collision_raises_friendly_error(tmp_path: Path) -> None:
    # byte 1 = 0x4B ('K') is GRAMS/Thermo Galactic's "new format" fversn
    # marker — exactly the byte position that collides with the EDAX
    # version float's second byte.
    fp = write_mini_spc_edax(tmp_path / "grams_like.spc", [1, 2, 3], fversn_byte=0x4B)
    assert not is_edax_spc(fp.read_bytes())
    with pytest.raises(SpcFormatError, match="GRAMS"):
        load_spc_edax(fp)

    fp_l = write_mini_spc_edax(tmp_path / "grams_like_l.spc", [1, 2, 3], fversn_byte=0x4C)
    with pytest.raises(SpcFormatError, match="GRAMS"):
        load_spc_edax(fp_l)

    fp_old = write_mini_spc_edax(tmp_path / "grams_like_old.spc", [1, 2, 3], fversn_byte=0x4D)
    with pytest.raises(SpcFormatError, match="GRAMS"):
        load_spc_edax(fp_old)


def test_is_edax_spc_true_for_valid_synthetic_file(tmp_path: Path) -> None:
    fp = write_mini_spc_edax(tmp_path / "ok.spc", [1, 2, 3, 4])
    assert is_edax_spc(fp.read_bytes())


# ── realdata: pinned values measured during development against the real
# EDAX corpus (../test-data/edax/eds) — auto-skips when the sibling repo
# isn't checked out. ─────────────────────────────────────────────────────


@pytest.mark.realdata
def test_real_single_spect(edax_examples: Path) -> None:
    ds = load_spc_edax(edax_examples / "single_spect.spc")
    assert ds.kind is DataKind.SPECTRUM
    assert ds.n_channels == 4096
    assert ds.metadata["ev_per_channel"] == 10
    assert float(ds.data.sum()) == pytest.approx(890652.0)
    assert ds.metadata["live_time_s"] == pytest.approx(50.000004, abs=1e-3)
    assert ds.metadata["beam_kv"] == pytest.approx(22.0)
    assert ds.metadata["n_elements"] == 8
    assert ds.metadata["spc_version"] == pytest.approx(0.70, abs=1e-3)


@pytest.mark.realdata
def test_real_v0_61_file(edax_examples: Path) -> None:
    ds = load_spc_edax(edax_examples / "spc0_61-ipr333_xrf.spc")
    assert ds.n_channels == 4000
    assert float(ds.data.sum()) == pytest.approx(185564380.0)
    assert ds.metadata["beam_kv"] == pytest.approx(30.0)
    assert ds.metadata["n_elements"] == 10
    assert ds.metadata["spc_version"] == pytest.approx(0.61, abs=1e-3)


@pytest.mark.realdata
def test_real_files_route_through_load_auto(edax_examples: Path) -> None:
    for name in ("single_spect.spc", "line_scan.spc", "spd_map.spc"):
        ds = load_auto(edax_examples / name)
        assert ds.kind is DataKind.SPECTRUM
        assert ds.n_channels == 4096


# ── oracle: cross-validated against rosettasciio's edax reader. GPL —
# dev-only oracle group, skips when not installed (see test_oracle_rsciio.py
# conventions — import is narrow and function-scoped, never a runtime dep). ─


@pytest.mark.realdata
@pytest.mark.oracle
def test_real_corpus_matches_rsciio_oracle(edax_examples: Path) -> None:
    file_reader = pytest.importorskip(
        "rsciio.edax", reason="oracle group not installed"
    ).file_reader

    for name in (
        "single_spect.spc",
        "line_scan.spc",
        "spd_map.spc",
        "spc0_61-ipr333_xrf.spc",
    ):
        f = edax_examples / name
        ours = load_spc_edax(f)
        theirs = file_reader(str(f))[0]
        assert ours.data.shape == theirs["data"].shape
        assert np.array_equal(ours.data, theirs["data"].astype(np.float64)), name
        energy_axis = next(a for a in theirs["axes"] if a["name"] == "Energy")
        assert ours.energy_cal.scale == pytest.approx(float(energy_axis["scale"])), name
        assert ours.energy_axis[0] == pytest.approx(float(energy_axis["offset"])), name
