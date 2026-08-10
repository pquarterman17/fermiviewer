# BACKLOG

**Derived from the plans in `plans/` — never edit this file in isolation.**
Regenerate it from `plans/MAIN_PLAN.md` and `plans/SPECTRAL_WORKSPACE_PLAN.md`
whenever an item opens, closes, or moves (see the plan-hygiene rules). When
this file and a plan disagree, the plan is authoritative — fix this file to
match it, never the reverse. A plan that reaches **Complete** and moves to
`plans/archive/` (e.g. `plans/archive/PROJECT_WORKFLOW_PLAN.md`) is dropped
from this file entirely, not left as an empty section.

---

## MAIN_PLAN.md

*Root of the plan tree. Status: Active.*

### Tier 2 — Medium Impact

1. **Pin-graduation campaign** — split `DiffractionWorkshop.tsx` (548/548,
   zero headroom) below 500 lines and delete its cap entry;
   `useStagePointers.ts` is at 498/500 with no clean extraction available —
   the next feature needing room there must restructure the hook.
2. **BACKLOG.md dashboard** — this file.

### Tier 3 — Nice-to-Have

3. **ci.yml stale coverage comment** — the "~85%" note contradicted the 82%
   gate.
4. **Region holes have no drawing gesture** — item 19 (PROJECT_WORKFLOW_PLAN,
   archived) shipped the area computation, but nothing in the UI creates a
   hole; blocked by item 1's `useStagePointers.ts` note.
5. **`AxisCal.scale` writes raw NaN into a `.fvp` manifest** — an
   uncalibrated axis's manifest entry is not strict JSON for an external
   tool reading `manifest.json` directly (ADR 0002's `unzip` inspection
   route).

**Open items: 5**

---

## SPECTRAL_WORKSPACE_PLAN.md

*Parent: MAIN_PLAN.md. Status: Active. Counted by top-level numbered item —
see the Dashboard note below for why that differs from MAIN_PLAN's own
"~30 open sub-tasks" description of this same plan.*

### W1 — Shared spectrum core

**Tier 1 — High Impact**
1. **Species model** — one type/store for an energy window + colour, shared
   by both modalities
2. **Window model abstraction** — one interface over EDS's single-window and
   EELS's background+signal window shapes
3. **Species list wiring into the shared shell** — one list component fed by
   either K/L/M lines or edge onsets
4. **Draggable window edges** — grab-to-resize, slide, keyboard nudge
7. **Shared composite** — generalise `EdsComposite` to a second caller

**Tier 2 — Medium Impact**
5. **Width presets and FWHM auto-fit**
6. **Numeric steppers with live net**

### W2 — EDS workspace

**Tier 1 — High Impact**
8. **`/eds/element-maps` endpoint** — expose `extract_element_maps()`
   directly, decoupled from Cliff–Lorimer/ZAF quantify
9. **Species list wired to EDS** — periodic-table multi-select feeding the
   list, batch "Extract maps"

**Tier 2 — Medium Impact**
10. **Composite → library** — register the combined map as an RGB image
    (owner gate: first-class library image vs. panel-local canvas)
11. **Retire the single-element Explore flow**

### W3 — EELS workspace

**Tier 1 — High Impact**
12. **Edge picker** — species list backed by `EELS_EDGES`, element + edge
    choice
13. **EELS zoom, colours and integration** — via the shared W1 core
14. **`/eels/maps` batch endpoint** — mirrors item 8; also fixes
    `extract_map`'s whole-cube float64 copy
22. **EELS edge identification** — the auto-ID half of the Maps workflow;
    no `/eels/auto-assign` exists yet
15. **EELS composite** — the capability EELS has never had

**Tier 2 — Medium Impact**
16. **Background-window auto-placement** (owner gate: auto-place from onset
    vs. always user-set)

### W4 — Test data and verification

**Tier 2 — Medium Impact**
18. **Quantification golden tests against truth** — assert `/eds/quantify`
    and `/eels/quantify` recover the synthetic composition within tolerance

**Tier 3 — Nice-to-Have**
19. **More presets** — diffusion-couple gradient, thickness ramp
20. **Window overlap detection** (deselected 2026-07-29; revisit only if a
    real case produces a silently wrong answer)

**Open items: 20**

---

## Dashboard

| Plan | Status | Open items |
|---|---|---|
| MAIN_PLAN.md | Active | 5 |
| SPECTRAL_WORKSPACE_PLAN.md | Active | 20 |

**Total open items:** 25

**Counting method:** top-level numbered items (the plan-format.md unit of a
tracked work item) — not nested `- [ ]` sub-task checkboxes. The spectral
plan's 20 open items carry roughly 30 nested checkboxes across them, which is
what MAIN_PLAN's own plan-tree table means by "~30 open sub-tasks" for the
same plan. A checkbox-based count would report ~30 there instead of 20 —
pick one convention when reading this table and don't mix the two.

**Last regenerated:** 2026-08-10
