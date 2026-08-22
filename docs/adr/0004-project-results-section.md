# ADR 0004 — Analysis results are a typed manifest section with member-stored arrays

**Status:** Accepted
**Date:** 2026-08-22
**Schema:** [`docs/schema/fvp-v2.schema.json`](../schema/fvp-v2.schema.json) (`results` property added in place, version stays 2)
**Plan:** `plans/MICROSCOPY_FEATURE_ROADMAP.md` item 1 (stack item 1A)

## Context

Every analysis in the app — EDS quantification, line profiles, particle
tables, diffraction indexing, and the rest of the catalogue — ends its
life as a transient HTTP response. Closing the workshop discards the
numbers, the parameters that produced them, and the calibration they
were computed under. A saved project reopens with its images and derived
maps but none of its conclusions, which fails the roadmap's outcome
("reopen, reproduce, and export figures + tables + methods") and pushes
users to screenshot results they cannot trace later.

The governing rule (MAIN_PLAN) is that any plan persisting new state
adds a **specified manifest section** rather than growing the opaque
`ui_state` blob. The ingredients already exist, scattered: `OpResult`
carries resolved params and a label, `ops/provenance.py` stamps version
and timestamp, every quant route already registers derived images, and
`calc/table_export.py` has a columns/units table contract. None of it is
named, kept, or reachable after a reload.

## Decision

### 1. A `results` section in the v2 manifest, no version bump

`manifest.json` gains a `results` array (schema updated in place). The
v2 schema permits and preserves unknown properties throughout, so a
project carrying `results` round-trips losslessly through a v0.1.32 or
older reader via the existing `unknown_keys` carry — this is a
non-breaking extension, exactly the mechanism ADR 0002 §6 reserved.

Each entry is a **lightweight record**: stable id (`uuid4().hex[:12]`,
the repo convention), analysis type, creation time, app version, status,
source/derived/region id lists, resolved parameters, calibration
snapshots, warnings, an error field, and typed outputs. A per-record
`schema` integer (currently 1) lets a future build migrate records
individually without re-versioning the container.

In code the record is a frozen dataclass over plain values
(`io/project_results.py`) — the pure-layer rule; routes adapt.

### 2. Arrays are ZIP members, never inline JSON

Output arrays are stored as `results/<result-id>/<n>.npy` entries in the
container (the `<future dirs>` slot ADR 0002 §1 reserved), written
streamed with `force_zip64` and read with `allow_pickle=False`, exactly
like pixels. The manifest holds only the member reference. Member paths
are validated against the same zip-slip threat model as image ids,
before any ZIP access.

### 3. One output envelope, seven kinds

An output is `{kind, name, data, member}` with `kind` drawn from a
closed set: `scalar`, `table`, `curve`, `fit`, `map`, `overlay`,
`figure`. `data` is the small inline JSON payload; `member` the large
numeric one. Conventions per kind (enforced by the item-1C creation API,
not the schema, so the format stays permissive):

- **scalar** — `data: {value, unit, sigma}`; `sigma` absent (not zero)
  when no honest uncertainty exists, mirroring the profile route's
  deliberate σ rule.
- **table** — `data: {columns, units}` (the `ExportTable` contract);
  rows inline under `data.rows` when small, else the member holds a 2D
  array in column order.
- **curve** — `data: {x_name, x_unit, y_name, y_unit}`; the member holds
  an `(N, 2)` or `(N, 3)` array (x, y, optional sigma).
- **fit** — like curve, plus `data.model`, `data.coefficients`,
  `data.residual` statistics.
- **map / overlay** — the member holds the raster; `data` carries
  display hints. A map that is also a session image records that image's
  id in `derived_ids` instead of duplicating pixels.
- **figure** — a rendered export (e.g. PNG bytes as a member) plus its
  caption inputs in `data`.

### 4. Status is `completed | failed | cancelled`

Deliberately not the job poller's `queued/running/done/error`
(`jobs.py`), which reports cancellation as an error only so pollers
always reach a terminal state. A result record is a scientific record,
not a polling state: failure and cancellation are recorded separately
from completed science (roadmap item 1 requires this distinction), with
the reason in `error` and no pretence of outputs.

### 5. Calibration is snapshotted, not referenced — and extensible

Each record embeds a **copy** of every source image's `AxisCal` tuple
and its `metadata.calibration_source` provenance string, taken at
compute time. Axes are the *first* supported snapshot content, not the
last: roadmap item 5's quantitative calibration (detector/profile/
standard identity, efficiency, dose and live-time provenance, factor
sets and their uncertainties) extends the same entries with further
keys rather than inventing a second snapshot mechanism. Keys this build
does not model are carried verbatim through a load → re-save
(`CalibrationSnapshot.extra`), so a richer snapshot written by a later
build survives an older one untouched — the same unknown-key rule as
every other structure in the format. Recalibrating an image later must not silently rewrite
what a stored composition or distance meant when it was measured; a
consumer compares the snapshot against the image's current axes to
surface staleness explicitly. This is the deliberate inverse of the
`measures` rule (areas derived from `pts` + live calibration, never
stored): a measure is a *definition* that should track calibration, a
result is a *record* that must not. Values are copied rather than keyed
into `~/.fermiviewer/calibrations.json` because that DB is per-machine
state and a project must survive transfer.

### 6. Results are server-carried and degrade, never vanish

`OpenProject` carries the loaded records exactly as it carries
unavailable placeholders: the client never echoes results back, so a
re-save that depended on the client would silently destroy them
(ADR 0002 §4's failure class). An append load merges by record id.

A member the container does not hold — or holds unreadably — **degrades
the record** (`missing_members` flags it, arrays stay `None`) and never
fails the project load; a re-save keeps the dangling member reference
rather than destroying the evidence of what the record carried. This
sits deliberately between the pixel rule (missing embedded pixels are a
hard `ProjectFormatError` — the image *is* the project) and the
thumbnail rule (absence is normal): results are precious but secondary
to the data they describe.

Id lists (`source_ids`, `derived_ids`, `region_ids`) may name things no
longer in the project; readers prune for display and keep them on save,
the same rule the schema states for `samples.image_ids`.

**Regions are snapshotted too.** `region_ids` link to the live
measures/ROIs so a UI can highlight ones that still exist, but regions
are mutable: they can be edited, have holes changed, or be deleted
after a result is computed, and a record that only referenced them
would silently come to mean different geometry (or none). Each record
therefore also carries `regions` — JSON-safe copies of the region
definitions at compute time, conventionally the `measures[]` entry
shape. The same copy-not-reference rule as calibration: the id links,
the snapshot reproduces. The entries stay schematically permissive
until roadmap item 4 defines the canonical geometry contract, and ride
through saves verbatim.

**Load enforces the save-side identity invariants.** The JSON schema
cannot express uniqueness or ownership, so `load_results` re-checks
what `prepare_results` guarantees: record ids unique, member references
unique across the section, and every member confined to its *owning*
record's `results/<id>/` directory. A crafted manifest must not be able
to alias one member into many outputs, claim another record's data as
its own, or smuggle in duplicate ids that a later session merge would
resolve unpredictably. Violations invalidate the manifest (a
`ProjectFormatError` before any member is read), matching the hostile-
`rel` rule for images.

### 7. Arrays load eagerly, for now

`load_project` reads member arrays into memory with the rest of the
container. Result arrays are orders of magnitude smaller than the source
cubes they summarise, so this is acceptable until roadmap item 7's
disk-backed result store generalises the machinery; the member layout is
already the on-disk shape that store needs.

## Consequences

- v1 workspaces migrate with `results=()` — a v1 file never carried any.
- A project saved by this build loads in any v2 reader; older builds
  carry `results` verbatim through `unknown_keys` without understanding
  it, and drop the member entries only if they rewrite the container
  (acceptable: those builds cannot create or display results either,
  and the metadata survives).
- The item-1C creation/query API and workshop adoption build on this
  contract; nothing in 1A changes analysis routes yet.
- Roadmap gate: 1C does not start until the 1B consumability review of
  this schema against the item-2 results-browser needs.

## Verification

`tests/test_project_results.py` covers: save/load round-trip of records
with inline and member outputs across the four representative analyses
(EDS quant, profile curve, particle table, diffraction indexing);
manifests stay strict-JSON under non-finite params; member arrays never
inline; missing, garbage, CRC-corrupted and truncated-stream members
degrade with `missing_members` set and survive a re-save; hostile
result ids and member paths are rejected before ZIP access; duplicate
ids/members and foreign-directory member references are errors on save
AND load; calibration and region snapshots round-trip with unknown
keys carried verbatim;
failed/cancelled records round-trip with `error` and without outputs;
v1 migration yields no results; unknown record/output keys round-trip
verbatim; `OpenProject` carries results through save-without-client and
merges append loads by id. `tests/test_project_format.py` continues to
assert schema-copy identity and container entry inventory.
