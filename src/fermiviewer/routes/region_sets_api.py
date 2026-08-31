"""Live named-region workspace API (roadmap 4B).

The `.fvp` section is server-carried, so project saves deliberately do not
accept region geometry. This thin adapter gives the browser one atomic way to
replace the live section after an edit. The wire form is exactly ADR 0006's
manifest form; `io.regions_model` remains the single parser and serializer.

The two conversion routes are the same workspace seen from the other
side. A segmentation produces a LABEL MAP, and correcting one by hand
means it has to become regions, be edited, and become a label map again
without the trip changing which pixels belong to what — `calc/
region_convert.py` is that conversion and this is where it is reachable
from. `from-labels` only READS the store and returns a set for the caller
to merge, so `/replace` stays the single path that writes the live
section; `to-labels` registers a derived image, which is what every
analysis route already does with a map it produces.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, FiniteFloat

from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.calc.region_convert import labels_to_regions, regions_to_labels
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.io.project_manifest import ProjectFormatError
from fermiviewer.io.regions_model import (
    RegionSet,
    load_regions,
    regions_to_manifest,
)
from fermiviewer.project_session import project
from fermiviewer.region_resolve import (
    RegionReferenceError,
    _check_image,
    _resolve_reference,
)
from fermiviewer.routes._arrays import value_error_as_422 as _as_422
from fermiviewer.routes.structure import _register
from fermiviewer.session import UnknownImageError, store

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


class FromLabelsRequest(BaseModel):
    """Turn a session label map into an editable region set."""

    image_id: str = Field(min_length=1)
    set_id: str = Field(min_length=1)
    name: str | None = None
    prefix: str = Field(default="label", min_length=1)
    #: Record the source image on the set (ADR 0006 `image_id`). A region
    #: traced from THIS map means nothing on another specimen, so binding
    #: is the honest default; a caller who wants the shapes to apply
    #: everywhere unbinds deliberately.
    bind_image: bool = True


class ToLabelsRequest(BaseModel):
    """Rasterize a named region set back into a label map."""

    set_id: str = Field(min_length=1)
    #: The image whose raster gives the output SHAPE — and, when the set
    #: is bound, the image the set must belong to.
    image_id: str = Field(min_length=1)
    #: region id → label value. Omitted, regions take 1..n in set order.
    values: dict[str, int] | None = None


def _label_array(ds: DataStruct, image_id: str) -> np.ndarray:
    """A session image as an integer label map, or a 422.

    The seam this exists for: `_register` stores every derived map as
    float64, so the label map a segmentation route hands back is
    `array([1., 2., ...])`. `labels_to_regions` refuses a float array
    because 1.9999 is label 1 or label 2 depending on a convention it
    cannot know — and casting here without checking would step straight
    past that refusal at the one boundary it was written to guard.

    So the values are checked to BE integers before being typed as them.
    A genuine intensity image reaching this route is the likely mistake,
    and it gets told what it is rather than coming back as a region per
    grey level.
    """
    if ds.kind is not DataKind.IMAGE:
        # `raster_of` would answer for a spectrum image (a SUM over the
        # energy axis) and for RGB (a luminance), and both can come out
        # whole-numbered — so the check below would pass and this would
        # trace a region per count. Neither is a label map, and the kind
        # says so before any values are looked at.
        raise HTTPException(
            422,
            f"image {image_id!r} is a {ds.kind.value}, not a label map",
        )
    # 2-D needs no check of its own: `DataStruct` refuses to hold an
    # IMAGE that is not, so the kind above has already settled it.
    array = np.asarray(ds.data)
    if np.issubdtype(array.dtype, np.integer):
        return array
    if not np.all(np.isfinite(array)) or not np.array_equal(array, np.rint(array)):
        raise HTTPException(
            422,
            f"image {image_id!r} is not a label map: its values are not whole "
            "numbers, so which label a pixel carries is undefined",
        )
    return array.astype(np.int64)


@router.post("/region-sets/from-labels")
def region_set_from_labels(req: FromLabelsRequest) -> dict[str, Any]:
    """A label map as one region per label, holes and components kept.

    Returns the set; it is NOT added to the workspace. `/replace` is the
    one path that writes the live section, and a second one would be a
    second set of rules about what a write means — the caller merges this
    into the manifest it already holds and posts that. The conversion
    itself is then a pure function of the session store, which is also
    what makes it safe to call from a preview.
    """
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    array = _label_array(ds, req.image_id)
    with _as_422():
        regions = labels_to_regions(array, prefix=req.prefix)
    group = RegionSet(
        id=req.set_id,
        name=req.name,
        image_id=req.image_id if req.bind_image else None,
        regions=regions,
        meta={"derived_from": req.image_id, "converter": "labels"},
    )
    # Through the manifest serializer rather than a hand-built dict, so
    # the wire form cannot drift from the one `/replace` parses back.
    return regions_to_manifest((group,), ())


@router.post("/region-sets/to-labels")
def region_set_to_labels(req: ToLabelsRequest) -> dict[str, Any]:
    """A named region set as a label map, registered as a session image.

    The other half of the edit loop: convert, correct by hand, convert
    back, and re-run the analysis on the corrected map. Overlapping
    regions are refused rather than resolved — see `LabelOverlapError`.
    """
    try:
        ds = store.get(req.image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.image_id}") from None
    try:
        raster = raster_of(ds)
    except NoRasterError:
        raise HTTPException(400, "1D spectra have no raster") from None

    state = project.current()
    with _as_422():
        # `_resolve_reference` and `_check_image` are CALLED, not restated:
        # the ambiguous-reference rule and ADR 0007 §6's image binding are
        # the resolver's, and a second copy is how a rule starts meaning
        # two things (the `recipe_regions._check_image` lesson).
        group, region_id = _resolve_reference(state.region_sets, req.set_id)
        if region_id is not None:
            raise RegionReferenceError(
                f"{req.set_id!r} names a single region; a label map is made "
                "from a whole set"
            )
        _check_image(group, req.image_id)
        labels = regions_to_labels(
            group.regions, (raster.shape[0], raster.shape[1]), values=req.values
        )

    name = f"labels({group.id})"
    return _register(
        labels.astype(np.float64),
        name,
        ds,
        req.image_id,
        extra_meta={"region_source": group.id, "converter": "regions"},
    )
