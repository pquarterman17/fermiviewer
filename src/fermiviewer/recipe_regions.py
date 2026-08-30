"""A recipe step's named region, resolved into geometry before dispatch.

ADR 0007 §8 says an op takes geometry and only a caller may take a name,
because `ops/registry.py` requires that the pure layer never look an id
up. This module is that caller. It sits at the app layer beside
`region_resolve` for the same reason: resolving a name needs the
session-carried project, which `ops/` may not import.

A step declares `region_ref` — ``"set_id"`` or ``"set_id/region_id"`` —
and the runner replaces it with the equivalent `params["region"]`
geometry, per image, before `run_recipe` sees the step. Three properties
follow, and all three are the point:

* the op still never sees an id, so `run()` is unchanged;
* the RECORDED params carry the resolved geometry, which is what ADR
  0005 requires of a reproduction key — a batch result replays on a
  machine with no project at all;
* the substitution is per image, so the same recipe can mean a different
  rectangle on each one, which is what a named region is for.

**A whole-set reference keeps its union.** Each region in the set becomes
its own `group`, exactly the field `ops/_region_param` added for this:
flattening the regions into one parts list would let one region's
`exclude` subtract from another's pixels, and a set's regions are
independent (ADR 0007 §7).

**Per-image failure needs no new policy.** A region set bound to another
image, or one naming nothing, raises `RegionReferenceError` — and
`routes/batch_ops._run_batch` already wraps each input in its own
try/except that records `status: "error"` with the reason and carries on
to the next image. That is exactly "skip this image and say why", and it
was already there. A caller who wants a region to apply to every image in
a batch leaves the set unbound (ADR 0006 makes `image_id` optional),
which resolves everywhere; a caller who binds it is asking for it to
apply to one image, and gets told about the others rather than getting
numbers from the wrong specimen.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.regions import Region
from fermiviewer.io.regions_model import RegionSet
from fermiviewer.region_resolve import (
    RegionReferenceError,
    _find_regions,
    _resolve_reference,
)

__all__ = [
    "REGION_REF_KEY",
    "RegionReferenceError",
    "recipe_region_refs",
    "region_param_json",
    "substitute_region_refs",
]

#: The step key naming a region symbolically. Deliberately NOT `region`:
#: that is the op's geometry param, and keeping the two apart is what
#: lets the recorded params hold the resolved value while the recipe
#: source keeps the name the user wrote.
REGION_REF_KEY = "region_ref"


def _ring(ring: np.ndarray) -> list[list[float]]:
    return [[float(r), float(c)] for r, c in np.asarray(ring, dtype=np.float64)]


def region_param_json(regions: tuple[Region, ...]) -> list[dict[str, Any]]:
    """`regions` as the JSON `ops/_region_param.REGION_PARAM` accepts.

    The inverse of that module's `_shape_of`. Each REGION gets its own
    `group`, so a set of several regions round-trips as a union rather
    than as one region whose parts fight each other.
    """
    out: list[dict[str, Any]] = []
    for group, region in enumerate(regions):
        for part in region.parts:
            shape = part.shape
            item: dict[str, Any] = {
                "kind": shape.kind,
                "mode": part.mode,
                "bounds": [],
                "outline": [],
                "holes": [_ring(h) for h in shape.holes],
                "group": group,
            }
            if shape.outline is not None:
                item["outline"] = _ring(shape.outline)
            if shape.bounds is not None:
                item["bounds"] = [[float(v) for v in shape.bounds]]
            out.append(item)
    if not out:
        raise RegionReferenceError("the reference names no geometry")
    return out


def recipe_region_refs(steps: list[dict[str, Any]]) -> list[str]:
    """Every distinct `region_ref` a recipe names, in first-seen order.

    The caller checks these once, before a long batch, for the same
    reason `validate_recipe` checks input names up front.
    """
    seen: list[str] = []
    for step in steps:
        ref = step.get(REGION_REF_KEY)
        if isinstance(ref, str) and ref and ref not in seen:
            seen.append(ref)
    return seen


def substitute_region_refs(
    steps: list[dict[str, Any]],
    sets: tuple[RegionSet, ...] = (),
    image_id: str | None = None,
) -> list[dict[str, Any]]:
    """`steps` with every `region_ref` replaced by resolved geometry.

    Returns new step dicts; the caller's recipe is not mutated, because a
    batch reuses one recipe across many images and substituting in place
    would leave image 2 running image 1's geometry.

    Raises `RegionReferenceError` when a step names both a `region_ref`
    and its own `region` geometry — the same refusal ADR 0007 §5 makes for
    a region and a roi, and for the same reason: two scopes is a caller
    bug, and picking one hides it.
    """
    out: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        ref = step.get(REGION_REF_KEY)
        if not ref:
            out.append(step)
            continue
        if not isinstance(ref, str):
            raise RegionReferenceError(
                f"recipe step {i}: {REGION_REF_KEY!r} must be a string"
            )
        params = dict(step.get("params") or {})
        if params.get("region"):
            raise RegionReferenceError(
                f"recipe step {i}: give either {REGION_REF_KEY!r} or an inline "
                "'region', not both"
            )
        group, region_id = _resolve_reference(sets, ref)
        _check_image(group, image_id, ref)
        params["region"] = region_param_json(_find_regions(group, region_id))
        replaced = {k: v for k, v in step.items() if k != REGION_REF_KEY}
        replaced["params"] = params
        out.append(replaced)
    return out


def _check_image(group: RegionSet, image_id: str | None, ref: str) -> None:
    """A set drawn on another image is refused (ADR 0007 §6).

    `region_resolve._check_image` says the same thing, but its message
    names a single analysis. In a batch the useful message names the
    IMAGE that was skipped, since the caller is reading a list of
    per-input results and needs to know which one this was.
    """
    if group.image_id and image_id and group.image_id != image_id:
        raise RegionReferenceError(
            f"region set {ref!r} was drawn on image {group.image_id!r}, "
            f"not {image_id!r}"
        )
