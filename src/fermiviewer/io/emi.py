"""FEI/TIA `.emi` experiment-file metadata — sibling lookup + XML extraction.

`.emi` is TIA's per-acquisition companion to a `.ser` pixel/spectrum file:
HT, magnification, detector, and (for EELS) energy dispersion live here,
never in the `.ser`. Real `.emi` files are OLE/CompoundFile ([MS-CFB])
containers (see `io.olefile_min`) holding an `ObjectInfo` XML block among
their streams — but empirically, every `.emi` in this project's real-data
corpus ships that XML directly with no CFB wrapper at all (confirmed: none
of them start with the CFB magic). `load_emi_metadata` handles both: it
opens the container when the CFB signature is present, and otherwise
searches the raw file bytes for the same `<ObjectInfo>...</ObjectInfo>`
marker — which is also what upstream rosettasciio's TIA reader does,
independent of whether the file is OLE-wrapped.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from fermiviewer.io.olefile_min import OleError, OleFile, is_ole

__all__ = [
    "energy_dispersion_ev",
    "find_emi_sibling",
    "load_emi_metadata",
    "parse_emi_xml",
    "pixel_size_m",
]

_OBJECT_INFO_OPEN = b"<ObjectInfo>"
_OBJECT_INFO_CLOSE = b"</ObjectInfo>"

# name/unit/value triples under ExperimentalDescription that double as
# fallback axis calibration when the .ser's own calibration is absent.
_ENERGY_DISPERSION_LABELS = ("Filter selected dispersion", "Dispersion")
_PIXEL_SIZE_LABELS = ("Pixel size", "Pixel Size", "Image pixel size")
_LENGTH_TO_M = {
    "pm": 1e-12,
    "a": 1e-10,
    "angstrom": 1e-10,
    "nm": 1e-9,
    "um": 1e-6,
    "µm": 1e-6,  # micro sign
    "mm": 1e-3,
    "m": 1.0,
}

_SIBLING_STEM_RE = re.compile(r"^(.*)_(\d+)$")


def find_emi_sibling(ser_path: str | Path) -> Path | None:
    """Locate the `.emi` paired with a `.ser`, or None if there isn't one.

    TIA writes `<stem>_N.ser` for the N-th data element of an acquisition
    described by `<stem>.emi` — e.g. a BF/DF pair writes `foo_1.ser` and
    `foo_2.ser`, both pairing to `foo.emi`. A same-stem `<name>.emi` is
    also accepted directly, for `.ser` files that don't carry a trailing
    `_N`.
    """
    ser_path = Path(ser_path)
    candidates: list[Path] = []
    m = _SIBLING_STEM_RE.match(ser_path.stem)
    if m:
        candidates.append(ser_path.with_name(m.group(1) + ".emi"))
    same_stem = ser_path.with_suffix(".emi")
    if same_stem not in candidates:
        candidates.append(same_stem)
    for c in candidates:
        if c.is_file():
            return c
    return None


def _find_object_info_bytes(buf: bytes) -> bytes | None:
    i0 = buf.find(_OBJECT_INFO_OPEN)
    if i0 == -1:
        return None
    i1 = buf.find(_OBJECT_INFO_CLOSE, i0)
    if i1 == -1:
        return None
    return buf[i0 : i1 + len(_OBJECT_INFO_CLOSE)]


def _extract_object_info_bytes(buf: bytes) -> bytes | None:
    """`<ObjectInfo>...</ObjectInfo>` bytes, searching CFB streams if the
    file is a real compound-file container, else the raw bytes directly."""
    if not is_ole(buf):
        return _find_object_info_bytes(buf)
    try:
        ole = OleFile(buf)
    except OleError:
        return _find_object_info_bytes(buf)
    for entry in ole.streams():
        xml_bytes = _find_object_info_bytes(ole.read_stream(entry))
        if xml_bytes is not None:
            return xml_bytes
    return None


def _text(elem: ET.Element | None, tag: str) -> str | None:
    found = elem.find(tag) if elem is not None else None
    return found.text if found is not None and found.text is not None else None


def _scalar_fields(root: ET.Element) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for tag, key in (("Uuid", "uuid"), ("AcquireDate", "acquire_date"),
                     ("Manufacturer", "manufacturer")):
        v = _text(root, tag)
        if v is not None:
            meta[key] = v

    av = _text(root, "ExperimentalConditions/MicroscopeConditions/AcceleratingVoltage")
    if av is not None:
        try:
            meta["acceleration_voltage_v"] = float(av)
        except ValueError:
            pass

    for tag, key in (("DetectorPixelHeight", "detector_pixel_height"),
                     ("DetectorPixelWidth", "detector_pixel_width")):
        v = _text(root, tag)
        if v is not None:
            try:
                meta[key] = int(float(v))
            except ValueError:
                pass
    return meta


def _detector_range(root: ET.Element) -> dict[str, float] | None:
    detector_range = root.find("DetectorRange")
    if detector_range is None:
        return None
    rng = {}
    for tag, key in (("StartX", "start_x"), ("EndX", "end_x"),
                     ("StartY", "start_y"), ("EndY", "end_y")):
        v = _text(detector_range, tag)
        if v is not None:
            try:
                rng[key] = float(v)
            except ValueError:
                pass
    return rng or None


def _acquire_info(root: ET.Element) -> dict[str, str] | None:
    acquire_info = root.find("AcquireInfo")
    if acquire_info is None:
        return None
    info = {child.tag: child.text for child in acquire_info if child.text}
    return info or None


def _description_fields(root: ET.Element) -> dict[str, dict[str, str]] | None:
    fields: dict[str, dict[str, str]] = {}
    for data in root.findall("ExperimentalDescription/Root/Data"):
        label = _text(data, "Label")
        if not label:
            continue
        fields[label] = {
            "value": _text(data, "Value") or "",
            "unit": _text(data, "Unit") or "",
        }
    return fields or None


def parse_emi_xml(xml_text: str) -> dict[str, Any]:
    """`<ObjectInfo>...</ObjectInfo>` XML text -> a flat metadata dict.

    Shape (all keys optional except "fields", present whenever any
    ExperimentalDescription/Root/Data entries were found)::

        {
          "uuid": str,
          "acquire_date": str,
          "manufacturer": str,
          "acceleration_voltage_v": float,
          "detector_pixel_height": int,
          "detector_pixel_width": int,
          "detector_range": {"start_x": .., "end_x": .., "start_y": .., "end_y": ..},
          "acquire_info": {tag: text, ...},        # <AcquireInfo> children
          "fields": {label: {"value": str, "unit": str}, ...},  # Label/Value/Unit triples
        }
    """
    root = ET.fromstring(xml_text)
    meta = _scalar_fields(root)
    detector_range = _detector_range(root)
    if detector_range is not None:
        meta["detector_range"] = detector_range
    acquire_info = _acquire_info(root)
    if acquire_info is not None:
        meta["acquire_info"] = acquire_info
    fields = _description_fields(root)
    if fields is not None:
        meta["fields"] = fields
    return meta


def load_emi_metadata(emi_path: str | Path) -> dict[str, Any] | None:
    """Read a paired `.emi` and return its flat ObjectInfo metadata dict.

    Returns None (never raises on malformed/absent content) when no
    `<ObjectInfo>` block is found or it doesn't parse as XML — a missing
    or corrupt `.emi` must never break loading the `.ser` it's paired
    with. File-system errors (permissions, etc.) propagate to the caller.
    """
    buf = Path(emi_path).read_bytes()
    xml_bytes = _extract_object_info_bytes(buf)
    if xml_bytes is None:
        return None
    try:
        xml_text = xml_bytes.decode("utf-8")
    except UnicodeDecodeError:
        xml_text = xml_bytes.decode("latin-1")
    try:
        return parse_emi_xml(xml_text)
    except ET.ParseError:
        return None


def energy_dispersion_ev(emi_meta: dict[str, Any]) -> float | None:
    """eV/channel dispersion from the emi Data fields, or None."""
    fields = emi_meta.get("fields", {})
    for label in _ENERGY_DISPERSION_LABELS:
        entry = fields.get(label)
        if entry is None or "ev" not in entry.get("unit", "").lower():
            continue
        try:
            return float(entry["value"])
        except (TypeError, ValueError):
            continue
    return None


def pixel_size_m(emi_meta: dict[str, Any]) -> float | None:
    """Real-space pixel size in metres from the emi Data fields, or None."""
    fields = emi_meta.get("fields", {})
    for label in _PIXEL_SIZE_LABELS:
        entry = fields.get(label)
        if entry is None:
            continue
        factor = _LENGTH_TO_M.get(entry.get("unit", "").strip().lower())
        if factor is None:
            continue
        try:
            return float(entry["value"]) * factor
        except (TypeError, ValueError):
            continue
    return None
