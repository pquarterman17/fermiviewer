"""Named region sets in the `.fvp` — roadmap item 4's persistence box.

`calc/regions` defines what a region IS. This module is how a project
remembers one: the `regions` manifest section, holding the named sets a
user drew and the class vocabulary they labelled them with.

## What this supersedes, and what it does not

Three things in this repo already store something region-shaped, and it
is worth being exact about which one this replaces:

* **`ui_state.savedRois`** — the ROI Manager's list, carried verbatim as
  unmodelled presentational state (ADR 0002 §5). It has no schema, no
  coordinate convention, and no way for an analysis to consume it. THIS
  is what the section supersedes.
* **`measures`** — drawn annotations in normalized 0–1 `(x, y)`, whose
  areas are deliberately derived rather than stored. A measure is a thing
  the user drew to READ a number off; a region is a thing an analysis
  runs INSIDE. They stay separate.
* **`results[].regions`** — a JSON snapshot of the geometry an analysis
  actually used, frozen at compute time so a reopened project can say
  what was measured even if the region has since been edited. It is a
  historical record, not a live set, and keeping the two apart is the
  point: editing a set must not rewrite what a past result reports.

## No `convention` string

The three sites that populate `results[].regions` each describe their
coordinates in English prose, in three mutually inconsistent spellings
(`"(row, col), 1-based"` in one, "0-based, half-open" in another). That
is the disease item 4 exists to cure, so this section does not carry a
prose convention field at all. `schema` is the convention: schema 1 means
`calc.regions` — 0-based `(row, col)`, float, INCLUSIVE bounds, rings
implicitly closed. A reader that knows the number knows the geometry.

## Geometry is stored inline, not as members

`results` puts large arrays in ZIP members because a spectrum cube has no
business in a JSON document. Region outlines are different, and I
measured rather than assumed: a 7,285-point traced contour is 120.5 KiB
as JSON against 114.0 KiB as `.npy` — 1.1x, because `.npy` pays 16 bytes
per point for float64 either way. JSON also round-trips float64 exactly
(`repr` is shortest-round-trip), so there is no precision argument
either. A bounds shape is 20 bytes.

What inline storage does cost is that the manifest is parsed WHOLE on
every project open, so a set of many traced contours is paid for just to
list the file. Hand-drawn regions — what this box is about — are a few
hundred points. Regions traced from segmentation labels are a later item
4 box, and if they land here in bulk this is the decision to revisit:
adding an optional `member` beside `outline` is a compatible change,
because the schema permits unknown properties throughout.

## Strict on save, precise on load

`validate_manifest` runs before a container is committed AND on every
load, so the JSON schema is the enforcement point at both ends and
carries the discriminated-variant rules (a polygon has an `outline` and
no `bounds`; everything else the reverse). `Shape.__post_init__` then has
nothing left to reject on schema-valid input — but it raises `ValueError`
for the invariants JSON Schema cannot express, so `load_regions` turns
those into `ProjectFormatError` naming the region. A `.fvp` is a file a
stranger can send; it may fail to load, but not with a raw `ValueError`
from three layers down.

Pure layer: stdlib + numpy + `fermiviewer.calc.regions`. No pydantic, no
routes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from fermiviewer.calc.regions import Part, Region, Shape
from fermiviewer.io.project_sections import finite_json

__all__ = [
    "REGIONS_SCHEMA",
    "RegionClass",
    "RegionSet",
    "free_set_id",
    "load_regions",
    "regions_to_manifest",
    "same_region_set",
]

#: Version of the `regions` section's own structure, written into it and
#: read back. Independent of the container's `VERSION`, exactly as
#: `RESULT_SCHEMA` is: a region set can gain a field without re-versioning
#: the `.fvp`, and an older set stays readable. It is also the ONLY
#: statement of the coordinate convention — see the module docstring.
REGIONS_SCHEMA = 1


@dataclass(frozen=True)
class RegionClass:
    """One entry in the project's class vocabulary.

    `Region.region_class` is free text and the contract says the
    vocabulary is the user's, so this registry is DESCRIPTIVE: it gives a
    class a display label and a colour, and a region may carry a class
    that was never declared here. Making persistence stricter than the
    contract would be a second convention, which is the failure this
    stack exists to remove — so an undeclared class round-trips intact
    and it is the UI's business whether to offer to declare it.
    """

    id: str
    label: str | None = None
    color: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class RegionSet:
    """A named group of regions drawn on one image.

    `image_id` links to `images[].id`. It is NOT validated against the
    project's images here, for the same reason an unavailable image keeps
    its reference (ADR 0002 §4): a set whose image is temporarily
    unresolvable is data to preserve, not data to drop.
    """

    id: str
    regions: tuple[Region, ...] = ()
    name: str | None = None
    image_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def _ring_json(ring: np.ndarray) -> list[list[float]]:
    return [[float(r), float(c)] for r, c in np.asarray(ring, dtype=np.float64)]


def _shape_json(shape: Shape) -> dict[str, Any]:
    """One shape as JSON. `bounds` XOR `outline`, matching the schema's
    discriminated variants and `Shape`'s own invariant."""
    out: dict[str, Any] = {"kind": shape.kind}
    if shape.outline is not None:
        out["outline"] = _ring_json(shape.outline)
    if shape.bounds is not None:
        out["bounds"] = [float(v) for v in shape.bounds]
    if shape.holes:
        out["holes"] = [_ring_json(h) for h in shape.holes]
    return out


def _region_json(region: Region) -> dict[str, Any]:
    return {
        "id": region.id,
        "name": region.name,
        "region_class": region.region_class,
        "parts": [
            {"mode": part.mode, "shape": _shape_json(part.shape)}
            for part in region.parts
        ],
        # `meta` is typed `dict[str, Any]` and is where a caller puts
        # whatever it likes, which in this app means ordinary scientific
        # metadata: a `np.float32` dose, a small ndarray, a NaN drift.
        # A numpy value reaches `json.dumps` AFTER the manifest has
        # validated and raises there, leaving a project that cannot be
        # saved at all; a NaN survives as the bare token `NaN`, which is
        # valid to `json.dumps` and rejected by every other JSON parser
        # including the browser's. `finite_json` is what `results` already
        # runs its carried values through, for exactly this.
        "meta": finite_json(region.meta) or {},
    }


def regions_to_manifest(
    sets: Sequence[RegionSet] = (),
    classes: Sequence[RegionClass] = (),
) -> dict[str, Any]:
    """The `regions` section, JSON-safe.

    Raises `ProjectFormatError` for duplicate set, region or class ids.
    Ids are how a caller addresses a set after reopening, so a duplicate
    is a silent overwrite waiting to happen — and unlike `results`, it is
    caught here rather than by member allocation, since nothing in this
    section names a ZIP entry.
    """
    from fermiviewer.io.project_manifest import ProjectFormatError

    seen_sets: set[str] = set()
    payload_sets = []
    for group in sets:
        if group.id in seen_sets:
            raise ProjectFormatError(f"duplicate region set id: {group.id!r}")
        seen_sets.add(group.id)
        seen_regions: set[str] = set()
        for region in group.regions:
            if region.id in seen_regions:
                raise ProjectFormatError(
                    f"duplicate region id {region.id!r} in set {group.id!r}"
                )
            seen_regions.add(region.id)
        payload_sets.append(
            {
                "id": group.id,
                "name": group.name,
                "image_id": group.image_id,
                "regions": [_region_json(r) for r in group.regions],
                "meta": finite_json(group.meta) or {},
            }
        )

    seen_classes: set[str] = set()
    payload_classes = []
    for entry in classes:
        if entry.id in seen_classes:
            raise ProjectFormatError(f"duplicate region class id: {entry.id!r}")
        seen_classes.add(entry.id)
        payload_classes.append(
            {
                "id": entry.id,
                "label": entry.label,
                "color": entry.color,
                "note": entry.note,
            }
        )

    return {
        "schema": REGIONS_SCHEMA,
        "classes": payload_classes,
        "sets": payload_sets,
    }


def _unique(ids: Any, what: str) -> None:
    """Reject repeated ids, naming the offender.

    Enforced on LOAD as well as on save. JSON Schema cannot express
    uniqueness by an object property, so without this a hand-edited or
    externally produced project opens with ambiguous ids and then fails
    only when the user tries to save it — the worst possible moment, since
    by then they have done work they cannot write down. An id is the
    addressing contract; two of them is not a thing this reader can
    represent.
    """
    from fermiviewer.io.project_manifest import ProjectFormatError

    seen: set[str] = set()
    for value in ids:
        if value in seen:
            raise ProjectFormatError(f"duplicate {what}: {value!r}")
        seen.add(value)


def same_region_set(a: RegionSet, b: RegionSet) -> bool:
    """Whether two sets are the same data, by value.

    Compares their SERIALIZED form rather than the objects. `Shape` is a
    frozen dataclass holding `np.ndarray` rings, so its generated
    `__eq__` returns an array and raises "truth value of an array is
    ambiguous" for any shape with an `outline` or `holes` — while working
    for a plain rect, which makes `a == b` a trap rather than a
    comparison. Serializing is also exactly the right notion of "same"
    here: two sets are the same iff they would be written to a `.fvp`
    identically.
    """
    return regions_to_manifest([a]) == regions_to_manifest([b])


def free_set_id(wanted: str, taken: Any) -> str:
    """`wanted` if it is free, else the first `wanted~2`, `wanted~3`, … that
    is not in `taken`. Deterministic, so re-running an append load twice
    produces the same ids rather than a new one each time."""
    if wanted not in taken:
        return wanted
    n = 2
    while f"{wanted}~{n}" in taken:
        n += 1
    return f"{wanted}~{n}"


def _ring(raw: Any) -> np.ndarray:
    return np.asarray([[float(p[0]), float(p[1])] for p in raw], dtype=np.float64)


def _shape(raw: Mapping[str, Any]) -> Shape:
    bounds = raw.get("bounds")
    outline = raw.get("outline")
    return Shape(
        kind=str(raw["kind"]),
        bounds=(
            (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
            if bounds is not None
            else None
        ),
        outline=_ring(outline) if outline is not None else None,
        holes=tuple(_ring(h) for h in raw.get("holes") or ()),
    )


def _region(raw: Mapping[str, Any]) -> Region:
    return Region(
        id=str(raw["id"]),
        parts=tuple(
            Part(shape=_shape(p["shape"]), mode=str(p.get("mode") or "include"))
            for p in raw.get("parts") or ()
        ),
        name=raw.get("name"),
        region_class=raw.get("region_class"),
        meta=dict(raw.get("meta") or {}),
    )


@dataclass(frozen=True)
class LoadedRegions:
    """The section as read back: the sets, and the class vocabulary."""

    sets: tuple[RegionSet, ...] = ()
    classes: tuple[RegionClass, ...] = ()


def load_regions(raw: Any) -> LoadedRegions:
    """Parse the `regions` section back into `calc.regions` values.

    The manifest has already been schema-validated by the time this runs,
    so the shape of `raw` is trusted; what is NOT trusted is the handful
    of cross-field invariants JSON Schema cannot state — a circle whose
    row and column extents disagree, a ring of two points, a region whose
    first part excludes. `Shape` and `Region` raise `ValueError` for
    those, and each is re-raised as a `ProjectFormatError` naming the set
    and region, because a caller opening someone else's project deserves
    to be told which region is malformed rather than a bare geometry
    complaint from two layers down.

    A manifest with no `regions` key — every project written before this
    section existed — yields empty tuples rather than an error. A section
    that IS present must declare a `schema` this build understands; see
    below for why an unknown one is refused rather than best-guessed.
    """
    from fermiviewer.io.project_manifest import ProjectFormatError

    if not isinstance(raw, Mapping):
        return LoadedRegions()

    # Checked HERE as well as in the JSON Schema, because the number is
    # the whole statement of the coordinate convention and this function
    # is public: a caller reaching it without `validate_manifest` must
    # not get geometry silently reinterpreted. Accepting a higher number
    # would parse a future build's regions under this build's convention
    # and then rewrite them as schema 1 on the next save, destroying the
    # newer fields — a silent downgrade precisely where the meaning of
    # the coordinates may have changed. Refusing to open is the safe
    # failure, and it is why there is no `>=` here.
    schema = raw.get("schema")
    if schema != REGIONS_SCHEMA:
        raise ProjectFormatError(
            f"unsupported regions schema {schema!r}; this build reads "
            f"schema {REGIONS_SCHEMA}. A project written by a newer build "
            f"is not opened rather than reinterpreted under an older "
            f"coordinate convention."
        )

    classes = tuple(
        RegionClass(
            id=str(entry["id"]),
            label=entry.get("label"),
            color=entry.get("color"),
            note=entry.get("note"),
        )
        for entry in raw.get("classes") or ()
        if isinstance(entry, Mapping) and entry.get("id")
    )
    _unique((c.id for c in classes), "region class id")

    sets = []
    for group in raw.get("sets") or ():
        if not isinstance(group, Mapping) or not group.get("id"):
            continue
        set_id = str(group["id"])
        regions = []
        for entry in group.get("regions") or ():
            if not isinstance(entry, Mapping):
                continue
            try:
                regions.append(_region(entry))
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                raise ProjectFormatError(
                    f"region {entry.get('id')!r} in set {set_id!r} is not a "
                    f"valid region: {exc}"
                ) from None
        _unique((r.id for r in regions), f"region id in set {set_id!r}")
        sets.append(
            RegionSet(
                id=set_id,
                regions=tuple(regions),
                name=group.get("name"),
                image_id=group.get("image_id"),
                meta=dict(group.get("meta") or {}),
            )
        )
    _unique((g.id for g in sets), "region set id")
    return LoadedRegions(sets=tuple(sets), classes=classes)
