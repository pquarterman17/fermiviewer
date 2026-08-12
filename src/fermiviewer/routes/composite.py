"""POST /composite/register — a colour composite becomes a library image.

The composite is composed ONCE, client-side (`lib/composite.ts` is the one
blend implementation), and posted here as pixels; the server stores them
verbatim (ADR 0003 §2 — the export philosophy is "what the user was looking
at", and a server-side re-blend would be a second implementation kept in
lockstep forever). Spatial axes are inherited from the parent so the scale
bar works everywhere it works for any image; the recipe rides in metadata
as provenance for captions, not as a second rendering path.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")

#: A composite is map-sized (its dims are its parent's scan dims); this cap
#: is a sanity bound on the request body, not a product limit.
_MAX_EDGE = 4096


class CompositeRegisterRequest(BaseModel):
    parent_id: str
    name: str = Field(min_length=1, max_length=200)
    width: int = Field(ge=1, le=_MAX_EDGE)
    height: int = Field(ge=1, le=_MAX_EDGE)
    #: base64 of raw uint8 RGB, row-major, exactly height*width*3 bytes
    pixels_b64: str
    #: provenance (species, colours, blend mode, legend selection) — stored
    #: verbatim in metadata so a saved project can caption its figure
    recipe: dict[str, Any] = {}


@router.post("/composite/register")
def composite_register(req: CompositeRegisterRequest) -> ImageMeta:
    try:
        parent = store.get(req.parent_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.parent_id}") from None
    if parent.kind not in (DataKind.IMAGE, DataKind.SPECTRUM_IMAGE):
        raise HTTPException(
            400, "composite parent must be an image or spectrum image"
        )
    if (int(parent.data.shape[0]), int(parent.data.shape[1])) != (
        req.height,
        req.width,
    ):
        # the inherited calibration below is only honest at the parent's own
        # scan resolution — a mismatch is a client bug, not a resize request
        raise HTTPException(
            422,
            f"composite is {req.height}x{req.width} but its parent's spatial "
            f"dims are {parent.data.shape[0]}x{parent.data.shape[1]}",
        )
    try:
        raw = base64.b64decode(req.pixels_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "pixels_b64 is not valid base64") from None
    expected = req.height * req.width * 3
    if len(raw) != expected:
        raise HTTPException(
            422,
            f"pixel payload is {len(raw)} bytes, expected {expected} "
            f"({req.height}x{req.width}x3 uint8)",
        )
    rgb = (
        np.frombuffer(raw, dtype=np.uint8)
        .reshape(req.height, req.width, 3)
        .copy()  # frombuffer views the b64 buffer; DataStruct freezes its own
    )
    ds = DataStruct(
        data=rgb,
        kind=DataKind.RGB_IMAGE,
        axes=(parent.axes[0], parent.axes[1]),
        metadata={
            "parser": "composite",
            "source": req.name,
            "recipe": req.recipe,
        },
    )
    new_id = store.add_derived(ds, req.name, req.parent_id)
    return ImageMeta.from_datastruct(new_id, req.name, ds)
