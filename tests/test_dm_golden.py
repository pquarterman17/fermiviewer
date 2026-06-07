"""DM parser vs frozen MATLAB reference values (tests/golden/).

Committed-corpus tests need ../fermi-viewer checked out (skip otherwise);
realdata tests additionally need the local-only EELS corpus.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.dm import load_dm

pytestmark = [pytest.mark.parser, pytest.mark.golden]

REL = 1e-9


def _dm_entries(golden) -> list[dict]:
    return [
        e for e in golden("parsers_committed")["images"]
        if e["file"].lower().endswith((".dm3", ".dm4"))
    ]


def test_committed_corpus_matches_matlab(golden, ml_datasets: Path) -> None:
    entries = _dm_entries(golden)
    assert entries, "no DM entries in golden"
    mic = ml_datasets / "Microscopy"

    for e in entries:
        ds = load_dm(mic / e["file"])
        if e["mode"] == "2D":
            assert ds.kind is DataKind.IMAGE, e["file"]
            h, w = ds.data.shape
            assert (h, w) == (e["height"], e["width"]), e["file"]
            assert ds.metadata["bit_depth"] == e["bitDepth"], e["file"]
            px = ds.data.astype(np.float64)
            assert px.sum() == pytest.approx(e["pixSum"], rel=REL), e["file"]
            assert px.mean() == pytest.approx(e["pixMean"], rel=REL), e["file"]
            assert px.min() == e["pixMin"] and px.max() == e["pixMax"], e["file"]
            if isinstance(e["pixelSize"], (int, float)):
                assert ds.pixel_size == pytest.approx(e["pixelSize"], rel=1e-6), e["file"]
        elif e["mode"] == "3D":
            assert ds.kind is DataKind.SPECTRUM_IMAGE, e["file"]
            assert ds.data.shape == (e["Ny"], e["Nx"], e["nChannels"]), e["file"]
            ax = ds.energy_axis
            assert ax[0] == pytest.approx(e["energyFirst"], rel=1e-6), e["file"]
            assert ax[-1] == pytest.approx(e["energyLast"], rel=1e-6), e["file"]
            assert ds.data.astype(np.float64).sum() == pytest.approx(
                e["cubeSum"], rel=REL
            ), e["file"]


@pytest.mark.realdata
def test_real_eels_corpus_matches_matlab(golden, eels_corpus: Path) -> None:
    g = golden("eels_realdata")

    z = g["zlp"]
    ds = load_dm(eels_corpus / "FigS6_apatite_ZLP.dm4")
    assert list(ds.data.shape) == z["dims"]
    ax = ds.energy_axis
    assert ax[0] == pytest.approx(z["energyFirst"], rel=1e-9)
    assert ds.energy_cal.scale == pytest.approx(z["energyScale"], rel=1e-12)
    ss = ds.sum_spectrum()
    assert ss.sum() == pytest.approx(z["sumTotal"], rel=REL)
    assert ax[int(np.argmax(ss))] == pytest.approx(z["zlpEnergy"], abs=1e-9)

    o = g["okedge"]
    ds = load_dm(eels_corpus / "Fig4_apatite79221_OKedge_vesicle.dm4")
    assert list(ds.data.shape) == o["dims"]
    assert ds.energy_axis[0] == pytest.approx(o["energyFirst"], rel=1e-9)
    assert ds.energy_axis[-1] == pytest.approx(o["energyLast"], rel=1e-9)

    r = g["rsciio"]
    ds = load_dm(eels_corpus / "rosettasciio_EELS_SI.dm4")
    assert list(ds.data.shape) == r["dims"]
    assert ds.energy_axis[0] == pytest.approx(r["energyFirst"], rel=1e-6)
    assert ds.pixel_size == pytest.approx(r["pixelSize"], rel=1e-9)
    assert ds.data.astype(np.float64).sum() == pytest.approx(r["cubeSum"], rel=REL)
