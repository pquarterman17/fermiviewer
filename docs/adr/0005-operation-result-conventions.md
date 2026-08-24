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
