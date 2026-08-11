# FermiViewer — Main Plan

Root of the plan tree: the mission, the live sub-plans, cross-plan
dependencies, and repo-wide items too small for a sub-plan. Every other
plan in `plans/` declares this file as its parent.

**Status:** Active
**Created:** 2026-08-09
**Updated:** 2026-08-10

---

## Context

### How the pieces fit together

FermiViewer is a desktop scientific image viewer: a FastAPI backend
(`src/fermiviewer` — pure `io`/`calc`/`ops` layers under thin `routes/`,
guarded by `tests/test_repo_integrity.py`'s layering test and 500-line
module ratchet) and a React/zustand frontend (`frontend/src` — same
500-line ratchet with pinned legacy caps that only move down). Two
campaigns are live, one per sub-plan: making the spectral (EDS/EELS)
workspaces usable for routine elemental analysis, and making the imaging
side usable for many-sample project studies (import, browsing, area
measurement, project hierarchy).

### Plan tree

| Sub-plan | Scope | Status | Why its own file |
|---|---|---|---|
| SPECTRAL_WORKSPACE_PLAN.md | EDS+EELS shared spectrum core, species lists, batch maps, composites, synthetic-SI verification | Active (~30 open sub-tasks, W1–W4) | Independent lifecycle, four workstreams of its own |
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

---

## Tier 1 — High Impact

(none open here — all Tier-1 work lives in the two sub-plans)

## Tier 2 — Medium Impact

1. **Pin-graduation campaign** — three legacy caps remain, down from four.
   `store/viewer.ts` graduated 2026-08-10 (575 → 444, entry deleted) as the
   price of fixing `closeImage`; Stage.tsx (584/617) and MeasureOverlay.tsx
   (527/562) fell but stay pinned. `DiffractionWorkshop.tsx` graduated
   2026-08-10 (548 → 445, entry deleted), leaving only those two.
   - [x] ~~Split DiffractionWorkshop.tsx below 500 and delete its cap entry~~
         (2026-08-10) — Simulate-tab state/logic → `useDiffractionSimulation.ts`
         (128) and the elliptical-distortion flow → `useDiffractionCalibration.ts`
         (57), both under `diffraction/`. Bodies moved verbatim as custom hooks
         with identical dependency arrays and destructured names, so the JSX
         needed zero edits. A third candidate (`buildReportTable`) was rejected
         for needing 10 dependencies — the ≥6-prop rule working.
   - [x] ~~`useStagePointers.ts` at 498/500 with no clean extraction~~
         (2026-08-10) — restructured to **418**, 82 lines of headroom.
         Pure decision logic lifted to `pointerDecisions.ts` (178) and
         `stageGrainEdit.ts` (79), leaving the hook holding only what needs
         the closure: refs, pointer capture, applying a result. This
         continued an ESTABLISHED seam — `regionCapture.ts` in the same
         directory is already this exact extraction from this exact file.
         Threading the context was rejected on evidence: `StagePointersCtx`
         has ~35 fields. Splitting by interaction mode was rejected because
         marquee/lasso/click-accumulating modes each span
         pointerdown→move→up through the same state, so a per-mode module
         would participate in three handlers — making event ordering, the
         actual regression risk, the thing under change.
         Payoff: 29 tests of rules that previously needed a synthetic drag,
         including the polygon close tolerance (8 px ÷ zoom) and the
         1-based-inclusive crop clamping at both ends.
         (was PROJECT_WORKFLOW_PLAN #9)
   Model: opus · Parallel: no — coordinate with any item touching these files

2. **BACKLOG.md dashboard** — with two live campaigns, create the
   derived dashboard per plan-hygiene (regenerated from the plans' open
   items; never edited in isolation).
   Model: haiku · Parallel: yes

## Tier 3 — Nice-to-Have

3. **ci.yml stale coverage comment** — the "~85%" note contradicts the
   82% gate; fix the comment only, never raise the gate from a local
   coverage reading. Local now measures ~93.8% (1808 tests).
   Model: haiku · Parallel: yes

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

5. **`AxisCal.scale` writes raw NaN into a `.fvp` manifest** — an
   uncalibrated axis defaults to NaN and `axes_to_manifest` passes it
   through. Python round-trips fine and nothing in the app parses the
   manifest in JS, but a `.fvp` written from an uncalibrated Helios frame
   is **not strict JSON for an external tool**. Found while wiring
   items 32–35; out of scope there.
   Model: sonnet · Parallel: yes

## Completed

(nothing yet — plan created 2026-08-09)
