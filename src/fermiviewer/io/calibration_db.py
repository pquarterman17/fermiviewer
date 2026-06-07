"""Persistent calibration database — checklist M / plan item 21.

Per-user JSON store keyed by an (instrument, magnification) string
extracted from parser metadata; uncalibrated imports auto-apply a
matching entry. Pure file I/O — routes adapt.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

__all__ = [
    "db_path",
    "delete_calibration",
    "extract_calibration_key",
    "list_calibrations",
    "lookup",
    "save_calibration",
]

_INSTRUMENT_KEYS = ("Microscope", "Instrument", "Device", "Microscope Info")
_MAG_KEYS = (
    "Indicated Magnification",
    "Actual Magnification",
    "Magnification",
    "mag",
)


def db_path() -> Path:
    """~/.fermiviewer/calibrations.json (FV_CALIB_PATH overrides — tests)."""
    override = os.environ.get("FV_CALIB_PATH")
    if override:
        return Path(override)
    return Path.home() / ".fermiviewer" / "calibrations.json"


def _load() -> dict[str, dict[str, Any]]:
    p = db_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _search(node: Any, key: str) -> Any:
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            found = _search(v, key)
            if found is not None:
                return found
    return None


def extract_calibration_key(metadata: dict[str, Any]) -> str | None:
    """'instrument|magnification' from parser metadata, or None."""
    instrument = None
    for k in _INSTRUMENT_KEYS:
        v = _search(metadata, k)
        if isinstance(v, str) and v.strip():
            instrument = v.strip()
            break
    mag = None
    for k in _MAG_KEYS:
        v = _search(metadata, k)
        if isinstance(v, (int, float)) and v > 0:
            mag = f"{float(v):g}"
            break
        if isinstance(v, str) and v.strip():
            mag = v.strip()
            break
    if instrument is None and mag is None:
        return None
    return f"{instrument or '?'}|{mag or '?'}"


def list_calibrations() -> dict[str, dict[str, Any]]:
    return _load()


def lookup(key: str) -> dict[str, Any] | None:
    return _load().get(key)


def save_calibration(
    key: str, pixel_size: float, unit: str, note: str = ""
) -> None:
    if pixel_size <= 0:
        raise ValueError("pixel_size must be positive")
    data = _load()
    data[key] = {
        "pixel_size": pixel_size,
        "unit": unit,
        "note": note,
        "saved": time.strftime("%Y-%m-%d %H:%M"),
    }
    _save(data)


def delete_calibration(key: str) -> bool:
    data = _load()
    if key in data:
        del data[key]
        _save(data)
        return True
    return False
