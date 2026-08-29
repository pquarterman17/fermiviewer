# ADR 0006 — Named region sets are a typed manifest section storing geometry inline

**Status:** Accepted
**Date:** 2026-08-29
**Schema:** [`docs/schema/fvp-v2.schema.json`](../schema/fvp-v2.schema.json) (`regions` property added in place, version stays 2)
**Plan:** `plans/MICROSCOPY_FEATURE_ROADMAP.md` item 4 (stack item 4A, second box)
**Builds on:** ADR 0002 (project file format), ADR 0004 (results section)

## Context

`calc/regions.py` (item 4A, first box) defines what a region *is*: one
canonical form — 0-based `(row, col)`, float, inclusive bounds, rings
implicitly closed — that the repo's nine disagreeing ROI spellings can be
converted into. It is pure geometry and knows nothing about projects.

Nothing persisted it. Three things in the repo already store something
region-shaped, and none of them is a named set an analysis can run inside:

* **`ui_state.savedRois`** — the ROI Manager's list. It reaches the
  `.fvp` because it is *not* a promoted key, so it falls through into the
  unvalidated `ui_state` blob (ADR 0002 §5). No schema, no stated
  coordinate convention, and no way for the backend to consume it.
* **`measures`** — drawn annotations, normalized 0–1 `(x, y)`, whose
  areas are deliberately derived rather than stored.
* **`results[].regions`** — a JSON snapshot of the geometry an analysis
  actually used, frozen at compute time.

So the geometry a user draws survives a reopen only as presentational
state the analyses cannot read, which is the gap this box closes. The
governing rule (MAIN_PLAN) is that persisting new state adds a
**specified** manifest section rather than growing `ui_state`.

## Decision

### 1. A `regions` section in the v2 manifest, no version bump

One new top-level key holding both the named sets and the class
vocabulary they label regions with. Two concepts, one section: the
classes exist to give the sets' `region_class` values a label and a
colour, and splitting them across two top-level keys would double the
wiring — seven files each — for no reader's benefit.

The container version stays 2. Unknown properties are permitted
throughout the manifest and preserved verbatim (ADR 0002 §6), so an older
build opening a project with this section carries it through a re-save
unharmed, and a newer build's section is not a breaking change.

`schema: 1` inside the section versions its own structure, exactly as
`RESULT_SCHEMA` does for a record, so region sets can be migrated later
without re-versioning the `.fvp`.

### 2. The schema number is the coordinate convention. There is no `convention` string

The three sites that populate `results[].regions` each describe their
coordinates in English prose, in three mutually inconsistent spellings:
`"(row, col), 1-based"` in `routes/measure.py`, and in
`routes/_diffraction_result.py` a table giving `"0-based, half-open"` for
a rect and `"0-based centre, radius, inclusive"` for a circle. Prose
conventions are how the repo arrived at nine incompatible ROI
representations in the first place.

This section therefore carries **no** convention field. `schema: 1` means
`calc.regions`, stated once in the JSON Schema's description and in
`io/regions_model.py`. A reader that knows the number knows the geometry;
there is nothing to keep in sync and nothing to spell two ways.

### 3. Geometry is stored inline in the manifest, not as ZIP members

`results` puts arrays in `results/<id>/<n>.npy` members because a
spectrum cube has no business in a JSON document. Region outlines are
different, and the choice was measured rather than assumed:

| | JSON | `.npy` |
|---|---|---|
| a 7,285-point traced contour | 120.5 KiB | 114.0 KiB |
| a bounds shape (rect/ellipse/circle) | 20 bytes | — |

**1.1x**, because `.npy` pays 16 bytes per point for float64 either way
and `find_contours` output is full of short-repr values. JSON also
round-trips float64 exactly (`repr` is shortest-round-trip), so there is
no precision argument either. Members would buy 1.1x at the cost of an
allocation path, a member-name safety path, and a degraded-load path —
all of which `results` needs and none of which pays for itself here.

The real cost of inline storage is that the manifest is parsed **whole on
every project open**, so a set of many traced contours is paid for just to
list the file. Hand-drawn regions — what this box is about — are a few
hundred points. **Revisit when segmentation labels become editable
regions** (a later item 4 box), which is where bulk traced geometry
arrives. Adding an optional `member` beside `outline` is a compatible
change precisely because the schema permits unknown properties.

### 4. Server-carried, like results and placeholders

The client never echoes region sets back — it posts only its own
`client_state`. A save route that took regions from the client would
therefore write an empty section over the user's regions on the very next
save. `OpenProject` carries them between calls and `_project_adapter`
passes them back down, with the same append-not-overwrite merge rule as
results: a replacing load swaps the sets, an append load adds arriving
sets and dedupes by id.

The wire form **is** the manifest form — `regions_payload` calls
`regions_to_manifest` rather than deriving a second shape — so the
browser and the `.fvp` cannot drift into two spellings of one region.

### 5. The JSON Schema is the validator, at both ends

`validate_manifest` runs before a container is committed *and* on every
load, so the schema is the single enforcement point. It carries the
discriminated-variant rule that `Shape` states in code: a polygon has an
`outline` and no `bounds`, every other kind the reverse. A shape carrying
both is two contradictory geometries with one silently ignored at
rasterization, so it is rejected rather than parsed.

What JSON Schema cannot express — a circle whose row and column extents
disagree, a region whose first part excludes — `Shape.__post_init__` and
`Region.__post_init__` raise `ValueError` for. `load_regions` re-raises
each as a `ProjectFormatError` naming the set and the region. A `.fvp` is
a file a stranger can send; it may fail to load, but not with a bare
geometry complaint from two layers down.

### 6. `classes` is descriptive, not a foreign key

`Region.region_class` is free text by contract — "the vocabulary is the
user's". A region may therefore carry a class that was never declared in
`classes[]`, and it round-trips intact. Making persistence stricter than
the contract would invent a second rule about what a class is, which is
the duplication this whole item exists to remove.

### 7. `image_id` is not validated against `images[]`

A set whose image is temporarily unresolvable is data to preserve, for
the same reason an unavailable image keeps its reference (ADR 0002 §4).
Dropping it would destroy the user's work to enforce a link that the next
re-point would have restored.

## Consequences

* Regions a user draws survive a reopen in a form the backend can
  consume, which is what item 4's later boxes (spectrum integration,
  statistics, segmentation, batch recipes) need in order to take a mask
  instead of a bounding box.
* `ui_state.savedRois` is superseded and should be migrated by the UI
  work in 4B; this ADR does not remove it, because removing a key the
  frontend still writes would lose data mid-transition.
* Nothing consumes the section yet. Populating it from the drawing tools
  is 4B; migrating analyses to read it is 4C.
* **Unknown keys nested inside the section are not carried.** Top-level
  manifest keys round-trip verbatim (ADR 0002 §6), but a future build's
  extra key *inside* a set or a region is dropped by this reader. `meta`
  on both a set and a region is the intended extension point and does
  round-trip verbatim. This is a deliberate limit of schema 1, not an
  oversight; a second version that needs sibling-key carry should add it
  at the same time.
* **`Shape` cannot be compared with `==`.** It is a frozen dataclass
  holding `np.ndarray` rings, so the generated `__eq__` raises "truth
  value of an array is ambiguous" for any shape with an `outline` or
  `holes`, while working for a plain rect. Every consumer comparing
  regions — including the round-trip tests here — must compare rings with
  `np.array_equal`. This is a defect in `calc/regions.py` inherited from
  item 4A's first box; fixing it needs that module split, since it stands
  at 491 of its 500-line ceiling.

## Verification

`tests/test_project_regions.py` — 26 tests:

* every field of a set and its regions survives save → load, asserted
  individually so a later field silently dropped shows up in review;
* the reopened region **rasterizes to the same pixels**, which is the
  only property a user cares about and the one a silently changed
  coordinate convention would break while leaving every field looking
  equal;
* every shape kind round-trips with its geometry, including a circle of
  radius 0 and shapes with holes;
* sub-pixel coordinates are not quantized on the way through;
* a project with no `regions` key — every project written before this
  section — loads to empty tuples, as does a migrated v1 workspace;
* the container gains no ZIP members;
* duplicate set, region and class ids are refused before anything is
  written;
* a malformed region names itself rather than leaking a `ValueError`;
* the schema refuses a shape carrying both `bounds` and an `outline`;
* the session carries sets across a replacing and an appending load,
  deduping by id;
* **the save route preserves regions the client never sent back** — the
  data-loss trap of §4, and the only test here that goes through HTTP.
