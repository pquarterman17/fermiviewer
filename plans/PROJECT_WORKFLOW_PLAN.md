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
  Filmstrip.tsx · {2, 4} FolderOpenDialog.tsx · {1, 16, 25} each add ~2
  lines to server.py (rebase-trivial)
- Cross-workstream: 24 needs W3's 15; 27 needs W1's 1–3 and gate G3;
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

### Owner gates

- **G6 — Manifest validation dependency.** "Validate on load" needs a
  JSON Schema validator, and `io/` is a pure layer forbidden from
  importing pydantic (which is already a dependency, but only usable
  above `io/`). RECOMMEND adding `jsonschema` (MIT, small) as a runtime
  dependency so the shipped schema file IS the enforced contract; the
  alternative is ~60 lines of hand-rolled checks in `io/`, no new
  dependency, but the schema and the loader can then drift. Note the
  installer grows either way only slightly. Sign-off before item 31.
- **G3 — Folder import recursion + non-image files.** RECOMMEND full
  recursion where each first-level subfolder becomes a candidate sample
  (deeper levels flatten into it), unsupported files skipped with a
  "skipped N" status count, and a per-import cap mirroring launch-dir's
  500. Sign-off before items 5 and 27.
- **G5 — Scale-lock scope.** Global stage lock vs per-group lock?
  RECOMMEND one global lock seeded from the active image when enabled
  (double-click-to-fit re-seeds it). Sign-off before item 10; items 6–8
  are unaffected either way.

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

1. **Folder-open endpoint** — directory paths in, per-folder ImageMeta
   lists out
   - [ ] New `io/folder_scan.py`: pure directory scan (supported-extension
         filter, OneDrive-safe is_file guard as in /session/launch-dir),
         returning a frozen dataclass (folder name, file paths, skipped
         count); no fastapi imports (layering guard)
   - [ ] New `routes/folders.py`: POST /api/session/open-folder — scan,
         then reuse store.open_paths + auto_apply_calibration exactly as
         /session/open does; register the router in server.py
   - [ ] Tests: synthetic tmp trees + FV_TEST_DATA vendor folders where
         present (realdata auto-skip)
   Ratchet: NEW MODULES (images.py at 497 untouched).
   Model: sonnet · Parallel: yes (only the 2-line server.py hookup
   overlaps 16/25)

2. **Import dialog grows folders + merge checkbox** —
   `FolderOpenDialog.tsx` (130/500) gains folder selection and a single
   "Merge into one group" checkbox
   - [ ] New `lib/api/folders.ts` client + new `lib/folderImport.ts`
         orchestrator: endpoint → ingest metas → createGroup per folder,
         or one merged group
   - [ ] Group name = folder name; collision suffixing; empty folders
         reported via status
   Ratchet: NEW MODULES + a roomy dialog. Model: sonnet · Parallel: yes
   (conflicts with 4 — same dialog)

3. **Seeding rules as pure, tested logic** — single folder = one group;
   N folders = N groups; merge = one group; rules live in
   lib/folderImport.ts with table-driven tests.
   Model: haiku · Parallel: yes (after 2)

### Tier 2 — Medium Impact

4. **Drag-and-drop folders onto the window** — directory entries walk
   into the same orchestrator as 2 (browser-picked files continue
   through /session/upload).
   Model: sonnet · Parallel: no — conflicts with 2 (dialog/drop wiring)

5. **Recursion + unsupported-file policy** — implement gate G3's
   resolution; per-import cap; "skipped N unsupported" status.
   Model: haiku · Parallel: yes · Blocked by G3

---

## W2 — Browsing at constant physical scale

Deliverable: paging through a series keeps a feature the same on-screen
size — same µm per screen px across consecutive frames and across panes.

### Tier 1 — High Impact

6. **Physical-scale math** — extend `lib/geometry.ts` (197/500):
   µm-per-screen-px of a view, view achieving a target scale about a
   kept centre, fitView fallback when pixel_size is null; unit tests
   beside geometry.test.ts.
   Ratchet: room in an existing pure module. Model: sonnet ·
   Parallel: yes

7. **Scale-lock store** — new standalone zustand store
   `store/browseScale.ts` (locked flag + locked µm/px + seed/clear
   actions), following the store/stage.ts pattern; viewer.ts (pin 575)
   untouched.
   Ratchet: NEW MODULE. Model: sonnet · Parallel: yes

8. **Stage honors the lock** — the pinned-file item
   - [ ] FRONT-LOADED EXTRACTION: move a cohesive block out of Stage.tsx
         (640 → ≤570) into a new Stage/ module and lower the pin in
         test_repo_integrity.py in the same change
   - [ ] Replace both fitView defaults in Stage.tsx with a resolver:
         locked + calibrated → scale view, else fitView
   - [ ] cycleImage keeps on-screen µm/px across images with different
         pixel sizes
   Model: opus · Parallel: NO — exclusive on Stage.tsx

9. **Compare surfaces honor the lock** — same resolver at
   CompareStage.tsx:39, SideBySideStage.tsx:145,
   useStagePointers.ts:393; linked SBS zoom propagates physical scale
   (lib/sbsView.ts nextGridViews gains pixel sizes) so panes match
   µm/px, not raw z.
   Model: sonnet · Parallel: NO — shares useStagePointers.ts with 14 and
   SideBySideStage.tsx with 26

10. **Lock affordance** — toggle + µm/px readout in StageChrome /
    FloatTools; double-click-to-fit re-seeds the lock rather than
    silently breaking it (wording per gate G5).
    Model: sonnet · Parallel: yes (after 8) · Blocked by G5

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

12. **One area computation** — polygon area (shoelace) + centroid +
    perimeter next to physDist in `lib/geometry.ts`; px² × pixelSize² →
    physical; shared by polygon AND lasso; tests cover non-convex and
    closed/duplicate-last-point inputs.
    Ratchet: room in an existing pure module. Model: sonnet ·
    Parallel: yes

13. **MeasureOverlay extraction (front-load)** — move per-kind renderers
    (or the label/hit-test block) from MeasureOverlay.tsx (636) into new
    Stage/ module(s); lower the pin toward ≤550 in the same change;
    behavior-preserving (MeasureOverlay.test.tsx stays green).
    Model: opus · Parallel: NO — exclusive on MeasureOverlay.tsx

14. **Polygon + lasso measure kinds**
    - [ ] Add "polygon"/"lasso" to MeasureKind (viewerTypes.ts 248/500)
          — grep every MeasureKind narrowing site first
    - [ ] Polygon rides the existing polyline click-flow
          (useStagePointers.ts) with close-on-first-vertex /
          double-click; vertex drag-adjust reuses the measure-move rails
    - [ ] Lasso capture in a NEW `Stage/regionCapture.ts` (pointermove
          append + simplification); thin glue keeps useStagePointers.ts
          (432) under its 500 cap
    - [ ] Closed-shape rendering goes in the module extracted by 13
    Model: opus · Parallel: NO — Stage pointer/overlay files; after 13;
    not concurrent with 9

15. **Region table + CSV (the deliverable)** — new Regions panel/tool
    window: rows = polygon/lasso measures of the active image, label
    (Measure.text), area in pixel_unit² via 12; CSV via
    lib/resultsExport.ts; exposes a pure per-image areas selector for
    W4's roll-up.
    Model: sonnet · Parallel: yes (after 12, 14) — row schema is the
    manifest's `measures` section (ADR 0002)

16. **Edge auto-detect assist** — segmentation proposes, user corrects
    - [ ] New `calc/contours.py`: label-mask → traced, simplified
          polygon (pure; frozen dataclass result)
    - [ ] New `routes/regions.py`: propose an outline from a seed click
          or rough region via calc.segment (multi_otsu + morph) or the
          trained-grain path; returns normalized polygon pts
    - [ ] Frontend: the proposal lands as an ordinary editable polygon
          measure, so 15's table just works
    Ratchet: NEW MODULES. Model: opus · Parallel: yes vs W4 (after 14)

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

20. **Sample/project group model** — extend ImageGroup with optional
    named parameter fields and an optional parent reference
    (project → sample nesting); groupMembers untouched
    - [ ] Grep every ImageGroup consumer before changing the shared type
    - [ ] New actions in store/viewerCompareActions.ts (243/500):
          setGroupParams, setGroupParent, add/removeGroupMember;
          signatures in viewerState.ts (274/500)
    - [ ] Persistence uses the `samples` section specified in ADR 0002
          (id, name, image_ids, parent, params with value+unit, color) —
          NOT the opaque client_state blob it used to ride
    Ratchet: roomy files only; viewer.ts untouched.
    Model: opus · Parallel: NO — blocks 22–28; run first in W4 ·
    Depends on item 30 for the manifest shape

21. **Filmstrip extraction (front-load)** — move ContextMenu + GroupsBar
    (~150 lines) out of Filmstrip.tsx (437 → ~300) into
    components/Library/ modules; behavior-preserving.
    Model: haiku · Parallel: NO — exclusive on Filmstrip.tsx; before 22

22. **One panel that grows** — Filmstrip renders collapsible sections
    per sample group when any exist (images in no sample under
    "Ungrouped"); with no groups it stays today's flat list; membership
    drag between sections edits group ids; selection/keyboard semantics
    preserved; new components/Library/SampleSection.tsx keeps Filmstrip
    ≤500.
    Model: opus · Parallel: NO — Filmstrip.tsx (after 20, 21)

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
    Model: sonnet · Parallel: yes (after 1–3, 20) · Blocked by G3

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

30. **`.fvp` container read/write** — new pure `io/project_file.py`
    - [ ] Single ZIP (DEFLATE): `manifest.json`, `pixels/<id>.npy`,
          `thumbs/<id>.png`; per-image `.npy` so one image can be read
          without inflating the rest
    - [ ] Atomic save: temp sibling in the same dir → flush + fsync →
          one `os.replace`. This RETIRES v1's manifest-last commit
          ordering; assert an interrupted save leaves the old file intact
    - [ ] Returns/accepts plain structures only — no fastapi/pydantic
          (pure-layer guard); `session_file.py` stays for v1 reads
    - [ ] Reject a manifest whose `rel` is absolute or escapes the root
          with `..` (path traversal on an untrusted project file)
    Ratchet: NEW MODULE. Model: opus · Parallel: NO — blocks 20, 31–36

31. **Schema validation + unknown-key preservation** — validate
    `manifest.json` on load against the shipped schema, failing with the
    offending path; round-trip unknown keys verbatim on save. A test
    asserts the schema file and the loader agree, so they cannot drift.
    Model: opus · Parallel: yes (after 30) · Blocked by G6

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

(nothing yet — plan created 2026-08-09)
