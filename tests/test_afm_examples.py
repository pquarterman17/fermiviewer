"""Real Bruker NanoScope AFM files from the sibling corpus (../fv-example-data).

Covers the two calibration conventions plus the parser's error paths:

* Modern PeakForce QNM (`minicircle.spm`, `plasmids.spm`): 8 channels,
  per-channel hard-scale units (Height in nm, DMTModulus in Arb, …).
* Legacy NanoScope III (`old_bruker.002/.004`): `Scan size`/`~m` header
  spellings and Method-B ADC-range z-scaling.
* Truncated / variant headers (`bruker_data_header.*`): must raise a
  clean ``NanoscopeError``, never crash.

Every height/ZSensor statistic below was cross-validated to an exact match
against the pySPM oracle (``pySPM.Bruker``), so these pins need no pySPM at
run time — like the EELS/BCF realdata tests, they auto-skip when the corpus
is absent.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fermiviewer.io.nanoscope import NanoscopeError, load_nanoscope, load_nanoscope_all
from fermiviewer.io.registry import load_auto

pytestmark = pytest.mark.realdata

# stem → (channels, primary channel, shape, nm/px, ptp nm, std nm) for the
# height/ZSensor channel; ptp+std pin the calibrated *scale*, mean pins the
# absolute z-offset where it also matched pySPM (legacy files).
_MODERN = {
    "topostats/minicircle.spm": dict(
        n=8, primary="ZSensor", shape=(1024, 1024), px=505.859 / 1024,
        ptp=19.971, std=4.324,
    ),
    "topostats/plasmids.spm": dict(
        n=8, primary="ZSensor", shape=(512, 512), px=378.906 / 512,
        ptp=13.62, std=2.544,
    ),
}
_LEGACY = {
    "topostats/old_bruker.002": dict(
        shape=(256, 256), px=15000.0 / 256, ptp=704.79, std=135.53, mean=379.62,
    ),
    "topostats/old_bruker.004": dict(
        shape=(256, 256), px=15000.0 / 256, ptp=912.37, std=177.33, mean=-572.49,
    ),
}


@pytest.fixture
def corpus(afm_examples: Path):
    return afm_examples


@pytest.mark.parametrize("stem", list(_MODERN))
def test_modern_peakforce_channels_and_height(corpus: Path, stem: str) -> None:
    ex = _MODERN[stem]
    chans = load_nanoscope_all(corpus / stem)
    assert len(chans) == ex["n"]

    ds = load_nanoscope(corpus / stem)  # picks the height/ZSensor channel
    assert ds.metadata["channel"] == ex["primary"]
    assert ds.data.shape == ex["shape"]
    assert ds.metadata["value_unit"] == "nm"
    assert ds.axes[1].units == "nm"
    assert ds.axes[1].scale == pytest.approx(ex["px"], rel=1e-3)

    z = np.asarray(ds.data, dtype=float)
    assert np.ptp(z) == pytest.approx(ex["ptp"], rel=2e-3)
    assert z.std() == pytest.approx(ex["std"], rel=2e-3)
    assert not np.isnan(z).any()


@pytest.mark.parametrize("stem", list(_MODERN))
def test_modern_channel_units_from_hard_scale(corpus: Path, stem: str) -> None:
    # non-height channels take their unit from the Z-scale hard-scale
    # parenthetical (Arb / log(Arb)), NOT the sensitivity's bogus "nm".
    by_channel = {c.metadata["channel"]: c for c in load_nanoscope_all(corpus / stem)}
    assert by_channel["Stiffness"].metadata["value_unit"] == "Arb"
    assert by_channel["LogStiffness"].metadata["value_unit"] == "log(Arb)"
    assert by_channel["Dissipation"].metadata["value_unit"] == "Arb"
    # a genuine length channel stays nm
    length_chan = "Deformation" if "Deformation" in by_channel else "Indentation"
    assert by_channel[length_chan].metadata["value_unit"] == "nm"


@pytest.mark.parametrize("stem", list(_LEGACY))
def test_legacy_nanoscope_iii_height(corpus: Path, stem: str) -> None:
    ex = _LEGACY[stem]
    ds = load_nanoscope(corpus / stem)  # `Scan size`, `~m`, Method-B scaling
    assert ds.metadata["channel"] == "Height"
    assert ds.data.shape == ex["shape"]
    assert ds.metadata["value_unit"] == "nm"
    assert ds.axes[1].scale == pytest.approx(ex["px"], rel=1e-3)

    z = np.asarray(ds.data, dtype=float)
    assert np.ptp(z) == pytest.approx(ex["ptp"], rel=2e-3)
    assert z.std() == pytest.approx(ex["std"], rel=2e-3)
    assert z.mean() == pytest.approx(ex["mean"], abs=0.5)  # absolute offset too


def test_legacy_routes_through_registry(corpus: Path) -> None:
    ds = load_auto(corpus / "topostats" / "old_bruker.002")  # numeric-ext route
    assert ds.metadata["parser"] == "nanoscope"
    assert ds.metadata["scan_size_nm"] == [15000.0, 15000.0]


@pytest.mark.parametrize("name", ["000", "001", "002"])
def test_truncated_headers_fail_cleanly(corpus: Path, name: str) -> None:
    # header-only captures: the data block is absent, so the parser must
    # reject them with a clear error rather than reading past EOF.
    with pytest.raises(NanoscopeError):
        load_nanoscope(corpus / "pyspm" / f"bruker_data_header.{name}")


def test_ec_file_list_variant_rejected(corpus: Path) -> None:
    # `\*EC File list` is an electrochemistry variant the sniffer declines.
    with pytest.raises(NanoscopeError):
        load_nanoscope(corpus / "pyspm" / "bruker_data_header.003")
