"""Per-user standards store, versioned edits (roadmap 5b, first box).

``~/.fermiviewer/standards.json`` beside the profile store, with the same
rules and for the same reasons: a `StoreLock` across every complete
read/modify/write (threads AND processes), a temp-then-replace write, a
corrupt file preserved as `.corrupt-<epoch>` rather than overwritten, and
a store whose `schema` is newer than this build reads REFUSED rather than
silently downgraded.

An edit never rewrites a version in place. A factor set derived from a
standard records the standard's id AND version, so a certificate
correction must produce a new version rather than retroactively changing
what a published derivation was based on -- the same reason a profile
edit is a new version (ADR 0009 §4).

Pure file I/O over `standards_model`; routes adapt.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fermiviewer.io.standards_model import (
    STANDARD_SCHEMA,
    ReferenceRegion,
    Standard,
    StandardError,
    reference_region_from,
    standard_from_json,
    standard_to_json,
)
from fermiviewer.storelock import StoreLock

__all__ = [
    "add_reference_region",
    "create_standard",
    "db_path",
    "delete_standard",
    "get_standard",
    "list_standards",
    "remove_reference_region",
    "standard_history",
    "update_standard",
]

#: guards every read/modify/write transaction on the store, across threads
#: and across processes
_LOCK = StoreLock(lambda: db_path())


def db_path() -> Path:
    """~/.fermiviewer/standards.json (FV_STANDARDS_PATH overrides -- tests)."""
    override = os.environ.get("FV_STANDARDS_PATH")
    if override:
        return Path(override)
    return Path.home() / ".fermiviewer" / "standards.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00"


def new_standard_id() -> str:
    return uuid.uuid4().hex[:12]


def _empty() -> dict[str, Any]:
    return {"schema": STANDARD_SCHEMA, "standards": {}}


def _load() -> dict[str, Any]:
    p = db_path()
    if not p.is_file():
        return _empty()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        backup: Path | None = None
        candidate = p.with_name(f"{p.name}.corrupt-{int(time.time())}")
        try:
            os.replace(p, candidate)
            backup = candidate
        except OSError:
            pass
        warnings.warn(
            f"standards store at {p} is corrupt and could not be parsed; starting fresh"
            + (f" (bad file preserved at {backup})" if backup else ""),
            stacklevel=2,
        )
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("standards"), dict):
        return _empty()
    try:
        schema = int(data.get("schema") or STANDARD_SCHEMA)
    except (TypeError, ValueError):
        raise StandardError(f"standards store {p} has an unreadable schema") from None
    if schema > STANDARD_SCHEMA:
        raise StandardError(
            f"standards store {p} has schema {schema}; this build reads {STANDARD_SCHEMA}"
        )
    return {"schema": STANDARD_SCHEMA, "standards": data["standards"]}


def _save(data: dict[str, Any]) -> None:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(dir=p.parent, prefix=f"{p.name}.tmp-", delete=False)
    tmp = Path(fd.name)
    try:
        with fd:
            fd.write(json.dumps(data, indent=1).encode("utf-8"))
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _entry(data: dict[str, Any], standard_id: str) -> dict[str, Any]:
    entry = data["standards"].get(standard_id)
    if not isinstance(entry, Mapping):
        raise KeyError(standard_id)
    return dict(entry)


# ── read ─────────────────────────────────────────────────────────────


def list_standards() -> list[Standard]:
    """Every standard's CURRENT version, name order.

    A malformed entry (a hand-edited file) is skipped with a warning
    rather than hiding every other standard behind it.
    """
    out: list[Standard] = []
    with _LOCK:
        standards = _load()["standards"]
    for sid, raw in standards.items():
        try:
            out.append(standard_from_json({**raw, "id": sid}))
        except (StandardError, TypeError, ValueError) as exc:
            warnings.warn(f"standard {sid!r} skipped: {exc}", stacklevel=2)
            continue
    out.sort(key=lambda s: (s.name.lower(), s.id))
    return out


def get_standard(standard_id: str) -> Standard | None:
    with _LOCK:
        data = _load()
        try:
            entry = _entry(data, standard_id)
        except KeyError:
            return None
    return standard_from_json({**entry, "id": standard_id})


def standard_history(standard_id: str) -> list[Standard]:
    """Every version, oldest first, current last. A derived factor set
    names the version it used, and compares against these."""
    with _LOCK:
        data = _load()
        entry = _entry(data, standard_id)
    history = entry.get("history") or []
    out = [
        standard_from_json({**body, "id": standard_id})
        for body in history
        if isinstance(body, Mapping)
    ]
    out.append(standard_from_json({**entry, "id": standard_id}))
    out.sort(key=lambda s: s.version)
    return out


# ── write ────────────────────────────────────────────────────────────


def create_standard(
    *,
    name: str,
    basis: str,
    composition: Mapping[str, Any],
    density: Any = None,
    mass_thickness: Any = None,
    thickness: Any = None,
    text: Mapping[str, str] | None = None,
    regions: Any = None,
    validity: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> Standard:
    """Store a new standard at version 1."""
    if not str(name).strip():
        raise StandardError("a standard needs a name")
    now = _now()
    sid = new_standard_id()
    body: dict[str, Any] = {
        "id": sid,
        "schema": STANDARD_SCHEMA,
        "name": str(name).strip(),
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "basis": basis,
        "composition": dict(composition),
        "text": dict(text or {}),
        "regions": list(regions or []),
        "validity": dict(validity or {}),
        "provenance": dict(provenance or {}),
    }
    for key, value in (
        ("density", density),
        ("mass_thickness", mass_thickness),
        ("thickness", thickness),
    ):
        if value is not None:
            body[key] = value
    standard = standard_from_json(body)  # validate before touching the file
    with _LOCK:
        data = _load()
        data["standards"][sid] = {k: v for k, v in standard_to_json(standard).items() if k != "id"}
        _save(data)
    return standard


def update_standard(standard_id: str, **changes: Any) -> Standard:
    """Append the current body to `history`, bump `version`, write the new
    one. Omitted parts are kept; a given part REPLACES its predecessor
    (the ADR 0009 §4 rule -- a merge would make it impossible to remove an
    element from a composition)."""
    with _LOCK:
        data = _load()
        entry = _entry(data, standard_id)  # KeyError → caller's 404
        history = list(entry.get("history") or [])
        current = {k: v for k, v in entry.items() if k != "history"}
        body = {**current, "id": standard_id}
        for key, value in changes.items():
            if value is not None:
                body[key] = value
        body["version"] = int(entry.get("version", 1)) + 1
        body["updated_at"] = _now()
        standard = standard_from_json(body)  # validate before writing
        history.append(current)
        stored = {k: v for k, v in standard_to_json(standard).items() if k != "id"}
        data["standards"][standard_id] = {**stored, "history": history}
        _save(data)
    return standard


def delete_standard(standard_id: str) -> bool:
    with _LOCK:
        data = _load()
        existed = data["standards"].pop(standard_id, None) is not None
        if existed:
            _save(data)
    return existed


def add_reference_region(standard_id: str, raw: Mapping[str, Any]) -> Standard:
    """Add (or replace by label) one reference region.

    Replacing by label rather than appending a duplicate: re-defining
    "matrix" after moving the box is the common edit, and two regions
    with one label would make a derivation's choice arbitrary.
    """
    region = reference_region_from(raw)
    with _LOCK:
        current = get_standard(standard_id)
        if current is None:
            raise KeyError(standard_id)
        kept = [r for r in current.regions if r.label != region.label]
        return update_standard(
            standard_id,
            regions=[_region_json(r) for r in (*kept, region)],
        )


def remove_reference_region(standard_id: str, label: str) -> Standard:
    with _LOCK:
        current = get_standard(standard_id)
        if current is None:
            raise KeyError(standard_id)
        kept = [r for r in current.regions if r.label != label]
        if len(kept) == len(current.regions):
            raise StandardError(f"no reference region labelled {label!r}")
        return update_standard(standard_id, regions=[_region_json(r) for r in kept])


def _region_json(r: ReferenceRegion) -> dict[str, str]:
    return {
        "label": r.label,
        "image_id": r.image_id,
        "region": r.region,
        "roi": r.roi,
        "note": r.note,
    }
