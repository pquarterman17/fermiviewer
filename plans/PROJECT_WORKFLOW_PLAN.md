# Project workflow plan — folder import, stable browsing, area measurement, projects

Make FermiViewer usable for many-sample studies (thin films, one varied
parameter, ~20 images per sample, several samples): import whole folders
as named groups, page through a series at constant physical scale,
measure region areas in physical units, and grow the flat filmstrip into
a project/sample hierarchy whose deliverables are a result-vs-parameter
table + plot (CSV), a shared-scale labelled comparison montage,
per-sample statistics, and sample-wise side-by-side stepping. Everything
extends the existing group / measure / workspace / montage primitives —
no parallel mechanisms. The project itself is a documented,
schema-validated single file (`.fvp`, ADR 0002) built to transfer
between machines.

**Status:** Active
**Parent:** MAIN_PLAN.md
**Created:** 2026-08-09
**Updated:** 2026-08-09

---

## Context

### How the pieces fit together

- **Samples and projects ARE `ImageGroup`s** (`frontend/src/lib/groups.ts`
  `{id, name, ids}`; store field `imageGroups`; actions in
  `store/viewerCompareActions.ts`). W1 folder import seeds them; W4
  renders them as collapsible filmstrip sections and hangs parameter
  fields off them; compare panes already bind to groups
  (`SideBySideStage.tsx` steps within a group), so sample stepping is
  nearly free. Groups persist today inside the opaque workspace
  `client_state` (`lib/api/workspace.ts` → `routes/session_io.py` →
  `io/session_file.py`); W5 promotes them to the schema-validated
  `samples` section of the `.fvp` manifest, because a parameter value
  with a unit is scientific data and must be checkable.
- **Region areas ride the measure rails** (`Measure {kind, pts}` in
  `store/viewerTypes.ts`, rendered by `MeasureOverlay.tsx`, captured by
  `useStagePointers.ts` — the polyline click-flow already exists). Two
  new kinds (polygon, lasso) share ONE area function placed next to
  `physDist` in `lib/geometry.ts`. Backend segmentation
  (`calc/segment.py` multi_otsu/morph, trained grains) proposes
  outlines; a new pure `calc/` contour tracer converts masks to editable
  polygons. Physical-area precedent: `calc/grain_layers.py:179`, and
  `calc/particles.py` `RegionStats.area_calibrated` (line 205) with
  `region_stats()` already computing calibrated area per labelled region.
- **Constant physical scale** = a µm-per-screen-px lock replacing the
  per-image `view ?? fitView(img, vp)` default in `Stage.tsx`,
  `CompareStage.tsx:39`, `SideBySideStage.tsx:145`,
  `useStagePointers.ts:393`. Math extends `lib/geometry.ts`; state lives
  in a standalone zustand store (pattern: `store/stage.ts`), never in
  the pinned `viewer.ts`.
- **Deliverable plumbing already exists**: labelled montage in
  `calc/montage.py` + `/analyze/montage` (`routes/imaging_ops.py`),
  CSV/table export in `lib/resultsExport.ts`, mean/spread aggregation in
  `lib/measureStats.ts`, parameter-field UI schema in `lib/params.ts`.

### Size ratchet — the sequencing driver

Per item, the strategy is stated as NEW MODULE or FRONT-LOADED
EXTRACTION. The capped files this plan is near:

- `Stage.tsx` 640, pin 640 (zero headroom) → item 8 extracts first
- `MeasureOverlay.tsx` 636, pin 636 (zero) → item 13 extracts first
- `store/viewer.ts` 575, pin 575 (zero) → never touched: new state goes
  in standalone stores; new group actions go in
  `viewerCompareActions.ts` (243/500)
- `routes/images.py` 497/500 → never touched: folder import is a new
  route module
- `Filmstrip.tsx` 437/500 → item 21 extracts before the tree lands
- `server.py` 476/500, `imaging_ops.py` 457/500 → new routers cost ~2
  lines in server.py (acceptable); montage-v2 goes in a NEW route
  module, not into imaging_ops. No pin is ever raised.

### Data / control flow

```
folders on disk ──/session/open-folder──> ImageMeta[] grouped per folder
        └──> createGroup(...) ──> imageGroups (samples, params, parent)
                                        │
filmstrip sections <────────────────────┤──> compare panes step per sample
                                        │
polygon/lasso pts (measures) ──shoelace × pixelSize²──> per-image region
  table ──CSV──> out                    │
        └──per-sample mean/sd/n─────────┴──> result-vs-parameter
             table + plot (CSV)  ·  shared-scale labelled montage (figure)
```

### Dependency map

- Parallel-safe starters (disjoint files): 1, 6, 7, 12, 13, 21, 30
- 30 blocks 20 and 31–36; 8 blocks 9–11; 13 blocks 14; 14 blocks 15–16;
  20 blocks 22–28; 21 blocks 22; 15 + 23 block 24; 34 blocks 35
- Same-file conflict sets (never run two agents inside one set):
  {8} Stage.tsx · {9, 14} useStagePointers.ts · {9, 26}
  SideBySideStage.tsx · {13, 14} MeasureOverlay.tsx · {21, 22}
  Filmstrip.tsx · {2, 4} FolderOpenDialog.tsx · **{6, 12} both extend
  lib/geometry.ts** · **{8, 13, 21} all lower a pin in
  tests/test_repo_integrity.py** — run each set as ONE unit of work,
  never as concurrent agents · {1, 16, 25} each add ~2 lines to
  server.py (rebase-trivial)
- Cross-workstream: 24 needs W3's 15; 27 needs W1's 1–3;
  W2's 9 makes 26 genuinely comparable but is not a hard dependency
- Backend items (1, 16, 25) must clear ruff + mypy + pytest
  (--cov-fail-under=82); prefer FV_TEST_DATA real fixtures where the
  corpus has suitable folders, asserting the fixture property used

### Resolved decisions

- (2026-08-09) Folder import: one ImageGroup per folder, named after the
  folder; an import-dialog checkbox merges all selected folders into a
  single group instead.
- (2026-08-09) Browsing: constant physical scale — same µm per screen px
  across a series; differing letterboxing between image sizes is
  accepted; uncalibrated images fall back to fitView.
- (2026-08-09) Areas: closed polygon AND freehand lasso share one area
  computation; edge auto-detection layers on top of both (segmentation
  proposes, user corrects); output is a per-image region table with
  physical areas + CSV, rolled up into project comparison; NOT baked
  into exported figures (out of scope).
- (2026-08-09) Projects: one panel that grows (today's flat filmstrip
  until sample sections exist; no second view or mode toggle); the tree
  is virtual — seeded from the disk layout at import, owned by the
  project afterwards (rename/regroup/nest freely; an image may sit in
  two samples; survives disk reorganisation); samples carry named
  parameter fields as real data; all four comparison outputs are wanted.
- (2026-08-09) Plan-level: samples/projects EXTEND ImageGroup +
  imageGroups (no parallel tree store); folder import and project
  seeding share createGroup; region tools ride the measure rails;
  scale-lock state lives in a standalone store so the pinned viewer.ts
  is never touched; the montage deliverable extends calc/montage.py.
- (2026-08-09) **Project file format — closes former gates G1 and G2.**
  Fully specified in `docs/adr/0002-project-file-format.md` with the
  machine-readable contract at `docs/schema/fvp-v2.schema.json`
  (validated as Draft 2020-12; accept/reject cases exercised). Summary:
  a project is a SINGLE ZIP with extension `.fvp` holding
  `manifest.json` + `pixels/<id>.npy` + `thumbs/<id>.png`; version 2
  SUPERSEDES the v1 two-file workspace, which becomes read-only legacy
  upgraded in memory on load; TWO payload modes (`light` references
  source pixels and always embeds derived images, measures, samples and
  thumbnails at ~2–20 MB; `bundle` embeds everything, ~250–700 MB, for
  transfer); references are stored as POSIX paths relative to ONE
  declared data root plus an absolute hint, resolved hint →
  project-dir-relative → user re-point, so relocation is one folder pick
  for all images; unresolved images load as placeholders and their
  references SURVIVE a save (no silent data loss), with a "Locate
  folder…" action invokable at any time and repeatable for subsets that
  moved elsewhere; the scientific content (`images`, `samples` with
  parameter values + units, `measures`) is schema-validated while purely
  presentational state stays opaque under `ui_state`; load validates and
  save PRESERVES unknown keys verbatim so versions are not one-way.
  Region areas are derived from `pts` + axis calibration, never stored,
  so they cannot go stale against a recalibration.
- (2026-08-09) **Region persistence — closes former gate G4.** Settled by
  the format spec above: regions ride the existing measure rails and
  persist in the manifest's specified `measures` section, keyed by image
  id, with `polygon` and `lasso` added to `MeasureKind`. Overlay
  rendering, undo and round-trip come free; no separate region store.
- (2026-08-09) **Folder import recursion — closes G3.** Selecting a folder
  recurses fully. Each FIRST-LEVEL subfolder holding supported images
  becomes one candidate sample named after it, and images deeper inside
  flatten into that sample; supported images sitting directly in the
  selected folder form a sample named after that folder. Unsupported and
  non-image files are skipped and counted, surfaced as "skipped N
  unsupported" rather than silently. The per-import cap is 500 supported
  files with a `truncated` flag, mirroring `/session/launch-dir`'s
  `files[:500]` so the two behave alike. The scan reuses launch-dir's
  per-entry `is_file()` OSError guard, so a OneDrive cloud-only
  placeholder skips itself instead of failing the whole import.
- (2026-08-09) **Scale lock is global — closes G5.** One lock, seeded
  from the active image's µm/px when enabled, re-seeded by
  double-click-to-fit, persisted as an additive `browseScale` key in
  `ui_state`. A per-group lock was rejected because the jarring this
  feature exists to remove happens while stepping through whatever is
  loaded, including across samples — a per-group lock would reintroduce a
  jump at every sample boundary, which is the worst place for one.
  Per-group can be added later with no format change, since `ui_state` is
  deliberately opaque.
- (2026-08-09) **Validation uses `jsonschema` — closes G6.** Added as a
  runtime dependency (MIT; verified absent from the repo's
  `GPL_PACKAGES` guard). The pure-layer test forbids `io/` from importing
  fastapi/pydantic/starlette/routes only, so `io/` may use it — meaning
  the shipped `docs/schema/fvp-v2.schema.json` IS the enforced contract
  and cannot drift from the loader, which was the reason to have a schema
  at all. Hand-rolled checks were rejected for exactly that drift risk.


### Owner gates

None open. G1, G2 and G4 were closed by ADR 0002; G3, G5 and G6 were
resolved 2026-08-09 with the reasoning recorded above so work could
proceed unattended. Reopen one here rather than deciding it inline if
implementation shows a resolution was wrong.

---

## Cross-cutting priorities

| # | Item | Workstream | Why first |
|---|------|------------|-----------|
| 30 | `.fvp` container read/write | W5 — Format | Foundational: 20 cannot freeze the persisted shape until this exists |
| 20 | Sample group model | W4 — Projects | Every W4 item plus 27 reads it; it is the data contract |
| 13 | MeasureOverlay extraction | W3 — Areas | Zero-headroom pin blocks all region drawing |
| 8 | Stage extraction + scale resolver | W2 — Browsing | The other zero-headroom pin; do it while nothing else touches Stage |
| 1 | Folder-open endpoint | W1 — Import | Independent, first user-visible win, unblocks W1 and 27 |
| 12 | Shared area math | W3 — Areas | Pure and parallel-safe; the one computation both tools share |
| 21 | Filmstrip extraction | W4 — Projects | Frees the 63-line file before the tree lands |

---

## W1 — Folder import

Deliverable: a library organised into per-folder named groups, straight
from an import.

### Tier 1 — High Impact

1. ~~**Folder-open endpoint**~~ — shipped 2026-08-09, see Completed

2. ~~**Import dialog grows folders + merge checkbox**~~ — shipped 2026-08-09, see Completed

3. ~~**Seeding rules as pure, tested logic**~~ — shipped 2026-08-09, see Completed

### Tier 2 — Medium Impact

4. **Drag-and-drop folders onto the window** — directory entries walk
   into the same orchestrator as 2 (browser-picked files continue
   through /session/upload).
   Model: sonnet · Parallel: no — conflicts with 2 (dialog/drop wiring)

5. **Recursion + unsupported-file policy** — implement gate G3's
   resolution; per-import cap; "skipped N unsupported" status.
   Model: haiku · Parallel: yes

---

## W2 — Browsing at constant physical scale

Deliverable: paging through a series keeps a feature the same on-screen
size — same µm per screen px across consecutive frames and across panes.

### Tier 1 — High Impact

6. ~~**Physical-scale math**~~ — shipped 2026-08-09, see Completed

7. ~~**Scale-lock store**~~ — shipped 2026-08-09, see Completed

8. ~~**Stage honors the lock**~~ — shipped 2026-08-09, see Completed

9. **Compare surfaces honor the lock** — same resolver at
   CompareStage.tsx:39, SideBySideStage.tsx:145,
   useStagePointers.ts:393; linked SBS zoom propagates physical scale
   (lib/sbsView.ts nextGridViews gains pixel sizes) so panes match
   µm/px, not raw z
   - [ ] ALSO: the double-click-on-canvas fit gesture lives at
         useStagePointers.ts:393 and does NOT yet re-seed the lock —
         item 8 wired re-seeding into the imperative fit() only, because
         that file was out of its scope. Route the gesture through the
         same `fitAndReseedScale` helper (components/Stage/stageScaleLock.ts)
   Model: sonnet · Parallel: NO — shares useStagePointers.ts with 14 and
   SideBySideStage.tsx with 26

10. ~~**Lock affordance**~~ — shipped 2026-08-09, see Completed

### Tier 2 — Medium Impact

11. **Persist the lock in client_state** — additive optional key; old
    payloads unaffected.
    Model: haiku · Parallel: yes (after 7)

---

## W3 — Area measurement

Deliverable: a per-image table of drawn regions with areas in physical
units, exportable as CSV; areas feed W4's comparison. Not baked into
exported figures.

### Tier 1 — High Impact

12. ~~**One area computation**~~ — shipped 2026-08-09, see Completed

13. ~~**MeasureOverlay extraction (front-load)**~~ — shipped 2026-08-09, see Completed

14. ~~**Polygon + lasso measure kinds**~~ — shipped 2026-08-09, see Completed

15. ~~**Region table + CSV (the deliverable)**~~ — shipped 2026-08-09, see Completed

16. ~~**Edge auto-detect assist**~~ — shipped 2026-08-09, see Completed

### Tier 2 — Medium Impact

17. **Lasso hygiene** — point-count guard + simplification tolerance
    preference.
    Model: haiku · Parallel: yes (after 14)

18. **Round-trip test** — polygon/lasso measures survive workspace
    save/load (measures already persist; assert it).
    Model: haiku · Parallel: yes (after 14)

### Tier 3 — Nice-to-Have

19. **Holes / multi-part regions** — subtract inner outlines from a
    region's area.
    Model: sonnet · Parallel: yes (after 15)

---

## W4 — Projects

Deliverables: result-vs-parameter table + plot (CSV), shared-scale
labelled montage figure, per-sample statistics, sample-wise side-by-side
stepping — all reading the same sample groups.

### Tier 1 — High Impact

20. ~~**Sample/project group model**~~ — shipped 2026-08-09, see Completed

21. ~~**Filmstrip extraction (front-load)**~~ — shipped 2026-08-09, see Completed

22. ~~**One panel that grows**~~ — shipped 2026-08-09, see Completed

23. **Sample parameter editing** — per-section editor reusing
    lib/params.ts ParamField; values stored via setGroupParams; one
    documented numeric-with-unit convention.
    Model: sonnet · Parallel: yes (after 20; UI slot after 22)

24. **Result-vs-parameter table + plot + CSV** — new pure
    lib/projectCompare.ts: per sample group, aggregate the chosen result
    (region areas via 15's selector) against a chosen parameter with
    mean/sd/n (reuse lib/measureStats.ts); panel renders table + plot
    (reuse components/plots) and exports via tableToCsv. Covers
    deliverables (a) and (d).
    Model: sonnet · Parallel: yes (after 15, 20, 23)

25. **Comparison montage with shared scale bar** — extend
    calc/montage.py (230/500) with a physical-scale mode: resample tiles
    to a common µm/px from each image's pixel_size, label tiles with
    sample name + parameter value, bake ONE scale bar; NEW route module
    (imaging_ops.py at 457 stays put); a "Montage samples" action from
    selected sample groups; result registers as a derived library image.
    Keep figure conventions aligned with the spectral plan's composite
    (see MAIN_PLAN cross-plan dependencies).
    Ratchet: extend roomy calc module + NEW route module.
    Model: opus · Parallel: yes (after 20; independent of 24)

### Tier 2 — Medium Impact

26. **Sample stepping affordance** — panes bound to groups already step
    within a sample; add "compare samples" seeding (pane i ← sample i at
    matched member index) and surface sample groups in the pane
    dropdowns.
    Model: sonnet · Parallel: NO — SideBySideStage.tsx conflicts with 9
    (after 20)

27. **Import seeds projects** — W1's per-folder groups get a parent
    project group when importing a folder of folders (per gate G3).
    Model: sonnet · Parallel: yes (after 1–3, 20)

28. **Round-trip + migration tests** — params/parent survive save/load;
    pre-extension payloads load unchanged.
    Model: haiku · Parallel: yes (after 20)

### Tier 3 — Nice-to-Have

29. **Polish** — sample colour tags in sections/panes; montage ordering
    by parameter value.
    Model: haiku · Parallel: yes

---

## W5 — Project file format (`.fvp` v2)

Deliverable: a documented, schema-validated, single-file project that
transfers between machines. Spec: `docs/adr/0002-project-file-format.md`;
contract: `docs/schema/fvp-v2.schema.json`. This workstream is
FOUNDATIONAL — item 20 cannot freeze the persisted sample shape until 30
lands.

### Tier 1 — High Impact

30. ~~**`.fvp` container read/write**~~ — shipped 2026-08-09, see Completed

31. ~~**Schema validation + unknown-key preservation**~~ — shipped 2026-08-09, see Completed

32. **v1 → v2 migration** — `load` accepts a v1 `.json`/`.npz` pair and
    upgrades in memory (splitting the opaque `client_state` into
    `samples`/`measures`/`ui_state`); the next save writes `.fvp`. v1
    write path is removed.
    Model: opus · Parallel: yes (after 30)

33. **Light vs bundle payload modes** — `payload_mode`; light embeds
    derived images + measures + samples + thumbnails and references
    sources; bundle embeds everything. Save Project / Export Project
    Bundle as distinct actions.
    Model: sonnet · Parallel: yes (after 30)

34. **Data-root resolution** — hint → project-dir-relative → session
    re-point, POSIX normalisation both ways, `size_bytes` sanity check;
    new route module exposing resolve + relocate (`routes/images.py` at
    497 stays untouched).
    Ratchet: NEW MODULE. Model: sonnet · Parallel: yes (after 30)

35. **Unavailable placeholders + "Locate folder…"** — unresolved images
    render as placeholders keeping name, sample membership, params and
    measures; the action is invokable any time and repeatable for
    subsets in different folders; saving preserves unresolved references.
    Model: sonnet · Parallel: yes (after 34; UI slot after 22)

### Tier 2 — Medium Impact

36. **Format test suite** — the verification list in ADR 0002:
    round-trip deep-equal, unknown-key survival, v1 migration,
    Windows-hint-on-POSIX resolution, unresolved-reference survives a
    save (the no-data-loss assertion), interrupted-save atomicity.
    Model: sonnet · Parallel: yes (after 30–34)

37. **Thumbnail generation** — ≤256 px longest edge on save, reusing the
    existing render path; enables browsing and review with data absent.
    Model: haiku · Parallel: yes (after 30)

### Tier 3 — Nice-to-Have

38. **Optional `sha256` verification** — opt-in content hashing so a
    re-pointed folder can be proven to hold the expected data.
    Model: haiku · Parallel: yes (after 34)

---

## Completed

- ~~**#16 Edge auto-detect assist**~~ (2026-08-09, PR #138) — segmentation PROPOSES,
  the user corrects: new pure `calc/contours.py` (174 lines) traces the
  outer boundary of a single labelled-region mask (skimage `find_contours`
  + `approximate_polygon`, no new dependency), simplifies it to a
  hand-correctable vertex count, and canonicalizes winding + start vertex
  so the same mask always yields the identical polygon (determinism was a
  named requirement, not an assumption — verified by a dedicated test).
  Holes are NOT subtracted — the outer ring alone is returned, documented
  in the module docstring; #19 owns subtracting inner outlines.
  New `routes/regions.py` (173 lines, registered in `server.py`) exposes
  `POST /api/regions/propose`: a normalized 0-1 seed point OR rough rect
  picks which multi-Otsu class/connected-component to trace (a rect also
  crops the search locally, padded so the true boundary is never clipped
  at the crop edge); 404 for an unknown image, 422 for any unusable seed
  (out of bounds, a degenerate rect, a class that doesn't classify, no
  boundary) — never a 500. Frontend glue lives in `RegionsCard.tsx` (a
  seed-percent control + "Detect Region" button) and the new
  `lib/api/regions.ts` client; the returned points are handed straight to
  the store's existing `addMeasure(imageId, {kind: "polygon", pts})` — no
  separate "detected region" concept anywhere, so overlay rendering,
  vertex dragging, the region table, CSV export, persistence and undo all
  work with zero special-casing, and the new polygon is immediately
  draggable because `addMeasure` already selects it.
  Verified on a synthetic bright-blob image: proposed area within 8% of
  the true pixel-count area (seed-only and rect-seed paths both), plus a
  `@pytest.mark.realdata` test against a real HAADF frame (auto-skips
  without the sibling corpus). No files near their ceiling were touched
  (`server.py` 477→478/500, one import + one tuple entry).
- ~~**#22 One panel that grows**~~ (2026-08-09, PR #137) — new pure
  `lib/sampleTree.ts` (103) + `Library/SampleSection.tsx` (114) +
  `Library/FilmCard.tsx` (109); `Filmstrip.tsx` 283 → 367. Sections only
  appear once groups exist: with none, the panel renders the same bare card
  list it always did, verified by rendering main's Filmstrip beside the new
  one over five states plus mid-drag and asserting identical DOM — the
  existing `Filmstrip.test.tsx` needed no edits. Arrow keys and the single
  tab stop walk the VISIBLE card sequence, so they cross section boundaries
  and skip collapsed ones; a cross-section drop is a membership edit
  (`addGroupMember`/`removeGroupMember`), a same-section drop still
  reorders. Collapse reuses `Inspector/useCollapsedGroups`.
  ALSO fixed the booked defect: `closeImage` pruned any group whose `ids`
  emptied, which under nesting deleted an image-less PROJECT. It now routes
  through `pruneGroups` (keep-if-live-descendant). Paid for by extracting
  `store/viewerCloseImage.ts` (92) and `store/viewerChromeActions.ts` (110)
  out of `store/viewer.ts`: **575 → 448 lines, so its 575 cap is DELETED —
  it graduated** to the plain 500-line ceiling.
- ~~**#10 Lock affordance — makes the browsing fix REACHABLE**~~ (2026-08-09,
  PR #136) — new `Stage/ScaleLockChip.tsx` (102), 7 tests; Stage.tsx 582 → 584
  against its 617 cap because the chip reads the store itself rather than
  threading props, so the Stage diff is two lines. Until this landed, item 8's
  resolver was correct but unreachable: `browseScale.locked` started false and
  nothing could set it, so the 92× scale jump was still happening. Readout is
  `1.76 µm/px` — 3 significant figures, unit from the image's `pixel_unit`,
  never hardcoded. Enabling seeds from the active image's current physical
  scale so it is visually a no-op. An uncalibrated image disables the toggle
  and says why, rather than silently doing nothing — which matters because 3
  of the 5 real Helios corpus files are uncalibrated. Follows FloatTools'
  disabled convention, including putting the tooltip on the wrapper since a
  disabled button swallows pointer events.
- ~~**#15 Region table + CSV — THE AREA DELIVERABLE**~~ (2026-08-09, PR #135)
  — new pure `lib/regionTable.ts` (158) + `Inspector/RegionsCard.tsx` (134),
  27 tests. This is the point where a measured area actually leaves the app:

      label,kind,area_px2,area_nm2,perimeter_px,centroid_x_px,centroid_y_px
      Grain A,polygon,5000,20000,300,50,25

  The unit in the header comes from the image's `pixel_unit`, so a
  collaborator never guesses µm² vs nm². Uncalibrated images leave the
  physical cell EMPTY — never 0, never NaN — and the panel shows px².
  Areas are derived from `pts` + calibration on every read per ADR 0002, so
  recalibrating updates every number with no migration; a test pins that by
  changing `pixel_size` and asserting the area changes.
  `regionPhysicalAreas(measures, image)` is the selector item 24 consumes for
  the per-sample roll-up, so it will not re-derive areas.
  Kept free of store types (structural `RegionCandidate`), the same
  separation `lib/geometry.ts` keeps.
- ~~**#14 Polygon + lasso measure kinds**~~ (2026-08-09, PR #133) — both kinds
  share the one area computation; new `closedShapeGlyph.tsx` (57) and
  `regionCapture.ts` (53); MeasureOverlay 512 → 527 (cap 562) and
  useStagePointers 432 → 489 (cap 500), no cap touched. The narrowing audit
  found a **real bug** — "Clear Measurements" used an explicit kind whitelist
  that excluded the new kinds — plus three silent gaps (MeasurePanel.valueOf,
  showLog, and measureStats omitting Area entirely). Sites typed as
  `Record<Measure["kind"], T>` or an exhaustive switch failed to COMPILE and
  so protected themselves; hand-written whitelists did not. Prefer the former.
  Tools were also registered in measureTools/the Measure menu/captureSteps —
  a kind reachable from nowhere is not a feature.
- ~~**#2 Import dialog grows folders + merge checkbox**~~ (2026-08-09, PR #132)
  — folder paths + a single "Merge into one group" checkbox; new
  `lib/api/folders.ts` (37) and `lib/folderImport.ts` (179); the existing
  file-open path untouched. Folder structure is derived ONLY in the backend;
  the frontend maps returned groups one-to-one, which is why "one folder → one
  group" and "N folders → N groups" are the same rule, not two branches.
- ~~**#3 Seeding rules as pure, tested logic**~~ (2026-08-09, PR #132) —
  `seedGroupSpecs`/`dedupeGroupName`/`mergedGroupName`/`summarizeImport`, split
  from the async orchestrator so the rules test against the real store with no
  fetch mocking. Collisions get a numeric suffix rather than silently merging;
  an empty folder yields no group and is named in the status line, as are
  skipped-unsupported counts and cap truncation.
- ~~**#20 Sample/project group model**~~ (2026-08-09, PR #130) — `ImageGroup`
  gains optional `parent`, `params` (`{name: {value, unit}}`) and `color`,
  matching the schema's `samples` entries exactly. Four actions, five pure
  cycle-safe helpers, 37 unit tests; `lib/groups.ts` 69 → 231. **Found a real
  pre-existing defect**: session restore rebuilt each group from a
  three-field whitelist, so `params`/`parent`/`color` would have been wiped
  on the first save/load cycle with no compile error — the
  narrowing-a-shared-type failure mode exactly. Now routed through
  `pruneGroups`. Store keeps `ids`; schema says `image_ids`; mapping is 1:1.
- ~~**#8 Stage honors the lock**~~ (2026-08-09, PR #131) — both `fitView`
  defaults in Stage.tsx now resolve through `resolveScaleView`; logic in a new
  `stageScaleLock.ts` (64) so Stage.tsx went 567 → 582 against its 617 cap.
  Real-corpus check: paging between the two real Helios frames under
  fit-each-image changed apparent scale **92×** (1.76 vs 161.6 µm per screen
  px) — that is the jarring this removes. Uncalibrated images still fall back
  to fitView exactly. Two carry-overs booked: the double-click gesture's
  re-seed on item 9, and it is not user-reachable until item 10's toggle.
- ~~**#30 `.fvp` container read/write**~~ (2026-08-09, PR #129) — three pure
  modules (`io/project_file.py` 461, `io/project_manifest.py` 373,
  `io/project_paths.py` 172; one module would have been 545, over the
  ceiling). Single ZIP, atomic single-`os.replace` save, light/bundle modes,
  data-root references. 49 tests. Found and fixed a real zip-slip vector:
  two images sharing an id wrote a duplicate `pixels/<id>.npy` and the
  second silently read back the first's pixels — surfaced only because the
  suite promotes warnings to errors. Ids are now validated as unique, single,
  separator-free path components on save AND load, which matters because the
  ADR advertises `unzip project.fvp` as an inspection route.
- ~~**#31 Schema validation + unknown-key preservation**~~ (2026-08-09,
  PR #129) — `jsonschema>=4.18` runtime dep (G6); packaged schema copy kept
  byte-identical to `docs/schema/` by a test; `tools/bundle/fv-server.spec`
  ships it into the frozen sidecar, without which a packaged build would
  validate against a missing file.
- ~~**#1 Folder-open endpoint**~~ (2026-08-09, PR #127) — `io/folder_scan.py`
  (185, pure) + `routes/folders.py` (72) + shared `routes/_open_paths.py`
  (74); `routes/images.py` 497 → **455**, so the feature made headroom
  instead of consuming the 3 lines left. G3 semantics implemented in full.
  CodeQL raised two `py/path-injection` alerts, dismissed "won't fix" per
  the repo's existing triage of that rule on watch.py/workspaces.py/
  session_io.py — a folder-open backend has no safe root to confine to, and
  the mitigation is server.py's Host-header allowlist.
- ~~**#13 MeasureOverlay extraction**~~ (2026-08-09, PR #128) — 636 → 512
  via `MeasureCtxMenu.tsx` (177); cap 636 → 562.
- ~~**#21 Filmstrip extraction**~~ (2026-08-09, PR #128) — 437 → 283 via
  `FilmstripContextMenu.tsx` (109) + `GroupsBar.tsx` (60); no cap needed.
- ~~**#8a Stage extraction**~~ (2026-08-09, PR #128) — 640 → 567 via
  `useStageImageLoad.ts` (143); cap 640 → 617. Caps carry the ratchet's
  50-line slack deliberately: pinned tight, an extraction made to create
  room leaves none and the next line of items 8/14 would fail.
- ~~**#6 Physical-scale math**~~ (2026-08-09, PR #126) — `physicalScale`,
  `viewForPhysicalScale`, `resolveScaleView` in `lib/geometry.ts`
  (197 → 320). Unit-agnostic by design (pixel_unit per screen px, not µm —
  the real Helios corpus is nm and its navcam µm); uncalibrated images
  fall back to `fitView` with a test asserting equality against
  `fitView`'s own output, so every uncalibrated path is provably
  unchanged; `clampZoom` reused so the lock cannot exceed interactive
  zoom limits. Not wired to any component — that is item 8.
- ~~**#7 Scale-lock store**~~ (2026-08-09, PR #126) — new standalone
  `store/browseScale.ts` (39 lines), global lock per the G5 resolution.
  `store/viewer.ts` untouched, so its 575 pin is intact.
- ~~**#12 One area computation**~~ (2026-08-09, PR #126) — `polygonStats`,
  `polygonStatsNormalized`, `areaPxToPhysical` in `lib/geometry.ts`,
  shared by the polygon and lasso kinds. Edge cases pinned rather than
  assumed: <3 points → zeros not NaN, duplicated closing point not
  double-counted, non-convex exact, degenerate zero-area centroid falls
  back to a vertex average instead of dividing by zero, self-intersecting
  input returns the signed shoelace result as documented behaviour.
  Known-answer tests (unit square, triangle) pin the arithmetic.
