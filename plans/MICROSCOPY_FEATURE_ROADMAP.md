# Microscopy Feature Roadmap

Turn FermiViewer's unusually broad analysis catalogue into a coherent,
traceable microscopy workflow. This plan prioritises capabilities used across
routine imaging, EDS, EELS, diffraction, particles, grains, layers, and sample
comparison. Specialist 4D-STEM and tomography work is deliberately last and is
not part of the default implementation schedule.

**Status:** Active — implementation in progress
**Parent:** MAIN_PLAN.md
**Created:** 2026-08-22
**Audit base:** `origin/main` at `13044e1` (v0.1.32)
**Owner decision:** 4D-STEM and tomography are rare-use options. Do not advance
either while a broadly useful item in Tiers 1–2 remains valuable and feasible.

---

## Outcome

The target experience is one connected workflow:

```text
import datasets
  -> calibrate and register modalities
  -> define reusable regions
  -> run a saved analysis recipe
  -> inspect result quality and uncertainty
  -> compare samples
  -> reopen, reproduce, and export figures + tables + methods
```

Adding more isolated analysis dialogs is not the primary goal. New work should
make existing analyses persistent, quantitatively trustworthy, interoperable,
and scalable.

## Current strengths to preserve

- Wide microscopy format support without GPL runtime dependencies.
- Mature EDS/EELS workspaces: full/point/ROI spectra, linked windows, mapping,
  quantification, model fitting, uncertainty, and composite figures.
- Diffraction calibration, indexing, simulation, and structured reports.
- Imaging, particle, grain, layer/interface, GPA, CTF, and atom workflows.
- Sample/project comparison, measurements, stack tools, batch recipes, and a
  public Python surface.
- Strict `io/` + `calc/` layering, source-module size ratchets, golden tests,
  warnings-as-errors, and real-data/oracle verification.

## Scope rules

1. Prefer shared infrastructure over one-off controls in individual workshops.
2. Every scientific result must identify its input, region, calibration,
   parameters, implementation/version, uncertainty, and warnings.
3. GUI, batch, macro, and Python execution should converge on the same
   registered operation and result contracts.
4. A saved project must reopen meaningful analysis state, not merely source and
   derived images.
5. Keep large datasets responsive through previews, cancellation, progress,
   caching, and bounded memory use.
6. Do not add general-purpose graphing/statistics unrelated to image-derived
   microscopy results.
7. Do not begin optional 4D-STEM or tomography work merely because earlier
   tiers are complete; require a concrete user need or representative dataset.

---

## Priority and sequence

| Order | Workstream | Priority | Size | Depends on |
|---:|---|---|---|---|
| 1 | Persistent result and methods model | Tier 1 | M–L | — |
| 2 | Results browser, rerun, comparison, and reporting | Tier 1 | M | 1 |
| 3 | Universal operation/automation parity | Tier 1 | M–L | 1 |
| 4 | First-class region and mask model | Tier 1 | M | 1 |
| 5 | Calibration profiles and quantitative standards | Tier 1 | L | 1, 4 |
| 6 | Cross-modal registration | Tier 2 | L | 1, 4 |
| 7 | Large-data execution and interoperable storage | Tier 2 | XL | 1, 3 |
| 8 | Optional 4D-STEM extensions | Specialty/parked | L–XL | 6, 7 |
| 9 | Optional tomography workflow | Specialty/parked | XL | 6, 7 |

Orders 1–7 form the general roadmap. Orders 8–9 are last-option specialist
tracks, not promised follow-on work.

---

## Ownership and implementation model

Assign each PR according to its hardest judgement, not according to which side
has more files. One agent owns a PR from implementation through its primary
tests; the other reviews it from their specialty. Do not have Claude and Codex
make overlapping edits in the same uncommitted worktree.

### Agent strengths used by this plan

**Claude owns backend/scientific engineering:**

- Python data models, schemas, migrations, persistence, and route contracts.
- Numerical algorithms, uncertainty propagation, calibration math, and golden
  reference work.
- Operation-registry sweeps, batch execution, job infrastructure, caching,
  chunking, storage formats, and performance tests.
- Broad mechanical implementation when the behavior and wire contract are
  already settled.

**Codex owns product/UI/graphics engineering:**

- Workflow design, interaction states, information hierarchy, and progressive
  disclosure.
- React component structure, Zustand UI state, plots, overlays, figure output,
  visual QC, responsive behavior, accessibility, and live browser validation.
- Turning scientific warnings/uncertainty into understandable interfaces.
- Cross-workshop consistency and end-to-end usability review.

### Model policy

- Use **Codex `gpt-5.6-sol`, high reasoning** for new workflows, difficult
  frontend architecture, visualization, interaction design, and final
  cross-stack integration. Raise to xhigh only for a genuinely tangled state or
  coordinate-system problem.
- Use **Codex `gpt-5.6-terra`, medium reasoning** for a tightly specified
  component, mechanical frontend wiring, test expansion, documentation, or a
  bounded follow-up fix. Use `gpt-5.6-luna` only for low-risk inventory or
  repetitive edits with strong tests; never for scientific behavior or UX
  decisions.
- Use **Claude's strongest available coding model** for schema design,
  scientific calculations, migrations, concurrency, performance, and the
  initial implementation of unfamiliar backend infrastructure.
- A lower-cost Claude coding model is appropriate for repetitive `OpSpec`
  registrations, route adapters, fixtures, and test matrices only after the
  contract is frozen by the lead implementation.
- Do not choose a cheap model merely because a PR is small. Calibration math,
  coordinate transforms, persistence migrations, and cancellation correctness
  remain high-reasoning tasks even in short diffs.

### Workstream ownership

| Workstream | Lead | Supporting handoff | Recommended implementation split |
|---|---|---|---|
| 1. Result/methods model | Claude | Codex defines user-visible result states and reviews consumability | Codex behavior/spec note -> Claude schema, migration, API, round-trip tests -> Codex minimal frontend proof |
| 2. Results browser/reporting | Codex | Claude supplies query/export endpoints and validates persisted provenance | Codex owns layout, cards, filters, comparison, methods view, figures, and browser QA; Claude owns backend bundle generation |
| 3. Automation parity | Claude | Codex audits GUI coverage and improves recipe discoverability/status UI | Claude owns coverage generator, `OpSpec` waves, Python/batch parity and tests; Codex owns any recipe-builder UI |
| 4. Regions/masks | Split | Each reviews the other's half | Claude owns canonical geometry/mask contract and exact calculations; Codex owns drawing/editing, holes, previews, naming, and region management |
| 5. Calibration/standards | Split, Claude scientific lead | Codex leads calibration and QC presentation | Claude owns calibration schema, factor derivation, uncertainty and validation; Codex owns profile manager, standards workflow, warnings and result presentation |
| 6. Registration | Split | Contract frozen before either UI or algorithms branch widely | Claude owns transform graph, resampling, metrics and numerical tests; Codex owns landmark workflow, overlay/blink/difference views, transform review, and ROI-transfer UI |
| 7. Large-data execution | Claude | Codex owns progress/cancel/cache-status experience | Claude owns jobs, cancellation semantics, chunking, storage, cache and benchmarks; Codex wires consistent responsive states after the contract is stable |
| 8. Optional 4D-STEM | Split if activated | Same rules as registration | Claude owns detector/calibration/Bragg/strain math; Codex owns the reciprocal-space inspector and QC visualization |
| 9. Optional tomography | Claude scientific lead if activated | Codex owns tilt-series inspection and volume/slice UI | Claude owns alignment/reconstruction/validation; Codex owns diagnostics, missing-wedge and slice/volume interaction |

### Standard cross-agent stack

For a mixed workstream, use this sequence:

1. **Codex UX contract** — concise states, interactions, visual hierarchy,
   accessibility, wire payload needs, and acceptance screenshots/mockups where
   visual ambiguity exists. This may be a plan/spec commit rather than code.
2. **Claude backend PR** — pure calculation/data contract first, then thin API,
   migrations, failure cases, and scientific/backend tests.
3. **Codex frontend PR** — components, state, plots/overlays, accessibility,
   responsive behavior, visual polish, and frontend/browser tests, stacked on
   Claude's backend PR.
4. **Claude correctness review** — inspect payload use, units, defaults,
   uncertainty, stale-result behavior, and backend load; fix backend defects in
   a follow-up PR rather than silently reshaping the frontend contract.
5. **Codex experience review** — exercise the complete workflow with realistic
   data, including empty/loading/error/cancelled/stale states, dark/light theme,
   narrow layouts, exports, and cleanup of test windows/tabs.

Pure-backend waves in items 3 and 7 can omit steps 1 and 3 when no user-visible
behavior changes. Pure-UI polish can omit the backend PR only when it does not
invent scientific values or duplicate calculation logic in TypeScript.

### Proposed PR ownership by roadmap item

#### Item 1 stack

- **1A — Claude/high capability:** result types, `.fvp` schema, migrations,
  array-member storage, and round-trip/failure tests.
- **1B — Codex/sol high:** result-state UX contract and a representative result
  card using EDS quantification.
- **1C — Claude/high capability:** shared result creation/query API and adoption
  by one spectral plus one non-spectral operation.
- **1D — Codex/terra medium:** frontend persistence/reopen integration and UI
  test matrix once 1B establishes the visual pattern.

**Stack gate:** 1C does not start until Codex has reviewed the 1A schema for
consumability against item-2 needs — every planned card, filter, comparison,
and methods view must be constructible from what 1A persists. Everything in
items 2–7 consumes this contract, and a schema revision after the item-3
waves adopt it is expensive; catch it here, before adoption.

#### Item 2 stack

- **2A — Codex/sol high:** Results/Methods workspace, navigation, filters,
  result detail, warnings, source links, and reopen/rerun flows.
- **2B — Claude/high capability:** compatible-result query and report-bundle
  backend, deterministic provenance and export tests.
- **2C — Codex/sol high:** comparison views, figure/table selection, methods
  composition, PDF/HTML-facing layout, and full browser QA.

#### Item 3 stack

- **3A — Claude/high capability:** generated parity audit and frozen operation
  result conventions.
- **3B–3E — Claude/lower-cost only after 3A:** the four registered-operation
  waves (3B = wave A, 3C = wave B, 3D = wave C, 3E = wave D — spectroscopy,
  measurement, and utility endpoints), each with full backend/API tests. The
  lower-cost tier is for pattern-following only: the first operation in a wave
  that does not fit the frozen 3A conventions bounces back to the
  high-capability model for contract work rather than being force-fit to the
  pattern.
- **3F — Codex/terra medium:** recipe-builder discoverability, validation and
  progress/error UI; documentation truth pass.
- **3I — Claude/lower-cost after 3G/3H:** the eleven remaining registrations
  plus their `calc/` lifts. Shipped 2026-08-25; pattern-following, as the
  contract re-opening predicted.
- **3H — Claude/high capability:** recipe-level named auxiliary inputs, so the
  multi-input ops 3G unlocked are scriptable and not merely callable. Shipped
  2026-08-24. The frontend's preset serializer and recipe builder still
  rebuild steps as `{op, params}` and need the key carried through (Codex).
- **3G — Claude/high capability:** the operation-contract re-opening (gaps 1–2
  from the wave addenda). Shipped 2026-08-24; ADR 0005 §8–§9. Its follow-on
  registrations (the eleven remaining bounces) are lower-cost wave work again,
  under the same bounce rule.

#### Item 4 stack

- **4A — Claude/high capability:** canonical region/mask schema, rasterization,
  exact-mask calculation adapters, persistence, and geometry tests.
- **4B — Codex/sol high:** region manager and precise drawing/editing for lasso,
  polygon, holes and disjoint regions.
- **4C — Claude/high capability:** analysis-consumer migration in bounded
  backend waves.
- **4D — Codex/sol high:** mask previews, conversion flows, consistency audit,
  accessibility and live interaction QA.

#### Item 5 stack

- **5A — Claude/high capability:** calibration profile/schema, versioned
  snapshots, units, migrations and validation.
- **5B — Codex/sol high:** Calibration Center information architecture and
  profile editor.
- **5C — Claude/high capability:** standards ingestion, factor derivation,
  uncertainty, QC rules and golden/reference tests.
- **5D — Codex/sol high:** standards workflow, warnings, residual/QC graphics,
  result integration and export presentation.

#### Item 6 stack

- **6A — Claude/high capability:** coordinate systems, transform graph,
  serialization, resampling and numerical tests.
- **6B — Codex/sol xhigh:** landmark interaction and overlay/blink/checkerboard/
  difference registration workspace.
- **6C — Claude/high capability:** automatic registration metrics, error
  estimates and ROI/mask transformation.
- **6D — Codex/sol high:** review/acceptance workflow, linked navigation,
  transfer affordances and end-to-end visual QA.

#### Item 7 stack

- **7A–7C — Claude/high capability:** cancellable job contract, chunked
  execution, disk-backed results/cache, failure cleanup, and benchmarks.
- **7D — Codex/sol high:** shared progress/cancel/preview/full-run and cache
  status UI across representative workflows.
- **7E — Claude/high capability:** Zarr/OME-NGFF evaluation or implementation
  after a written format decision; Codex reviews only user-facing import/export
  and registration consequences. The written decision must audit the licenses
  of every required codec and dependency against the existing no-GPL-runtime-
  dependency constraint before any implementation starts.

#### Items 8–9

Do not create implementation PRs until their activation gates are explicitly
cleared. If cleared, write a fresh small stack from the ownership table instead
of treating the parked checklists as blanket authorization.

---

## Tier 1 — Scientific trust and daily workflow

### 1. Persistent result and methods model

Add a typed `results` section to `.fvp` rather than storing more opaque state in
`ui_state`. A result references source image IDs and keeps data products
separate from lightweight metadata.

**Item-1 stack status (reconciled 2026-08-24):** 1A shipped 2026-08-22
(PR #162, ADR 0004): schema, member storage, migrations, session carry, and
review hardening. 1B shipped 2026-08-22 (PR #164): the consumability review,
Results & Methods window, and representative persisted-result cards. 1C
shipped 2026-08-23 (PR #165): the shared create/query/member API plus EDS
quantification and particle-analysis adopters. The 1B implementation also
delivered 1D's frontend project-load/reopen integration and UI/store test
matrix, so no separate 1D PR remains. The remaining two representative
adopters — `measure.profile` and `diffraction.index` — shipped 2026-08-26,
closing item 1's cross-domain done condition: all four analysis families
named there now save, close, reopen and inspect with their parameters,
calibration snapshot, geometry and provenance intact. Capture stays
opt-in (`record`) on every adopter; the client affordance that offers it to
a user belongs to item 2's Results workspace, not here.

- [x] Define a versioned result schema with stable result ID, analysis type,
      created time, application version, source IDs, derived IDs, region/mask
      IDs, resolved parameters, calibration snapshot, warnings, and status.
      (1A also snapshots region geometry, not only ids — review finding.)
- [x] Represent scalar, table, curve, fit, map, overlay, and figure outputs
      without giving every workshop its own persistence format.
- [x] Store large result arrays as project members; never inline them into the
      JSON manifest.
- [x] Add project migration, validation, round-trip, missing-member, and
      forward-compatibility tests.
- [x] Provide a small backend/frontend result API that workshops can adopt
      incrementally. (1C, PR #165; initial EDS and particle adopters.)
- [x] Record failure/cancellation separately from completed scientific results.

**Done when:** a project can save, close, reopen, and inspect a representative
EDS quantification, profile, particle table, and diffraction indexing result
with their original parameters and provenance intact. **Met 2026-08-26** —
EDS quantification and particle analysis via PR #165, intensity profile and
diffraction indexing via the adopters above.

### 2. Results browser, rerun, comparison, and reporting

Build one result experience on the schema from item 1.

- [x] Add a Results/Methods workspace grouped by sample, source, analysis type,
      and creation time.
- [x] Result cards show primary values, uncertainty, warnings, calibration,
      source/ROI links, and produced images.
- [x] Reopen the originating workshop with saved parameters and offer explicit
      **Rerun** and **Duplicate with changes** actions.
- [x] Compare compatible results across images or samples with shared units and
      explicit incompatibility messages. (2B: `results_compare` +
      `POST /api/results/compare`. Backend only — 2C renders the verdicts.)
- [x] Build a report from selected results: figures, tables, captions,
      calibration summary, software version, and generated methods text.
      (2B: `results_report`/`results_methods` + `POST /api/results/report`.
      Captions and per-record prose are generated here; PDF/HTML layout is 2C.)
- [x] Export selected results as a structured bundle in addition to existing
      per-tool CSV/JSON/figure exports. (2D: `results_export` +
      `POST /api/results/export`.) A ZIP carrying the report manifest, the
      methods prose, a README, and every cited array as
      `results/<result-id>/<n>.npy` — the same entry names
      `prepare_results` allocates inside a `.fvp`, so the manifest's
      existing `member` citations resolve *within the archive* and nothing
      in the download needs the project it came from. Byte-reproducible
      apart from `generated_at`. An output whose member was already lost
      writes no entry, keeps its citation and is named in the warnings,
      rather than being filled with invented zeros. The download
      affordance in the workspace is still 2A/2C's.

**Item-2 backend status (2026-08-27):** 2B shipped the compatible-result
query and report manifest with deterministic provenance tests. It deliberately
does not deliver the self-contained export described above. The compare and
report endpoints still await 2C's user-facing composition and layout.

**2A completed 2026-08-27:** the Results & Methods workspace now searches,
filters and groups saved runs; cards link sources and produced images; EDS,
particle, profile and diffraction workflows offer explicit capture; and the
four representative adopters support saved-setting reopen, exact recorded
rerun, and Duplicate with changes. The remaining UI work is 2C's comparison,
report composition/layout and a genuinely self-contained structured bundle.

**2C UI completed 2026-08-28:** the workspace now consumes 2B's compatibility
and report endpoints. It provides reference-based comparison with explicit
rejection/calibration states, ordered result and per-output report composition,
an isolated print/HTML preview, vector curve rendering, and HTML/PDF-facing
export. The structured-bundle checkbox remains open: Manifest JSON still cites
large arrays inside the originating project and is labelled accordingly.

**2D completed 2026-08-29:** `POST /api/results/export` closes the
structured-bundle box the note above left open, and with it item 2. The
archive reuses the project container's own member layout, so a manifest
citation that pointed into the `.fvp` now resolves inside the download
itself; `results_export` composes `prepare_results` and `build_report`
rather than re-deriving either. Manifest JSON's "project-dependent" label
in the workspace is still correct for *that* button — it is a different,
lighter artifact, and both are worth offering. Wiring the archive to a
download control in Results & Methods is 2C's remaining piece.

**Done when:** a user can create a short, reproducible sample report without
manually collecting outputs from several transient workshops.

### 3. Universal operation and automation parity

The HTTP surface is much broader than the registered operation catalogue.
Close that gap in coherent waves; do not add a second scripting mechanism.

**3A shipped 2026-08-22** (ADR 0005): generated audit
`docs/operation-coverage.md` + drift test (13/80 analysis endpoints
op-backed), frozen result conventions for the waves, `produces_value_result`
predicate consolidated, README parity overclaim corrected.

- [x] Publish a generated coverage table: GUI action -> route -> `OpSpec` ->
      batch/macro -> Python API -> result type.
- [x] Wave A: particles, grains, trained segmentation, layers, interfaces.
      **Shipped 2026-08-23** (3B): 7 ops registered — `particles`,
      `efd_similarity`, `propose_region`, `grains`, `layers`, `layers_edit`
      (new `structure` category) and `interface_width` (analysis, blessed on
      the `distribution_fit` no-subject precedent) — each emitting ADR 0005
      §5 typed envelopes, with the shared compositions lifted to
      `calc/{efd_rank,region_propose,grain_report,layers_report}.py` so op
      and route run one code path. Six endpoints bounced back per the 3A
      rule (grains/edit, train-segment, train-preview, layers/grains,
      layers/multi, fit-shape) — the contract gaps (multi-input ops,
      structured params) are logged in ADR 0005's wave-A addendum and those
      rows stay wave A in the audit until the ops contract grows.
- [x] Wave B: GPA, CTF, atoms, lattice, and structure/defect operations.
      **Shipped 2026-08-23** (3C): 8 ops registered — `fft`, `vdf` (filter),
      `gpa`, `lattice`, `ctf` (analysis), `atoms`, `template_match`,
      `defects` (structure) — with the compositions lifted to
      `calc/{fourier,gpa,texture}.py` additions and a new
      `calc/atom_report.py`. Multi-map results (gpa ×4, defects ×2) adopt
      the wave-A grains resolution: inline `map` envelopes in the op, session
      images on the route. Two endpoints bounced back per the 3A rule
      (fft-mask, atoms/strain — both structured-params gap 2, logged in
      ADR 0005's wave-B addendum); the one-new-category allowance stays
      unspent.
- [x] Wave C: diffraction calibration, indexing, simulation, stack alignment,
      MIP, and montage.
      **Shipped 2026-08-24** (3D): 3 ops registered — `diffraction_detect`,
      `diffraction_calibrate`, `diffraction_simulate` (existing `diffraction`
      category; allowance unspent for the third wave) — with the
      compositions lifted to `calc/diffraction.find_spots_roi`,
      `calc/diffraction_calib.calibrate_rings` and
      `calc/phase_registry.standard_d_spacing`. Seven endpoints bounced per
      the 3A rule: index (gap 2) and the six-row multi-input cluster
      (image-math, align-stack, mip, stitch, montage, montage-compare — all
      gap 1; montage-compare also gap 2). The audit's `figure` cells for the
      montages were corrected to `map (derived image)`, and the ADR wave-C
      addendum names the would-be `figure` case "gap 3". The ops contract
      re-opening (gaps 1–2) now has its full evidence set and is its own
      high-capability item, not wave work.
- [x] Wave D: remaining spectroscopy (EELS background/thickness/KK/SVD/
      alignment/deconvolution/maps/auto-assign, EDS zeta/continuum/artifacts/
      recalibration/auto-assign), measurement (profiles, ROI statistics,
      distances, spectra/histograms, scale-bar detect), and utility
      (databar strip) operations — every analysis endpoint the coverage
      table lists is in a wave or behind a named item-8/9 gate; item 3
      does not close with any endpoint unassigned (3A review finding).
      **Shipped 2026-08-24** (3E): all 26 endpoints registered — 13 EELS,
      5 EDS, 6 measurement (analysis), `sum_spectrum` (spectral) and
      `strip_databar` (filter) — under the new optional-input omission
      rule (ADR 0005 wave-D addendum), which annotates optional
      variable-length modes as "no op" instead of bouncing whole
      endpoints. Nine calc lifts (two new modules) shrank the three
      route modules that sat at the 500-line ceiling. The audit stands at
      57 of 80 op-backed; the 23 remaining rows are the gap-1/gap-2
      bounce set plus the parked item-8/9 gates, all blocked on the ops
      contract re-opening, which is its own high-capability item.
- [x] Have registered operations emit the item-1 result contract.
      Every wave-registered op (3B–3E) emits ADR 0005 §5 typed envelopes;
      the pre-wave flat-dict set stays frozen behind 1C's legacy adapter
      (ADR 0005 §5), so the contract holds registry-wide.
- [x] Re-open the operation contract for the shapes the waves bounced.
      **Shipped 2026-08-24** (3G, ADR 0005 §8–§9): the high-capability item
      waves A–D kept deferring to. Gap 1 — ops declare named/variadic
      auxiliary `DataStruct` inputs (`OpSpec.inputs`), which the CALLER
      resolves, so `ops/` still never reads the session store; every op
      keeps one primary subject, and a spec's declared inputs decide its
      fn arity (arity-drift test). Gap 2 — `OpParam` takes real JSON lists
      via `RowSpec` (fixed-width/ragged/nullable numeric rows) or
      `RecordSpec` (one level of named fields, a field may be a row list).
      Also closed: exclusive bounds, an any-scalar union, and fractional-int
      rejection contract-wide. Four exemplars registered (`fft_mask`,
      `image_math`, `align_stack`, `mip`) — audit 57 → 61 of 80. The
      eleven remaining bounces are now pattern-following registrations plus
      the `calc/` lifts §1 requires. Two gaps stay open by decision and are
      recorded in the ADR: the shipped CSV param spellings are NOT migrated
      (public surface, cross-lane), and recipes still have no vocabulary for
      naming a second dataset, so multi-input ops are callable from the API
      and HTTP but are not recipe steps.
- [x] Register the remaining eleven bounced endpoints against the re-opened
      contract (fit-shape, atoms/strain, diffraction/index, train-segment,
      train-preview, stitch, montage, grains/edit, layers/grains,
      layers/multi, montage-compare).
      **Shipped 2026-08-25** (3I): all eleven registered — 88 ops, audit at
      72 of 80, every wave at zero and only the eight item-8/9 gated rows
      left. Five `calc/` lifts came with them (§1), one of which exposed a
      d-spacing correctness bug in `/diffraction/index`: a ROI overhanging
      the image left spot coordinates unshifted while shrinking the width
      that scales d, so measured d-spacings were quietly wrong. No shape
      needed a mechanism the contract lacked; the one rough edge found is
      flat scalar lists, recorded in ADR 0005 rather than worked around.
- [x] Give recipe steps a named-input vocabulary so multi-input ops are
      scriptable, not just callable — required by this item's done
      condition, which asks for a saved recipe, not merely an op.
      **Shipped 2026-08-24** (3H, ADR 0005 §8 + its recipe addendum): a step
      carries `"inputs": {"<op input>": "<recipe input>"}` and the run binds
      the pool those symbolic names resolve against, so one saved recipe
      still runs over many subjects. Bound by each caller from what it owns —
      `/batch/run` and `/watch/start` from session image ids (resolved once
      per batch, 404 before queueing), `fv --script` from files named
      relative to the recipe file, `Image.pipeline` from session Images.
      References are checked against the pool before the first step. The
      palette's short-lived `recipe_step` flag is gone (no op is unscriptable
      now); derived-image `recipe_version` is 2, with the id binding recorded
      beside the steps.
- [x] Add recipe validation, versioning, dry-run summaries, and clear failure
      provenance. **Shipped 2026-08-25** (3F): the operation palette is
      searchable; structured params accept JSON lists; named/variadic inputs
      have open-image pickers and pre-run arity checks; preset format v2
      preserves portable symbolic references while importing v1; batch and
      watch runs bind those references separately; the dry-run card reports
      workload, and per-image errors are visible beside progress.
- [x] Correct public documentation until claimed GUI/headless parity matches
      the generated coverage table. README now states 72/80 and names the
      eight item-8/9 gates; generated API docs describe recipe input bindings;
      macro docs no longer imply its narrower wire translator covers every op.

**Done when:** every commonly used GUI analysis can be reproduced through a
saved recipe and Python without maintaining different scientific logic.

### 4. First-class region and mask model

Stop reducing precise regions to bounding rectangles where an operation can
consume a mask.

- [x] Define a shared region contract for rectangle, ellipse, polygon, lasso,
      holes, disjoint regions, inclusion masks, and exclusion masks.
- [x] Persist named ROI sets and region classes in `.fvp`.
- [x] Supply both exact masks and bounding boxes so older calculations can be
      migrated safely.
- [x] Make spectrum integration, statistics, segmentation, particles, grains,
      layers, and batch recipes consume the same contract.
      **Shipped 2026-08-31** (4C-1..5, PRs #191, #192, #194, #195, #196).
- [x] Convert segmentation labels to editable regions and regions to label
      images without losing holes or disconnected components.
      **Shipped 2026-08-31** (`calc/region_convert.py`, the two
      `/api/region-sets` conversion routes).
- [ ] Add clear mask previews and pixel-count/physical-area summaries before
      expensive execution.
      **Summaries shipped 2026-09-01** (`POST /api/regions/preview`); the
      previews themselves are 4D's UI half and remain Codex/sol's.

**Done when:** the same irregular specimen region produces consistent results
in EDS/EELS, imaging statistics, and structural analysis.

> **4A completed 2026-08-29.** `calc/regions.py` is the contract (PR #183);
> the `regions` manifest section persists named sets and their class
> vocabulary (ADR 0006). `rasterize` supplies the exact mask and
> `bounding_box`/`to_rect_roi` the boxes older calculations migrate through,
> the latter in `calc.roi.RectRoi`'s 1-based inclusive form.
>
> The three unchecked boxes are deliberately not started: nothing consumes
> the contract yet. Drawing and editing regions in the workspace is 4B,
> migrating analyses onto them is 4C, and previews/QA are 4D.
>
> **Amended 2026-08-29, starting 4C.** The predicted split happened, forced
> by a real defect rather than by tidiness: `rect` was rasterized through
> its corner polygon, so a rect with one degenerate axis was a zero-area
> ring and a one-pixel-wide rectangle came back as its two corners. The fix
> did not fit in the remaining 9 lines. `calc/regions.py` is now the
> vocabulary (346) and `calc/region_mask.py` the rasterizer (176);
> `rasterize`/`bounding_box`/`to_rect_roi` moved. Still outstanding:
> `Shape` cannot be compared with `==` (it holds numpy rings), and
> `io.regions_model.same_region_set` is the working substitute.
>
> **4C-0 landed 2026-08-30 — the shared resolver, before any wave.**
> `region_resolve.resolve_region` (ADR 0007) is the one place a region
> reference becomes pixels: a named `"set_id"`/`"set_id/region_id"` from the
> ADR 0006 workspace, the frozen `"r1,c1,r2,c2"` string, or nothing at all.
> It returns a `ResolvedRegion` carrying BOTH an exact mask and the 1-based
> inclusive `RectRoi` every bbox-shaped analysis already speaks, so a
> consumer adopts it without changing anything downstream.
>
> The load-bearing invariant is that `mask is None` exactly when the
> selection fills its own bounding box — which makes a rectangle-only
> consumer *correct* rather than merely unbroken, and keeps a rectangle a
> slice instead of forcing a multi-gigabyte cube through an all-True mask.
> Provenance names the frame in typed fields rather than adding an eleventh
> dialect to the free-text `convention` string (16 sites, ten incompatible
> kinds of claim: coordinate frames, label encodings, value semantics).
>
> **4C-1 landed 2026-08-30 — EDS/EELS spectrum integration on exact masks.**
> `GET /image/{id}/spectrum` takes `region_ref` (`"set_id"` or
> `"set_id/region_id"`) and sums the region's EXACT mask.
> `calc/raster.masked_sum_spectrum` is the one summation, and
> `region_sum_spectrum` now delegates to it so the legacy rect answer
> cannot drift from the masked one. `region` in the response is still the
> 1-based inclusive bounding rect, so existing clients are untouched; the
> new `exact_mask` says whether that rect is the whole truth.
>
> **The resolution happens in the route, not the op.** `ops/registry.py`'s
> contract is that auxiliary inputs arrive already resolved because "the
> caller owns the session store, so the pure layer never looks an id up".
> A region reference is an id, so `sum_spectrum` keeps its 1-based corner
> params and stays reproducible from params alone. Teaching registered ops
> to take a region needs `run()` to gain a resolved-region channel beside
> `inputs` — an ops-contract change (ADR 0005), deliberately not smuggled
> in here. That is what 4C-5 has to settle before batch recipes can carry
> a region.
>
> Adding the named path pushed `routes/images.py` past 500 lines, so the
> scoping decision moved whole into `routes/_spectrum_scope.py` rather
> than being trimmed in place.
>
> **4C-2 landed 2026-08-30 — imaging statistics over canonical regions.**
> `calc/region_stats.region_stats` is the one place a region becomes
> mean/std/min/max, and `/measure/roi` (via `region_ref`), the
> `image_stats` op and `profile_stats.roi_stats` all read through it.
> `roi_stats`' inscribed ellipse now routes through the 4A `ellipse`
> primitive — the two are pixel-identical over square, oblong and
> degenerate bounds, which is what 4A's footprint semi-axis was chosen
> for, now asserted rather than asserted-in-a-docstring.
>
> **Two conventions were deliberately NOT unified.** `roi_stats` reports
> MATLAB's sample std (ddof=1); `image_stats` reports the population std
> (ddof=0). 4C converges which PIXELS an analysis reads, not which
> estimator it publishes; switching either would change numbers users
> already have. `STD_MATLAB`/`STD_POPULATION` name them so the divergence
> is legible, and a test pins both.
>
> **Counting and averaging are now separate questions.** `n_pixels` is
> what the region selects, `n_finite` how many carry a value; physical
> `area` follows `n_pixels` because a dead pixel still occupies specimen
> area, while the aggregates use the finite subset. That makes `roi_stats`
> no longer return NaN for a whole ROI because one pixel was NaN — the
> single behaviour change in this wave, and visible via `n_finite`.
>
> `np.std(..., where=...)` turned out to allocate a float64 copy of the
> whole view (33.6 MB on a 2048² float32 raster), so the deviation pass is
> chunked and two-pass — one-pass `E[x²]-E[x]²` loses most of the
> precision on an EM image with mean 30000 and std 50. The bounded-memory
> guard caught that; it is budgeted against the raster's own size, since
> the `isfinite` mask is unavoidable.
>
> #189's moved names (`rasterize`, `bounding_box`, `to_rect_roi`) are
> re-exported from `calc/regions.py` through PEP 562 — lazily, because
> `region_mask` imports `regions` and a top-level import would cycle.
>
> **4C-5's prerequisite landed 2026-08-30 — a region as an op PARAMETER.**
> Registered ops could not be region-scoped at all, and the obvious fix
> (let an op call the resolver) breaks `ops/registry.py`'s stated contract
> that the pure layer never looks an id up — a breach the pure-layer guard
> would not catch, since it names the server stack rather than session
> coupling.
>
> `ops/_region_param.REGION_PARAM` carries the canonical geometry inline as
> an ordinary list-shaped `OpParam`. **`run()` does not change** (ADR 0007
> §8). Naming stays a caller concern: a recipe runner owns the session, so
> it resolves a symbolic reference and substitutes the geometry into this
> param before dispatch — the op never sees an id, and the recorded params
> stay the complete reproduction key ADR 0005 requires.
>
> `sum_spectrum` is the first adopter; the seven catalogues that parse the
> frozen `"r1,c1,r2,c2"` string are 4C-5's remaining surface. The
> `mask is None` invariant moved into `calc.region_mask.mask_and_rect`, now
> shared by the named path and the geometry param.
>
> Waves 3–4 remain: segmentation and particles and grains, layers and
> structural. Then 4C-5: the recipe-runner substitution above, plus the
> cross-consumer consistency test item 4's "Done when" asks for — for which
> `test_the_op_and_the_route_agree_on_the_same_region` is the first
> instance, an op and a route reaching one answer by different paths.

> **Label conversion completed 2026-08-31.** `calc/region_convert.py`
> converts both ways and `/api/region-sets/from-labels` and `/to-labels`
> are where it is reachable. The stack's other half — the region manager
> and precise drawing/editing (4B, Codex/sol) — is untouched, as are 4D's
> previews.
>
> The load-bearing choice was that ring NESTING defines the parts, not
> connected components. Grouping by components first is a trap: with
> 8-connectivity two diagonally-touching pixels are ONE component but
> marching squares traces TWO rings, so "largest ring is the outline, the
> rest are holes" turns the second pixel into a hole — a region that
> rasterizes, looks like a shape, and is not the label. With
> 4-connectivity the rings match but a diagonal pair becomes two regions
> and the label's identity is lost instead. Depth comes from containment
> rather than winding direction, for the reason `calc/contours.py`
> already distrusts skimage's start vertex. The mask is padded before
> tracing: `find_contours` leaves a path open at an array edge and
> closing it afterwards cuts the corner, which made a 4x4 block in a
> corner round-trip as 6 pixels of 16.
>
> Lossless has a price worth stating: an outline keeps a vertex per
> boundary step, so 150 grains at 512x512 trace to ~32,000 vertices.
> `calc/contours.py` remains the SIMPLIFYING tracer for the UI's draw
> assist and is deliberately not what this uses.
>
> The self-review dispatched an adversarial agent, whose findings were
> two wrong cost models and four permissive writes — `find_objects`
> allocating per label VALUE (433 MB for an 8x8 array holding
> 10,000,000), a containment test that rasterized every ring (~30 GB on a
> 512x512 salt-and-pepper label, which is what a noisy segmentation
> looks like), and conversions that merged two regions through a
> duplicate id, a duplicate value, a truncated float or an empty `values`
> mapping read as "none given". Mutation testing then found three
> REDUNDANCIES rather than three gaps: a hole's parent selected by two
> rules that always agree, a bounding-box test restated inside the
> predicate the screen guards, and a self-containment guard the area test
> already made unreachable. Each is now stated once — the same "a second
> copy is how a rule starts meaning two things" that 4C-5 hit with
> `_check_image`.
>
> The seam, as in every previous wave, was between new code and old: the
> app stores every derived map as float64, and `labels_to_regions`
> refuses a float array on purpose, so a route casting blindly would have
> stepped past that refusal at the one boundary it exists to guard. The
> route checks the values ARE integers before typing them as integers,
> and refuses a spectrum image by KIND — its raster is a sum over energy,
> which can be whole-numbered and would have traced a region per count.

> **4D backend half completed 2026-09-01.** `POST /api/regions/preview`
> reports what an analysis WOULD read — pixel count, fraction of the
> image, clamped bounding box, whether the selection is narrower than
> that box, and physical area — without reading a pixel value. The box
> stays unchecked because the previews themselves, the conversion-flow
> UI, the consistency audit and the accessibility/interaction QA are
> 4D's Codex/sol half and are untouched.
>
> The design is one line: a preview RESOLVES, it does not re-derive. It
> calls the same `resolve_region` the analyses call, so it inherits their
> clamping, image binding and refusals, and its test asserts its
> `pixel_count` equals the `n_pixels` `/measure/roi` reports over the same
> reference rather than a constant of its own. A preview computed by a
> second code path is a preview of something else, and a scope summary
> that disagrees with the run spends the user's trust to tell them the
> wrong number (ADR 0007 §12).
>
> Two decisions worth naming. An uncalibrated area is reported ABSENT,
> not as the pixel count: `region_stats` returns the count in its `area`
> field, which is defensible inside a bundle whose caller knows the unit
> and is not defensible in a user-facing summary, where the same number
> would silently mean px² or nm². And the request field is `region_ref`,
> not `region`, because that is already the wire name for a symbolic
> reference at `/measure/roi`, in batch steps and in recipe steps, while
> `region` on the wire means an op's inline geometry — a third spelling
> of one idea is how a caller learns to guess.
>
> **Amended 2026-09-01: areas no longer assume square pixels.** The
> review of this endpoint found that its physical area was
> `n * pixel_size ** 2`, four times wrong on a 0.5 nm x 2.0 nm scan — and
> those are real, since `io/nanoscope` derives the two spatial scales
> independently. Correcting it only in the preview would have broken the
> agreement that endpoint exists to have, so it was corrected at the
> source: `DataStruct.pixel_area` multiplies the two scales, and every
> consumer that reports an area now takes an AREA rather than deriving
> one from a length — `region_stats`, `roi_stats`, `region_propose`,
> particles, grains, grain layers, and the preview.
>
> Square pixels are numerically unchanged, which the MATLAB golden tests
> confirm. The area is absent unless both axes are calibrated in the same
> unit, since nm x um is a number in neither.
>
> This did NOT close item 5's "do not assume square" box; see the
> lengths amendment below, which closes the analysis half of it.
>
> **Amended 2026-09-01: lengths no longer assume square pixels either.**
> The convention chosen is measurement in PHYSICAL coordinates: every
> length is computed on the calibrated grid rather than derived from a
> pixel measurement times one scale. Verified property-first — the same
> physical disc sampled at 1:1, 2:1, 1:2 and 4:1 returns the same
> diameter and the same circumference.
>
> Three things had to be true for that to work.
>
> First, most of `regionprops` already honours anisotropic `spacing`
> correctly — area, equivalent diameter, Feret, the moment-ellipse axes,
> eccentricity and orientation were all checked against closed forms.
> But `perimeter_crofton` REFUSES anisotropic spacing outright, so
> `calc/crofton.py` supplies it: Crofton's formula discretised over
> lattice line families, with the directions CHOSEN by physical angle
> rather than fixed, because the four fixed pixel offsets collapse into a
> 19-degree band at 6:1 anisotropy and take the error from -5.5% to
> -15.7%. On square pixels the search provably picks skimage's own four
> offsets, so it reproduces `perimeter_crofton` bit for bit and existing
> circularity values do not move.
>
> Second, dimensionless is NOT scale-invariant when only one axis is
> scaled. Circularity, eccentricity, aspect ratio, solidity and
> orientation are all invariant under scaling both axes together — which
> is why a single `pixel_size` never mattered to them — and none survives
> scaling one axis alone. A round particle on 3:1 pixels read as aspect
> ratio 3.0 and eccentricity 0.94, i.e. a rod. These are now measured in
> physical space whenever calibration allows.
>
> Third, `boundary_network_calibrated` had the same bug in a different
> shape: two horizontally-adjacent pixels share a VERTICAL edge whose
> length is the ROW extent, and vice versa, so summing the edge COUNT and
> multiplying by one scale assumes the two are equal.
>
> `DataStruct.pixel_spacing` is the per-axis companion to `pixel_area`,
> with the same refusals, and `pixel_area` is its product by
> construction. Square pixels are bit-for-bit unchanged, asserted rather
> than assumed.
>
> **Scope, stated precisely, because the first draft of this note
> overclaimed.** What is fixed is the PARTICLE AND GRAIN SHAPE path.
> A self-review found four other places carrying the identical
> single-scale assumption, none of them touched:
>
> * `calc/gpa.py` — `ux` is a COLUMN displacement and `uy` a ROW
>   displacement, and both are multiplied by `pixel_size`. They then feed
>   `np.gradient` for the strain components, so the error compounds.
>   The most serious of the four.
> * `calc/export.py` — the `distance`, `profile` and `polyline`
>   measurement LABELS. A user-drawn segment's physical length is
>   `sqrt((dr*s_r)^2 + (dc*s_c)^2)`, not its pixel length times one
>   scale. These are numbers a user reads straight off an exported
>   figure.
> * `calc/defects.py` — Ham line-intercept dislocation density. The
>   horizontal test lines span COLUMNS and the vertical ones span ROWS,
>   and `total_len` multiplies both by `pixel_size`. Exactly the
>   boundary-network bug, in a different subsystem.
> * `calc/eds_maps.py` — line-profile distance along an arbitrary line,
>   same diagonal-length error as the export labels.
>
> `calc/grain_layers.py`'s `pixel_area = pixel_size ** 2` is NOT one of
> these: it is a documented fallback used only when a caller supplies no
> area, and the routes pass `ds.pixel_area`.
>
> Also still open: per-axis energy and reciprocal calibration (`ctf.py`
> and `diffraction.py` scale the FFT by one `pixel_size`, so anisotropic
> pixels give anisotropic reciprocal space), and the project/UI
> calibration model. The box stays unchecked.
>
> **Amended 2026-09-04: the v0.4.0 *Known limitations* list is closed.**
> The four sites above shipped in v0.4.0 (#203, #204). The release's
> pre-tag audit named the same shape still live in `calc/profiles.py`,
> `calc/profile_stats.py`, `calc/radial.py`, `calc/layers.py` with
> `calc/trace_roughness.py`, and `calc/grain_layers.py`; each now takes
> a keyword-only `spacing` and every route and op passes
> `DataStruct.pixel_spacing`. Two of them are not simple lengths: a
> RADIAL profile bins by physical distance, because on 2:1 pixels a
> physically round ring spans pixel radii 15 to 30 and no rescaling of
> pixel bins can put it back into one; and a LAYER stack has two axes
> with different meanings, so thickness, σ_erf and σ_w scale by the
> extent along the growth axis the analysis actually chose, while the
> trace's correlation length and PSD wavelengths scale by the other one
> (`LayerResult.lateral_size`, `analyze_trace(lateral_size=)`). The
> `pixel_size ** 2` fallbacks in `calc/grains.py` and `calc/particles.py`
> were verified to be exactly that -- every in-tree caller passes
> `pixel_area` and `spacing` -- and were left as the documented
> single-length compatibility path. Square pixels are bit-for-bit
> unchanged at each site, asserted in `tests/test_anisotropic_followup.py`.
> Reciprocal/energy calibration and the project/UI model remain open.
>
> **For the UI half:** the preview reports the RASTERIZED pixel count,
> under `calc/region_mask`'s centre-sampling convention. A polygon drawn
> in SVG and the mask an analysis uses differ at the boundary, so a
> preview that outlines the polygon while the summary counts the raster
> is showing two different regions. Whether that gap matters at display
> resolution is a UI judgement, but it is a real one.

> **Math audit, 2026-09-01.** Prompted by the pixel-area bug: if one
> physical quantity was built from the wrong ingredient, others might be.
> Checked by PROPERTY and against published references rather than by
> reading, because 87 calc modules and 19,000 lines do not survive
> inspection.
>
> **One real error, in `astm_grain_size_number`.** The ASTM E112 grain
> size number used `log2` with the coefficient 6.6439 — which is exactly
> `2/log10(2)`, a constant CONSTRUCTED for `log10`. The slope was
> therefore 3.3219x too steep: 10 µm grains reported G = 40.8 where E112
> gives 10.7, and the scale itself only runs from about 00 to 14, so
> every value the function ever returned for an ordinary micrograph was
> off the scale it claimed to be on. Now derived from E112's planimetric
> relation in the docstring so the constants can be checked, and tested
> against published G/density pairs from the standard's own table.
>
> Its old test could not have caught it: it recomputed the
> implementation's own expression and asserted the two matched, which is
> true of any formula whatsoever. That is the third tautological or
> false-passing test found in this branch.
>
> **A second, smaller bias in the same function, found while reviewing the
> first fix.** `grain_report` reached G through the mean equivalent
> DIAMETER, which assumes every grain is the same size: `4/(π·D̄²)`
> exceeds the true `1/mean(area)` by Jensen's inequality whenever they
> vary, so G came out high and the microstructure read finer than it was —
> +0.06 at a coefficient of variation of 0.2, +0.22 at 0.4, +0.44 at 0.6,
> on a scale quoted to a tenth. E112's planimetric method is grains per
> unit AREA and both numbers were already in hand, so it counts now
> instead of inferring. `astm_grain_size_from_density` is the primitive;
> the diameter form stays for direct callers and documents what it
> assumes.
>
> **Two claims corrected where the code was right and the comment was
> not.** `trace_psd`'s Parseval note said `sum(power)` gives the variance
> of the WINDOWED trace; it is window-compensated and recovers the
> ORIGINAL variance (a sinusoid of amplitude A sums to exactly A²/2),
> which understated it by 8/3 and would send anyone verifying the
> normalization hunting a bug that is not there. And `orientation_rad`
> documented no reference axis, though it is measured from the ROW axis —
> 90° from what most readers assume, so a consumer plotting it as "from
> horizontal" draws every particle across its own short axis.
>
> **Verified correct, by measurement rather than assumption:** dimensional
> scaling (area exponent 2.000, length 1.000) across grain, particle and
> region statistics; FFT/lattice d-spacing to 0.1% with γ = 90.000° and
> the right cell area; roughness Ra/Rq exactly `2A/π` and `A/√2`
> unleveled — the leveled default differs because a sinusoid genuinely
> has a non-zero best-fit tilt, not because of an error; the EELS
> cross-section's θ_E, Lorentzian angular integral and 4πa₀²(R/E)(R/T)
> prefactor against Egerton; `2√(2 ln 2)` for FWHM/σ; BT.601 luma
> coefficients; and natural logs in power-law fits, which are
> base-independent for a slope.
>
> Circularity deserves its own line because it LOOKS wrong: a square
> reports 0.876 against the textbook π/4 = 0.785. That is the Crofton
> perimeter estimator's known bias on axis-aligned edges, the estimator
> is named in the field's own comment, and it is the better choice for
> the grain shapes this tool actually measures (a disc reports 0.9967).
> Not a defect.

### 5. Calibration profiles and quantitative standards

> **4C completed 2026-08-31 — the consumer migration, and its "Done when".**
> Nine ops take the region contract: `sum_spectrum`, `image_stats`,
> `particles`, `efd_similarity`, `grains`, `train_segment`, `train_preview`,
> `layers`, `layers_edit`. A recipe step may NAME one, and the runner
> substitutes resolved geometry per image so the op never sees an id and the
> recorded params stay a replay key (ADR 0007 §11).
>
> Item 4's "Done when" is pinned as a test rather than asserted: five
> consumers read one reference and are each compared against a mask
> rasterized independently by `calc.region_mask`, so agreeing with each
> other is not enough to pass.
>
> Three decisions the waves forced, all recorded in ADR 0007 §9-§11:
> **labels are exact, context is the bounding box** — a threshold is a
> function of the selected values, a texture feature is a function of a
> neighbourhood, and `label_context` says which an op got;
> **a reduction over varying support is refused, not approximated** —
> `reduce="sum"` over an irregular region tracks the region's width, so a
> flat specimen grows flanks a detector reads as interfaces;
> **naming is a caller concern** — geometry is the op contract.
>
> Sixteen defects were found in review (eight by ChatGPT, eight in a
> self-review) and every one sat at a SEAM rather than in the logic: a
> request model that dropped a new field, a sibling op that never got the
> same fix, a second call site, a summary left unscoped beside a masked
> map, a rule restated instead of called. Three were false claims in
> comments or provenance labels, which are worse than silent bugs because
> they tell the next reader not to check. Worth carrying into 4B/4D as a
> review checklist: for each change, name every OTHER place that must
> change with it, and re-read every claim the diff makes about itself.


Create a shared Calibration Center, with EDS as the first complete workflow and
EELS/dose/spatial/reciprocal calibration using the same persistence rules.

#### 5a. Calibration profiles

- [ ] Named microscope, detector, camera, and acquisition profiles.
- [ ] Per-axis spatial/scan/energy/reciprocal calibration; do not assume square
      pixels in the project/UI model.
- [ ] EDS detector window/efficiency, solid angle, takeoff angle, live time,
      dead time, probe current, dwell time, and beam energy.
- [ ] Calibration validity range, source, date, operator note, uncertainty, and
      version history.
- [ ] Snapshot the applied profile into each result so later profile edits do
      not rewrite history.

> **2026-09-04 — the reciprocal half of the second box shipped.**
> `calc/ctf.py`, `calc/lattice.py` and `calc/diffraction.py::index_spots`
> (with `index_spots_roi`) take a keyword-only `spacing`; the lattice, CTF
> and index routes and ops pass
> `spacing_at_column_scale(<the pixel size the caller typed>, ds.pixel_spacing)`
> (`calc/calibration.py`), so a user-typed pixel size keeps meaning the
> column scale and the row extent follows the image's own ratio. On 2:1
> pixels a round Thon ring was an ellipse, a square 4 Å lattice was 4 by
> 2, and a (200) spot along rows indexed as (400). Square pixels are
> bit-for-bit unchanged (`tests/test_reciprocal_spacing.py`). **Owner
> decision, same day:** the FFT-mode `d = W·px/r` in `index_spots`
> (verbatim `indexDiffraction.m`, off by H/W for a row-direction spot on a
> NON-SQUARE image) is replaced by the reciprocal-vector form on every
> image shape — the MATLAB workshop model uses `sqrt(H·W)` and disagrees
> with its own calc, so parity had nothing to hold, and the golden pattern
> is square. `diffraction_simulate.py` simulates a camera with one
> detector pixel size by design. The box stays unchecked for its other
> half: energy-axis profiles and the project/UI calibration model.

#### 5b. Standards and quantification QC

- [ ] Import a known-composition standard and define its reference regions.
- [ ] Derive and store experimental Cliff–Lorimer, ζ, and supported EELS factor
      sets with uncertainty and provenance.
- [ ] Compare measured and built-in factors without silently replacing either.
- [ ] Surface peak interference, fit residuals, detection limits, absorption or
      thickness concerns, extrapolation, missing metadata, and poor-count
      warnings beside the reported composition.
- [ ] Add a compact calibration/QC panel to every quantitative result and
      export.
- [ ] Verify representative cases against golden or independently calculated
      references before enabling a method by default.

**Done when:** an EDS composition can be traced from raw counts through the
standard, detector/acquisition metadata, factors, corrections, uncertainty,
and final exported result.

---

## Tier 2 — Correlative work and large datasets

### 6. Cross-modal registration

Add a transform graph to the project so datasets share coordinates without
destructively resampling their source data.

- [ ] Define coordinate systems and saved translation/rigid/affine transforms,
      with source/target IDs, residual error, and method provenance.
- [ ] Manual landmark registration with overlay, opacity, blink, checkerboard,
      and difference previews.
- [ ] Automatic translation/rigid/affine registration using appropriate image
      metrics, followed by user review rather than silent acceptance.
- [ ] Apply transforms to displays, ROIs, masks, measurements, annotations, and
      derived maps.
- [ ] Support different pixel dimensions, fields of view, crops, and physical
      units.
- [ ] Export transform matrices and a flattened registered image when needed,
      while retaining the non-destructive project representation.

**Done when:** a region drawn on HAADF can be inspected and analysed at the
corresponding location in EDS, EELS, diffraction, or another registered image.

### 7. Large-data execution and interoperable storage

Generalise the existing job and streaming foundations beyond the few operations
that currently use them.

- [ ] One cancellable job contract with progress, phase, warnings, and partial
      cleanup for every expensive operation.
- [ ] Preview-resolution execution for interactive tuning, followed by an
      explicit full-resolution run.
- [ ] Memory-budgeted chunked execution for spectrum images, stacks, large
      images, and other compatible analyses.
- [ ] Cache results by immutable input identity, mask, resolved parameters, and
      algorithm version; make cache use visible and invalidation deterministic.
- [ ] Disk-backed derived/result arrays and bounded project extraction.
- [ ] Evaluate Zarr/OME-NGFF import/export for multiscales, labels, coordinate
      systems, and transformations without weakening microscopy metadata.
- [ ] Add realistic performance tests and document supported dataset sizes and
      fallback behaviour.

**Done when:** multi-GB routine EDS/EELS and image-stack workflows remain
interruptible, memory-bounded, and recover cleanly from cancellation or error.

---

## Specialty tracks — last options, parked by default

These appear last intentionally. Completing Tier 2 does not automatically
activate either track.

### 8. Optional 4D-STEM extensions

The existing virtual-detector, COM, DPC, and iDPC implementation remains
supported. Advanced work stays in `PLAN_4DSTEM.md` and starts only when a real
use case and representative dataset justify it.

- [ ] First optional increment: diffraction-pattern inspector with calibrated
      axes, pan/zoom, contrast/log controls, center/ring/spot tools, and direct
      aperture editing.
- [ ] Bragg-disk detection and calibration with inspection/QC.
- [ ] Strain mapping with reference-region selection and uncertainty.
- [ ] Orientation/phase mapping or ACOM only after strain is validated.
- [ ] Ptychography remains a separate, later decision with explicit algorithm,
      validation-data, performance, and licensing review.

**Activation gate:** at least one recurring user workflow, representative real
data, expected quantitative outputs, and time budget for independent
validation.

### 9. Optional tomography workflow

Do not build a standalone 3D renderer first. If tomography becomes valuable,
start from the experimental workflow.

- [ ] Tilt-series import, metadata inspection, ordering, and bad-frame handling.
- [ ] Fiducial and cross-correlation alignment with tilt-axis correction.
- [ ] Alignment residuals and missing-wedge visualisation.
- [ ] Validated FBP followed by iterative SIRT if justified.
- [ ] Orthogonal slice inspection, segmentation, and volume measurements.
- [ ] Optional 3D rendering only after reconstruction and quantitative volume
      tools work reliably.

**Activation gate:** a concrete tilt-series corpus, a user who needs the
workflow, defined reconstruction ground truth, and willingness to support the
large-data/volume model.

---

## Progressive PR discipline

Each numbered item is a stack, not one oversized PR.

1. Land contracts/schema and migrations before workshop wiring.
2. Keep pure calculations in `calc/`, storage/parsing in `io/`, and routes thin.
3. Add one vertical slice with tests before sweeping other analyses.
4. Keep every PR independently reviewable and green; document its parent branch
   when stacking.
5. Validate backend pytest, ruff, mypy, frontend type-check/tests/build, and any
   relevant golden/real-data cases before starting the next PR.
6. Include project save/reopen tests for every persisted feature.
7. Require visible failure, cancellation, invalid-calibration, and stale-result
   states—not only happy-path screenshots.
8. Do not merge as part of an autonomous implementation run; hand the stack to
   the reviewer with order, scope, test evidence, and known limitations.

## Review checkpoints

After items 1–2: confirm the result model works across spectral, structural,
and diffraction outputs before broad adoption.

After items 3–5: perform a real EDS session from standard calibration through a
saved/reopened quantitative report, plus one non-spectral recipe.

After item 6: register dissimilar-resolution HAADF and elemental data, transfer
an irregular ROI, and verify physical coordinates and exported provenance.

After item 7: run a representative multi-GB dataset under a declared memory
budget, cancel it, rerun it, and confirm cache and cleanup behaviour.

Only then consider the activation gates for items 8 or 9.
