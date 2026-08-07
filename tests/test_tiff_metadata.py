"""TIFF vendor-tag calibration — io/tiff_meta.py.

A `.tif` off a Thermo Fisher dual-beam used to open uncalibrated and
untilted even though both numbers sit in tag 34682, because `load_tiff`
read the pixels and nothing else. These tests pin the recovery for each
tag family the reader understands, plus the cases where inventing a
calibration would be worse than having none.

The FEI pixel sizes below were cross-checked against rosettasciio's TIFF
reader on the same synthetic files (3.4e-9 m / 1.2e-8 m / 2e-6 m, exact),
so the numbers are not just self-consistent with our own writer.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.images import load_tiff
from fermiviewer.io.metadata import get_stage_tilt
from fermiviewer.io.registry import load_auto
from fermiviewer.models import ImageMeta
from fixtures.minitiff import (
    TAG_FEI_HELIOS,
    TAG_FEI_SFEG,
    fei_ini,
    fei_sections,
    write_cz_sem_tiff,
    write_fei_tiff,
    write_imagej_tiff,
)

pytestmark = pytest.mark.parser

# 1536x1103 = a Helios frame with its 79-row databar baked in.
_W, _H = 1536, 1103


@pytest.fixture
def frame() -> np.ndarray:
    return np.arange(_H * _W, dtype=np.uint16).reshape(_H, _W) % 4096


# ── Thermo Fisher / FEI ──────────────────────────────────────────────

def test_fei_fib_image_calibrates_and_tilts(tmp_path, frame) -> None:
    """The reported case: a FIB image at 52° stage tilt, 3.4 nm/px."""
    f = write_fei_tiff(tmp_path / "fib.tif", frame)

    ds = load_tiff(f)
    assert ds.kind is DataKind.IMAGE
    assert ds.pixel_size == pytest.approx(3.4)      # 3.4e-9 m in the file
    assert ds.pixel_unit == "nm"
    assert ds.axes[0].scale == pytest.approx(ds.axes[1].scale)  # square pixels

    tilt, key = get_stage_tilt(ds.metadata)
    assert tilt == pytest.approx(52.0, abs=1e-6)    # 0.90757 rad in the file
    assert key == "stage_tilt_deg"
    assert ds.metadata["beam"] == "IBeam"
    assert ds.metadata["vendor"] == "thermofisher"
    assert ds.metadata["calibration_source"] == "fei"
    assert ds.metadata["instrument_name"] == "Helios NanoLab 660"
    assert ds.metadata["beam_kv"] == pytest.approx(30.0)
    assert ds.metadata["working_distance_mm"] == pytest.approx(4.0)


def test_fei_databar_is_reported_not_cropped(tmp_path, frame) -> None:
    """FEI bakes its info bar into the pixels. Record its height so callers
    can exclude it; never silently change the array."""
    ds = load_tiff(write_fei_tiff(tmp_path / "bar.tif", frame))
    assert ds.data.shape == (_H, _W)          # nothing cropped
    assert ds.metadata["databar_height"] == pytest.approx(79)
    assert ds.metadata["image_rows"] == pytest.approx(1024)


def test_fei_sfeg_tag_is_read_too(tmp_path, frame) -> None:
    """Older S-FEG columns write tag 34680 instead of 34682."""
    ds = load_tiff(write_fei_tiff(tmp_path / "sfeg.tif", frame, tag=TAG_FEI_SFEG))
    assert ds.pixel_size == pytest.approx(3.4)
    assert ds.metadata["calibration_source"] == "fei"


def test_fei_electron_beam_image(tmp_path, frame) -> None:
    ds = load_tiff(
        write_fei_tiff(tmp_path / "sem.tif", frame, beam="EBeam", pixel_m=1.2e-8)
    )
    assert ds.pixel_size == pytest.approx(12.0)
    assert ds.pixel_unit == "nm"
    assert ds.metadata["beam"] == "EBeam"


def test_fei_low_mag_switches_to_microns(tmp_path, frame) -> None:
    """An SEM overview at 2 µm/px must not read as 2000 nm on the scale bar."""
    ds = load_tiff(write_fei_tiff(tmp_path / "low.tif", frame, pixel_m=2e-6))
    assert ds.pixel_unit == "um"
    assert ds.pixel_size == pytest.approx(2.0)


def test_fei_beam_specific_scan_section(tmp_path, frame) -> None:
    """Single-column exports omit the shared [Scan]; [IScan]/[EScan] carry
    the same PixelWidth and must be used."""
    sections = fei_sections(beam="IBeam", pixel_m=6.5e-9)
    del sections["Scan"]
    ds = load_tiff(write_fei_tiff(tmp_path / "iscan.tif", frame, sections=sections))
    assert ds.pixel_size == pytest.approx(6.5)


def test_fei_field_width_fallback(tmp_path, frame) -> None:
    """No PixelWidth anywhere: derive it from HorFieldsize / ResolutionX."""
    ds = load_tiff(
        write_fei_tiff(
            tmp_path / "field.tif", frame, pixel_m=None, hor_field_m=1536 * 3.4e-9
        )
    )
    assert ds.pixel_size == pytest.approx(3.4, rel=1e-9)


def test_fei_column_hfw_fallback(tmp_path, frame) -> None:
    """Nav-cam / Apreo exports state only HFW+VFW on the column block, and
    the raster to divide by is [Image] ResolutionX/Y, not the array shape
    (which includes the databar)."""
    sections = fei_sections(beam="EBeam", pixel_m=None)
    del sections["Scan"], sections["EScan"]
    sections["EBeam"]["HFW"] = 1536 * 5.0e-9
    sections["EBeam"]["VFW"] = 1024 * 5.0e-9  # ResolutionY, not the 1103 rows
    ds = load_tiff(write_fei_tiff(tmp_path / "hfw.tif", frame, sections=sections))
    assert ds.pixel_size == pytest.approx(5.0, rel=1e-9)
    assert ds.axes[0].scale == pytest.approx(5.0, rel=1e-9)


def test_fei_tilt_from_column_block_when_stage_absent(tmp_path, frame) -> None:
    sections = fei_sections(beam="IBeam", tilt_rad=None)
    sections["IBeam"]["StageTa"] = 0.5235987755982988  # 30°
    ds = load_tiff(write_fei_tiff(tmp_path / "ta.tif", frame, sections=sections))
    assert get_stage_tilt(ds.metadata)[0] == pytest.approx(30.0, abs=1e-6)


def test_fei_zero_tilt_is_recorded_not_dropped(tmp_path, frame) -> None:
    """A flat stage is a measurement, not a missing value — 0.0 must survive
    to the wire rather than being filtered out as falsy."""
    ds = load_tiff(write_fei_tiff(tmp_path / "flat.tif", frame, tilt_rad=0.0))
    assert ds.metadata["stage_tilt_deg"] == 0.0
    meta = ImageMeta.from_datastruct("i", "flat.tif", ds)
    assert meta.stage_tilt_deg == 0.0


def test_fei_metadata_reaches_the_wire(tmp_path, frame) -> None:
    ds = load_tiff(write_fei_tiff(tmp_path / "wire.tif", frame))
    meta = ImageMeta.from_datastruct("img0", "wire.tif", ds)
    assert meta.pixel_size == pytest.approx(3.4)
    assert meta.pixel_unit == "nm"
    assert meta.stage_tilt_deg == pytest.approx(52.0, abs=1e-6)
    assert meta.meta["beam"] == "IBeam"
    # the full INI stays off the wire (it is `image_tags`, like DM/Velox)
    assert "image_tags" not in meta.meta
    assert "Scan.PixelWidth" in ds.metadata["image_tags"]


def test_fei_uncalibratable_blob_leaves_axes_blank(tmp_path, frame) -> None:
    """A section map with no pixel size and no stage: metadata still lands,
    the axes stay honestly uncalibrated."""
    ds = load_tiff(
        write_fei_tiff(
            tmp_path / "bare.tif",
            frame,
            sections={"System": {"SystemType": "Scios 2"}, "Beam": {"Beam": "IBeam"}},
        )
    )
    assert not ds.axes[1].calibrated
    assert ds.pixel_unit == ""
    assert ds.metadata["instrument_name"] == "Scios 2"
    assert np.isnan(get_stage_tilt(ds.metadata)[0])


def test_unparseable_vendor_tag_degrades_silently(tmp_path, frame) -> None:
    """A vendor tag holding something that isn't an INI is not an error —
    it just yields no calibration. No warning, no lost pixels."""
    import tifffile

    f = tmp_path / "junk.tif"
    tifffile.imwrite(
        f,
        frame,
        photometric="minisblack",
        extratags=[(TAG_FEI_HELIOS, 2, 0, "not an INI file at all", True)],
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ds = load_tiff(f)
    assert ds.data.shape == (_H, _W)
    assert not ds.axes[1].calibrated


def test_metadata_failure_never_costs_the_pixels(tmp_path, frame, monkeypatch) -> None:
    """If the metadata reader itself blows up, the image must still open —
    a calibration is a bonus, the array is the deliverable."""
    import fermiviewer.io.tiff_meta as tiff_meta

    def boom(*_a, **_k):
        raise RuntimeError("tag reader exploded")

    monkeypatch.setattr(tiff_meta, "tiff_calibration", boom)
    f = write_fei_tiff(tmp_path / "boom.tif", frame)
    with pytest.warns(UserWarning, match="TIFF metadata unreadable"):
        ds = load_tiff(f)
    assert ds.data.shape == (_H, _W)
    assert not ds.axes[1].calibrated


def test_sparse_vendor_tag_falls_back_to_imagej_scale(tmp_path) -> None:
    """An FEI tag with no pixel size next to a usable ImageJ header: keep the
    vendor metadata, but take the scale from the header rather than dropping
    the calibration on the floor."""
    import tifffile

    small = np.arange(64 * 64, dtype=np.uint16).reshape(64, 64)
    f = tmp_path / "mixed.tif"
    tifffile.imwrite(
        f,
        small,
        photometric="minisblack",
        imagej=True,
        resolution=(0.5, 0.5),
        metadata={"unit": "nm"},
        extratags=[
            (
                TAG_FEI_HELIOS,
                2,
                0,
                fei_ini({"System": {"SystemType": "Helios 5"}, "Stage": {"StageT": 0.5}}),
                True,
            )
        ],
    )
    ds = load_tiff(f)
    assert ds.pixel_size == pytest.approx(2.0)  # 1 / 0.5 px per nm
    assert ds.metadata["calibration_source"] == "imagej"
    assert ds.metadata["instrument_name"] == "Helios 5"
    assert get_stage_tilt(ds.metadata)[0] == pytest.approx(np.degrees(0.5))


# ── Zeiss SmartSEM ───────────────────────────────────────────────────

def test_zeiss_cz_sem_calibrates_and_tilts(tmp_path) -> None:
    frame = np.arange(64 * 64, dtype=np.uint8).reshape(64, 64)
    ds = load_tiff(write_cz_sem_tiff(tmp_path / "zeiss.tif", frame))
    assert ds.pixel_size == pytest.approx(3.4)
    assert ds.pixel_unit == "nm"
    # SmartSEM states degrees, unlike FEI — 52 must stay 52, not become 2979
    assert get_stage_tilt(ds.metadata)[0] == pytest.approx(52.0)
    assert ds.metadata["calibration_source"] == "zeiss"
    assert ds.metadata["beam_kv"] == pytest.approx(5.0)
    assert ds.metadata["working_distance_mm"] == pytest.approx(4.1)


def test_zeiss_prefers_image_pixel_size_over_pixel_size(tmp_path) -> None:
    """SmartSEM writes both. `Pixel Size` stays at the store resolution while
    `Image Pixel Size` tracks the acquisition settings actually used, so the
    latter is the one that describes these pixels."""
    frame = np.arange(64 * 64, dtype=np.uint8).reshape(64, 64)
    ds = load_tiff(
        write_cz_sem_tiff(
            tmp_path / "two.tif",
            frame,
            extra={"ap_pixel_size": ("Pixel Size", "99.00 nm")},
        )
    )
    assert ds.pixel_size == pytest.approx(3.4)


@pytest.mark.parametrize(
    "mag, expected",
    [
        ("10.00 K X", 10000.0),   # LEO1550 dump
        ("40.15 K X", 40150.0),   # Merlin dump
        ("1.250 M X", 1_250_000.0),
        ("500 X", 500.0),         # two tokens — tifffile splits this one
    ],
)
def test_zeiss_magnification_suffix_forms(tmp_path, mag, expected) -> None:
    """"10.00 K X" is three tokens, so tifffile hands it over unparsed —
    without the suffix handling the magnification is silently dropped."""
    frame = np.arange(64 * 64, dtype=np.uint8).reshape(64, 64)
    ds = load_tiff(write_cz_sem_tiff(tmp_path / f"m{expected}.tif", frame, mag=mag))
    assert ds.metadata["magnification"] == pytest.approx(expected)


def test_zeiss_unparseable_magnification_is_omitted(tmp_path) -> None:
    frame = np.arange(64 * 64, dtype=np.uint8).reshape(64, 64)
    ds = load_tiff(
        write_cz_sem_tiff(tmp_path / "badmag.tif", frame, mag="Unknown Q X")
    )
    assert "magnification" not in ds.metadata
    assert ds.pixel_size == pytest.approx(3.4)  # the rest still lands


def test_zeiss_micron_pixel_unit(tmp_path) -> None:
    frame = np.arange(64 * 64, dtype=np.uint8).reshape(64, 64)
    ds = load_tiff(
        write_cz_sem_tiff(tmp_path / "z_um.tif", frame, pixel="1.500 µm")
    )
    assert ds.pixel_unit == "um"
    assert ds.pixel_size == pytest.approx(1.5)


# ── ImageJ + baseline resolution tags ────────────────────────────────

def test_imagej_unit_and_resolution(tmp_path) -> None:
    """A DM image exported through Fiji keeps its nm/px in `unit=` plus
    XResolution — 1.102271 px/nm is the corpus file's spacing."""
    frame = np.arange(64 * 64, dtype=np.uint16).reshape(64, 64)
    ds = load_tiff(write_imagej_tiff(tmp_path / "ij.tif", frame))
    assert ds.pixel_unit == "nm"
    assert ds.pixel_size == pytest.approx(1 / 1.102271, rel=1e-9)
    assert ds.metadata["calibration_source"] == "imagej"


def test_imagej_micron_spellings(tmp_path) -> None:
    """ImageJ spells microns several ways; all must land on the same scale.
    (Only the ASCII spellings are written here — a TIFF ImageDescription is
    7-bit ASCII, so `µm` only reaches us through byte-valued vendor tags,
    which the Zeiss case above exercises.)"""
    frame = np.arange(64 * 64, dtype=np.uint16).reshape(64, 64)
    for i, unit in enumerate(("micron", "um")):
        ds = load_tiff(
            write_imagej_tiff(tmp_path / f"u{i}.tif", frame, unit=unit, pixels_per_unit=4.0)
        )
        assert ds.pixel_unit == "nm", unit
        assert ds.pixel_size == pytest.approx(250.0), unit  # 0.25 µm


def test_imagej_pixel_unit_stays_uncalibrated(tmp_path) -> None:
    """`unit=pixel` means "no calibration", not "1 pixel per pixel"."""
    frame = np.arange(64 * 64, dtype=np.uint16).reshape(64, 64)
    ds = load_tiff(
        write_imagej_tiff(tmp_path / "px.tif", frame, unit="pixel", pixels_per_unit=1.0)
    )
    assert not ds.axes[1].calibrated
    assert ds.pixel_unit == ""


def test_resolution_unit_inch(tmp_path) -> None:
    import tifffile

    frame = np.arange(32 * 32, dtype=np.uint8).reshape(32, 32)
    f = tmp_path / "dpi.tif"
    tifffile.imwrite(f, frame, photometric="minisblack", resolution=(2540, 2540),
                     resolutionunit="INCH")
    ds = load_tiff(f)
    # 2540 px/inch → 1/2540 inch = 10 µm per pixel
    assert ds.pixel_unit == "um"
    assert ds.pixel_size == pytest.approx(10.0, rel=1e-6)
    assert ds.metadata["calibration_source"] == "resolution_tag"


def test_resolution_unit_none_invents_nothing(tmp_path) -> None:
    """ResolutionUnit NONE means the X/YResolution pair is an aspect ratio.
    Honouring it would fabricate a calibration out of a formatting default."""
    import tifffile

    frame = np.arange(32 * 32, dtype=np.uint8).reshape(32, 32)
    f = tmp_path / "none.tif"
    tifffile.imwrite(f, frame, photometric="minisblack", resolution=(72, 72),
                     resolutionunit="NONE")
    ds = load_tiff(f)
    assert not ds.axes[1].calibrated
    assert ds.pixel_unit == ""
    assert "calibration_source" not in ds.metadata


def test_plain_tiff_has_no_calibration(tmp_path) -> None:
    import tifffile

    frame = np.arange(16 * 16, dtype=np.uint8).reshape(16, 16)
    f = tmp_path / "plain.tif"
    tifffile.imwrite(f, frame, photometric="minisblack")
    ds = load_tiff(f)
    assert not ds.axes[0].calibrated and not ds.axes[1].calibrated
    assert np.isnan(get_stage_tilt(ds.metadata)[0])


# ── registry integration ─────────────────────────────────────────────

def test_load_auto_routes_tiff_calibration(tmp_path, frame) -> None:
    for name in ("fib.tif", "fib.tiff"):
        ds = load_auto(write_fei_tiff(tmp_path / name, frame))
        assert ds.pixel_size == pytest.approx(3.4), name
        assert ds.metadata["stage_tilt_deg"] == pytest.approx(52.0, abs=1e-6), name


def test_multipage_fei_keeps_page_zero_calibration(tmp_path) -> None:
    """n_frames still records the page count; the calibration is page 0's."""
    import tifffile

    frames = np.stack([np.full((32, 32), i, dtype=np.uint16) for i in range(3)])
    f = tmp_path / "multi.tif"
    with tifffile.TiffWriter(f) as tw:
        for i, fr in enumerate(frames):
            tw.write(
                fr,
                photometric="minisblack",
                extratags=[(TAG_FEI_HELIOS, 2, 0, fei_ini(fei_sections()), True)]
                if i == 0
                else None,
            )
    ds = load_tiff(f)
    assert ds.metadata["n_frames"] == 3
    assert ds.pixel_size == pytest.approx(3.4)
