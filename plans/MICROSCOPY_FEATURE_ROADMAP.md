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
matrix, so no separate 1D PR remains. Item 1 itself stays open until the
profile and diffraction representative adopters satisfy its cross-domain
done condition; that adoption belongs in the operation/result waves rather
than another persistence UI PR.

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
with their original parameters and provenance intact.

### 2. Results browser, rerun, comparison, and reporting

Build one result experience on the schema from item 1.

- [ ] Add a Results/Methods workspace grouped by sample, source, analysis type,
      and creation time.
- [ ] Result cards show primary values, uncertainty, warnings, calibration,
      source/ROI links, and produced images.
- [ ] Reopen the originating workshop with saved parameters and offer explicit
      **Rerun** and **Duplicate with changes** actions.
- [ ] Compare compatible results across images or samples with shared units and
      explicit incompatibility messages.
- [ ] Build a report from selected results: figures, tables, captions,
      calibration summary, software version, and generated methods text.
- [ ] Export selected results as a structured bundle in addition to existing
      per-tool CSV/JSON/figure exports.

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

- [ ] Define a shared region contract for rectangle, ellipse, polygon, lasso,
      holes, disjoint regions, inclusion masks, and exclusion masks.
- [ ] Persist named ROI sets and region classes in `.fvp`.
- [ ] Supply both exact masks and bounding boxes so older calculations can be
      migrated safely.
- [ ] Make spectrum integration, statistics, segmentation, particles, grains,
      layers, and batch recipes consume the same contract.
- [ ] Convert segmentation labels to editable regions and regions to label
      images without losing holes or disconnected components.
- [ ] Add clear mask previews and pixel-count/physical-area summaries before
      expensive execution.

**Done when:** the same irregular specimen region produces consistent results
in EDS/EELS, imaging statistics, and structural analysis.

### 5. Calibration profiles and quantitative standards

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
