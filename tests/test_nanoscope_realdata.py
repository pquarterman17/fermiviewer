"""Real-file validation of the Nanoscope parser against a public Bruker
sample (AFM-SPM/AFMReader ``sample_0.spm``, GPL — NOT committed).

The expected height statistics were cross-validated against the pySPM
oracle (exact match: peak-to-peak 19.971 nm, std 4.324 nm on the Height
Sensor channel), so this test pins them without needing pySPM installed.

Fetch the sample locally to run this (otherwise it skips, like the EELS
corpus tests)::

    curl -sL -o build/afm-samples/sample_0.spm \\
      https://raw.githubusercontent.com/AFM-SPM/AFMReader/main/tests/resources/sample_0.spm
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fermiviewer.io.nanoscope import load_nanoscope, load_nanoscope_all

_SAMPLE = (
    Path(__file__).resolve().parents[1] / "build" / "afm-samples" / "sample_0.spm"
)
pytestmark = pytest.mark.realdata


@pytest.fixture
def sample() -> Path:
    if not _SAMPLE.is_file():
        pytest.skip(f"Bruker AFM sample absent ({_SAMPLE}); see module docstring")
    return _SAMPLE


def test_channels_and_primary(sample: Path) -> None:
    chans = load_nanoscope_all(sample)
    assert len(chans) == 8
    assert chans[0].metadata["channel"] == "ZSensor"  # "Height Sensor"
    ds = load_nanoscope(sample)  # primary picks the height/zsensor channel
    assert ds.metadata["channel"] == "ZSensor"
    assert ds.data.shape == (1024, 1024)


def test_lateral_calibration(sample: Path) -> None:
    ds = load_nanoscope(sample)
    assert ds.axes[1].units == "nm"
    assert ds.axes[1].scale == pytest.approx(505.859 / 1024, rel=1e-4)


def test_height_calibration_pinned_to_pyspm(sample: Path) -> None:
    # absolute z-offset is tool-dependent; the calibrated *scale* (which
    # peak-to-peak and std capture) matched pySPM exactly.
    z = np.asarray(load_nanoscope(sample).data, dtype=float)
    assert load_nanoscope(sample).metadata["value_unit"] == "nm"
    assert np.ptp(z) == pytest.approx(19.971, abs=0.01)
    assert z.std() == pytest.approx(4.324, abs=0.01)
