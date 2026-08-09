"""Calibration + acquisition metadata carried inside TIFF tags.

A TIFF is a container, not a format: an SEM/FIB vendor writes its whole
acquisition record into one private tag and leaves the baseline tags
almost empty. Reading only the pixels — which is all `io.images.load_tiff`
did before this module existed — throws that away, so a Thermo Fisher
(FEI) dual-beam image opened as `.tif` came up uncalibrated and untilted
even though both numbers sit in the file.

This module owns the dispatch and the vendor-neutral sources; the private
SEM/FIB tags live in `io.tiff_vendor` and the shared unit arithmetic in
`io.tiff_units`. Sources, highest priority first:

1. **Thermo Fisher / FEI** — tags 34682 (`FEI_HELIOS`) and 34680
   (`FEI_SFEG`). See `io.tiff_vendor`.
2. **Zeiss SmartSEM** — tag 34118 (`CZ_SEM`). See `io.tiff_vendor`.
3. **Gatan DigitalMicrograph** — private tags 65003-65010 written by a
   direct DM TIFF export. See `io.tiff_vendor`.
4. **ImageJ / Fiji** — ``unit=`` in the ImageDescription plus
   XResolution/YResolution (pixels per unit). This is how a Gatan DM image
   exported through ImageJ keeps its nm/px.
5. **Baseline TIFF** — XResolution/YResolution with a real ResolutionUnit
   (inch or cm). Never trusted when ResolutionUnit is NONE: that combination
   means "aspect ratio only", and honouring it invents a calibration.

Returns AxisCals in nm (or µm above 1 µm/px — an SEM overview at mm field
width should not read "1200000 nm"), plus a flat metadata dict. Pure
parsing over an already-open `tifffile.TiffFile`; no I/O of its own.

None of the vendor layouts is a published standard, so the unit conventions
these readers rely on are cross-checked against independent implementations
rather than assumed:

* `[Scan] PixelWidth` is **metres**. Bio-Formats' `FEITiffReader` labels the
  raw value `UNITS.METER` unscaled, NIST's NexusLIMS Quanta extractor
  multiplies it by 1e9 to report nm, and rosettasciio's TIFF reader assigns
  it "m" — all three agree, and our synthetic fixtures reproduce
  rosettasciio's scales exactly (3.4e-9 m, 1.2e-8 m, 2e-6 m).
* FEI states **angles in radians**, unconditionally — see
  `tiff_units.deg_from_radians` for why the tempting "|v| > π must already be
  degrees" guard is actively wrong here. NexusLIMS converts the sibling
  `ScanRotation` field with a bare `degrees()`, and its Quanta reference file
  reads 179.9947° after that conversion, i.e. 3.141435 rad in the file.
  Thermo Fisher's own AutoScript API uses the same SI convention (metres,
  radians) for stage position.
* Zeiss labels/units follow published LEO1550 and Merlin tag dumps:
  `Image Pixel Size = 35.94 nm`, `Stage at T = -0.1 °`, `WD = 4.1 mm`,
  `Mag = 10.00 K X`, `EHT = 5.00 kV`.
* ImageJ's own `TiffDecoder` computes `pixelWidth = 1/XResolution` and maps
  ResolutionUnit 2 → inch, 3 → cm, and 1 → no unit at all — which is why
  NONE is not honoured here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fermiviewer.datastruct import AxisCal
from fermiviewer.io.tiff_units import TO_NM, axes_nm, to_float
from fermiviewer.io.tiff_vendor import (
    fei_calibration,
    gatan_calibration,
    zeiss_calibration,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import tifffile

__all__ = ["tiff_calibration"]

_TAG_X_RESOLUTION = 282
_TAG_Y_RESOLUTION = 283
_TAG_RESOLUTION_UNIT = 296

# ResolutionUnit values that mean something physical (1 = NONE does not).
_RESUNIT_NM = {2: 2.54e7, 3: 1.0e7}  # inch, centimetre

# Screen/print defaults that imaging libraries stamp on every file they
# write. All three FEI navcam images in the rosettasciio corpus carry
# XResolution = 96/1 INCH — including the one whose real field width FEI
# also states — so 96 dpi there is Windows' desktop DPI, not a measurement.
# Honouring it reported 264.583 um/px for a navigation-camera image, which
# is only coincidentally near the true 263.97 um/px.
_SCREEN_DPI = {72.0, 96.0}
_SCREEN_PX_PER_CM = {round(d / 2.54, 3) for d in _SCREEN_DPI}


# ────────────────────────────────────────────────────────────────────
#  ImageJ + baseline TIFF resolution tags
# ────────────────────────────────────────────────────────────────────

def _resolution_nm(tf: tifffile.TiffFile) -> tuple[float, float, str]:
    """(y, x) pixel size in nm plus the source label, from XResolution/
    YResolution. ImageJ's ``unit=`` overrides ResolutionUnit; a bare
    ResolutionUnit of NONE means the tags are only an aspect ratio."""
    tags = tf.pages.first.tags

    def per_unit(code: int) -> float:
        value = tags.valueof(code, default=None)
        if isinstance(value, tuple) and len(value) == 2:
            num, den = to_float(value[0]), to_float(value[1])
            return num / den if den else float("nan")
        return to_float(value)

    x_per, y_per = per_unit(_TAG_X_RESOLUTION), per_unit(_TAG_Y_RESOLUTION)
    if not (x_per > 0 or y_per > 0):
        return float("nan"), float("nan"), ""

    ij = tf.imagej_metadata or {}
    unit_nm = TO_NM.get(str(ij.get("unit", "")).strip().lower().replace("μ", "µ"))
    source = "imagej"
    if unit_nm is None:
        resunit = int(tags.valueof(_TAG_RESOLUTION_UNIT, default=1) or 1)
        unit_nm = _RESUNIT_NM.get(resunit)
        source = "resolution_tag"
        # An ImageJ `unit=` is a deliberate statement; a bare ResolutionUnit
        # is whatever the writing library defaulted to, so screen DPI here
        # is a formatting artefact rather than a calibration.
        defaults = _SCREEN_DPI if resunit == 2 else _SCREEN_PX_PER_CM
        if any(round(v, 3) in defaults for v in (x_per, y_per) if v > 0):
            return float("nan"), float("nan"), ""
    if unit_nm is None:
        return float("nan"), float("nan"), ""
    y_nm = unit_nm / y_per if y_per > 0 else float("nan")
    x_nm = unit_nm / x_per if x_per > 0 else float("nan")
    return y_nm, x_nm, source


def _resolution_calibration(
    tf: tifffile.TiffFile, vendor_present: bool = False
) -> tuple[AxisCal, AxisCal, dict[str, Any]] | None:
    y_nm, x_nm, source = _resolution_nm(tf)
    if not source:
        return None
    if vendor_present and source == "resolution_tag":
        # The instrument wrote its own record and did not state a pixel size
        # there. The baseline tags alongside it are its imaging library's
        # defaults, so falling back to them invents a scale the instrument
        # declined to give. (ImageJ's `unit=` is exempt: that is a user's
        # explicit calibration, which can legitimately post-date the vendor.)
        return None
    y_cal, x_cal = axes_nm(y_nm, x_nm)
    if not (y_cal.calibrated or x_cal.calibrated):
        return None
    return y_cal, x_cal, {"calibration_source": source}


# ────────────────────────────────────────────────────────────────────
#  Entry point
# ────────────────────────────────────────────────────────────────────

def _note(
    seen: list[bool], found: tuple[AxisCal, AxisCal, dict[str, Any]] | None
) -> tuple[AxisCal, AxisCal, dict[str, Any]] | None:
    """Record that a vendor source recognised the file, and pass it through."""
    if found is not None:
        seen.append(True)
    return found


def tiff_calibration(
    tf: tifffile.TiffFile, shape: tuple[int, ...] = ()
) -> tuple[AxisCal, AxisCal, dict[str, Any]]:
    """(y, x) AxisCal + metadata harvested from `tf`'s tags.

    `shape` is the page's (rows, cols) — used only for the FEI field-width
    fallback. Returns blank AxisCals and an empty dict when the file carries
    no usable calibration; never raises on a malformed vendor blob.

    Every source contributes metadata (a vendor blob that states a stage tilt
    but no pixel size is still worth keeping), while the axes come from the
    first source that actually calibrates — so a sparse vendor tag alongside
    a usable ImageJ header does not cost the image its scale.
    """
    y_cal, x_cal = AxisCal(), AxisCal()
    meta: dict[str, Any] = {}
    vendor: list[bool] = []
    for extract in (
        lambda: _note(vendor, fei_calibration(tf, shape)),
        lambda: _note(vendor, zeiss_calibration(tf, shape)),
        lambda: _note(vendor, gatan_calibration(tf, shape)),
        lambda: _resolution_calibration(tf, vendor_present=any(vendor)),
    ):
        try:
            found = extract()
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if found is None:
            continue
        y, x, found_meta = found
        if not (y_cal.calibrated or x_cal.calibrated) and (y.calibrated or x.calibrated):
            y_cal, x_cal = y, x
        else:
            # `calibration_source` names where the SCALE came from, so a
            # source that did not supply one must not claim it.
            found_meta.pop("calibration_source", None)
        # First source wins on conflicts: a vendor tag is more specific than
        # the generic resolution tags it sits alongside.
        meta = {**found_meta, **meta}
    return y_cal, x_cal, meta
