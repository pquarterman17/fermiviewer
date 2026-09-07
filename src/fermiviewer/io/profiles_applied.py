"""Profiles APPLIED to an image (ADR 0009 §5): the snapshot an image
carries in its metadata, one per kind, and the resolver a consumer calls.

Split from `profiles_model.py` (the record types) under the module
ceiling: that module says what a profile IS, this one says what it means
for an image to carry one. Metadata rides the `.fvp` manifest, so the
snapshots travel with the project without the per-machine store.

Pure layer, stdlib only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fermiviewer.io.profile_units import UnitError, convert
from fermiviewer.io.profiles_model import (
    FIELD_UNITS,
    Profile,
    ProfileError,
    Quantity,
    profile_to_json,
    quantity_from,
)

__all__ = [
    "PROFILES_META_KEY",
    "ProfileValue",
    "Resolved",
    "UnitError",
    "applied_profiles",
    "attach_profile",
    "detach_profile",
    "profile_quantity",
    "profile_value",
    "resolve_param",
    "snapshot_profile",
    "snapshot_version",
]

#: `DataStruct.metadata` key under which an image carries the profiles
#: applied to it, one snapshot per kind.
PROFILES_META_KEY = "profiles"


def snapshot_version(value: Any) -> int:
    """Coerce a snapshot's `version` field to an int, defaulting to 0 for
    anything that isn't cleanly one (a float with a fractional part, a
    non-digit string, `None`, ...). Shared by `models.py` (the wire
    summary) and `results_calibration.py` (the `id@version` comparison
    key) so the same snapshot always coerces to the same version instead
    of comparing unequal to itself across the two readings."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


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
    """The `name` field of the applied `kind` profile, or None when no such
    profile or field. A typed request value must still win over this
    (ADR 0009 non-goals).

    A bare number in the snapshot takes the field's canonical unit from
    `FIELD_UNITS`. `validate_fields` writes an explicit unit for every
    known field, so that only arises for a hand-edited or foreign store --
    but resolving `takeoff_angle: 20` to a UNITLESS 20 would then hand a
    consumer a number it cannot check, which is the failure `profile_value`
    exists to make impossible.
    """
    snap = applied_profiles(metadata).get(kind)
    if snap is None:
        return None
    raw = snap.get("fields")
    if not isinstance(raw, Mapping) or name not in raw:
        return None
    try:
        return quantity_from(name, raw[name], FIELD_UNITS.get(kind, {}).get(name, ""))
    except ProfileError:
        return None


@dataclass(frozen=True)
class ProfileValue:
    """One profile field resolved into the unit a consumer asked for."""

    value: float
    unit: str
    sigma: float | None
    #: ``<kind>.<field>`` -- what was read
    field: str
    #: ``profile:<id>@<version>``, the same spelling `recalibrate_axes`
    #: writes as `calibration_source` (ADR 0009 §5)
    source: str


def profile_value(
    metadata: Mapping[str, Any], kind: str, name: str, *, unit: str
) -> ProfileValue | None:
    """The `name` field of the applied `kind` profile, restated in `unit`.

    None when there is no such profile or field. Raises `UnitError` when
    the stored unit cannot be converted to `unit`: a detector whose
    takeoff angle is recorded in some unit this build cannot read must
    stop the request, not quietly contribute a number of unknown scale to
    a published composition.

    `sigma` rides along in the same unit, so an uncertainty stated on the
    profile stays usable by the consumer.
    """
    q = profile_quantity(metadata, kind, name)
    if q is None:
        return None
    value = convert(q.value, q.unit, unit)
    sigma = None if q.sigma is None else abs(convert(q.sigma, q.unit, unit))
    snap = applied_profiles(metadata).get(kind) or {}
    ident = f"{snap.get('id', '?')}@{snapshot_version(snap.get('version'))}"
    return ProfileValue(
        value=value, unit=unit, sigma=sigma, field=f"{kind}.{name}", source=f"profile:{ident}"
    )


@dataclass(frozen=True)
class Resolved:
    """A consumer parameter after precedence, and where it came from."""

    value: float
    unit: str
    #: "request" | "profile" | "default"
    origin: str
    #: ``profile:<id>@<version>`` and the field, when origin is "profile"
    source: str | None = None
    field: str | None = None
    sigma: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """The provenance block a response reports for this parameter."""
        out: dict[str, Any] = {"value": self.value, "unit": self.unit, "origin": self.origin}
        if self.source is not None:
            out["source"] = self.source
        if self.field is not None:
            out["field"] = self.field
        if self.sigma is not None:
            out["sigma"] = self.sigma
        return out


def resolve_param(
    metadata: Mapping[str, Any],
    *,
    requested: float | None,
    candidates: Sequence[tuple[str, str]],
    unit: str,
    default: float,
) -> Resolved:
    """Precedence for one consumer parameter (ADR 0010 §2).

    An explicitly requested value ALWAYS wins -- a profile is a default,
    never an override, so a user who typed a number sees that number used.
    Otherwise the first `candidates` entry (``(kind, field)``, in order)
    that the image's applied profiles supply is used, converted into
    `unit`. With neither, the route's own documented literal.

    `UnitError` from an unconvertible stored unit propagates: the caller
    turns it into a 422 rather than falling through to `default`, because
    silently ignoring a profile the user applied and answering with a
    built-in default is the same lie in the other direction.
    """
    if requested is not None:
        return Resolved(value=float(requested), unit=unit, origin="request")
    for kind, name in candidates:
        found = profile_value(metadata, kind, name, unit=unit)
        if found is not None:
            return Resolved(
                value=found.value,
                unit=unit,
                origin="profile",
                source=found.source,
                field=found.field,
                sigma=found.sigma,
            )
    return Resolved(value=float(default), unit=unit, origin="default")
