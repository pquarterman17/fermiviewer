# BACKLOG

**Derived from the plans in `plans/` — never edit this file in isolation.**
Regenerate it from `plans/MAIN_PLAN.md`,
`plans/MICROSCOPY_FEATURE_ROADMAP.md`, `plans/PLAN_4DSTEM.md` and
`plans/ANALYSIS_PRESENTATION_PLAN.md` whenever an
item opens, closes, or moves (see the
plan-hygiene rules). When this file and a plan disagree, the plan is
authoritative — fix this file to match it, never the reverse. A plan that
reaches **Complete** and moves to `plans/archive/` (e.g.
`plans/archive/PROJECT_WORKFLOW_PLAN.md`) is dropped from this file entirely,
not left as an empty section.

---

## MAIN_PLAN.md

*Root of the plan tree. Status: Active — 9 open items, all folded up from
archived legacy plans on 2026-08-11 (PORT_PLAN, PLAN_DIFFRACTION,
PLAN_SPECTRAL_QUANT, CROSS_SECTION_LAYERS, FEATURE_AUDIT_2026-06-21 — each
re-verified against the code before folding).*

**Tier 2 — Medium Impact**
10. **Hartree-Slater / GOS cross-sections for EELS** (was
    PLAN_SPECTRAL_QUANT.md #3) — blocked on sourcing a permissively-licensed
    GOS table

**Tier 3 — Nice-to-Have**
6. **Manual owner sign-offs outstanding** (was PORT_PLAN.md #31 +
   CROSS_SECTION_LAYERS.md's visual sign-off) — two pending manual
   verification actions, not blocked on code
7. **Code signing** (was PORT_PLAN.md) — Windows/macOS installers unsigned;
   deferred by owner decision
8. **Additional AFM parsers** (was PORT_PLAN.md #50 follow-up) — Igor
   `.ibw`, Gwyddion `.gwy`, JPK/NT-MDT/Park `.tiff`-based; no demand
   signalled
9. **Advanced dynamical diffraction** (was PLAN_DIFFRACTION.md #5–7) —
   Kikuchi / CBED / multislice; parked pending real user demand
11. **Non-rigid / sub-pixel drift correction** (was FEATURE_AUDIT
    GAP-19) — no implementation exists; parked
12. **Advanced atom-column analysis** (was FEATURE_AUDIT GAP-26/27) —
    iterative refinement + polarization maps + HAADF atom-counting; parked
13. **3D volume rendering for tomography/stacks** (was FEATURE_AUDIT
    GAP-32) — no volume data model exists; speculative, parked
14. **Dose/detector calibration** (was FEATURE_AUDIT GAP-36) — no
    implementation exists; parked

**Open items: 9**

---

## MICROSCOPY_FEATURE_ROADMAP.md

*Parent: MAIN_PLAN.md. Status: Active — implementation in progress; the
current feature-priority spine (adopted 2026-08-22 from a feature audit
against v0.1.32). Tier 1 items 1–3 (persistent results, results browser /
report, universal operation parity) shipped in full 2026-08-22 → 08-27
(every sub-task checked). Item 4's backend halves shipped 2026-08-29 →
09-01 (region contract, `.fvp` persistence, consumer migration 4C-1..5,
label↔region conversion, preview summaries), and the anisotropic-pixel
prerequisite for item 5 landed in v0.4.0 + PR #208. Items 8–9 are parked
by owner decision: do not advance them while a Tier 1–2 item remains
valuable and feasible.*

**Tier 1 — Scientific trust and daily workflow**
4. **First-class region and mask model** — one sub-task left: mask
   previews before expensive execution (the summaries endpoint shipped
   2026-09-01; the previews themselves are the frontend lane's)
5. **Calibration profiles and quantitative standards** — open (5a
   profiles: 5 sub-tasks; 5b standards/QC: 6). The reciprocal half of
   5a's per-axis box shipped 2026-09-04 (`calc/ctf.py`, `calc/lattice.py`,
   `calc/diffraction.py::index_spots` take per-axis `spacing`); next is
   the project/UI calibration model and energy-axis profiles — designed
   in ADR 0008 (2026-09-05, Proposed, two owner gates); the 5a-A backend
   PR is the next build

**Tier 2 — Correlative work and large datasets**
6. **Cross-modal registration** — 6 sub-tasks, none started
7. **Large-data execution and interoperable storage** — 7 sub-tasks, none
   started

**Specialty tracks — parked by default (owner decision)**
8. **Optional 4D-STEM extensions** — 5 sub-tasks; overlaps PLAN_4DSTEM
   Tier 3 (items 10–13 there)
9. **Optional tomography workflow** — 6 sub-tasks

**Open items: 6** *(4 active, 2 parked)*

---

## PLAN_4DSTEM.md

*Parent: MAIN_PLAN.md. Status: Active. Tier 1 / Phase 1 (items 1–6) shipped
2026-08-02; Tier 2 (items 7–9, COM/DPC/iDPC) shipped 2026-08-14 (PR #153,
released v0.1.28) and is CLOSED. Only parked Tier 3 remains.*

**Tier 3 — Nice-to-Have**
10. **Disk-detection strain mapping**
11. **Ptychography (SSB / WDD)**
12. **Orientation / phase mapping (ACOM)**
13. **More 4D formats + async ingest** — Gatan K2/K3, NCEM EMD 4D, blockfile
    `.blo`, job-queued batch virtual-detector

**Open items: 4** *(Tier 2 closed 2026-08-14 — items 7–9 shipped via
PR #153, released v0.1.28)*

---

## ANALYSIS_PRESENTATION_PLAN.md

*Parent: MAIN_PLAN.md. Status: Active — booked 2026-08-12 from the merged
OriginPro/JMP gap audit (`docs/originpro-jmp-gap-audit.md`), each item
re-verified against main before booking. Scope rule: image-derived results
only; the audit's DECLINED general-graphing list is out. **All eight
engineering items (1–8) shipped 2026-08-12** across four same-day waves;
only Tier 3 (build-on-demand by rule) remains.*

**Tier 3 — Nice-to-Have**
9. **Two-sample population comparison** (was R9) — only if 6 gets real use
10. **Headless folder batch** (was R10)
11. **Baseline options: SNIP / anchor spline** (was R11)
12. **Chart dark-mode theming** (was R12)

**Open items: 4** *(all Tier 3, build-on-demand)*

---

## Dashboard

| Plan | Status | Open items |
|---|---|---|
| MAIN_PLAN.md | Active (root) | 9 |
| MICROSCOPY_FEATURE_ROADMAP.md | Active (priority spine; items 4–7 live, 8–9 parked) | 6 |
| PLAN_4DSTEM.md | Active (Tier 3 residue only) | 4 |
| ANALYSIS_PRESENTATION_PLAN.md | Active (Tier 3 residue only) | 4 |

**Total open items:** 23

**Counting method:** top-level numbered items (the plan-format.md unit of a
tracked work item) — not nested `- [ ]` sub-task checkboxes. Nested-checkbox
counts by plan, for reference: MAIN_PLAN 5, MICROSCOPY_FEATURE_ROADMAP 36,
PLAN_4DSTEM 0, ANALYSIS_PRESENTATION_PLAN 0 (41 total). A checkbox-based
count would disagree with the open-items count above — pick one convention
when reading this table and don't mix the two.

**Last regenerated:** 2026-09-04 (MICROSCOPY_FEATURE_ROADMAP added +6 — the
plan was adopted 2026-08-22 and had shipped its Tier 1 items 1–3 and most
of item 4 without ever appearing here; the other three plans re-verified
against their files, unchanged at 9 / 4 / 4)
