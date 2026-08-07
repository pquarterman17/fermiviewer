"""Calibration + acquisition metadata carried inside TIFF tags.

A TIFF is a container, not a format: an SEM/FIB vendor writes its whole
acquisition record into one private tag and leaves the baseline tags
almost empty. Reading only the pixels — which is all `io.images.load_tiff`
did before this module existed — throws that away, so a Thermo Fisher
(FEI) dual-beam image opened as `.tif` came up uncalibrated and untilted
even though both numbers sit in the file.

Sources, highest priority first:

1. **Thermo Fisher / FEI** — tags 34682 (`FEI_HELIOS`, Helios/Scios/Quanta/
   Apreo dual-beam and SEM) and 34680 (`FEI_SFEG`, older S-FEG columns).
   An INI blob; tifffile parses it to ``{section: {key: value}}``.
   ``[Scan] PixelWidth/PixelHeight`` are **metres**; ``[Stage] StageT`` is
   the stage tilt in **radians** (52° on a FIB lift-out is 0.9076). The
   active column is named by ``[Beam] Beam`` = ``EBeam``/``IBeam``, which
   selects the ``[EScan]``/``[IScan]`` and ``[EBeam]``/``[IBeam]`` blocks
   when the shared ``[Scan]``/``[Stage]`` ones are absent.
2. **Zeiss SmartSEM** — tag 34118 (`CZ_SEM`); ``ap_image_pixel_size`` and
   ``ap_stage_at_t`` arrive as ``(label, value[, unit])`` tuples. These
   labelled entries are used rather than the tag's unlabelled leading tuple
   of raw SI parameters (which rosettasciio indexes positionally, scaled by
   1024/width). The labelled value carries fewer significant figures, but a
   positional index into an undocumented tuple mis-reads silently and by a
   large factor; a displayed-precision pixel size does not.
   ``ap_image_pixel_size`` outranks ``ap_pixel_size``: SmartSEM writes both,
   and only the former tracks the acquisition settings actually used.
3. **ImageJ / Fiji** — ``unit=`` in the ImageDescription plus
   XResolution/YResolution (pixels per unit). This is how a Gatan DM image
   exported through ImageJ keeps its nm/px.
4. **Baseline TIFF** — XResolution/YResolution with a real ResolutionUnit
   (inch or cm). Never trusted when ResolutionUnit is NONE: that combination
   means "aspect ratio only", and honouring it invents a calibration.

Returns AxisCals in nm (or µm above 1 µm/px — an SEM overview at mm field
width should not read "1200000 nm"), plus a flat metadata dict. Pure
parsing over an already-open `tifffile.TiffFile`; no I/O of its own.

None of these vendor layouts is a published standard, so the unit
conventions here are cross-checked against independent readers rather than
assumed:

* `[Scan] PixelWidth` is **metres**. Bio-Formats' `FEITiffReader` labels the
  raw value `UNITS.METER` unscaled, NIST's NexusLIMS Quanta extractor
  multiplies it by 1e9 to report nm, and rosettasciio's TIFF reader assigns
  it "m" — all three agree, and our synthetic fixtures reproduce
  rosettasciio's scales exactly (3.4e-9 m, 1.2e-8 m, 2e-6 m).
* FEI states **angles in radians**. NexusLIMS converts the sibling
  `ScanRotation` field with `degrees()`, and Thermo Fisher's own AutoScript
  API uses the same SI convention (metres, radians) for stage position. The
  |v| > π guard in `_tilt_deg_from_radians` covers the alternative anyway.
* Zeiss labels/units follow published LEO1550 and Merlin tag dumps:
  `Image Pixel Size = 35.94 nm`, `Stage at T = -0.1 °`, `WD = 4.1 mm`,
  `Mag = 10.00 K X`, `EHT = 5.00 kV`.
* ImageJ's own `TiffDecoder` computes `pixelWidth = 1/XResolution` and maps
  ResolutionUnit 2 → inch, 3 → cm, and 1 → no unit at all — which is why
  NONE is not honoured here.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from fermiviewer.datastruct import AxisCal

if TYPE_CHECKING:  # pragma: no cover - typing only
    import tifffile

__all__ = ["tiff_calibration"]

# Private tag codes (tifffile parses 34680/34682/34118 for us; the codes are
# spelled out here because that parsing is what we depend on, not the names).
_TAG_FEI_SFEG = 34680
_TAG_FEI_HELIOS = 34682
_TAG_CZ_SEM = 34118
_TAG_X_RESOLUTION = 282
_TAG_Y_RESOLUTION = 283
_TAG_RESOLUTION_UNIT = 296

# ResolutionUnit values that mean something physical (1 = NONE does not).
_RESUNIT_NM = {2: 2.54e7, 3: 1.0e7}  # inch, centimetre

_TO_NM: dict[str, float] = {
    "pm": 1e-3,
    "a": 0.1, "å": 0.1, "ang": 0.1, "angstrom": 0.1,
    "nm": 1.0,
    "um": 1e3, "µm": 1e3, "μm": 1e3, "micron": 1e3, "microns": 1e3, "micrometer": 1e3,
    "mm": 1e6,
    "cm": 1e7,
    "m": 1e9,
    "inch": 2.54e7, "in": 2.54e7,
}

# Above this, express the axis in µm instead of nm (SEM/FIB overviews).
_UM_THRESHOLD_NM = 1e3


def _to_float(value: Any) -> float:
    """Best-effort float; NaN for anything non-numeric. FEI/Zeiss INI values
    arrive already coerced by tifffile, but empty keys stay as ``''``."""
    if isinstance(value, bool):
        return float("nan")
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out if math.isfinite(out) else float("nan")


def _positive(value: Any) -> float:
    """`_to_float`, but a non-positive length is as useless as a missing one."""
    out = _to_float(value)
    return out if out > 0 else float("nan")


def _length_to_nm(value: Any, unit: str) -> float:
    factor = _TO_NM.get(unit.strip().lower().replace("μ", "µ"))
    if factor is None:
        return float("nan")
    return _positive(value) * factor


def _axes_nm(y_nm: float, x_nm: float) -> tuple[AxisCal, AxisCal]:
    """(y, x) AxisCals from per-pixel sizes in nm, in a readable unit.

    Both axes share one unit even when the pixels are non-square, because
    `DataStruct.pixel_unit` reports a single label for the pair. A source
    that states only one of the two gets square pixels rather than a
    half-calibrated image: `DataStruct.pixel_cal` reads the x axis alone, so
    a lone PixelHeight would otherwise be thrown away entirely.
    """
    finite = [v for v in (y_nm, x_nm) if math.isfinite(v) and v > 0]
    if not finite:
        return AxisCal(), AxisCal()
    unit, divisor = ("um", 1e3) if max(finite) >= _UM_THRESHOLD_NM else ("nm", 1.0)

    def cal(v: float) -> AxisCal:
        if not (math.isfinite(v) and v > 0):
            v = finite[0]
        return AxisCal(scale=v / divisor, origin=0.0, units=unit)

    return cal(y_nm), cal(x_nm)


def _tilt_deg_from_radians(value: Any) -> float:
    """FEI stage angles are radians. Values beyond ±π cannot be — no stage
    tilts past 180° — so those are taken as degrees already, the same
    salvage `io.metadata.get_stage_tilt` applies to unlabelled FEI keys."""
    raw = _to_float(value)
    if not math.isfinite(raw):
        return float("nan")
    return math.degrees(raw) if abs(raw) <= math.pi else raw


# ────────────────────────────────────────────────────────────────────
#  Thermo Fisher / FEI
# ────────────────────────────────────────────────────────────────────

# Order matters: the shared blocks win, then the active column's, then the
# other one's — a single-column SEM writes only [EScan], a dual-beam writes
# all three and keeps them consistent.
_FEI_SCAN_SECTIONS = ("Scan", "EScan", "IScan")
_FEI_STAGE_SECTIONS = ("Stage", "EBeam", "IBeam")
# Column blocks carrying a field width (HFW/VFW) — the last resort when no
# scan block states a pixel size at all. `IRBeam` is the navigation camera,
# whose images never get a [Scan] section.
_FEI_FIELD_SECTIONS = ("EBeam", "IBeam", "IRBeam")


def _fei_sections(fei: dict[str, Any], names: tuple[str, ...], active: str) -> list[dict]:
    """Present sections in try-order: the column-agnostic `[Scan]`/`[Stage]`
    first, then the active column's block, then the idle column's."""
    shared = [n for n in names if n in ("Scan", "Stage")]
    per_column = [n for n in names if n not in ("Scan", "Stage")]
    prefix = "I" if active == "IBeam" else "E"
    per_column.sort(key=lambda n: not n.startswith(prefix))  # stable: ties keep order
    return [fei[n] for n in (*shared, *per_column) if isinstance(fei.get(n), dict)]


def _fei_image_dims(fei: dict[str, Any], shape: tuple[int, ...]) -> tuple[float, float]:
    """(rows, cols) to divide a field width by. `[Image] ResolutionX/Y` is
    the scanned raster; the array can be taller when FEI bakes its databar
    into the file, so prefer the declared resolution."""
    image = fei.get("Image", {})
    rows = _positive(image.get("ResolutionY")) if isinstance(image, dict) else float("nan")
    cols = _positive(image.get("ResolutionX")) if isinstance(image, dict) else float("nan")
    arr_rows, arr_cols = ((*shape, 0, 0))[:2]
    if not math.isfinite(rows):
        rows = float(arr_rows)
    if not math.isfinite(cols):
        cols = float(arr_cols)
    return rows, cols


def _fei_pixel_nm(fei: dict[str, Any], active: str, shape: tuple[int, ...]) -> tuple[float, float]:
    """(y, x) pixel size in nm from the FEI INI. All lengths are metres."""
    for sec in _fei_sections(fei, _FEI_SCAN_SECTIONS, active):
        h = _positive(sec.get("PixelHeight")) * 1e9
        w = _positive(sec.get("PixelWidth")) * 1e9
        if math.isfinite(w) or math.isfinite(h):
            return h, w

    # No explicit pixel size — divide a field width by the raster instead.
    # Older Quanta exports state HorFieldsize/VerFieldsize on the scan
    # block; nav-cam and some Apreo images only state HFW/VFW on the column.
    rows, cols = _fei_image_dims(fei, shape)
    candidates = (
        *((sec, "HorFieldsize", "VerFieldsize")
          for sec in _fei_sections(fei, _FEI_SCAN_SECTIONS, active)),
        *((sec, "HFW", "VFW")
          for sec in _fei_sections(fei, _FEI_FIELD_SECTIONS, active)),
    )
    for sec, hor_key, ver_key in candidates:
        hor = _positive(sec.get(hor_key)) * 1e9
        ver = _positive(sec.get(ver_key)) * 1e9
        if not (math.isfinite(hor) and cols > 0):
            continue
        # Square pixels are the FEI norm; only trust a separate vertical
        # field width when the row count to divide it by is known.
        h = ver / rows if math.isfinite(ver) and rows > 0 else hor / cols
        return h, hor / cols
    return float("nan"), float("nan")


def _fei_tilt_deg(fei: dict[str, Any], active: str) -> float:
    """Stage tilt in degrees. `[Stage] StageT` is the dual-beam tilt a FIB
    lift-out is set up around; `StageTa` is the same angle as the column
    blocks record it."""
    for sec in _fei_sections(fei, _FEI_STAGE_SECTIONS, active):
        for key in ("StageT", "StageTa"):
            tilt = _tilt_deg_from_radians(sec.get(key))
            if math.isfinite(tilt):
                return tilt
    return float("nan")


def _fei_metadata(tf: tifffile.TiffFile) -> dict[str, Any]:
    """Merged FEI_SFEG + FEI_HELIOS INI, or {} when neither tag is present.

    Read straight off the tags rather than through `TiffFile.fei_metadata`
    so a file carrying the tag without tifffile's `is_fei` flag still
    parses, and so a malformed blob degrades to {} instead of raising.
    """
    tags = tf.pages.first.tags
    out: dict[str, Any] = {}
    for code in (_TAG_FEI_SFEG, _TAG_FEI_HELIOS):
        try:
            value = tags.valueof(code)
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(value, dict):
            out.update(value)
    return out


def _fei_calibration(
    tf: tifffile.TiffFile, shape: tuple[int, ...]
) -> tuple[AxisCal, AxisCal, dict[str, Any]] | None:
    fei = _fei_metadata(tf)
    if not fei:
        return None
    beam = fei.get("Beam", {})
    active = str(beam.get("Beam", "EBeam")) if isinstance(beam, dict) else "EBeam"
    column = fei.get(active if active in ("EBeam", "IBeam") else "EBeam", {})
    system = fei.get("System", {})
    private = fei.get("PrivateFei", {})
    image = fei.get("Image", {})

    y_cal, x_cal = _axes_nm(*_fei_pixel_nm(fei, active, shape))
    meta: dict[str, Any] = {
        "calibration_source": "fei",
        "vendor": "thermofisher",
        "beam": active,
        "image_tags": _flatten(fei),
    }
    _put(meta, "stage_tilt_deg", _fei_tilt_deg(fei, active))
    if isinstance(column, dict):
        _put(meta, "beam_kv", _to_float(column.get("HV")) / 1e3)
        _put(meta, "working_distance_mm", _to_float(column.get("WD")) * 1e3)
        _put(meta, "scan_rotation_deg", _tilt_deg_from_radians(column.get("ScanRotation")))
    if isinstance(system, dict):
        name = str(system.get("SystemType") or system.get("Type") or "").strip()
        if name:
            meta["instrument_name"] = name
    # The databar is baked into the pixels FEI ships; record its height so
    # callers can exclude it. Nothing here crops — that would change the
    # array a golden/checksum test pins.
    if isinstance(private, dict):
        _put(meta, "databar_height", _positive(private.get("DatabarHeight")))
    if isinstance(image, dict):
        _put(meta, "image_rows", _positive(image.get("ResolutionY")))
    return y_cal, x_cal, meta


# ────────────────────────────────────────────────────────────────────
#  Zeiss SmartSEM
# ────────────────────────────────────────────────────────────────────

def _cz_value(sem: dict[str, Any], key: str) -> tuple[float, str]:
    """(value, unit) for a CZ_SEM entry stored as (label, value[, unit])."""
    entry = sem.get(key)
    if not isinstance(entry, tuple) or len(entry) < 2:
        return float("nan"), ""
    unit = str(entry[2]) if len(entry) > 2 else ""
    return _to_float(entry[1]), unit


def _zeiss_calibration(
    tf: tifffile.TiffFile,
) -> tuple[AxisCal, AxisCal, dict[str, Any]] | None:
    try:
        sem = tf.pages.first.tags.valueof(_TAG_CZ_SEM)
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(sem, dict):
        return None

    px_nm = float("nan")
    for key in ("ap_image_pixel_size", "ap_pixel_size"):
        value, unit = _cz_value(sem, key)
        px_nm = _length_to_nm(value, unit)
        if math.isfinite(px_nm):
            break
    y_cal, x_cal = _axes_nm(px_nm, px_nm)

    meta: dict[str, Any] = {
        "calibration_source": "zeiss",
        "vendor": "zeiss",
        "image_tags": _flatten_cz(sem),
    }
    # SmartSEM writes stage angles in degrees, unlike FEI.
    for key in ("ap_stage_at_t", "ap_tilt_angle", "ap_stage_at_tilt"):
        tilt, _ = _cz_value(sem, key)
        if math.isfinite(tilt):
            meta["stage_tilt_deg"] = tilt
            break
    _put(meta, "beam_kv", _cz_beam_kv(sem))
    wd, wd_unit = _cz_value(sem, "ap_wd")
    _put(meta, "working_distance_mm", _length_to_nm(wd, wd_unit) / 1e6)
    _put(meta, "magnification", _cz_magnification(sem))
    name = sem.get("sv_serial_number")
    if isinstance(name, tuple) and len(name) > 1 and str(name[1]).strip():
        meta["instrument_name"] = str(name[1]).strip()
    return y_cal, x_cal, meta


# SmartSEM's magnification multiplier suffix, e.g. "10.00 K X" = 10000x.
_CZ_MAG_MULTIPLIER = {"k": 1e3, "m": 1e6}


def _cz_magnification(sem: dict[str, Any]) -> float:
    """Magnification from `ap_mag`, including the "K"/"M" suffix form.

    SmartSEM writes it as "<value> [K|M] X". tifffile's CZ_SEM reader only
    coerces a two-token "<value> <unit>" pair, so a bare "500 X" arrives as
    (500.0, "X") but the far more common "10.00 K X" arrives as an
    unsplit string and would otherwise be dropped. Both spellings appear
    in real LEO1550 and Merlin tag dumps.
    """
    value, _unit = _cz_value(sem, "ap_mag")
    if math.isfinite(value):
        return value
    entry = sem.get("ap_mag")
    raw = entry[1] if isinstance(entry, tuple) and len(entry) > 1 else None
    if not isinstance(raw, str):
        return float("nan")
    tokens = [t for t in raw.split() if t.upper() != "X"]
    if not tokens:
        return float("nan")
    mag = _to_float(tokens[0])
    factor = 1.0 if len(tokens) == 1 else _CZ_MAG_MULTIPLIER.get(tokens[1].lower(), float("nan"))
    return mag * factor


def _cz_beam_kv(sem: dict[str, Any]) -> float:
    for key in ("ap_actualkv", "ap_manualkv"):
        value, unit = _cz_value(sem, key)
        if math.isfinite(value):
            return value * (1e-3 if unit.strip().lower() == "v" else 1.0)
    return float("nan")


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
            num, den = _to_float(value[0]), _to_float(value[1])
            return num / den if den else float("nan")
        return _to_float(value)

    x_per, y_per = per_unit(_TAG_X_RESOLUTION), per_unit(_TAG_Y_RESOLUTION)
    if not (x_per > 0 or y_per > 0):
        return float("nan"), float("nan"), ""

    ij = tf.imagej_metadata or {}
    unit_nm = _TO_NM.get(str(ij.get("unit", "")).strip().lower().replace("μ", "µ"))
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
    y_cal, x_cal = _axes_nm(y_nm, x_nm)
    if not (y_cal.calibrated or x_cal.calibrated):
        return None
    return y_cal, x_cal, {"calibration_source": source}


# ────────────────────────────────────────────────────────────────────
#  Entry point
# ────────────────────────────────────────────────────────────────────

def _put(meta: dict[str, Any], key: str, value: float) -> None:
    """Record `value` only when it is a real number — a metadata dict full
    of NaN placeholders reads as "the instrument said 0", not "absent"."""
    if isinstance(value, float) and math.isfinite(value):
        meta[key] = value


def _flatten(sections: dict[str, Any]) -> dict[str, Any]:
    """INI sections → dotted scalar leaves, matching the `image_tags` shape
    dm.py/emd.py already publish (and that `_public_meta` keeps off the wire)."""
    out: dict[str, Any] = {}
    for section, body in sections.items():
        if not isinstance(body, dict):
            continue
        for key, value in body.items():
            if isinstance(value, (int, float, str, bool)):
                out[f"{section}.{key}"] = value
    return out


def _flatten_cz(sem: dict[str, Any]) -> dict[str, Any]:
    """CZ_SEM ``{key: (label, value[, unit])}`` → scalar leaves keyed by label."""
    out: dict[str, Any] = {}
    for key, entry in sem.items():
        if not key or not isinstance(entry, tuple) or len(entry) < 2:
            continue
        if isinstance(entry[1], (int, float, str, bool)):
            out[str(key)] = entry[1]
    return out


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
        lambda: _fei_calibration(tf, shape),
        lambda: _zeiss_calibration(tf),
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
