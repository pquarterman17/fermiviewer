"""Persistent calibration database — checklist M / plan item 21.

Per-user JSON store keyed by an (instrument, magnification) string
extracted from parser metadata; uncalibrated imports auto-apply a
matching entry. Pure file I/O — routes adapt.

An entry is ``{pixel_size, unit, note, saved}`` and, for an instrument
state whose pixels are not square, ``pixel_spacing: [row, column]`` as
well (ADR 0008 §4). ``pixel_size`` stays the COLUMN scale -- the only
field for square pixels and what every older file holds -- so a reader
that does not know about ``pixel_spacing`` keeps working, and
:func:`entry_spacing` is how a reader that does gets both extents out of
either shape of entry.

A module-level `_LOCK` (`storelock.StoreLock`) is held across each
complete read/modify/write transaction (and across reads). It excludes
both other threads -- FastAPI's threadpool -- and other *processes*
sharing the same config dir, which the launcher can produce: `server.py`
floats a second launch to another port when its health probe misses a
sibling that has bound the port but is still starting.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any

from fermiviewer.storelock import StoreLock

__all__ = [
    "db_path",
    "delete_calibration",
    "entry_spacing",
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

#: guards every read/modify/write transaction on the store, across
#: threads AND across processes (`storelock`)
_LOCK = StoreLock(lambda: db_path())


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
        # Corrupt file: preserve it for forensics instead of silently
        # letting the next _save() overwrite it, then warn and fall back
        # to an empty DB (same behaviour as before, minus the data loss).
        backup: Path | None = None
        candidate = p.with_name(f"{p.name}.corrupt-{int(time.time())}")
        try:
            os.replace(p, candidate)
            backup = candidate
        except OSError:
            pass
        warnings.warn(
            f"calibration DB at {p} is corrupt and could not be parsed; "
            f"starting fresh"
            + (f" (bad file preserved at {backup})" if backup else ""),
            stacklevel=2,
        )
        return {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file in the same directory then atomically replace,
    # so a crash/kill mid-write never leaves a half-written JSON file.
    fd = tempfile.NamedTemporaryFile(
        dir=p.parent, prefix=f"{p.name}.tmp-", delete=False
    )
    tmp = Path(fd.name)
    try:
        with fd:
            fd.write(json.dumps(data, indent=1).encode("utf-8"))
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


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
    with _LOCK:
        return _load()


def lookup(key: str) -> dict[str, Any] | None:
    with _LOCK:
        return _load().get(key)


def _positive(value: float, what: str) -> float:
    """A finite, positive length. `<= 0` alone lets NaN through, and a NaN
    or zero scale would write axes that `AxisCal.calibrated` rejects while
    the caller is told the apply succeeded; a negative one would be
    accepted as calibrated. None of those is a calibration."""
    v = float(value)
    if not math.isfinite(v) or v <= 0:
        raise ValueError(f"{what} must be positive")
    return v


def _positive_pair(spacing: tuple[float, float]) -> tuple[float, float]:
    return (
        _positive(spacing[0], "pixel_spacing extents"),
        _positive(spacing[1], "pixel_spacing extents"),
    )


def save_calibration(
    key: str,
    pixel_size: float | None,
    unit: str,
    note: str = "",
    pixel_spacing: tuple[float, float] | None = None,
) -> None:
    """Store a calibration under `key`.

    Give ``pixel_size`` for square pixels, or ``pixel_spacing`` as
    ``(row, column)`` for an instrument state whose pixels are not; the
    stored ``pixel_size`` is then the column extent, so the two names can
    never disagree in the file. Equal extents are stored as a plain
    ``pixel_size`` entry: that entry means square pixels already, and a
    redundant pair is one more place for the two to drift apart.
    """
    entry: dict[str, Any]
    if pixel_spacing is not None:
        row, col = _positive_pair(pixel_spacing)
        if pixel_size is not None and float(pixel_size) != col:
            raise ValueError("pixel_size must be the column extent of pixel_spacing")
        entry = {"pixel_size": col}
        if row != col:
            entry["pixel_spacing"] = [row, col]
    else:
        if pixel_size is None:
            raise ValueError("pixel_size must be positive")
        entry = {"pixel_size": _positive(pixel_size, "pixel_size")}
    with _LOCK:
        data = _load()
        data[key] = {
            **entry,
            "unit": unit,
            "note": note,
            "saved": time.strftime("%Y-%m-%d %H:%M"),
        }
        _save(data)


def entry_spacing(entry: dict[str, Any]) -> tuple[float, float]:
    """``(row, column)`` extents of a stored entry.

    An entry written before per-axis calibration existed has only
    ``pixel_size`` and is read as square pixels; one with
    ``pixel_spacing`` returns that pair. Either way the column extent is
    ``pixel_size``, which is what a caller that only knows about that
    field sees -- the two readers agree on the axis they share.

    Every length is checked finite and positive, the legacy one included:
    a hand-edited ``-1``, ``0`` or ``NaN`` is malformed, not a calibration,
    and raises ValueError like any other bad entry.
    """
    px = _positive(entry["pixel_size"], "pixel_size")
    spacing = entry.get("pixel_spacing")
    if spacing is None:
        return px, px
    if not isinstance(spacing, (list, tuple)) or len(spacing) != 2:
        raise ValueError("pixel_spacing must be a [row, column] pair")
    row, col = _positive_pair((float(spacing[0]), float(spacing[1])))
    if col != px:
        # a hand-edited file where the two names disagree: refuse rather
        # than apply a column extent the entry's own pixel_size denies
        raise ValueError("pixel_size must be the column extent of pixel_spacing")
    return row, col


def delete_calibration(key: str) -> bool:
    with _LOCK:
        data = _load()
        if key in data:
            del data[key]
            _save(data)
            return True
        return False
