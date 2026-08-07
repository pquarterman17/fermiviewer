"""Vendor private-tag readers for SEM/FIB TIFFs — Thermo Fisher and Zeiss.

Split from `io.tiff_meta`, which dispatches to these and owns the baseline
TIFF/ImageJ path. Both readers take an already-open `tifffile.TiffFile`,
never raise on a malformed blob, and return
``(y_cal, x_cal, metadata)`` or None when their tag is absent.

**Thermo Fisher / FEI** — tags 34682 (`FEI_HELIOS`: Helios, Scios, Quanta,
Apreo dual-beam and SEM) and 34680 (`FEI_SFEG`, older S-FEG columns). The
value is an INI blob that tifffile parses to ``{section: {key: value}}``.
``[Scan] PixelWidth/PixelHeight`` are **metres** and ``[Stage] StageT`` is
the stage tilt in **radians** (52° on a FIB lift-out is 0.9076); ``[Beam]
Beam`` names the active column, selecting the ``[EScan]``/``[IScan]`` and
``[EBeam]``/``[IBeam]`` blocks when the shared sections are absent.

**Zeiss SmartSEM** — tag 34118 (`CZ_SEM`), whose entries arrive as
``(label, value[, unit])`` tuples. The labelled entries are used rather
than the tag's unlabelled leading tuple of raw SI parameters (which
rosettasciio indexes positionally, scaled by 1024/width): the labelled
value carries fewer significant figures, but a positional index into an
undocumented tuple mis-reads silently and by a large factor.
``ap_image_pixel_size`` outranks ``ap_pixel_size`` — SmartSEM writes both,
and only the former tracks the acquisition settings actually used.

See `io.tiff_meta` for how these unit conventions were cross-checked.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from fermiviewer.datastruct import AxisCal
from fermiviewer.io.tiff_units import (
    axes_nm,
    length_to_nm,
    positive,
    put,
    tilt_deg_from_radians,
    to_float,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import tifffile

__all__ = ["fei_calibration", "zeiss_calibration"]

# Private tag codes (tifffile parses these for us; the codes are spelled out
# because that parsing is what we depend on, not the names).
_TAG_FEI_SFEG = 34680
_TAG_FEI_HELIOS = 34682
_TAG_CZ_SEM = 34118

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
    rows = positive(image.get("ResolutionY")) if isinstance(image, dict) else float("nan")
    cols = positive(image.get("ResolutionX")) if isinstance(image, dict) else float("nan")
    arr_rows, arr_cols = ((*shape, 0, 0))[:2]
    if not math.isfinite(rows):
        rows = float(arr_rows)
    if not math.isfinite(cols):
        cols = float(arr_cols)
    return rows, cols


def _fei_pixel_nm(fei: dict[str, Any], active: str, shape: tuple[int, ...]) -> tuple[float, float]:
    """(y, x) pixel size in nm from the FEI INI. All lengths are metres."""
    for sec in _fei_sections(fei, _FEI_SCAN_SECTIONS, active):
        h = positive(sec.get("PixelHeight")) * 1e9
        w = positive(sec.get("PixelWidth")) * 1e9
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
        hor = positive(sec.get(hor_key)) * 1e9
        ver = positive(sec.get(ver_key)) * 1e9
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
            tilt = tilt_deg_from_radians(sec.get(key))
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


def fei_calibration(
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

    y_cal, x_cal = axes_nm(*_fei_pixel_nm(fei, active, shape))
    meta: dict[str, Any] = {
        "calibration_source": "fei",
        "vendor": "thermofisher",
        "beam": active,
        "image_tags": _flatten(fei),
    }
    put(meta, "stage_tilt_deg", _fei_tilt_deg(fei, active))
    if isinstance(column, dict):
        put(meta, "beam_kv", to_float(column.get("HV")) / 1e3)
        put(meta, "working_distance_mm", to_float(column.get("WD")) * 1e3)
        put(meta, "scan_rotation_deg", tilt_deg_from_radians(column.get("ScanRotation")))
    if isinstance(system, dict):
        name = str(system.get("SystemType") or system.get("Type") or "").strip()
        if name:
            meta["instrument_name"] = name
    # The databar is baked into the pixels FEI ships; record its height so
    # callers can exclude it. Nothing here crops — that would change the
    # array a golden/checksum test pins.
    if isinstance(private, dict):
        put(meta, "databar_height", positive(private.get("DatabarHeight")))
    if isinstance(image, dict):
        put(meta, "image_rows", positive(image.get("ResolutionY")))
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
    return to_float(entry[1]), unit


def zeiss_calibration(
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
        px_nm = length_to_nm(value, unit)
        if math.isfinite(px_nm):
            break
    y_cal, x_cal = axes_nm(px_nm, px_nm)

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
    put(meta, "beam_kv", _cz_beam_kv(sem))
    wd, wd_unit = _cz_value(sem, "ap_wd")
    put(meta, "working_distance_mm", length_to_nm(wd, wd_unit) / 1e6)
    put(meta, "magnification", _cz_magnification(sem))
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
    mag = to_float(tokens[0])
    factor = 1.0 if len(tokens) == 1 else _CZ_MAG_MULTIPLIER.get(tokens[1].lower(), float("nan"))
    return mag * factor


def _cz_beam_kv(sem: dict[str, Any]) -> float:
    for key in ("ap_actualkv", "ap_manualkv"):
        value, unit = _cz_value(sem, key)
        if math.isfinite(value):
            return value * (1e-3 if unit.strip().lower() == "v" else 1.0)
    return float("nan")



# ────────────────────────────────────────────────────────────────────
#  Flatteners
# ────────────────────────────────────────────────────────────────────

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
