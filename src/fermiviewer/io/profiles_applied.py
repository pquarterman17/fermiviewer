"""Profiles APPLIED to an image (ADR 0009 §5): the snapshot an image
carries in its metadata, one per kind, and the resolver a consumer calls.

Split from `profiles_model.py` (the record types) under the module
ceiling: that module says what a profile IS, this one says what it means
for an image to carry one. Metadata rides the `.fvp` manifest, so the
snapshots travel with the project without the per-machine store.

Pure layer, stdlib only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fermiviewer.io.profiles_model import (
    Profile,
    ProfileError,
    Quantity,
    _quantity,
    profile_to_json,
)

__all__ = [
    "PROFILES_META_KEY",
    "applied_profiles",
    "attach_profile",
    "detach_profile",
    "profile_quantity",
    "snapshot_profile",
]

#: `DataStruct.metadata` key under which an image carries the profiles
#: applied to it, one snapshot per kind.
PROFILES_META_KEY = "profiles"


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
