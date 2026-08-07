"""`.ser` <-> `.emi` metadata pairing (PLAN_DATA_FORMATS #4a).

Synthetic tests build both `.emi` flavours seen in practice — a genuinely
valid CFB container (exercising `io.olefile_min`) and a raw, unwrapped
`<ObjectInfo>` block (matching every real file in the fei/microscopy
corpus) — via tests/fixtures/miniemi.py, reusing tests/fixtures/ser.py for
the paired `.ser`. Realdata tests open the real rosettasciio TIA pairs and
pin known metadata values; they skip when ../test-data isn't checked out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.ser import load_ser
from fixtures.miniemi import write_mini_emi_cfb, write_raw_emi
from fixtures.ser import write_ser_image, write_ser_spectra

pytestmark = pytest.mark.parser

_XML_TEMPLATE = (
    "<ObjectInfo><Uuid>{uuid}</Uuid>"
    "<ExperimentalConditions><MicroscopeConditions>"
    "<AcceleratingVoltage>{av}</AcceleratingVoltage>"
    "</MicroscopeConditions></ExperimentalConditions>"
    "<ExperimentalDescription><Root>{fields}</Root></ExperimentalDescription>"
    "{acquire_info}"
    "<AcquireDate>{date}</AcquireDate><Manufacturer>{manufacturer}</Manufacturer>"
    "</ObjectInfo>"
).format


def _field_xml(label: str, value: str, unit: str = "") -> str:
    return f"<Data><Label>{label}</Label><Value>{value}</Value><Unit>{unit}</Unit></Data>"


def _sample_xml(
    *, uuid: str = "abc-123", av: str = "200000", date: str = "Mon Jan 1 00:00:00 2026",
    manufacturer: str = "FEI", extra_fields: str = "", camera: str | None = None,
) -> bytes:
    fields = (
        _field_xml("High tension", "200", "kV")
        + _field_xml("Microscope", "Tecnai 200 kV", "")
        + extra_fields
    )
    # <AcquireInfo> is a sibling of <ExperimentalDescription>, not a Data
    # field; CameraNamePath in it is what marks a camera-recorded frame.
    acquire_info = (
        f"<AcquireInfo><CameraNamePath>{camera}</CameraNamePath></AcquireInfo>"
        if camera
        else ""
    )
    return _XML_TEMPLATE(
        uuid=uuid, av=av, date=date, manufacturer=manufacturer, fields=fields,
        acquire_info=acquire_info,
    ).encode("utf-8")


# ── synthetic: pairing + merge ──────────────────────────────────────────


def test_cfb_emi_pairs_via_trailing_underscore_number(tmp_path):
    ser_path = tmp_path / "acquire_1.ser"
    write_ser_image(ser_path, width=4, height=4, cal_delta_x=0)
    write_mini_emi_cfb(tmp_path / "acquire.emi", _sample_xml())

    ds = load_ser(ser_path)
    assert "emi" in ds.metadata
    assert ds.metadata["emi"]["acceleration_voltage_v"] == 200000.0
    assert ds.metadata["emi"]["fields"]["High tension"] == {"value": "200", "unit": "kV"}
    assert ds.metadata["emi_source"] == str(tmp_path / "acquire.emi")


def test_cfb_emi_pairs_via_same_stem(tmp_path):
    ser_path = tmp_path / "single.ser"
    write_ser_spectra(ser_path, scan_dims=[], n_channels=4)
    write_mini_emi_cfb(tmp_path / "single.emi", _sample_xml())

    ds = load_ser(ser_path)
    assert ds.metadata["emi"]["manufacturer"] == "FEI"


def test_no_emi_sibling_loads_unchanged(tmp_path):
    ser_path = tmp_path / "lonely_1.ser"
    write_ser_image(ser_path, width=4, height=4)
    ds = load_ser(ser_path)
    assert "emi" not in ds.metadata
    assert "emi_source" not in ds.metadata


def test_bf_df_pair_shares_one_emi(tmp_path):
    """Two .ser (BF/DF) elements both pair to the same .emi."""
    write_ser_image(tmp_path / "scan_1.ser", width=4, height=4)
    write_ser_image(tmp_path / "scan_2.ser", width=4, height=4)
    write_mini_emi_cfb(tmp_path / "scan.emi", _sample_xml())

    ds1 = load_ser(tmp_path / "scan_1.ser")
    ds2 = load_ser(tmp_path / "scan_2.ser")
    assert ds1.metadata["emi_source"] == ds2.metadata["emi_source"]
    assert ds1.metadata["emi_source"] == str(tmp_path / "scan.emi")


def test_raw_unwrapped_emi_pairs(tmp_path):
    """No CFB wrapper at all — the shape of every real corpus file."""
    ser_path = tmp_path / "raw_1.ser"
    write_ser_image(ser_path, width=4, height=4)
    write_raw_emi(
        tmp_path / "raw.emi", _sample_xml(), prefix=b"\x01\x02junk", suffix=b"trailer\x00"
    )

    ds = load_ser(ser_path)
    assert ds.metadata["emi"]["acceleration_voltage_v"] == 200000.0


def test_emi_without_object_info_is_silently_ignored(tmp_path):
    ser_path = tmp_path / "noinfo_1.ser"
    write_ser_image(ser_path, width=4, height=4)
    (tmp_path / "noinfo.emi").write_bytes(b"not an emi file at all")

    ds = load_ser(ser_path)
    assert "emi" not in ds.metadata


def test_emi_with_malformed_xml_is_silently_ignored(tmp_path):
    ser_path = tmp_path / "bad_1.ser"
    write_ser_image(ser_path, width=4, height=4)
    write_raw_emi(tmp_path / "bad.emi", b"<ObjectInfo><Unclosed></ObjectInfo>")

    ds = load_ser(ser_path)  # must not raise
    assert "emi" not in ds.metadata


# ── synthetic: axis-calibration fallback ────────────────────────────────


def test_emi_fills_energy_axis_when_ser_calibration_absent(tmp_path):
    ser_path = tmp_path / "eels_1.ser"
    write_ser_spectra(ser_path, scan_dims=[], n_channels=8, cal_delta=0)
    xml = _sample_xml(extra_fields=_field_xml("Filter selected dispersion", "0.25", "eV/Channel"))
    write_mini_emi_cfb(tmp_path / "eels.emi", xml)

    ds = load_ser(ser_path)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.energy_cal.calibrated
    assert ds.energy_cal.scale == pytest.approx(0.25)
    assert ds.energy_cal.units == "eV"


def test_emi_fills_pixel_axis_when_ser_calibration_absent(tmp_path):
    ser_path = tmp_path / "img_1.ser"
    write_ser_image(ser_path, width=4, height=4, cal_delta_x=0)
    xml = _sample_xml(extra_fields=_field_xml("Pixel size", "1.5", "nm"))
    write_mini_emi_cfb(tmp_path / "img.emi", xml)

    ds = load_ser(ser_path)
    assert ds.kind is DataKind.IMAGE
    assert ds.pixel_cal.calibrated
    assert ds.pixel_size == pytest.approx(1.5e-9)
    assert ds.pixel_unit == "m"


def test_emi_does_not_override_present_ser_calibration(tmp_path):
    ser_path = tmp_path / "cal_1.ser"
    write_ser_spectra(ser_path, scan_dims=[], n_channels=8, cal_delta=0.2)
    xml = _sample_xml(extra_fields=_field_xml("Filter selected dispersion", "9.99", "eV/Channel"))
    write_mini_emi_cfb(tmp_path / "cal.emi", xml)

    ds = load_ser(ser_path)
    assert ds.energy_cal.scale == pytest.approx(0.2)  # .ser wins, not 9.99


# ── synthetic: CFB reader stress (regular-FAT path, multiple streams) ──


def test_cfb_object_info_in_regular_fat_stream(tmp_path):
    """Force the payload well past the mini-stream cutoff so the reader
    exercises the regular-FAT chain, not MiniFAT."""
    ser_path = tmp_path / "big_1.ser"
    write_ser_image(ser_path, width=4, height=4, cal_delta_x=0)
    padded = _sample_xml() + b"\x00" * 5000  # extra trailing bytes, still one stream
    write_mini_emi_cfb(tmp_path / "big.emi", padded, mini_cutoff=64)

    ds = load_ser(ser_path)
    assert ds.metadata["emi"]["acceleration_voltage_v"] == 200000.0


def test_cfb_object_info_found_among_sibling_streams(tmp_path):
    ser_path = tmp_path / "multi_1.ser"
    write_ser_image(ser_path, width=4, height=4)
    write_mini_emi_cfb(
        tmp_path / "multi.emi",
        b"AcquireInfoStream not xml",
        stream_name="AcquireInfo",
        extra_streams={"ObjectInfo": _sample_xml(), "Filler": b"noise" * 10},
    )

    ds = load_ser(ser_path)
    assert ds.metadata["emi"]["acceleration_voltage_v"] == 200000.0


# ── realdata: real rosettasciio TIA .emi/.ser pairs ─────────────────────
#
# Reuses the shared `rsciio_examples` fixture (../test-data root; see
# test_em_examples.py, which already exercises these same .ser files'
# pixel/energy parsing) rather than a new fei-specific fixture.

_FEI_DIR = "fei/microscopy"


@pytest.mark.realdata
def test_real_emi_pairs_and_known_metadata(rsciio_examples: Path) -> None:
    fei_dir = rsciio_examples / _FEI_DIR
    ds = load_ser(fei_dir / "rosettasciio_64x64_TEM_images_acquire_1.ser")

    assert ds.metadata["emi_source"] == str(
        fei_dir / "rosettasciio_64x64_TEM_images_acquire.emi"
    )
    emi = ds.metadata["emi"]
    assert emi["acceleration_voltage_v"] == pytest.approx(200000.0)
    assert emi["manufacturer"] == "FEI"
    assert emi["fields"]["High tension"] == {"value": "200", "unit": "kV"}
    assert emi["fields"]["Microscope"]["value"] == "Microscope Tecnai 200 kV D2267 SuperTwin"
    assert emi["acquire_info"]["CameraNamePath"] == "WA-Orius"


@pytest.mark.realdata
def test_real_bf_df_pair_shares_one_emi(rsciio_examples: Path) -> None:
    fei_dir = rsciio_examples / _FEI_DIR
    bf = load_ser(fei_dir / "rosettasciio_16x16_STEM_BF_DF_acquire_1.ser")
    df = load_ser(fei_dir / "rosettasciio_16x16_STEM_BF_DF_acquire_2.ser")
    assert bf.metadata["emi_source"] == df.metadata["emi_source"]
    assert bf.metadata["emi_source"] == str(
        fei_dir / "rosettasciio_16x16_STEM_BF_DF_acquire.emi"
    )
    assert bf.metadata["emi"]["fields"]["High tension"]["value"] == "200"


@pytest.mark.realdata
def test_real_spectrum_image_dispersion_matches_ser_calibration(
    rsciio_examples: Path,
) -> None:
    """The .emi's "Filter selected dispersion" field and the .ser's own
    energy-axis calibration describe the same physical quantity — cross-
    check them, even though the .ser calibration (present here) is what
    actually wins over the .emi fallback."""
    fei_dir = rsciio_examples / _FEI_DIR
    ds = load_ser(fei_dir / "rosettasciio_16x16-spectrum_image-5x5x1024_1.ser")
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    dispersion_field = ds.metadata["emi"]["fields"]["Filter selected dispersion"]
    assert dispersion_field == {"value": "0.20", "unit": "eV/Channel"}
    assert ds.energy_cal.scale == pytest.approx(float(dispersion_field["value"]))


@pytest.mark.realdata
def test_all_real_corpus_ser_files_pair_successfully(rsciio_examples: Path) -> None:
    fei_dir = rsciio_examples / _FEI_DIR
    ser_files = sorted(fei_dir.glob("rosettasciio_*.ser"))
    assert len(ser_files) >= 8, "expected the 6-.emi / 8-.ser rosettasciio TIA corpus"
    for ser_path in ser_files:
        # One file (line_profile ..._2.ser) is a 5-frame image stack that
        # load_ser warns about — an unrelated, already-covered limitation
        # (test_em_examples.py::test_ser_multiframe_stack_limitation); avoid
        # tripping this repo's filterwarnings=error here.
        if ser_path.name.endswith("line_profile_horizontal_5x128x128_EDS_2.ser"):
            with pytest.warns(UserWarning, match="only the first is returned"):
                ds = load_ser(ser_path)
        else:
            ds = load_ser(ser_path)
        assert "emi" in ds.metadata, ser_path.name
        assert "acceleration_voltage_v" in ds.metadata["emi"], ser_path.name


# ── real vs reciprocal space ────────────────────────────────────────────
#
# A .ser states a CalibrationDeltaX and nothing about what it measures. For a
# TEM diffraction pattern that field is a reciprocal spacing, so labelling
# every image "m" reported the corpus's 64x64 pattern at 1.0e8 metres per
# pixel. Only the paired .emi distinguishes them; the rule (and the STEM
# carve-out below) is rosettasciio's `_guess_units_from_mode`.

def _paired(tmp_path, mode: str, *, camera: str | None = None, delta: float = 2.5e-9):
    write_ser_image(tmp_path / "acq_1.ser", width=4, height=3, dtype_code=2,
                    cal_delta_x=delta)
    write_raw_emi(tmp_path / "acq.emi",
                  _sample_xml(extra_fields=_field_xml("Mode", mode), camera=camera))
    return load_ser(tmp_path / "acq_1.ser")


def test_tem_diffraction_axes_are_reciprocal(tmp_path):
    ds = _paired(tmp_path, " TEM uP SA Zoom Diffraction", delta=1.0157e8)
    assert ds.pixel_unit == "1/m"
    assert ds.pixel_size == pytest.approx(1.0157e8)  # same number, honest label
    assert ds.metadata["spatial_domain"] == "reciprocal"


def test_tem_image_axes_stay_real_space(tmp_path):
    ds = _paired(tmp_path, " TEM uP SA Zoom Image")
    assert ds.pixel_unit == "m"
    assert ds.pixel_size == pytest.approx(2.5e-9)
    assert ds.metadata["spatial_domain"] == "real"


def test_stem_diffraction_mode_is_still_a_real_space_scan(tmp_path):
    """The carve-out that made this worth getting right: under STEM the
    projector sits in diffraction mode while the image formed is a real-space
    scan. Without corroboration (a camera, or a genuine multi-position nav
    axis) these must stay metres — the corpus's STEM BF/DF pair at 21.5 nm/px
    would otherwise be relabelled reciprocal."""
    ds = _paired(tmp_path, " STEM nP SA Zoom Diffraction")
    assert ds.pixel_unit == "m"
    assert ds.metadata["spatial_domain"] == "real"


def test_stem_with_camera_is_reciprocal(tmp_path):
    ds = _paired(tmp_path, " STEM nP SA Zoom Diffraction", camera="BM-Ceta")
    assert ds.pixel_unit == "1/m"
    assert ds.metadata["spatial_domain"] == "reciprocal"


def test_unpaired_ser_defaults_to_real_space(tmp_path):
    """No .emi means no way to know; metres is the overwhelmingly common case
    and mislabelling it would be worse than the status quo."""
    write_ser_image(tmp_path / "lone.ser", width=4, height=3, dtype_code=2)
    ds = load_ser(tmp_path / "lone.ser")
    assert ds.pixel_unit == "m"
    assert "spatial_domain" not in ds.metadata


def test_emi_without_mode_defaults_to_real_space(tmp_path):
    write_ser_image(tmp_path / "nomode_1.ser", width=4, height=3, dtype_code=2)
    write_raw_emi(tmp_path / "nomode.emi", _sample_xml())
    ds = load_ser(tmp_path / "nomode_1.ser")
    assert ds.pixel_unit == "m"
    assert ds.metadata["spatial_domain"] == "real"
