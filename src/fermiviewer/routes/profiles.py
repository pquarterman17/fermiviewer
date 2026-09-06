"""Calibration profile endpoints (ADR 0009): the per-user store's CRUD and
history, apply/unapply on an image, and the one-shot legacy import.

Applying writes the profile's snapshot into the image's metadata (one per
kind); an acquisition profile that states a pixel spacing also writes the
spatial axes through `calibration.recalibrate_axes`, the single writer of
a spatial calibration (ADR 0008). Applicability is reported, never
enforced (ADR 0009 §3).
"""

from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.io.calibration_db import list_calibrations
from fermiviewer.io.profiles_applied import (
    applied_profiles,
    attach_profile,
    detach_profile,
    snapshot_profile,
)
from fermiviewer.io.profiles_db import (
    applicability,
    create_profile,
    delete_profile,
    get_profile,
    import_legacy_calibrations,
    list_profiles,
    profile_history,
    update_profile,
)
from fermiviewer.io.profiles_model import (
    PROFILE_KINDS,
    Profile,
    ProfileError,
    profile_to_json,
    spatial_spacing,
)
from fermiviewer.models import ImageMeta
from fermiviewer.routes.calibration import recalibrate_axes
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _get_image(img_id: str) -> DataStruct:
    try:
        return store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None


def _get_profile(profile_id: str) -> Profile:
    try:
        profile = get_profile(profile_id)
    except ProfileError as exc:
        raise HTTPException(422, str(exc)) from None
    if profile is None:
        raise HTTPException(404, f"unknown profile id: {profile_id}")
    return profile


def _today() -> str:
    return datetime.date.today().isoformat()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ── store ────────────────────────────────────────────────────────────


@router.get("/profiles")
def profiles_list(kind: str | None = None) -> dict[str, Any]:
    if kind is not None and kind not in PROFILE_KINDS:
        raise HTTPException(422, f"unknown profile kind {kind!r}")
    try:
        return {"profiles": [profile_to_json(p) for p in list_profiles(kind)]}
    except ProfileError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/profiles/kinds")
def profiles_kinds() -> dict[str, Any]:
    """The kinds and the fields each is expected to carry, with canonical
    units -- what an editor offers, straight from the model's table."""
    from fermiviewer.io.profiles_model import FIELD_UNITS

    return {"kinds": sorted(PROFILE_KINDS), "fields": FIELD_UNITS}


@router.get("/profiles/{profile_id}")
def profiles_get(profile_id: str) -> dict[str, Any]:
    return {"profile": profile_to_json(_get_profile(profile_id))}


@router.get("/profiles/{profile_id}/history")
def profiles_history(profile_id: str) -> dict[str, Any]:
    try:
        versions = profile_history(profile_id)
    except KeyError:
        raise HTTPException(404, f"unknown profile id: {profile_id}") from None
    except ProfileError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"versions": [profile_to_json(p) for p in versions]}


class ProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    kind: str
    fields: dict[str, Any] = {}
    text: dict[str, str] = {}
    validity: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None


@router.post("/profiles")
def profiles_create(req: ProfileCreateRequest) -> dict[str, Any]:
    try:
        profile = create_profile(
            name=req.name,
            kind=req.kind,
            fields=req.fields,
            text=req.text,
            validity=req.validity,
            provenance=req.provenance,
        )
    except ProfileError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"profile": profile_to_json(profile)}


class ProfileUpdateRequest(BaseModel):
    """Omitted parts are kept; a given part replaces its predecessor
    wholesale. Every accepted update is a new version (ADR 0009 §1)."""

    name: str | None = Field(default=None, min_length=1)
    fields: dict[str, Any] | None = None
    text: dict[str, str] | None = None
    validity: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None


@router.put("/profiles/{profile_id}")
def profiles_update(profile_id: str, req: ProfileUpdateRequest) -> dict[str, Any]:
    try:
        profile = update_profile(
            profile_id,
            name=req.name,
            fields=req.fields,
            text=req.text,
            validity=req.validity,
            provenance=req.provenance,
        )
    except KeyError:
        raise HTTPException(404, f"unknown profile id: {profile_id}") from None
    except ProfileError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"profile": profile_to_json(profile)}


@router.delete("/profiles/{profile_id}")
def profiles_delete(profile_id: str) -> dict[str, str]:
    try:
        deleted = delete_profile(profile_id)
    except ProfileError as exc:
        raise HTTPException(422, str(exc)) from None
    if not deleted:
        raise HTTPException(404, f"unknown profile id: {profile_id}")
    return {"deleted": profile_id}


@router.post("/profiles/import-calibrations")
def profiles_import_calibrations() -> dict[str, Any]:
    """Every legacy `calibrations.json` entry as an acquisition profile
    (ADR 0009 §8). Idempotent; the legacy file is left as it is."""
    try:
        created, skipped = import_legacy_calibrations(list_calibrations())
    except ProfileError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"created": [profile_to_json(p) for p in created], "skipped": skipped}


# ── apply ────────────────────────────────────────────────────────────


class ProfileApplyRequest(BaseModel):
    image_id: str
    profile_id: str


def _meta(img_id: str, ds: DataStruct) -> dict[str, Any]:
    return ImageMeta.from_datastruct(img_id, store.name(img_id), ds).model_dump()


@router.post("/profiles/apply")
def profiles_apply(req: ProfileApplyRequest) -> dict[str, Any]:
    """Attach a profile's snapshot to an image, replacing any earlier
    profile of the same kind. Reports why it might not apply
    (`applicability`) and proceeds regardless (ADR 0009 §3)."""
    ds = _get_image(req.image_id)
    profile = _get_profile(req.profile_id)
    try:
        spacing = spatial_spacing(profile)
    except ProfileError as exc:
        raise HTTPException(422, str(exc)) from None
    if spacing is not None and ds.kind is DataKind.SPECTRUM:
        raise HTTPException(400, "1D spectra have no spatial calibration")
    reasons = applicability(profile, ds.metadata, on=_today())
    snapshot = snapshot_profile(profile, applied_at=_now(), applicability=reasons)
    metadata = attach_profile(ds.metadata, snapshot)
    axes = ds.axes
    if spacing is not None:
        (row, col), unit = spacing
        axes = recalibrate_axes(ds, (row, col), unit).axes
        # provenance names where the SCALE came from (ADR 0008 §6, 0009 §4)
        metadata["calibration_source"] = f"profile:{profile.id}@{profile.version}"
    new_ds = DataStruct(data=ds.data, kind=ds.kind, axes=axes, metadata=metadata)
    store.replace(req.image_id, new_ds)
    return {
        "image": _meta(req.image_id, new_ds),
        "applicability": list(reasons),
    }


class ProfileUnapplyRequest(BaseModel):
    image_id: str
    kind: str


@router.post("/profiles/unapply")
def profiles_unapply(req: ProfileUnapplyRequest) -> dict[str, Any]:
    """Drop the applied profile of one kind. The spatial axes are left as
    they are: a spacing the profile wrote is now a calibration the image
    has, and `/calibration/clear` exists to remove one."""
    if req.kind not in PROFILE_KINDS:
        raise HTTPException(422, f"unknown profile kind {req.kind!r}")
    ds = _get_image(req.image_id)
    if req.kind not in applied_profiles(ds.metadata):
        raise HTTPException(404, f"no {req.kind} profile applied to {req.image_id}")
    metadata = detach_profile(ds.metadata, req.kind)
    new_ds = DataStruct(data=ds.data, kind=ds.kind, axes=ds.axes, metadata=metadata)
    store.replace(req.image_id, new_ds)
    return {"image": _meta(req.image_id, new_ds)}


@router.get("/profiles/applied/{img_id}")
def profiles_applied(img_id: str) -> dict[str, Any]:
    """The full snapshots an image carries, by kind."""
    return {"profiles": applied_profiles(_get_image(img_id).metadata)}
