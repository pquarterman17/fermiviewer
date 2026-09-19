"""What the k/ζ and σ derivations both need: a standard, and the pixels.

`routes/factors.py` derives EDS factors and `routes/factors_eels.py`
derives EELS cross-sections. The physics has nothing in common — one
inverts Cliff-Lorimer on weight fractions, the other inverts
``N ∝ I/σ`` on atomic ones — but the two questions asked BEFORE the
physics are identical: which standard is this, and which pixels of which
image am I measuring? Those answers live here so the two routes cannot
drift into disagreeing about what a `region_label` means or what counts
as a valid inline composition.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from fermiviewer.calc.raster import masked_sum_spectrum
from fermiviewer.datastruct import DataKind
from fermiviewer.io.standards_db import get_standard
from fermiviewer.io.standards_model import (
    Standard,
    StandardError,
    standard_from_json,
)
from fermiviewer.project_session import project
from fermiviewer.region_resolve import RegionReferenceError, resolve_region

__all__ = ["measurement_scope", "resolved_standard", "scoped_spectrum"]


def resolved_standard(
    standard_id: str | None,
    composition: dict[str, float] | None,
    basis: str | None,
    mass_thickness_kg_m2: float | None = None,
) -> Standard:
    """The stored standard, or a throwaway one built from the request.

    An inline composition is validated by exactly the same
    `standard_from_json` the store uses, so the two paths cannot diverge
    on what counts as a valid composition.
    """
    if standard_id:
        if composition is not None:
            raise HTTPException(
                422, "give a standard_id or an inline composition, not both"
            )
        std = get_standard(standard_id)
        if std is None:
            raise HTTPException(404, f"unknown standard id: {standard_id}")
        return std
    if not composition or basis is None:
        raise HTTPException(
            422, "give a standard_id, or an inline composition with its basis"
        )
    body: dict[str, Any] = {
        "id": "inline",
        "name": "inline composition",
        "version": 0,
        "created_at": "-",
        "updated_at": "-",
        "basis": basis,
        "composition": dict(composition),
    }
    if mass_thickness_kg_m2 is not None:
        body["mass_thickness"] = {"value": mass_thickness_kg_m2, "unit": "kg/m2"}
    try:
        return standard_from_json(body)
    except StandardError as exc:
        raise HTTPException(422, str(exc)) from None


def measurement_scope(
    std: Standard,
    *,
    image_id: str | None,
    region_label: str | None,
    region: str | None,
    roi: str | None,
) -> tuple[str, str, str]:
    """``(image_id, region, roi)`` — which pixels this derivation measures.

    The measured image is returned rather than re-read from the request
    because `region_label` resolves to one and the request's own
    `image_id` is then None: recording that would give a factor set a null
    provenance for the one thing it is a factor for.
    """
    region_ref, roi_ref = region or "", roi or ""
    if image_id is not None:
        return image_id, region_ref, roi_ref
    if not region_label:
        raise HTTPException(
            422,
            "give an image_id, or a region_label naming a stored reference region",
        )
    stored = next((r for r in std.regions if r.label == region_label), None)
    if stored is None:
        raise HTTPException(
            404, f"standard has no reference region labelled {region_label!r}"
        )
    if not stored.image_id:
        raise HTTPException(
            422,
            f"reference region {stored.label!r} records no image; it cannot be "
            "measured until one is given",
        )
    # The stored region IS the scope. A reference region that names an
    # image but no sub-region means the whole image, which is what
    # `resolve_region` already reads an empty pair as.
    if not (region or roi):
        region_ref, roi_ref = stored.region, stored.roi
    return stored.image_id, region_ref, roi_ref


def scoped_spectrum(
    ds: Any, image_id: str, region: str, roi: str
) -> tuple[Any, dict[str, Any]]:
    """The spectrum to fit, restricted to a region when one is given.

    The whole point of a reference region on a standard: a specimen has a
    matrix and inclusions, and a factor derived from the WHOLE field is a
    factor for the average of everything in it, not for the phase whose
    composition the certificate states.

    Uses `resolve_region` and `masked_sum_spectrum` -- the same pair the
    spectrum route and the `sum_spectrum` op use (ADR 0005 §1, ADR 0007
    §11) -- so a reference here selects exactly the pixels the same string
    selects anywhere else. An exact (non-rectangular) region narrows to
    its mask, not to its bounding box.
    """
    if not (region or roi):
        return ds.sum_spectrum(), {"scoped": False, "region": "", "roi": ""}
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise HTTPException(
            422, "a region needs a spectrum-image cube (a 1D spectrum has no pixels)"
        )
    grid = (int(ds.data.shape[0]), int(ds.data.shape[1]))
    try:
        resolved = resolve_region(
            grid,
            region=region,
            roi=roi,
            sets=project.current().region_sets,
            image_id=image_id,
        )
    except (RegionReferenceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None
    return masked_sum_spectrum(ds.data, resolved.rect, resolved.mask), {
        "scoped": True,
        "region": region,
        "roi": roi,
        "rect": list(resolved.rect),
        "pixel_count": resolved.pixel_count,
        "exact": resolved.is_exact,
    }
