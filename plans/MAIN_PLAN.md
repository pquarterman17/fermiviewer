# FermiViewer — Main Plan

Root of the plan tree: the mission, the live sub-plans, cross-plan
dependencies, and repo-wide items too small for a sub-plan. Every other
plan in `plans/` declares this file as its parent.

**Status:** Active
**Created:** 2026-08-09
**Updated:** 2026-08-11 — legacy-plan consolidation: PORT_PLAN,
PLAN_DIFFRACTION, PLAN_SPECTRAL_QUANT, CROSS_SECTION_LAYERS and
FEATURE_AUDIT_2026-06-21 folded up/archived (each verified against the code
first — several claimed-open items were already shipped); PLAN_4DSTEM
adopted as a live sub-plan; 9 items opened (6–14)

---

## Context

### How the pieces fit together

FermiViewer is a desktop scientific image viewer: a FastAPI backend
(`src/fermiviewer` — pure `io`/`calc`/`ops` layers under thin `routes/`,
guarded by `tests/test_repo_integrity.py`'s layering test and 500-line
module ratchet) and a React/zustand frontend (`frontend/src` — same
500-line ratchet with pinned legacy caps that only move down). Two
campaigns are live, one per sub-plan: making the spectral (EDS/EELS)
workspaces usable for routine elemental analysis, and 4D-STEM beyond its
shipped Phase 1 (owner-deferred DPC tier + usability follow-ups). The
many-sample project-workflow campaign completed 2026-08-10; this root
plan additionally carries the fold-up residue of five archived legacy
plans (items 6–14).

### Plan tree

| Sub-plan | Scope | Status | Why its own file |
|---|---|---|---|
| SPECTRAL_WORKSPACE_PLAN.md | EDS+EELS shared spectrum core, species lists, batch maps, composites, synthetic-SI verification | Active (8 open items / 5 sub-task boxes; W3 complete 2026-08-11) | Independent lifecycle, four workstreams of its own |
| PLAN_4DSTEM.md | Lazy 4D-STEM dataset model (`FourDDataset`), MIB/HyperSpy-4D ingest, virtual-detector imaging (Phase 1 shipped 2026-08-02); COM/DPC/iDPC (owner-deferred), usability follow-ups, and parked strain/ptychography/ACOM | Active (8 open items / 14 sub-task boxes, Tier 2–3) | Independent lifecycle and its own architectural decision (Option B: 4D data is a source, not a `DataStruct`) with memory-streaming constraints the other two plans don't share |
| ~~PROJECT_WORKFLOW_PLAN.md~~ | Folder import, constant-physical-scale browsing, area measurement, project/sample hierarchy + comparison deliverables, and the `.fvp` project file format | **Complete 2026-08-10** → `plans/archive/` | 27 items shipped, 6 gates resolved. Kept for the decision record: ADR 0002's rationale, the `py/path-injection` triage, and the ratchet outcomes (`store/viewer.ts` graduated 575→444) |

### Cross-plan dependencies

- The two sub-plans are file-disjoint almost everywhere. Both add
  routers to `server.py` (476/500 — ~2 lines each; if it nears the
  ceiling, extract the router-registration block into its own module
  first). Trivial rebases only.
- Figure outputs converge: spectral #7/#10 (shared composite → library)
  and project-workflow #25 (shared-scale sample montage) must keep one
  figure convention (labels, legend/scale bar, result registered as a
  derived library image). Whichever lands second reuses the first's
  conventions; do not fork the `lib/elemental/figure.ts`-style renderer
  a third time.
- `SideBySideStage.tsx` is touched by project-workflow items 9 and 26;
  the spectral plan does not touch it — no conflict today.
- The `.fvp` project format (ADR 0002, schema in `docs/schema/`) is
  owned by PROJECT_WORKFLOW_PLAN W5 and supersedes the v1 workspace
  format. Any plan that persists new state adds a specified manifest
  section rather than growing the opaque `ui_state` blob.
- Ratchet pins: project-workflow items 8, 13 and 21 lower the
  Stage.tsx / MeasureOverlay.tsx / Filmstrip.tsx caps. Sequence those
  before any other work touches the same files (see that plan's
  cross-cutting priorities table).
- PLAN_4DSTEM is file-disjoint from the other two: it owns `calc/fourd/`,
  `routes/fourd.py`, `io/fourd/`, and `FourDWorkshop.tsx` alone. No conflict
  with spectral or project-workflow work.

---

## Tier 1 — High Impact

(none open here — all Tier-1 work lives in the two sub-plans)

## Tier 2 — Medium Impact

1. ~~**Pin-graduation campaign**~~ — shipped 2026-08-10, see Completed

2. ~~**BACKLOG.md dashboard**~~ — shipped 2026-08-10, see Completed

10. **Hartree-Slater / GOS cross-sections for EELS** — was
    PLAN_SPECTRAL_QUANT.md #3, its only remaining item (folded 2026-08-11
    when the plan archived). Only hydrogenic K/L cross-sections exist
    (`calc/eels_quant.py`); GOS is needed for transition-metal L and
    rare-earth M edges. **Blocked** on sourcing an Apache-compatible /
    public-domain GOS table — cannot vendor HyperSpy's GPL table, cannot
    fabricate one (verified 2026-08-11: no `calc/eels_gos.py` or GOS data
    file exists yet). Revisit if a permissively-licensed table surfaces.

## Tier 3 — Nice-to-Have

3. ~~**ci.yml stale coverage comment**~~ — shipped 2026-08-10, see Completed

4. ~~**Region holes have no drawing gesture**~~ — CLOSED 2026-08-10.
   Right-click a drawn polygon/lasso wholly inside another region →
   "Mark as hole"; "Remove hole N" detaches it back to a top-level measure.
   Chosen over auto-converting any nested shape (which would silently
   swallow a region drawn inside another for its own sake) and over an
   Alt-modifier (which would have had to thread `altKey` through both the
   multi-click and drag capture paths in `useStagePointers.ts` — this
   gesture touches that file not at all). Two overlapping hosts resolve to
   the SMALLEST containing region, tested with the order reversed both
   ways. Containment is a real point-in-polygon test, pinned by a concave
   "U" case whose notch is inside the bounding box but outside the polygon
   — the case a bbox shortcut gets wrong.
   **Found a live bug while doing it:** `measureGlyphs.tsx` called plain
   `polygonStats` unconditionally, so a holed region's CSV was net (item 19)
   while its ON-SCREEN label showed the GROSS area. Export and display
   disagreed. Now both net out, and the label appends "(N holes)".
   `viewerSession.ts` hit 510 adding the undo case, so the logic split into
   `viewerHoleUndo.ts` (55) — the ratchet forcing a module rather than a
   bulge, again.

5. ~~**`AxisCal.scale` writes raw NaN into a `.fvp` manifest**~~ — shipped 2026-08-10, see Completed

6. **Manual owner sign-offs outstanding** — two long-standing manual
   verification actions, not engineering work:
   - [ ] was PORT_PLAN.md #31 — human side-by-side MATLAB parity session
         (the automated halves — golden/realdata/oracle comparison — closed
         long ago via `tests/golden/` + the rsciio oracle harness; only the
         manual sit-down remains)
   - [ ] was CROSS_SECTION_LAYERS.md — live visual sign-off (overlay
         alignment, drag feel) on the layer-analysis stage overlay; all 13
         engineering items in that plan shipped
   Folded 2026-08-11 when both source plans archived. Neither is blocked on
   code; both are owner actions whenever convenient.

7. **Code signing** — was PORT_PLAN.md (open since 2026-06-08, deferred by
   owner decision). Windows/macOS installers are unsigned. Verified
   2026-08-11: `.github/workflows/release.yml` only signs the Tauri
   **updater** manifest (`TAURI_SIGNING_PRIVATE_KEY`, an Ed25519
   update-signature key that lets the app trust its own auto-updates) —
   that is a different mechanism from an Authenticode/Developer-ID
   code-signing certificate, and no such certificate is configured
   anywhere. Revisit if the cost-vs-SmartScreen-warning calculus changes.

8. **Additional AFM parsers** — was PORT_PLAN.md #50 follow-up (2026-06-14).
   Bruker Nanoscope is the only AFM format read (`io/nanoscope.py`); Asylum
   Igor `.ibw`, Gwyddion `.gwy`, and JPK/NT-MDT/Park `.tiff`-based formats
   remain unimplemented (verified 2026-08-11: no matching files in
   `src/fermiviewer/io/`, no matching commits since). No user demand
   signalled since; parked.

9. **Advanced dynamical diffraction (Kikuchi / CBED / multislice)** — was
   PLAN_DIFFRACTION.md #5–7, its only remaining items (folded 2026-08-11
   when the plan archived — Tier 1–2 there shipped 2026-06-21 in full,
   including the calibrate route, CIF import/delete routes, and the
   Doyle–Turner scattering-factor UI selector this audit re-verified live
   in `routes/diffraction_setup.py` and `DiffractionPanels.tsx` — the
   plan's own "Deferred" notes on those three items were stale). Each of
   the three needs a dynamical, not kinematic, intensity model:
   - [ ] Kikuchi line simulation + band-based orientation indexing
   - [ ] CBED thickness/symmetry (two-beam dynamical minimum)
   - [ ] Full dynamical (multislice/Bloch-wave) pattern simulation
   Parked pending real user demand — the kinematic + real-scattering-factor
   path already covers the common quantitative-SAED/NBED workflow.

11. **Non-rigid / sub-pixel drift (scan-distortion) correction** — was
    FEATURE_AUDIT_2026-06-21.md GAP-19 (landscape #19). Stack align is
    integer-pixel FFT cross-correlation only; picometer metrology and
    revolving-STEM averaging need non-rigid + sub-pixel registration. No
    implementation exists (verified 2026-08-11: no match for
    non-rigid/scan-distortion/elastic-registration in `src/`). Medium
    effort, no concrete request yet; parked.

12. **Advanced atom-column analysis** — was FEATURE_AUDIT_2026-06-21.md
    GAP-26/27 (landscape #26 multi-sublattice iterative refinement +
    polarization/displacement maps; #27 quantitative HAADF atom-counting
    via GMM). `calc/atoms.py` has single-pass Gaussian-fit detection +
    strain only; neither extension exists (verified 2026-08-11). Combined
    into one item since both extend the same module. atomap/StatSTEM-class
    work; parked.

13. **3D volume rendering for tomography/stacks** — was
    FEATURE_AUDIT_2026-06-21.md GAP-32 (landscape #32). No isosurface/
    volume viewer exists (verified 2026-08-11: no match in
    `frontend/src`); also no 3D-volume data model — the same architectural
    gap 4D-STEM had before its `FourDDataset` decision. Multi-week,
    speculative; parked.

14. **Dose/detector calibration** — was FEATURE_AUDIT_2026-06-21.md GAP-36
    (landscape #36): counts→electrons, gain/dark, MTF/DQE for dose-aware
    quantitative imaging. No implementation exists (verified 2026-08-11).
    Medium effort, no concrete request; parked.

## Completed

- ~~**#1 Pin-graduation campaign**~~ (2026-08-10) — both booked graduations
  landed. `store/viewer.ts` 575 → 442, cap DELETED (paid for by fixing
  `closeImage`); `DiffractionWorkshop.tsx` 548 → 445, cap DELETED (PR #146,
  Simulate + calibration tabs → `diffraction/` hooks; a third candidate
  rejected for needing 10 dependencies). `useStagePointers.ts` 498 → 418 with
  82 lines spare (PR #148) by lifting pure decisions to `pointerDecisions.ts`
  — an established seam, `regionCapture.ts` being the same extraction from the
  same file; threading the ~35-field `StagePointersCtx` and per-mode splitting
  were both rejected on evidence. Payoff: 29 tests of rules that previously
  needed a synthetic drag.
  **Two caps remain and are NOT drift:** `Stage.tsx` 584/617 and
  `MeasureOverlay.tsx` 533/562 both shrank this campaign but stay above the
  500 ceiling, so they keep their pins legitimately.
  This campaign also closed the last open item of the per-machine
  REPO_HEALTH_2026-07-07 plan (#33 god-module split — residue accepted as
  pinned debt), which is now Complete and archived (2026-08-11).
- ~~**#5 `AxisCal.scale` writes raw NaN into a `.fvp` manifest**~~ (2026-08-10,
  PR #147) — non-finite `scale`/`origin` now write `0.0`. Lossless, not lossy:
  `AxisCal.calibrated` is `isfinite(scale) and scale != 0 and units != ""` and
  `.axis()` guards identically, so NaN and 0.0 already meant the same thing and
  nothing distinguishes them. No schema change needed. The assertion that
  actually pins it is a raw-bytes check for `NaN`/`Infinity` plus
  `json.loads(parse_constant=<raises>)` — a "still uncalibrated" test would pass
  with NaN still in the file, because Python's reader accepts it. Scope noted
  honestly: no corpus file carries a non-finite axis (24 DM files checked), so
  the path is covered by a unit test constructing the NaN directly.
- ~~**#3 ci.yml stale coverage comment**~~ (2026-08-10, PR #147) — stopped
  asserting an unverifiable CI-only percentage (probably how it drifted),
  states the private-corpus asymmetry, records ~93.8 % as the full local
  reading, and says why the 82 gate must not be raised from a local number.
  `--cov-fail-under=82` unchanged.
- ~~**#2 BACKLOG.md dashboard**~~ (2026-08-10, PR #147) — created, derived from
  the plans and saying so. MAIN_PLAN 5 + SPECTRAL 20 = 25 open, counts verified
  independently. Counts top-level numbered items and explicitly flags that the
  same spectral plan carries ~30 nested checkboxes, so the two conventions are
  not conflated. The archived PROJECT_WORKFLOW_PLAN appears nowhere.
