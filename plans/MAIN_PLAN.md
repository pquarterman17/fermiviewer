# FermiViewer — Main Plan

Root of the plan tree: the mission, the live sub-plans, cross-plan
dependencies, and repo-wide items too small for a sub-plan. Every other
plan in `plans/` declares this file as its parent.

**Status:** Active
**Created:** 2026-08-09
**Updated:** 2026-08-11

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
| SPECTRAL_WORKSPACE_PLAN.md | EDS+EELS shared spectrum core, species lists, batch maps, composites, synthetic-SI verification | Active (15 open items / 14 sub-task boxes, W1–W4) | Independent lifecycle, four workstreams of its own |
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

1. ~~**Pin-graduation campaign**~~ — shipped 2026-08-10, see Completed

2. ~~**BACKLOG.md dashboard**~~ — shipped 2026-08-10, see Completed

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
