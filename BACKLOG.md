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

*Root of the plan tree. Status: Active — **no open items of its own**.*

All five items it carried closed on 2026-08-10 (PRs #146–#149): the
pin-graduation campaign, this dashboard, the `ci.yml` coverage comment, the
hole-drawing gesture, and the raw-`NaN`-in-a-manifest defect. See the plan's
`## Completed` section for outcomes.

The section is kept rather than deleted because MAIN_PLAN is the **root** — it
still holds the plan tree and the cross-plan dependencies even with no items of
its own. An empty root is not the same as an archived plan; only a plan that
reaches Complete and moves to `plans/archive/` is dropped from this file.

**Open items: 0**

---

## SPECTRAL_WORKSPACE_PLAN.md

*Parent: MAIN_PLAN.md. Status: Active. Counted by top-level numbered item —
see the Dashboard note below for why that differs from MAIN_PLAN's own
"~30 open sub-tasks" description of this same plan.*

### W1 — Shared spectrum core

**Tier 1 — High Impact**
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
9. **Species list wired to EDS** — periodic-table multi-select feeding the
   list, batch "Extract maps" (unblocked: item 8 shipped 2026-08-10)

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

**Open items: 18**

---

## Dashboard

| Plan | Status | Open items |
|---|---|---|
| MAIN_PLAN.md | Active (root) | 0 |
| SPECTRAL_WORKSPACE_PLAN.md | Active | 18 |

**Total open items:** 18

**Counting method:** top-level numbered items (the plan-format.md unit of a
tracked work item) — not nested `- [ ]` sub-task checkboxes. The spectral
plan's 20 open items carry roughly 30 nested checkboxes across them, which is
what MAIN_PLAN's own plan-tree table means by "~30 open sub-tasks" for the
same plan. A checkbox-based count would report ~30 there instead of 20 —
pick one convention when reading this table and don't mix the two.

**Last regenerated:** 2026-08-10
