"""Real TEM/STEM/EDS/EELS files from the sibling corpus (../fv-example-data/rsciio).

A stress test of every EM parser against genuine instrument output drawn from
the rosettasciio test suite, spanning all four modalities and six formats:

* **DM3/DM4** (Gatan) — EELS/EDS spectra, STEM image, diffraction, EELS SI.
* **TIA SER** (FEI/ThermoFisher) — TEM/STEM images + EDS/EELS spectrum images
  and line profiles.
* **EMD** (Velox + NCEM) — images and stacks.
* **MRC** — STEM HAADF.
* **MSA** — single EDS/EELS spectra.
* **BCF** (Bruker) — EDS spectrum-image cubes with varied packing/bit depth.

Every pinned value below (shape, sum, calibration) was cross-validated to an
exact match against the rosettasciio oracle, so these tests need no oracle at
run time — like the AFM/BCF realdata tests they auto-skip when the corpus is
absent. Known limitations are asserted explicitly (see the ``*_limitation``
tests) so any future change in behaviour is caught.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.dm import DMFormatError
from fermiviewer.io.emd import EMDFormatError
from fermiviewer.io.registry import load_auto

pytestmark = pytest.mark.realdata


def _load(corpus: Path, rel: str):
    return load_auto(corpus / rel)


# ── DM3/DM4 (Gatan) ──────────────────────────────────────────────────

def test_dm_eels_spectrum(rsciio_examples: Path) -> None:
    ds = _load(rsciio_examples, "dm/test-EELS_spectrum.dm3")
    assert ds.kind is DataKind.SPECTRUM
    assert ds.data.shape == (2048,)
    assert float(np.asarray(ds.data, float).sum()) == pytest.approx(-7678.56, rel=1e-4)
    assert ds.energy_cal.units == "eV"
    assert ds.energy_cal.scale == pytest.approx(0.5, rel=1e-6)
    assert ds.energy_axis[0] == pytest.approx(-100.0, abs=1e-3)  # (0 − 200)·0.5


def test_dm_eds_spectrum(rsciio_examples: Path) -> None:
    ds = _load(rsciio_examples, "dm/test-EDS_spectrum.dm3")
    assert ds.kind is DataKind.SPECTRUM
    assert ds.data.shape == (4096,)
    assert int(np.asarray(ds.data, float).sum()) == 17051
    assert ds.energy_cal.units == "keV"
    assert ds.energy_axis[0] == pytest.approx(-0.478, abs=1e-3)


def test_dm_stem_image(rsciio_examples: Path) -> None:
    ds = _load(rsciio_examples, "dm/test_STEM_image.dm3")
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (68, 68)
    assert float(np.asarray(ds.data, float).sum()) == pytest.approx(1.50999e8, rel=1e-4)
    assert ds.pixel_unit == "nm"
    assert ds.pixel_size == pytest.approx(0.248538, rel=1e-4)


def test_dm_diffraction_pattern(rsciio_examples: Path) -> None:
    ds = _load(rsciio_examples, "dm/test_diffraction_pattern.dm3")
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (87, 87)
    assert ds.pixel_unit == "1/nm"  # reciprocal-space calibration


def test_dm_eels_spectrum_image(rsciio_examples: Path) -> None:
    ds = _load(rsciio_examples, "dm/EELS_SI.dm4")
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (2, 2, 2048)  # (y, x, energy)
    assert float(np.asarray(ds.data, float).sum()) == pytest.approx(7.16907e6, rel=1e-4)
    assert ds.energy_cal.units == "eV"


def test_dm_complex_fft_limitation(rsciio_examples: Path) -> None:
    # packed-complex FFT (DM DataType 27) is not supported — must fail cleanly
    with pytest.raises(DMFormatError, match="27"):
        _load(rsciio_examples, "dm/test_fft_packed_complex8.dm4")


# ── TIA SER (FEI) ────────────────────────────────────────────────────

def test_ser_tem_image(rsciio_examples: Path) -> None:
    ds = _load(rsciio_examples, "tia/64x64_TEM_images_acquire_1.ser")
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (64, 64)
    assert float(np.asarray(ds.data, float).sum()) == pytest.approx(1.65051e8, rel=1e-4)
    assert ds.pixel_unit == "m"  # SER keeps SI metres (MATLAB-parity)
    assert ds.pixel_size == pytest.approx(6.282e-9, rel=1e-3)


def test_ser_stem_bf_df_separate_signals(rsciio_examples: Path) -> None:
    bf = _load(rsciio_examples, "tia/16x16_STEM_BF_DF_acquire_1.ser")
    df = _load(rsciio_examples, "tia/16x16_STEM_BF_DF_acquire_2.ser")
    assert bf.data.shape == df.data.shape == (16, 16)
    assert int(np.asarray(bf.data, float).sum()) == 131
    assert int(np.asarray(df.data, float).sum()) == 686169


def test_ser_eds_spectrum_image(rsciio_examples: Path) -> None:
    # 0x4120 spectrum image — an enhancement beyond the MATLAB SER parser
    ds = _load(rsciio_examples, "tia/16x16-spectrum_image-5x5x1024_1.ser")
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (5, 5, 1024)
    assert int(np.asarray(ds.data, float).sum()) == 164488
    assert ds.energy_cal.units == "eV"
    assert ds.energy_cal.scale == pytest.approx(0.2, rel=1e-6)
    assert ds.energy_axis[0] == pytest.approx(-20.0, abs=1e-3)


def test_ser_eds_line_profile(rsciio_examples: Path) -> None:
    ds = _load(rsciio_examples, "tia/16x16-line_profile_horizontal_5x128x128_EDS_1.ser")
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (1, 5, 4000)  # line profile → (1, N, energy)
    assert int(np.asarray(ds.data, float).sum()) == 11
    assert ds.energy_cal.units == "eV"


def test_ser_multiframe_stack_limitation(rsciio_examples: Path) -> None:
    # a 5-frame image series: only the first frame is returned, with a warning
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ds = _load(rsciio_examples, "tia/16x16-line_profile_horizontal_5x128x128_EDS_2.ser")
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (128, 128)
    assert ds.metadata["ser_frames_total"] == 5
    assert any("frames" in str(w.message) for w in caught)


# ── EMD (Velox + NCEM) ───────────────────────────────────────────────

def test_emd_ncem_image(rsciio_examples: Path) -> None:
    ds = _load(rsciio_examples, "emd/example_image.emd")
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (3, 3)
    assert int(np.asarray(ds.data, float).sum()) == 36


def test_emd_velox_stack_limitation(rsciio_examples: Path) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ds = _load(rsciio_examples, "emd/fei_example_tem_stack.emd")
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (3, 3)  # first frame of the 2-frame stack
    assert ds.metadata["n_frames"] == 2
    assert any("frames" in str(w.message) for w in caught)


def test_emd_ncem_4d_sim_limitation(rsciio_examples: Path) -> None:
    # NCEM CBED-style layout (Si100_3D) isn't a recognised /Data/Image or
    # emd_group_type structure — must fail cleanly, not crash
    with pytest.raises(EMDFormatError):
        _load(rsciio_examples, "emd/Si100_3D.emd")


# ── MRC ──────────────────────────────────────────────────────────────

def test_mrc_haadf(rsciio_examples: Path) -> None:
    ds = _load(rsciio_examples, "mrc/HAADFscan.mrc")
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (16, 16)
    assert float(np.asarray(ds.data, float).sum()) == pytest.approx(1.55295e6, rel=1e-4)
    assert ds.pixel_unit == "A"  # MRC keeps Angstroms (5.679 nm = 56.79 A)
    assert ds.pixel_size == pytest.approx(56.79131, rel=1e-4)


def test_mrc_4dstem_degrades_to_first_frame_limitation(rsciio_examples: Path) -> None:
    # a 4D-STEM .mrc (deferred feature) loads as the first 2D frame, gracefully
    ds = _load(rsciio_examples, "mrc/4DSTEMscan.mrc")
    assert ds.kind is DataKind.IMAGE
    assert ds.data.ndim == 2


# ── MSA (single spectra) ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "rel, n, total, scale",
    [
        ("msa/example1.msa", 21, 104070, 3.1),
        ("msa/example2.msa", 80, 21060.1, 10.0),
        ("msa/ISO_22029_2022_compliance.msa", 21, 104070, 3.1),
    ],
)
def test_msa_spectrum(rsciio_examples: Path, rel: str, n: int, total: float, scale: float) -> None:
    ds = _load(rsciio_examples, rel)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.data.shape == (n,)
    assert float(np.asarray(ds.data, float).sum()) == pytest.approx(total, rel=1e-4)
    assert ds.energy_cal.scale == pytest.approx(scale, rel=1e-6)


# ── BCF (Bruker EDS cubes) ───────────────────────────────────────────

@pytest.mark.parametrize(
    "rel, shape, total",
    [
        ("bruker/bcf_v2_50x50px.bcf", (50, 50, 4096), 949769),
        ("bruker/bcf-edx-ebsd.bcf", (87, 100, 4096), 36864),
        ("bruker/over16bit.bcf", (3, 4, 4096), 176786251),
        ("bruker/30x30_instructively_packed_16bit_compressed.bcf", (30, 30, 4096), 18621362),
    ],
)
def test_bcf_cube(rsciio_examples: Path, rel: str, shape: tuple, total: int) -> None:
    ds = _load(rsciio_examples, rel)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == shape
    assert int(np.asarray(ds.data, float).sum()) == total
    assert ds.energy_cal.units == "keV"


def test_bcf_calibration_needs_sem_dx_limitation(rsciio_examples: Path) -> None:
    # this instructive packing-test file lacks the TRTSEMData/DX tag, so the
    # spatial axes stay uncalibrated (scale 1.0) — we don't invent a value
    calibrated = _load(rsciio_examples, "bruker/bcf_v2_50x50px.bcf")
    assert calibrated.pixel_unit == "um"  # normal file: calibrated
    uncal = _load(rsciio_examples, "bruker/30x30_instructively_packed_16bit_compressed.bcf")
    assert uncal.pixel_unit == ""  # no DX tag → uncalibrated, not wrong
