# ADR 0005 — Registered-operation result conventions for the parity waves

**Status:** Accepted
**Date:** 2026-08-22
**Plan:** `plans/MICROSCOPY_FEATURE_ROADMAP.md` item 3 (stack item 3A — these are the "frozen operation result conventions" waves 3B–3D implement against)
**Audit:** [`docs/operation-coverage.md`](../operation-coverage.md) (generated; `tools/gen_coverage_table.py`)

## Context

The coverage audit shows 13 of 80 analysis endpoints backed by a
registered op. Headless reach — batch recipes, folder watch,
`fv --script`, the Python API, and the macro's op conversion — is
exactly registry reach, so the other 67 endpoints are GUI-only. Waves
3B–3D close that gap mechanically, at the lower-cost model tier, which
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

- **Every value-producing op registered from waves 3B–3D onward —
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

- Waves 3B–3D become pattern-following: route request model → OpParam
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
