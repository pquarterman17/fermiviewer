"""Live named-region workspace API (roadmap 4B).

The `.fvp` section is server-carried, so project saves deliberately do not
accept region geometry. This thin adapter gives the browser one atomic way to
replace the live section after an edit. The wire form is exactly ADR 0006's
manifest form; `io.regions_model` remains the single parser and serializer.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, FiniteFloat

from fermiviewer.io.project_manifest import ProjectFormatError
from fermiviewer.io.regions_model import (
    load_regions,
    regions_to_manifest,
)
from fermiviewer.project_session import project

router = APIRouter(prefix="/api")

Point = tuple[FiniteFloat, FiniteFloat]
Bounds = tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]


class ShapeWire(BaseModel):
    kind: Literal["rect", "ellipse", "circle", "polygon"]
    bounds: Bounds | None = None
    outline: list[Point] | None = None
    holes: list[list[Point]] = Field(default_factory=list)


class PartWire(BaseModel):
    mode: Literal["include", "exclude"] = "include"
    shape: ShapeWire


class RegionWire(BaseModel):
    id: str = Field(min_length=1)
    name: str | None = None
    region_class: str | None = None
    parts: list[PartWire] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class RegionSetWire(BaseModel):
    id: str = Field(min_length=1)
    name: str | None = None
    image_id: str | None = None
    regions: list[RegionWire] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class RegionClassWire(BaseModel):
    id: str = Field(min_length=1)
    label: str | None = None
    color: str | None = None
    note: str | None = None


class RegionsWire(BaseModel):
    schema_version: Literal[1] = Field(alias="schema")
    classes: list[RegionClassWire] = Field(default_factory=list)
    sets: list[RegionSetWire] = Field(default_factory=list)


@router.get("/region-sets")
def list_region_sets() -> dict[str, Any]:
    state = project.current()
    return regions_to_manifest(state.region_sets, state.region_classes)


@router.post("/region-sets/replace")
def replace_region_sets(req: RegionsWire) -> dict[str, Any]:
    """Validate and atomically replace the session's complete workspace."""
    try:
        parsed = load_regions(req.model_dump(by_alias=True))
        project.replace_regions(parsed.sets, parsed.classes)
        return regions_to_manifest(parsed.sets, parsed.classes)
    except (ProjectFormatError, ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None
