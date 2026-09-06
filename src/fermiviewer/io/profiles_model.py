"""Calibration profiles — the record types (ADR 0009, roadmap 5a).

A profile is a NAMED, VERSIONED description of one thing the numbers in a
result depend on but the pixels do not carry: the microscope, a detector,
a camera, or an acquisition condition set. It wraps the per-axis
`AxisCal` record (ADR 0008) rather than replacing it -- an acquisition
profile MAY state a pixel spacing, and applying it writes the axes through
the same `recalibrate_axes` every other edit uses.

Every physical field is a `Quantity` ``{value, unit, sigma}``, the same
shape a result's scalar output has (ADR 0004 §3): `sigma` is absent, not
zero, when no honest uncertainty exists. Descriptive strings (make, model,
serial, window material) live in `text`. Unknown keys ride through a load
→ re-save verbatim, as everywhere else in the project format.

Pure layer: dataclasses over plain values, stdlib only. The JSON store is
`profiles_db.py`; routes adapt.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

__all__ = [
    "FIELD_UNITS",
    "PROFILE_KEYS",
    "PROFILE_KINDS",
    "PROFILE_SCHEMA",
    "PROFILES_META_KEY",
    "SPATIAL_FIELDS",
    "Profile",
    "ProfileError",
    "Provenance",
    "Quantity",
    "Validity",
    "applied_profiles",
    "attach_profile",
    "detach_profile",
    "new_profile_id",
    "profile_from_json",
    "profile_quantity",
    "profile_to_json",
    "snapshot_profile",
    "spatial_spacing",
    "validate_fields",
]

#: `DataStruct.metadata` key under which an image carries the profiles
#: applied to it, one snapshot per kind (ADR 0009 §5). Metadata rides the
#: `.fvp` manifest, so the snapshots travel with the project.
PROFILES_META_KEY = "profiles"

#: Revision of the per-profile shape (and of the store file). Written into
#: every profile so a later build can migrate one at a time.
PROFILE_SCHEMA = 1

PROFILE_KINDS = frozenset({"microscope", "detector", "camera", "acquisition"})

#: Keys this build models on a profile entry; anything else is `extra`.
PROFILE_KEYS = frozenset(
    {
        "id",
        "schema",
        "name",
        "kind",
        "version",
        "created_at",
        "updated_at",
        "fields",
        "text",
        "validity",
        "provenance",
        # store-only: prior versions, never part of a snapshot
        "history",
    }
)

#: The physical fields each kind is expected to carry, with their canonical
#: unit. Documentation and a unit check for known names -- a profile may
#: carry a field this table does not list (a lab's own quantity), so the
#: table is a vocabulary, not a schema. Names follow the roadmap 5a boxes.
FIELD_UNITS: dict[str, dict[str, str]] = {
    "microscope": {
        "accelerating_voltage": "kV",
        "cs": "mm",
        "cc": "mm",
        "convergence_semi_angle": "mrad",
        "energy_spread": "eV",
    },
    "detector": {
        "solid_angle": "sr",
        "takeoff_angle": "deg",
        "elevation_angle": "deg",
        "azimuth_angle": "deg",
        "active_area": "mm2",
        "window_thickness": "um",
        "energy_resolution": "eV",  # FWHM at Mn Kα
        "collection_semi_angle": "mrad",  # EELS
        "efficiency": "",  # relative, dimensionless
    },
    "camera": {
        "pixel_pitch": "um",
        "binning": "",
        "gain": "counts/e",
        "readout_noise": "e",
        "camera_length_scale": "",  # nominal → effective camera length factor
    },
    "acquisition": {
        "beam_energy": "keV",
        "probe_current": "pA",
        "dwell_time": "us",
        "live_time": "s",
        "real_time": "s",
        "dead_time": "%",
        "magnification": "",
        "camera_length": "mm",
        "dose": "e/A2",
        # any length unit, but the two must agree (`spatial_spacing`): the
        # legacy calibration DB stores µm entries beside nm ones
        "pixel_size_row": "",
        "pixel_size_column": "",
    },
}

#: An acquisition profile that carries BOTH of these (same unit, positive)
#: states a pixel spacing, and applying it writes the spatial axes.
SPATIAL_FIELDS = ("pixel_size_row", "pixel_size_column")


class ProfileError(ValueError):
    """A profile that does not satisfy the contract. A `ValueError` so the
    routes' existing 422 mapping applies without a second except clause."""


def new_profile_id() -> str:
    """Mint a profile id -- the repo's stable-id convention (`session.py`)."""
    return uuid.uuid4().hex[:12]


# ── structures ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Quantity:
    """One physical value with its unit and, when honestly known, its 1σ."""

    value: float
    unit: str = ""
    sigma: float | None = None


@dataclass(frozen=True)
class Validity:
    """Where a profile applies. Every bound is optional; an absent bound is
    unbounded. Dates are ISO ``YYYY-MM-DD``; ranges are inclusive."""

    valid_from: str | None = None
    valid_to: str | None = None
    beam_energy_kev: tuple[float, float] | None = None
    magnification: tuple[float, float] | None = None
    camera_length_mm: tuple[float, float] | None = None
    note: str = ""


@dataclass(frozen=True)
class Provenance:
    """Where the numbers came from: a datasheet, a measurement, a guess."""

    source: str = ""
    date: str | None = None
    operator: str = ""
    note: str = ""


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    kind: str
    version: int = 1
    schema: int = PROFILE_SCHEMA
    created_at: str = ""
    updated_at: str = ""
    fields: dict[str, Quantity] = field(default_factory=dict)
    text: dict[str, str] = field(default_factory=dict)
    validity: Validity = field(default_factory=Validity)
    provenance: Provenance = field(default_factory=Provenance)
    extra: dict[str, Any] = field(default_factory=dict)

    def bumped(self, updated_at: str, **changes: Any) -> Profile:
        """The next version of this profile: `changes` applied, version +1."""
        return replace(self, version=self.version + 1, updated_at=updated_at, **changes)


# ── validation ───────────────────────────────────────────────────────


def _finite(value: Any, what: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ProfileError(f"{what} must be a number") from None
    if not math.isfinite(v):
        raise ProfileError(f"{what} must be finite")
    return v


def _quantity(name: str, raw: Any, default_unit: str = "") -> Quantity:
    if isinstance(raw, Quantity):
        value, unit, sigma = raw.value, raw.unit, raw.sigma
    elif isinstance(raw, Mapping):
        if "value" not in raw:
            raise ProfileError(f"field {name!r} needs a value")
        value, unit, sigma = raw["value"], raw.get("unit", default_unit), raw.get("sigma")
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # a bare number takes the field's canonical unit (documented in
        # FIELD_UNITS); for an unknown field that is no unit at all
        value, unit, sigma = raw, default_unit, None
    else:
        raise ProfileError(f"field {name!r} must be a number or {{value, unit, sigma}}")
    v = _finite(value, f"field {name!r} value")
    if not isinstance(unit, str):
        raise ProfileError(f"field {name!r} unit must be a string")
    s: float | None = None
    if sigma is not None:
        s = _finite(sigma, f"field {name!r} sigma")
        if s < 0:
            raise ProfileError(f"field {name!r} sigma must be >= 0")
    return Quantity(value=v, unit=unit, sigma=s)


def validate_fields(kind: str, raw: Mapping[str, Any]) -> dict[str, Quantity]:
    """Coerce a fields mapping to `Quantity` values, or raise `ProfileError`.

    A known field (`FIELD_UNITS[kind]`) with a canonical unit must carry
    that unit -- ``beam_energy`` stated in ``eV`` when every consumer reads
    ``keV`` is exactly the silent error profiles exist to prevent. A bare
    number, or a ``{value}`` without a unit, takes the canonical unit. A
    known dimensionless field takes any unit string; an unknown field is
    accepted as given (the table is a vocabulary, not a schema).
    """
    if kind not in PROFILE_KINDS:
        raise ProfileError(f"unknown profile kind {kind!r}")
    canonical = FIELD_UNITS[kind]
    out: dict[str, Quantity] = {}
    for name, raw_q in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ProfileError("field names must be non-empty strings")
        q = _quantity(name, raw_q, canonical.get(name, ""))
        expected = canonical.get(name)
        if expected and q.unit != expected:
            raise ProfileError(
                f"field {name!r} must be in {expected!r}, got {q.unit!r}"
            )
        out[name] = q
    return out


def _range(raw: Any, what: str) -> tuple[float, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ProfileError(f"{what} must be a [low, high] pair")
    lo, hi = _finite(raw[0], f"{what}[0]"), _finite(raw[1], f"{what}[1]")
    if lo > hi:
        raise ProfileError(f"{what} low bound exceeds high bound")
    return lo, hi


def _date(raw: Any, what: str) -> str | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or len(raw) < 10 or raw[4] != "-" or raw[7] != "-":
        raise ProfileError(f"{what} must be an ISO date (YYYY-MM-DD)")
    return raw[:10]


def validity_from(raw: Mapping[str, Any] | Validity | None) -> Validity:
    if raw is None:
        return Validity()
    if isinstance(raw, Validity):
        raw = validity_to_json(raw)
    vf, vt = _date(raw.get("valid_from"), "valid_from"), _date(raw.get("valid_to"), "valid_to")
    if vf and vt and vf > vt:
        raise ProfileError("valid_from is after valid_to")
    return Validity(
        valid_from=vf,
        valid_to=vt,
        beam_energy_kev=_range(raw.get("beam_energy_kev"), "beam_energy_kev"),
        magnification=_range(raw.get("magnification"), "magnification"),
        camera_length_mm=_range(raw.get("camera_length_mm"), "camera_length_mm"),
        note=str(raw.get("note") or ""),
    )


def provenance_from(raw: Mapping[str, Any] | Provenance | None) -> Provenance:
    if raw is None:
        return Provenance()
    if isinstance(raw, Provenance):
        return raw
    return Provenance(
        source=str(raw.get("source") or ""),
        date=_date(raw.get("date"), "provenance.date"),
        operator=str(raw.get("operator") or ""),
        note=str(raw.get("note") or ""),
    )


def text_from(raw: Mapping[str, Any] | None) -> dict[str, str]:
    if raw is None:
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not k.strip():
            raise ProfileError("text keys must be non-empty strings")
        if not isinstance(v, str):
            raise ProfileError(f"text {k!r} must be a string")
        out[k] = v
    return out


def spatial_spacing(profile: Profile) -> tuple[tuple[float, float], str] | None:
    """``((row, column), unit)`` when an acquisition profile states a pixel
    spacing, else None. Both extents must be present, positive and in the
    same unit -- half a spacing is not a spacing, and nm by µm is neither."""
    if profile.kind != "acquisition":
        return None
    row, col = (profile.fields.get(f) for f in SPATIAL_FIELDS)
    if row is None and col is None:
        return None
    if row is None or col is None:
        raise ProfileError(
            "pixel_size_row and pixel_size_column must be given together"
        )
    if row.value <= 0 or col.value <= 0 or row.unit != col.unit or not row.unit:
        raise ProfileError(
            "pixel_size_row and pixel_size_column must be positive and share a unit"
        )
    return (row.value, col.value), row.unit


# ── JSON ─────────────────────────────────────────────────────────────


def quantity_to_json(q: Quantity) -> dict[str, Any]:
    out: dict[str, Any] = {"value": q.value, "unit": q.unit}
    if q.sigma is not None:
        out["sigma"] = q.sigma
    return out


def validity_to_json(v: Validity) -> dict[str, Any]:
    return {
        "valid_from": v.valid_from,
        "valid_to": v.valid_to,
        "beam_energy_kev": list(v.beam_energy_kev) if v.beam_energy_kev else None,
        "magnification": list(v.magnification) if v.magnification else None,
        "camera_length_mm": list(v.camera_length_mm) if v.camera_length_mm else None,
        "note": v.note,
    }


def provenance_to_json(p: Provenance) -> dict[str, Any]:
    return {"source": p.source, "date": p.date, "operator": p.operator, "note": p.note}


def profile_to_json(profile: Profile) -> dict[str, Any]:
    """The profile as a JSON-safe dict -- the store entry (minus `history`)
    AND the immutable snapshot a result or an image carries. One shape, so
    a snapshot can always be read back as a `Profile`."""
    entry: dict[str, Any] = {
        "id": profile.id,
        "schema": int(profile.schema),
        "name": profile.name,
        "kind": profile.kind,
        "version": int(profile.version),
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "fields": {k: quantity_to_json(q) for k, q in profile.fields.items()},
        "text": dict(profile.text),
        "validity": validity_to_json(profile.validity),
        "provenance": provenance_to_json(profile.provenance),
    }
    for k, v in profile.extra.items():
        if k not in PROFILE_KEYS:
            entry[k] = v
    return entry


def snapshot_profile(
    profile: Profile, *, applied_at: str, applicability: tuple[str, ...] = ()
) -> dict[str, Any]:
    """The immutable copy an image (and through it, a result) carries:
    the profile body plus when it was applied and why it might not
    apply. Reads back as a `Profile` via `profile_from_json` -- the two
    additions are unmodelled keys and ride `extra`."""
    return {
        **profile_to_json(profile),
        "applied_at": applied_at,
        "applicability": list(applicability),
    }


def applied_profiles(metadata: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """``{kind: snapshot}`` for the profiles applied to an image; empty when
    none. A hand-edited or foreign value that is not a mapping of
    mappings is read as none rather than raised on every metadata read."""
    raw = metadata.get(PROFILES_META_KEY)
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(kind): dict(snap)
        for kind, snap in raw.items()
        if isinstance(snap, Mapping)
    }


def attach_profile(metadata: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `metadata` with `snapshot` as the applied profile of its
    kind, replacing any earlier one of that kind."""
    out = dict(metadata)
    profiles = applied_profiles(out)
    profiles[str(snapshot["kind"])] = dict(snapshot)
    out[PROFILES_META_KEY] = profiles
    return out


def detach_profile(metadata: Mapping[str, Any], kind: str) -> dict[str, Any]:
    """A copy of `metadata` without the applied profile of `kind`; the key
    goes away entirely when no profile remains."""
    out = dict(metadata)
    profiles = applied_profiles(out)
    profiles.pop(kind, None)
    if profiles:
        out[PROFILES_META_KEY] = profiles
    else:
        out.pop(PROFILES_META_KEY, None)
    return out


def profile_quantity(metadata: Mapping[str, Any], kind: str, name: str) -> Quantity | None:
    """The resolver a consumer calls for a default: the `name` field of the
    applied `kind` profile, or None when no such profile or field. A typed
    request value must still win over this (ADR 0009 non-goals)."""
    snap = applied_profiles(metadata).get(kind)
    if snap is None:
        return None
    raw = snap.get("fields")
    if not isinstance(raw, Mapping) or name not in raw:
        return None
    try:
        return _quantity(name, raw[name])
    except ProfileError:
        return None


def profile_from_json(raw: Mapping[str, Any]) -> Profile:
    """A store entry or snapshot back as a `Profile`, validated."""
    try:
        pid = str(raw["id"])
        name = str(raw["name"])
        kind = str(raw["kind"])
    except KeyError as exc:
        raise ProfileError(f"profile is missing {exc.args[0]!r}") from None
    if not pid.strip() or not name.strip():
        raise ProfileError("profile id and name must be non-empty")
    schema = int(raw.get("schema") or PROFILE_SCHEMA)
    if schema > PROFILE_SCHEMA:
        # refusing is the safe failure: reading a later revision under this
        # build's meaning and re-saving it would silently downgrade it
        raise ProfileError(
            f"profile {pid!r} has schema {schema}; this build reads {PROFILE_SCHEMA}"
        )
    version = int(raw.get("version") or 1)
    if version < 1:
        raise ProfileError("profile version must be >= 1")
    return Profile(
        id=pid,
        name=name,
        kind=kind,
        version=version,
        schema=schema,
        created_at=str(raw.get("created_at") or ""),
        updated_at=str(raw.get("updated_at") or ""),
        fields=validate_fields(kind, raw.get("fields") or {}),
        text=text_from(raw.get("text")),
        validity=validity_from(raw.get("validity")),
        provenance=provenance_from(raw.get("provenance")),
        extra={k: v for k, v in raw.items() if k not in PROFILE_KEYS},
    )
