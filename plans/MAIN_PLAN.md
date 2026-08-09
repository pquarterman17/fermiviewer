# FermiViewer — Main Plan

Root of the plan tree: the mission, the live sub-plans, cross-plan
dependencies, and repo-wide items too small for a sub-plan. Every other
plan in `plans/` declares this file as its parent.

**Status:** Active
**Created:** 2026-08-09
**Updated:** 2026-08-09

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
| PROJECT_WORKFLOW_PLAN.md | Folder import, constant-physical-scale browsing, area measurement, project/sample hierarchy + comparison deliverables | Active (29 items, W1–W4) | Four coupled feature workstreams sharing the group/measure/workspace primitives |

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
- Ratchet pins: project-workflow items 8, 13 and 21 lower the
  Stage.tsx / MeasureOverlay.tsx / Filmstrip.tsx caps. Sequence those
  before any other work touches the same files (see that plan's
  cross-cutting priorities table).

---

## Tier 1 — High Impact

(none open here — all Tier-1 work lives in the two sub-plans)

## Tier 2 — Medium Impact

1. **Pin-graduation campaign** — the pinned files no sub-plan item
   already shrinks: `store/viewer.ts` (575) and
   `components/workshops/DiffractionWorkshop.tsx` (548) split below 500
   so their `FRONTEND_LEGACY_CAPS` entries are deleted
   (Stage.tsx and MeasureOverlay.tsx pins fall via
   PROJECT_WORKFLOW_PLAN #8/#13).
   Model: opus · Parallel: no — coordinate with any item touching viewer.ts

2. **BACKLOG.md dashboard** — with two live campaigns, create the
   derived dashboard per plan-hygiene (regenerated from the plans' open
   items; never edited in isolation).
   Model: haiku · Parallel: yes

## Tier 3 — Nice-to-Have

3. **ci.yml stale coverage comment** — the "~85%" note contradicts the
   82% gate; fix the comment only, never raise the gate from a local
   coverage reading.
   Model: haiku · Parallel: yes

## Completed

(nothing yet — plan created 2026-08-09)
