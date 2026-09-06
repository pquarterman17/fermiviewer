"""Per-user profile store, versioned edits, legacy import, applicability
(ADR 0009 §3, §7, §8).

``~/.fermiviewer/profiles.json`` beside the calibration DB, the same
temp-then-replace write and the same corrupt-file backup
(`calibration_db._load`). Shape::

    {"schema": 1, "profiles": {<id>: {<profile body>, "history": [<older bodies>]}}}

An edit never rewrites a version in place: `update_profile` appends the
current body to `history`, bumps `version`, writes the new body. A store
whose `schema` is higher than this build reads is refused (the regions
rule, ADR 0006 §8) -- reading it under this build's meaning and re-saving
would silently downgrade it.

Pure file I/O over `profiles_model`; routes adapt.
"""

from __future__ import annotations

import json
import logging
import os
import time
import warnings
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fermiviewer.io.calibration_db import _MAG_KEYS, _search, entry_spacing
from fermiviewer.io.profiles_model import (
    PROFILE_SCHEMA,
    Profile,
    ProfileError,
    Provenance,
    new_profile_id,
    profile_from_json,
    profile_to_json,
    provenance_from,
    spatial_spacing,
    text_from,
    validate_fields,
    validity_from,
)

__all__ = [
    "LEGACY_SOURCE",
    "applicability",
    "create_profile",
    "db_path",
    "delete_profile",
    "get_profile",
    "import_legacy_calibrations",
    "list_profiles",
    "profile_history",
    "update_profile",
]

LEGACY_SOURCE = "legacy calibration DB"

_log = logging.getLogger(__name__)

#: keys stated in kV (the parsers' normalised names) …
_KV_KEYS = ("beam_kv", "voltage_kV")
#: … and keys stated in VOLTS: TIA's normalised field, and the raw vendor
#: tags (DM's "Voltage", FEI's "HV") that reach metadata unconverted
_VOLT_KEYS = ("acceleration_voltage_v", "Voltage", "HV")
_CL_KEYS = ("camera_length_mm",)


def db_path() -> Path:
    """~/.fermiviewer/profiles.json (FV_PROFILES_PATH overrides -- tests)."""
    override = os.environ.get("FV_PROFILES_PATH")
    if override:
        return Path(override)
    return Path.home() / ".fermiviewer" / "profiles.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00"


# ── file ─────────────────────────────────────────────────────────────


def _empty() -> dict[str, Any]:
    return {"schema": PROFILE_SCHEMA, "profiles": {}}


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
            f"profile store at {p} is corrupt and could not be parsed; starting fresh"
            + (f" (bad file preserved at {backup})" if backup else ""),
            stacklevel=2,
        )
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        return _empty()
    schema = int(data.get("schema") or PROFILE_SCHEMA)
    if schema > PROFILE_SCHEMA:
        raise ProfileError(
            f"profile store {p} has schema {schema}; this build reads {PROFILE_SCHEMA}"
        )
    return {"schema": PROFILE_SCHEMA, "profiles": data["profiles"]}


def _save(data: dict[str, Any]) -> None:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _entry(data: dict[str, Any], profile_id: str) -> dict[str, Any]:
    entry = data["profiles"].get(profile_id)
    if not isinstance(entry, Mapping):
        raise KeyError(profile_id)
    return dict(entry)


# ── read ─────────────────────────────────────────────────────────────


def list_profiles(kind: str | None = None) -> list[Profile]:
    """Every profile's CURRENT version, name order; `kind` filters.

    A malformed entry (a hand-edited file) is skipped with a warning
    rather than hiding every other profile behind it.
    """
    out: list[Profile] = []
    for pid, raw in _load()["profiles"].items():
        try:
            profile = profile_from_json({**raw, "id": pid})
        except (ProfileError, TypeError, ValueError) as exc:
            warnings.warn(f"profile {pid!r} skipped: {exc}", stacklevel=2)
            continue
        if kind is None or profile.kind == kind:
            out.append(profile)
    out.sort(key=lambda p: (p.name.lower(), p.id))
    return out


def get_profile(profile_id: str) -> Profile | None:
    data = _load()
    try:
        return profile_from_json({**_entry(data, profile_id), "id": profile_id})
    except KeyError:
        return None


def profile_history(profile_id: str) -> list[Profile]:
    """Every version of a profile, oldest first, current last. None of
    them is the live record: a snapshot in a result compares against
    these by version."""
    data = _load()
    entry = _entry(data, profile_id)  # KeyError → caller's 404
    versions = [
        profile_from_json({**old, "id": profile_id})
        for old in entry.get("history") or ()
        if isinstance(old, Mapping)
    ]
    versions.append(profile_from_json({**entry, "id": profile_id}))
    return versions


# ── write ────────────────────────────────────────────────────────────


def _build(
    profile_id: str,
    *,
    name: str,
    kind: str,
    version: int,
    created_at: str,
    updated_at: str,
    fields: Mapping[str, Any] | None,
    text: Mapping[str, Any] | None,
    validity: Mapping[str, Any] | None,
    provenance: Mapping[str, Any] | Provenance | None,
    extra: Mapping[str, Any] | None = None,
) -> Profile:
    if not isinstance(name, str) or not name.strip():
        raise ProfileError("profile name must be non-empty")
    profile = Profile(
        id=profile_id,
        name=name.strip(),
        kind=kind,
        version=version,
        created_at=created_at,
        updated_at=updated_at,
        fields=validate_fields(kind, fields or {}),
        text=text_from(text),
        validity=validity_from(validity),
        provenance=provenance_from(provenance),
        extra=dict(extra or {}),
    )
    spatial_spacing(profile)  # half a spacing is refused at the door, not on apply
    return profile


def create_profile(
    *,
    name: str,
    kind: str,
    fields: Mapping[str, Any] | None = None,
    text: Mapping[str, Any] | None = None,
    validity: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | Provenance | None = None,
    clock: Callable[[], str] = _now,
    profile_id: str | None = None,
) -> Profile:
    """Store a new profile at version 1 and return it."""
    now = clock()
    profile = _build(
        profile_id or new_profile_id(),
        name=name, kind=kind, version=1, created_at=now, updated_at=now,
        fields=fields, text=text, validity=validity, provenance=provenance,
    )
    data = _load()
    if profile.id in data["profiles"]:
        raise ProfileError(f"profile id {profile.id!r} already exists")
    data["profiles"][profile.id] = {**profile_to_json(profile), "history": []}
    _save(data)
    return profile


def update_profile(
    profile_id: str,
    *,
    name: str | None = None,
    fields: Mapping[str, Any] | None = None,
    text: Mapping[str, Any] | None = None,
    validity: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | Provenance | None = None,
    clock: Callable[[], str] = _now,
) -> Profile:
    """The next version: given parts replace the current ones wholesale,
    omitted parts are kept. `kind` is immutable -- a detector does not
    become a microscope; make a new profile. Raises KeyError when unknown."""
    data = _load()
    entry = _entry(data, profile_id)
    current = profile_from_json({**entry, "id": profile_id})
    nxt = _build(
        profile_id,
        name=current.name if name is None else name,
        kind=current.kind,
        version=current.version + 1,
        created_at=current.created_at,
        updated_at=clock(),
        fields=(
            {k: q for k, q in current.fields.items()} if fields is None else fields
        ),
        text=current.text if text is None else text,
        validity=(
            profile_to_json(current)["validity"] if validity is None else validity
        ),
        provenance=current.provenance if provenance is None else provenance,
        extra=current.extra,
    )
    history = [h for h in entry.get("history") or () if isinstance(h, Mapping)]
    history.append({k: v for k, v in entry.items() if k != "history"})
    data["profiles"][profile_id] = {**profile_to_json(nxt), "history": history}
    _save(data)
    return nxt


def delete_profile(profile_id: str) -> bool:
    """Remove a profile and its history. Snapshots already taken into
    images and results are copies and are unaffected (ADR 0009 §6)."""
    data = _load()
    if profile_id in data["profiles"]:
        del data["profiles"][profile_id]
        _save(data)
        return True
    return False


# ── legacy import ────────────────────────────────────────────────────


def import_legacy_calibrations(
    entries: Mapping[str, Mapping[str, Any]], *, clock: Callable[[], str] = _now
) -> tuple[list[Profile], list[str]]:
    """`calibrations.json` entries → acquisition profiles (ADR 0009 §8).

    Returns ``(created, skipped)``: profiles created this call, and one
    sentence per entry left alone -- already imported (idempotent, keyed
    by ``text.legacy_key``) or malformed. The legacy file is not touched.
    """
    existing = {
        p.text.get("legacy_key") for p in list_profiles("acquisition") if "legacy_key" in p.text
    }
    created: list[Profile] = []
    skipped: list[str] = []
    for key, entry in entries.items():
        if key in existing:
            skipped.append(f"{key!r}: already imported")
            continue
        try:
            (row, col), unit = entry_spacing(dict(entry)), str(entry["unit"])
            if not unit:
                raise ValueError("unit is empty")
        except (KeyError, TypeError, ValueError) as exc:
            # the reason stays server-side: exception text is not part of
            # the response contract
            _log.warning("legacy calibration %r not imported: %s", key, exc)
            skipped.append(f"{key!r}: malformed entry")
            continue
        fields: dict[str, Any] = {
            "pixel_size_row": {"value": row, "unit": unit},
            "pixel_size_column": {"value": col, "unit": unit},
        }
        instrument, _, mag = key.partition("|")
        try:
            mag_value = float(mag)
        except ValueError:
            mag_value = float("nan")
        if mag_value > 0:
            fields["magnification"] = {"value": mag_value, "unit": ""}
        text = {"legacy_key": key}
        if instrument and instrument != "?":
            text["instrument"] = instrument
        saved = str(entry.get("saved") or "")
        created.append(
            create_profile(
                name=key,
                kind="acquisition",
                fields=fields,
                text=text,
                provenance={
                    "source": LEGACY_SOURCE,
                    "date": saved[:10] if len(saved) >= 10 else None,
                    "note": str(entry.get("note") or ""),
                },
                clock=clock,
            )
        )
        existing.add(key)
    return created, skipped


# ── applicability ────────────────────────────────────────────────────


def _number(metadata: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    for k in keys:
        v = _search(metadata, k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
        if isinstance(v, str):
            try:
                f = float(v.strip().rstrip("xX"))
            except ValueError:
                continue
            if f > 0:
                return f
    return None


def image_conditions(metadata: Mapping[str, Any]) -> dict[str, float]:
    """What the image's metadata states, in the profile's units: beam
    energy (keV), magnification, camera length (mm). Every parser spells
    the voltage differently (`beam_kv`, `voltage_kV`, a Volt-valued
    `acceleration_voltage_v`); one reader, so validity has one meaning."""
    out: dict[str, float] = {}
    kv = _number(metadata, _KV_KEYS)
    if kv is None:
        volts = _number(metadata, _VOLT_KEYS)
        kv = volts / 1000.0 if volts is not None else None
    if kv is not None:
        out["beam_energy_kev"] = kv
    mag = _number(metadata, ("magnification", *_MAG_KEYS))
    if mag is not None:
        out["magnification"] = mag
    cl = _number(metadata, _CL_KEYS)
    if cl is not None:
        out["camera_length_mm"] = cl
    return out


def applicability(
    profile: Profile, metadata: Mapping[str, Any], *, on: str | None = None
) -> tuple[str, ...]:
    """Why `profile` does not apply to an image with `metadata` -- empty
    when nothing it can check is out of range. A condition the image does
    not state is not checked (absence is not a violation). `on` is the
    date of use (ISO) for the validity window; None skips the window."""
    reasons: list[str] = []
    v = profile.validity
    stated = image_conditions(metadata)
    for name, bounds, unit in (
        ("beam_energy_kev", v.beam_energy_kev, "keV"),
        ("magnification", v.magnification, "x"),
        ("camera_length_mm", v.camera_length_mm, "mm"),
    ):
        if bounds is None or name not in stated:
            continue
        lo, hi = bounds
        value = stated[name]
        if not (lo <= value <= hi):
            reasons.append(
                f"{name.replace('_kev', '').replace('_mm', '')} {value:g} {unit} is "
                f"outside the profile's {lo:g}-{hi:g} {unit} range"
            )
    if on is not None:
        if v.valid_from and on < v.valid_from:
            reasons.append(f"used on {on}, before the profile is valid ({v.valid_from})")
        if v.valid_to and on > v.valid_to:
            reasons.append(f"used on {on}, after the profile expired ({v.valid_to})")
    return tuple(reasons)
