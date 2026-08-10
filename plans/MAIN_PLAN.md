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
   (527/562) fell but stay pinned. Still to graduate:
   `components/workshops/DiffractionWorkshop.tsx` (548/548 — zero headroom).
   - [ ] Split DiffractionWorkshop.tsx below 500 and delete its cap entry
   - [ ] `frontend/src/components/Stage/useStagePointers.ts` is at **498 of
         the 500 default ceiling** with NO clean extraction available: it is
         one hook whose handlers all close over its local state, so pulling
         one out means threading a large context object. The next feature
         needing room there must restructure the hook deliberately.
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

4. **Region holes have no drawing gesture** — item 19 shipped the area
   computation, the schema field and the reporting, but nothing in the UI
   creates a hole: the gesture belongs in `useStagePointers.ts`/`Stage.tsx`,
   which that work was fenced out of. The number is correct; the way to
   draw one is missing. (was PROJECT_WORKFLOW_PLAN #19)
   Model: sonnet · Parallel: no — blocked by item 1's useStagePointers note

5. **`AxisCal.scale` writes raw NaN into a `.fvp` manifest** — an
   uncalibrated axis defaults to NaN and `axes_to_manifest` passes it
   through. Python round-trips fine and nothing in the app parses the
   manifest in JS, but a `.fvp` written from an uncalibrated Helios frame
   is **not strict JSON for an external tool**. Found while wiring
   items 32–35; out of scope there.
   Model: sonnet · Parallel: yes

## Completed

(nothing yet — plan created 2026-08-09)
