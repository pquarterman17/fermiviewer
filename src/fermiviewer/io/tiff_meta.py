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
3. **ImageJ / Fiji** — ``unit=`` in the ImageDescription plus
   XResolution/YResolution (pixels per unit). This is how a Gatan DM image
   exported through ImageJ keeps its nm/px.
4. **Baseline TIFF** — XResolution/YResolution with a real ResolutionUnit
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
* FEI states **angles in radians**. NexusLIMS converts the sibling
  `ScanRotation` field with `degrees()`, and Thermo Fisher's own AutoScript
  API uses the same SI convention (metres, radians) for stage position. The
  |v| > π guard in `tiff_units.tilt_deg_from_radians` covers the alternative
  anyway.
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
from fermiviewer.io.tiff_vendor import fei_calibration, zeiss_calibration

if TYPE_CHECKING:  # pragma: no cover - typing only
    import tifffile

__all__ = ["tiff_calibration"]

_TAG_X_RESOLUTION = 282
_TAG_Y_RESOLUTION = 283
_TAG_RESOLUTION_UNIT = 296

# ResolutionUnit values that mean something physical (1 = NONE does not).
_RESUNIT_NM = {2: 2.54e7, 3: 1.0e7}  # inch, centimetre


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
        resunit = tags.valueof(_TAG_RESOLUTION_UNIT, default=1)
        unit_nm = _RESUNIT_NM.get(int(resunit) if resunit is not None else 1)
        source = "resolution_tag"
    if unit_nm is None:
        return float("nan"), float("nan"), ""
    y_nm = unit_nm / y_per if y_per > 0 else float("nan")
    x_nm = unit_nm / x_per if x_per > 0 else float("nan")
    return y_nm, x_nm, source


def _resolution_calibration(
    tf: tifffile.TiffFile,
) -> tuple[AxisCal, AxisCal, dict[str, Any]] | None:
    y_nm, x_nm, source = _resolution_nm(tf)
    if not source:
        return None
    y_cal, x_cal = axes_nm(y_nm, x_nm)
    if not (y_cal.calibrated or x_cal.calibrated):
        return None
    return y_cal, x_cal, {"calibration_source": source}


# ────────────────────────────────────────────────────────────────────
#  Entry point
# ────────────────────────────────────────────────────────────────────

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
    for extract in (
        lambda: fei_calibration(tf, shape),
        lambda: zeiss_calibration(tf),
        lambda: _resolution_calibration(tf),
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
