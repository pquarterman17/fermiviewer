"""Known-composition standards: CRUD and reference regions (roadmap 5b).

Thin adapter over `io.standards_db` / `io.standards_model`, mirroring
`routes/profiles.py`: validation errors from the pure layer become 422s,
a missing id becomes a 404, and the wire shape is the stored shape.

Deriving factors FROM a standard lives in `routes/factors.py` — that
needs the spectral stack, and a client listing standards should not pull
the peak fitter in behind it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.io.standards_db import (
    add_reference_region,
    create_standard,
    delete_standard,
    get_standard,
    list_standards,
    remove_reference_region,
    standard_history,
    update_standard,
)
from fermiviewer.io.standards_model import (
    COMPOSITION_BASES,
    Standard,
    StandardError,
    normalized_fractions,
    standard_to_json,
)

router = APIRouter(prefix="/api")


def _wire(std: Standard) -> dict[str, Any]:
    """The stored body plus the normalised fractions a client would
    otherwise recompute (and could get wrong: a certificate need not sum
    to 100, and the ratios must not depend on whether it does)."""
    body = standard_to_json(std)
    body["normalized_fractions"] = normalized_fractions(std.composition)
    return body


def _get(standard_id: str) -> Standard:
    std = get_standard(standard_id)
    if std is None:
        raise HTTPException(404, f"unknown standard id: {standard_id}")
    return std


@router.get("/standards")
def standards_list() -> dict[str, Any]:
    return {"standards": [_wire(s) for s in list_standards()]}


@router.get("/standards/bases")
def standards_bases() -> dict[str, Any]:
    """The composition bases this build accepts, so a client does not
    hard-code them."""
    return {"bases": list(COMPOSITION_BASES)}


@router.get("/standards/{standard_id}")
def standards_get(standard_id: str) -> dict[str, Any]:
    return {"standard": _wire(_get(standard_id))}


@router.get("/standards/{standard_id}/history")
def standards_history(standard_id: str) -> dict[str, Any]:
    """Every version, oldest first. A derived factor set names the version
    it used, so a certificate correction never rewrites what a published
    derivation was based on."""
    _get(standard_id)
    return {"versions": [standard_to_json(s) for s in standard_history(standard_id)]}


class StandardCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    #: "wt" or "at" — NOT interchangeable, so it is required rather than
    #: defaulted: guessing costs the whole point of using a standard
    basis: str
    #: element symbol -> percent of `basis`, as a number or
    #: {value, unit: "%", sigma}
    composition: dict[str, Any]
    density: Any = None
    mass_thickness: Any = None
    thickness: Any = None
    text: dict[str, str] = {}
    regions: list[dict[str, Any]] = []
    validity: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None


@router.post("/standards")
def standards_create(req: StandardCreateRequest) -> dict[str, Any]:
    try:
        std = create_standard(
            name=req.name,
            basis=req.basis,
            composition=req.composition,
            density=req.density,
            mass_thickness=req.mass_thickness,
            thickness=req.thickness,
            text=req.text,
            regions=req.regions,
            validity=req.validity,
            provenance=req.provenance,
        )
    except StandardError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"standard": _wire(std)}


class StandardUpdateRequest(BaseModel):
    """Omitted parts are kept; a given part REPLACES its predecessor, so a
    composition can lose an element (a merge could not)."""

    name: str | None = None
    basis: str | None = None
    composition: dict[str, Any] | None = None
    density: Any = None
    mass_thickness: Any = None
    thickness: Any = None
    text: dict[str, str] | None = None
    regions: list[dict[str, Any]] | None = None
    validity: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None


@router.post("/standards/{standard_id}")
def standards_update(standard_id: str, req: StandardUpdateRequest) -> dict[str, Any]:
    _get(standard_id)
    try:
        std = update_standard(standard_id, **req.model_dump(exclude_none=True))
    except StandardError as exc:
        raise HTTPException(422, str(exc)) from None
    except KeyError:
        raise HTTPException(404, f"unknown standard id: {standard_id}") from None
    return {"standard": _wire(std)}


@router.delete("/standards/{standard_id}")
def standards_delete(standard_id: str) -> dict[str, Any]:
    if not delete_standard(standard_id):
        raise HTTPException(404, f"unknown standard id: {standard_id}")
    return {"deleted": standard_id}


class ReferenceRegionRequest(BaseModel):
    """Where this standard was measured.

    `region` and `roi` are the frozen strings every other route takes, and
    giving both is an error rather than a precedence rule — a caller
    naming two scopes has a bug that silently honouring one would hide.
    """

    label: str = Field(min_length=1)
    image_id: str = ""
    region: str = ""
    roi: str = ""
    note: str = ""


@router.post("/standards/{standard_id}/regions")
def standards_add_region(standard_id: str, req: ReferenceRegionRequest) -> dict[str, Any]:
    """Add or replace a reference region by label.

    The image id is NOT checked against the session here. A standard
    outlives the session that measured it, so a reference is resolved
    when a derivation actually reads it — where a stale id is something
    the user can act on — rather than refused at storage time, which
    would make a standard un-saveable once its session closed.
    """
    try:
        std = add_reference_region(standard_id, req.model_dump())
    except StandardError as exc:
        raise HTTPException(422, str(exc)) from None
    except KeyError:
        raise HTTPException(404, f"unknown standard id: {standard_id}") from None
    return {"standard": _wire(std)}


@router.delete("/standards/{standard_id}/regions/{label}")
def standards_remove_region(standard_id: str, label: str) -> dict[str, Any]:
    try:
        std = remove_reference_region(standard_id, label)
    except StandardError as exc:
        raise HTTPException(404, str(exc)) from None
    except KeyError:
        raise HTTPException(404, f"unknown standard id: {standard_id}") from None
    return {"standard": _wire(std)}
