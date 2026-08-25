# ADR 0005 — Registered-operation result conventions for the parity waves

**Status:** Accepted
**Date:** 2026-08-22
**Plan:** `plans/MICROSCOPY_FEATURE_ROADMAP.md` item 3 (stack item 3A — these are the "frozen operation result conventions" waves 3B–3E implement against)
**Audit:** [`docs/operation-coverage.md`](../operation-coverage.md) (generated; `tools/gen_coverage_table.py`)

## Context

The coverage audit shows 13 of 80 analysis endpoints backed by a
registered op. Headless reach — batch recipes, folder watch,
`fv --script`, the Python API, and the macro's op conversion — is
exactly registry reach, so the other 67 endpoints are GUI-only. Waves
3B–3E close that gap mechanically, at the lower-cost model tier, which
only works if every judgement is settled here first: the roadmap
amendment (2026-08-22) bounces any op that does not fit these
conventions back to the high-capability tier rather than force-fitting
it.

## Conventions

### 1. One op, one route, one calc function

A registered op wires the SAME pure `calc/` function its route calls —
wiring and schema only, never reimplemented physics (the rule the
existing catalogues state). An op whose route composes several calc
calls registers the composition as the route performs it. Where an op
and its route already diverge (`composition_profile`'s input contract,
`eds_peakfit`'s entry point), the divergence is documented in the
coverage table's note column and must not be replicated in new waves.

### 2. Naming and placement

Op names are `snake_case`, domain-prefixed only when the bare name is
ambiguous across domains (`eds_quantify` vs `eels_quantify`; but
`particles`, not `structure_particles`). Categories stay the closed set
in use — `filter`, `geometry`, `analysis`, `spectral`, `eels`, `eds`,
`diffraction` — plus at most one new category per wave when a domain
genuinely arrives (e.g. `structure` for wave A, `fourd` if item 8 ever
activates). New ops land in `catalogue_<domain>.py` modules on the
existing precedent (`catalogue_analysis.py` exists because
`catalogue_spectral.py` neared the 500-line ceiling); never grow an
existing catalogue past the ratchet.

### 3. Value-vs-image is `produces_value_result`

`ops.produces_value_result(spec)` (added with this ADR) is the single
predicate; the batch palette and the API reference both call it. New
code never re-derives the rule from `category`/`produces_value`.

### 4. Params follow the route's request model

An op's `OpParam` schema mirrors its route's Pydantic request model —
same names, same defaults, same bounds — minus session-specific fields
(`image_id`: the op receives the `DataStruct`). Compound params
(element lists, window pairs) use the CSV-string flattening the
spectral catalogue established, until the registry grows richer param
types; a wave does not invent per-op encodings.

### 5. Ops emit the item-1 result contract through `value` — typed envelopes for every new op

The roadmap requires registered operations to emit the ADR 0004 result
contract. `OpResult` stays a plain dataclass, and the convention is:

- **Every value-producing op registered from waves 3B–3E onward —
  scalar- and table-shaped included — returns
  `value = {"outputs": [...]}`**, where each entry is an ADR 0004 output
  envelope `{kind, name, data}` with the per-kind `data` conventions of
  ADR 0004 §3. A flat dict is not an acceptable shape for a new op: a
  generic 1C adapter cannot mechanically tell whether its keys are
  scalar outputs, table columns, metadata, or units/uncertainties, so a
  flat dict is precisely the shape that cannot become a `ResultRecord`
  or a 1B result card without per-op knowledge. Arrays inline as lists
  here — the op layer is pure and has no project file; the 1C result
  API turns an envelope list into a persisted record with members.
- **The value ops already registered at this ADR's date are
  grandfathered, as a frozen, closed set** (the audit's "shipped" rows:
  `image_stats`, `noise`, `roughness`, `distribution_fit`,
  `radial_profile`, `composition_profile`, and the spectral/EDS quant
  and fit ops). Their flat dicts keep working through a per-op legacy
  adapter that 1C carries for exactly this set; no new op may join it,
  and each member migrates to envelopes when its domain's wave touches
  it.
- σ/uncertainty and units live inside the envelope `data`
  (`sigma` absent — not zero — when no honest uncertainty exists),
  never as bare parallel lists at top level in new ops.
- `label` stays the short human description; resolved params remain the
  reproduction key (`OpResult.params` is already resolved by
  `registry.run`).

This keeps `ops/` free of any 1C dependency while making every wave
op's output mechanically convertible to a `ResultRecord` — the generic
adapter needs no per-op knowledge outside the frozen legacy set.

### 6. Waves do not fork execution semantics

`ops.batch.run_recipe` is the one chaining implementation for recipes;
`Image.pipeline` (`fermiviewer.api`) is a known second copy and is
slated to delegate — a wave must not add a third. Job-backed routes
(`/analyze/grains`) register an op for the synchronous computation; job
orchestration stays in `routes/`/`jobs.py`, never in `ops/`.

### 7. The audit is part of the definition of done

A wave PR regenerates `docs/operation-coverage.md` (its rows move from
wave X to shipped) and `docs/api-reference.md` (the new ops appear),
and both drift tests pass. An op that cannot be expressed within these
conventions is the bounce-back signal the roadmap amendment describes —
stop and re-open the contract at the high-capability tier instead of
bending the op to fit.

### 8. Auxiliary inputs: an op may need more than its subject

*Added 2026-08-24, closing gap 1. The four wave addenda below are the
evidence that produced this section; they stand as written.*

An op declares extra datasets by name in `OpSpec.inputs`
(`dict[str, OpInput]`), and the caller passes them to
`run(name, ds, params, inputs={...})` as already-resolved `DataStruct`s.
`OpInput` carries `required`, `variadic` (a list of datasets rather than
one), `min_count`/`max_count`, and an optional accepted-`kinds` tuple.

Three rules make this safe rather than merely possible:

1. **The caller resolves ids; `ops/` never does.** What blocked these
   endpoints was never multi-image analysis — it was that a session id
   smuggled through a string param would make the pure layer read the
   session store. Handing over resolved structs inverts that, and the
   layering guard keeps it honest.
2. **Every op keeps exactly ONE primary subject.** The `ds` positional
   stays the recipe chain's spine, the provenance root, and the thing
   `Image.<op>()` is called on; auxiliary inputs are always named. A
   stack op's subject is its FIRST frame (the alignment reference, as in
   the route), with `others` carrying the rest — not an opaque bag of N.
3. **The call convention follows the schema.** A spec that declares
   `inputs` has `fn(ds, params, inputs)`; every other op keeps
   `fn(ds, params)` untouched. `tests/test_ops_contract.py` asserts each
   registered fn's arity against its spec, so the two conventions cannot
   drift apart silently.

Consequences recorded with the mechanism:

- **Provenance is a DAG.** `ProvenanceStep.inputs` was already a tuple, so
  the log needed nothing; `ancestry()` walks the PRIMARY spine, and
  `_describe` names the other contributors ("… with b.dm4") so a methods
  paragraph cannot silently omit a dataset that went into the number.
- **Recipes name auxiliary inputs symbolically** (added 2026-08-24; this
  paragraph previously recorded the gap). A step may carry
  `"inputs": {"<op input>": "<recipe input>"}`, and the run supplies the
  pool those names resolve against: `run_recipe(ds, steps, inputs={...})`.
  The indirection is the point — a saved recipe runs over many subjects, so
  an auxiliary dataset cannot be frozen into a step as a session id, and the
  pure layer could not resolve such an id anyway. Each caller binds the pool
  from what it owns: `/batch/run` and `/watch/start` from session image ids,
  `fv --script` from files named relative to the recipe file, and
  `Image.pipeline` from session `Image`s. References are validated against
  the pool BEFORE the first step, so a 200-input batch cannot start on a
  recipe that would fail on every one of them.
- **Per-input labels ride `metadata`**, not a parallel param: an op that
  must letter its inputs (montage) reads each struct's `source`, the
  static-name convention wave B set for the pure layer.

### 9. List-shaped params: `RowSpec` and `RecordSpec`

*Added 2026-08-24, closing gap 2.*

`OpParam` accepts `ptype=list` with exactly one of:

- **`row=RowSpec(width, item_type, columns, min_rows, max_rows,
  allow_none_rows)`** — variable-length lists of fixed-width numeric rows:
  coordinate pairs (`points`, `positions`, `spots`), `fft-mask`'s
  (row, col, radius) triples, `eds_recalibrate`'s non-coordinate pairs.
  `width=None` accepts ragged rows and `allow_none_rows` nullable ones
  (`layers/grains`'s `interface_traces`) — both opt-in, because a width
  mismatch is the coordinate-list typo worth catching.
- **`record=RecordSpec(fields, min_rows, max_rows)`** — rows of named
  fields, each field an `OpParam`, so a field may itself be a row list
  (`strokes` = class id + radius + polyline). Records do NOT nest: one
  level covers the whole evidence set, and a bounded depth is what keeps
  the palette, the generated reference, and the error messages
  renderable.

The value is a **real JSON list**, never a delimited string. A string
reaching a row list is an error, not a re-split: the CSV flattenings that
waves A–D used (`"Fe,O"`, `"708:758,532:582"`) were §4 compromises for a
contract that could not hold lists, and silently accepting them here would
resurrect exactly the per-op encoding invention §4 forbids.

**The shipped CSV params stay frozen.** They are public surface — recipes,
macros, and the frontend's `macroOpMap.ts` all spell them that way — so
they are NOT migrated by this ADR. New list params use the native shape;
minting a new CSV flattening is now out of contract. A deliberate
migration of the ~20 shipped spellings is a separate cross-lane item
(it changes the frontend map with the ops).

Three smaller gaps the addenda recorded are closed with the same edit:

- **Exclusive bounds.** `exclusive_minimum`/`exclusive_maximum` are the
  routes' `Field(gt=)`/`Field(lt=)` twins, sighted in wave B
  (`ctf.pixel_size_a`) and wave C (`montage.overlap`). `ctf` drops its
  hand-written `ValueError` for the schema spelling.
- **`ANY_SCALAR`.** The one union a route model needs that no single
  constructor covers — `montage-compare`'s `param_value`
  (`float|str|bool|None`). Containers are still refused: "any scalar", not
  "anything".
- **Fractional ints.** `int(1.5) == 1` silently addressed a different
  pixel/reflection than requested, where every route's pydantic int field
  rejects the same input. Wave C hand-rolled this per op group
  (`int_group`); it is now enforced for every int param and every int row
  item. No shipped test depended on the truncation.

One incidental fix belongs to this section because §4 caused it:
`Image.run`'s operation name is now positional-only, so an op mirroring a
route field literally named `op` (`image_math`) can pass it as a param
instead of colliding with the façade's own argument.

## Consequences

- Waves 3B–3E become pattern-following: route request model → OpParam
  schema, route payload → envelope list, calc function unchanged.
- The frontend's `macroOpMap.ts` gains op conversions wave by wave and
  should be regenerated/reviewed against the coverage table each time.
- The `README.md` parity claim is corrected with this ADR to describe
  registered-op reach and point at the audit, and tightens back up as
  waves land.

## Verification

`tests/test_coverage_table.py` (byte-drift + determinism);
`tests/test_api_reference.py` (unchanged output under the consolidated
predicate); wave PRs add per-op parity tests comparing op output to the
route's payload for the same inputs.

## Addendum — wave A outcome (2026-08-23)

Wave A (roadmap 3B) registered 7 of its 13 endpoints and bounced 6 back,
per the Context section's rule. What the wave established:

### Shipped

`particles`, `efd_similarity`, `propose_region`, `grains`, `layers`,
`layers_edit` under the new `structure` category (§2's one-new-category
allowance; each sets `produces_value=True` explicitly since the category
does not imply it), plus `interface_width` in `analysis`. All seven emit
§5 typed envelopes; the grandfathered flat-dict set did not grow.

Two conventions this wave firmed up for waves 3C–3E:

- **Route-local numerics get lifted to `calc/`, not duplicated.** Four
  compositions lived in `routes/` (the regions window/seed maths, the
  grain payload aggregates, the layers roughness/serialisation blocks,
  the EFD trace-describe-rank loop); registering their ops under §1 meant
  lifting them (`calc/region_propose.py`, `calc/grain_report.py`,
  `calc/layers_report.py`, `calc/efd_rank.py`) so op and route run ONE
  code path. Later waves should expect and budget for the same lift work.
- **A no-subject op is admissible on the `distribution_fit` precedent
  only in its narrowest form**: every input flattens to flat scalar CSV
  lists, one calc call, `ds` deliberately unused and documented.
  `interface_width` (x/y profile lists) qualifies; `fit-shape` — which
  would ALSO need a variable-length coordinate-pair encoding — does not,
  and stays bounced rather than force-fit (§4: a wave does not invent
  per-op encodings).

### Bounced back, and the contract gaps they expose

| Endpoint | Blocking shape |
|---|---|
| `/api/analyze/fit-shape` | no image subject + variable-length `[[row, col], ...]` list |
| `/api/grains/edit` | label map addressed by session id, source image resolved from its metadata; click list |
| `/api/grains/train-segment` | `strokes`: an array of nested models each carrying a coordinate list |
| `/api/grains/train-preview` | same strokes shape; also two derived maps |
| `/api/analyze/layers/grains` | label map by session id + nested layer bands + ragged `interface_traces` |
| `/api/analyze/layers/multi` | N input images by session id — `fn(ds, params)` has exactly one subject |

Two registry-contract gaps account for all six, and they are contract
work for the high-capability tier, not wave work:

1. **Multi-input operations.** `OpSpec.fn(ds, params)` takes exactly one
   `DataStruct`. Ops over several session images (`layers/multi`) or over
   a derived label map plus the source image it references
   (`grains/edit`, `layers/grains`) need a registry-level input schema
   (named `DataStruct` inputs), not image ids smuggled through string
   params — `ops/` reaching into the session store would break the pure
   layer.
2. **Structured parameters.** The §4 CSV flattening ends at flat scalar
   lists and `"lo:hi"` pairs. Coordinate-pair lists (`points`), and
   arrays of nested models (`strokes`), need richer param types in
   `OpParam` itself before their endpoints can register.

The six rows stay wave A in the coverage audit, each annotated with its
blocking shape, until the ops contract grows; re-opening that contract is
its own high-capability work item, not part of waves 3C–3E.

## Addendum — wave B outcome (2026-08-23)

Wave B (roadmap 3C) registered 8 of its 10 endpoints and bounced 2 back.

### Shipped

`fft` and `vdf` in `filter` (derived-image producers — `fft` deliberately
drops the parent calibration, FFT space not being real space); `gpa`,
`lattice`, `ctf` in `analysis` (the category implies their value result);
`atoms`, `template_match`, `defects` in `structure` with explicit
`produces_value=True`. §2's one-new-category allowance stays unspent:
wave B is FFT-domain measurement of ordinary images, not a new domain,
and the allowance remains earmarked for `fourd` (item 8). Four lifts
followed the wave-A rule (`calc/fourier.local_fft_region`,
`calc/gpa.gpa_mean_strain`, `calc/texture.template_match_rect`, and
`calc/atom_report.py` — whose `pair_strain_payload` is now shared by
/analyze/atoms and /atoms/strain). The shared helper trio
(`nan_none`/`pixel_cal`/`sentinel_group`) moved into
`ops/_envelopes.py`/`ops/_parsing.py` so wave C does not mint a third
copy.

### Standing resolution: multiple derived images

`gpa` (four strain maps) and `defects` (two diagnostic maps) exceed
`OpResult.derived`'s single slot. This is NOT a bounce: wave A's `grains`
already established the resolution — the op inlines each raster as a
`map` envelope in `value` while the route registers session images — and
wave B adopts it as the standing rule. The accepted divergence (headless
callers get inline arrays; GUI callers get session images) is noted on
each affected audit row. Clarification to the wave-A table:
`train-preview`'s bounce was its `strokes` parameter, not its two derived
maps — map count alone never bounces an op.

### Two small §4 fidelity gaps (recorded, not bounces)

- **`OpParam` has no exclusive minimum**: the routes' `Field(gt=0)`
  bounds (`ctf.pixel_size_a`, `defects.foil_thickness`) are enforced by
  an explicit `ValueError` in the op fn, with `minimum=0.0` as the
  closest schema spelling.
- **Naming divergence**: derived-image routes compose display names from
  `store.name(...)`; the pure op layer cannot, so op-derived images carry
  a static `source` (the filter-op convention).

### Bounced back

| Endpoint | Blocking shape |
|---|---|
| `/api/analyze/fft-mask` | `masks`: a variable-length (row, col, radius) coordinate-triple list |
| `/api/atoms/strain` | `positions`: a variable-length coordinate-pair list, and no image subject — exactly `fit-shape`'s shape |

Both are **gap 2 (structured parameters)** from the wave-A addendum; no
wave-B endpoint touches gap 1 (multi-input). Each was individually
flattenable with enough per-op encoding invention — a `"r:c:rad,…"`
triple string, parallel x/y CSV lists — and each stays bounced for the
same reason `fit-shape` did: §4 says a wave does not invent per-op
encodings, and blessing them piecemeal would make the earlier bounces
arbitrary. `fft-mask` is now the cleanest motivator for re-opening gap 2:
its calc function is a pure single call with zero lift work the moment a
list-shaped `OpParam` type exists.

## Addendum — wave C outcome (2026-08-24)

Wave C (roadmap 3D) registered 3 of its 10 endpoints and bounced 7 back —
the wave with the highest bounce rate, because six of its endpoints are
the multi-input cluster gap 1 describes.

### Shipped

`diffraction_detect`, `diffraction_calibrate`, `diffraction_simulate` in
the existing `diffraction` category (which does not imply a value result
— each sets `produces_value=True` like `radial_profile`). The
one-new-category allowance stays unspent for the third consecutive wave,
still earmarked for `fourd`. Lifts per the standing rule:
`calc/diffraction.find_spots_roi`,
`calc/diffraction_calib.calibrate_rings`,
`calc/phase_registry.standard_d_spacing`. `radial_profile` stays
grandfathered in `catalogue_spectral.py` — §2 migrates a member only when
its wave touches its code, and this wave did not.

### Decisions this wave recorded

- **The `_Roi` discriminated union flattens.** detect/index's ROI model
  (`kind: "rect"|"circle"` + per-shape ints) is a fixed-arity,
  scalar-only union: it flattens to a `roi_kind` choices discriminator
  plus two NaN-sentinel groups — only already-blessed vocabulary, so §4
  is not tripped. One deliberate tightening: a `roi_kind` without its
  coordinate group errors instead of silently analyzing the whole image
  (the strict `parse_roi_param` rationale; the route's zero-defaults
  would silently no-op).
- **`lt=` is the exclusive-maximum twin of the wave-B `OpParam` bound
  gap** (sighted on montage's `overlap: Field(lt=1.0)`, a bounced row —
  no code needed this wave, but the vocabulary gap now has both ends).
- **The audit's `figure` cells were wrong.** montage and montage-compare
  register a session-derived image; neither renders an export, so their
  kinds cells now read `map (derived image)`. If an op ever genuinely
  needs ADR 0004's `figure` kind, inlining PNG bytes is NOT a fit: a
  base64 blob is neither an array-as-list nor a member, and the pure op
  layer has no member store. Name it **gap 3 — member-bearing output
  kinds in a pure op** if it arises; it did not arise this wave.

### Bounced back

| Endpoint | Blocking shape |
|---|---|
| `/api/diffraction/index` | gap 2: `spots` is a variable-length coordinate-pair list (the fit-shape/atoms-strain shape) |
| `/api/analyze/image-math` | gap 1: two equal image inputs (`a_id`/`b_id`) — primary-ds + id-param would smuggle a session read into the pure layer |
| `/api/analyze/align-stack` | gap 1: N image inputs; its only field is the blocking one |
| `/api/analyze/mip` | gap 1: same |
| `/api/analyze/stitch` | gap 1: N image inputs |
| `/api/analyze/montage` | gap 1: N image inputs; `labels=True` additionally bakes session names into pixels — a future multi-input contract must carry per-input labels |
| `/api/analyze/montage-compare` | gap 1 AND gap 2: an array of nested tile models, each naming a session image, with a `float\|str\|bool` field no scalar encoding covers |

The gap-1 cluster is now six rows across two waves; together with
`fft-mask` (the cleanest gap-2 motivator) and `montage-compare` (the
strongest joint gap-1+2 case), the contract re-opening has its full
evidence set. No wave-C route is job-backed, so §6 had nothing to bite
on.

## Addendum — wave D outcome (2026-08-24)

Wave D (roadmap 3E), the final parity wave, registered all 26 of its
endpoints — zero new bounces — closing item 3's mechanical phase at
57 of 80 analysis endpoints op-backed (73 ops). That result rests on one
new rule and two clarifications, recorded here.

### The optional-input omission rule (new)

*A variable-length or multi-input field that is OPTIONAL in the route's
request model may be omitted from the op: the op registers the remaining
fixed-arity form, and the omitted mode is annotated "no op" in the
audit's note column. A REQUIRED such field still bounces.*

This generalises existing practice rather than inventing it — shipped
rows already annotate unbacked modes (`/api/analyze/radial`'s azimuthal
sector, `/api/filter`'s `crop` and arbitrary-angle `rotate`). The rule
leaves every one of the fifteen prior bounces intact: in each, the
blocking field is required or IS the operation (verified case by case in
the wave-D recon). It unlocked three wave-D rows: `elnes`
(`reference_id`, an optional second image — the only gap-1 touch this
wave), `line_profile` (`points` polyline mode), and `eds_recalibrate`
(`pairs`). A caller who supplies an omitted field gets a hard
`ParamError`, never silent divergence.

### Modes without an op

`eels_svd`'s `denoise=True` flips the route payload from curves+maps to
a derived cube. `produces_value_result` is a schema-time predicate — the
batch palette and the API reference read it before running anything — so
a spec whose payload kind depends on a param cannot exist. The op drops
`denoise` and the mode is annotated, the radial-sector treatment.

### Standing rule: derived DataStructs and their diagnostics

The wave-B inline-`map` rule covers 2-D rasters. A derived 1-D/3-D
DataStruct (aligned SI cubes from `eels_align_zlp`/`eels_subpixel_align`,
the recalibrated struct from `eds_recalibrate`) stays in
`OpResult.derived` — ADR 0004 has no cube kind to inline as — and its
scalar diagnostics (max_shift, shifted_fraction, gain/offset/skipped)
ride `derived.metadata`, the `savgol_derivative` precedent.

### Notes for the record

- **The one-new-category allowance retires unspent** after four waves; a
  `measure` category was argued and rejected (`analysis` already holds
  exactly this work, implies the value result, and categories are op
  taxonomy, not GUI panels). It remains earmarked for `fourd` (item 8),
  which now re-opens §2 on its own terms.
- **Gap 3 (member-bearing/figure kinds) never arose** in waves C or D;
  it stays named but unexercised.
- `eds_recalibrate`'s `pairs` is the first NON-coordinate float-pair
  list to meet gap 2 — the final piece of evidence that the params
  contract re-opening (gaps 1–2) should consider pair lists generally,
  not just spatial coordinates.
- `eels_thickness` deliberately diverges from its route in ONE respect:
  the route registers `nan_to_num(t)` as the session image but reports
  statistics over raw `t`; the op inlines the RAW map (NaN → null) —
  zero-filling invalid pixels in a headless array would silently bias
  any downstream mean. Annotated on the audit row.
- `strip_databar` introduces the tree's first `ops → io` import
  (both are PURE_LAYERS; the guard forbids only fastapi/pydantic/routes/
  starlette) — deliberate, for `databar_content_rows` and the lifted
  carry-forward rule.

## Addendum — the contract re-opening (2026-08-24)

The high-capability item the four wave addenda kept deferring to. §8 and
§9 above ARE its output; this records what it cost and what it left.

### What the evidence set decided

Every shape the fifteen bounces needed was already enumerated by the
addenda, and each mapped to exactly one of two mechanisms — which is the
argument for having bounced rather than force-fitting them one at a time:

| Bounced shape | Mechanism |
|---|---|
| coordinate pairs (`points`, `positions`, `spots`) | `RowSpec(2)` |
| `masks` (row, col, radius) | `RowSpec(3)` |
| `pairs` (non-coordinate floats) | `RowSpec(2)` |
| `interface_traces` (ragged, nullable) | `RowSpec(None, allow_none_rows=True)` |
| `strokes`, layer bands, tiles | `RecordSpec` (+ a row-list field) |
| `param_value` (`float\|str\|bool\|None`) | `ANY_SCALAR` |
| two equal images (`image-math`) | one named `OpInput` |
| N images (align/mip/stitch/montage/layers-multi) | one variadic `OpInput` |
| label map + its source image (`grains/edit`, `layers/grains`) | one named `OpInput` |

No shape needed a third mechanism, and none needed records inside records.
The one shape the addenda predicted but nothing required is still gap 3
(member-bearing/`figure` kinds in a pure op) — named, unexercised.

### Registered here, and what remains

Four exemplars land with the contract, one per mechanism, chosen because
their calc functions were already shared with their routes (zero lift
work, so the PR is contract + proof and nothing else): `fft_mask`
(row list), `image_math` (named input), `align_stack` and `mip` (variadic
input). The audit moves 57 → **61 of 80**; the registry holds 77 ops.

The remaining eleven bounces are now pattern-following registrations
against a contract that fits them, not contract work: `fit-shape`,
`atoms/strain`, `diffraction/index`, `train-segment`, `train-preview`,
`stitch`, `montage`, `grains/edit`, `layers/grains`, `layers/multi`,
`montage-compare`. Several still need route-local numerics lifted to
`calc/` first (§1) — `layers/multi`'s cross-map calibration checks,
`index`'s ROI re-centring, `grains/edit`'s merge branch,
`montage-compare`'s tile ordering — which is the bulk of that work, not
the registration.

### Two things deliberately NOT done

- **The CSV params were not migrated** (§9). They are public surface and
  the migration is cross-lane; doing it inside the contract PR would have
  mixed a mechanical rename of ~20 shipped ops into the change that has to
  be reviewed as a contract.
- **Recipes did not gain a named-input vocabulary** (§8). Multi-input ops
  are callable from the API and HTTP but are not recipe steps, and say so
  in the palette. Item 3's "done when" wants a saved recipe to reproduce
  any GUI analysis, so this IS a real remaining gap — recorded here rather
  than hidden behind a passing audit, because the coverage table counts an
  endpoint as op-backed without asking whether a recipe can carry it.

### Note for the record

`interface_traces`'s nullable rows are the only place the contract accepts
a null INSIDE a param value. It stays opt-in per param: a null coordinate
is almost always a caller bug, and the one route that means it (a layer
with no measured interface) says so in its own schema.


## Addendum — recipe auxiliary inputs (2026-08-24)

§8 left multi-input ops callable but not scriptable, which was a real gap
against item 3's "done when" (a saved *recipe*, not merely an op). Closed
here; §8's bullet above is rewritten to describe the mechanism.

### Symbolic names, bound per run

A step names what it needs (`{"other": "dark"}`); the run says what "dark"
is. The alternative — an image id inside the step — was rejected for the
reason the whole §8 design turns on: it would freeze a recipe to one
session, and resolving it would drag the session store into `ops/`.

The pool is resolved ONCE per batch, not per subject: the datasets are the
same for every input, and re-reading the store per input would let a
mid-batch deletion silently change the computation half way through.

### What each caller had to change

The step dict was never "closed" — nothing rejected unknown keys — but
three layers silently REBUILT it as `{op, params}`, so an `inputs` key
would have been dropped in transit rather than rejected: the pydantic
`BatchStepRequest` (pydantic's default `extra="ignore"`), the CLI's
`_normalize_steps`, and the frontend's preset serializer. Transport had to
be opened deliberately at each. The frontend rebuilders are the Codex lane's
to update; until they are, a preset saved from the UI still round-trips
only `{op, params}`.

### Notes for the record

- **`recipe_step` is gone from the palette.** It shipped one release earlier
  meaning "this op cannot be a recipe step"; that is now false for every op,
  and a permanently-true flag is worse than none. `inputs[]` already tells a
  builder how many pickers to render. No consumer read it.
- **`recipe_version` in derived-image metadata is now 2**, with a sibling
  `recipe_inputs` recording the id binding. Once a step can name a dataset,
  the steps alone no longer describe the computation, so a v1 reader must
  not silently treat a v2 recipe as complete.
- **`Session.adopt` is new public API.** The façade could previously only
  bring datasets in by parsing a file, but an op's auxiliary datasets must
  belong to the same session as its subject — without `adopt`, `fv --script`
  would have to re-parse every reference file once per batch input.
- The recipe pool binds AUXILIARY inputs only. The subject still chains
  through the recipe, so a later step's `other` is the pool's dataset, never
  the previous step's output; `test_a_recipe_chains_a_multi_input_step_onto_the_derived_image`
  pins that.
