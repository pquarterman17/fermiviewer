# BACKLOG

**Derived from the plans in `plans/` — never edit this file in isolation.**
Regenerate it from `plans/MAIN_PLAN.md`, `plans/SPECTRAL_WORKSPACE_PLAN.md`,
`plans/PLAN_4DSTEM.md` and `plans/ANALYSIS_PRESENTATION_PLAN.md` whenever an
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

## SPECTRAL_WORKSPACE_PLAN.md

*Parent: MAIN_PLAN.md. Status: Active. Counted by top-level numbered item —
see the Dashboard note below for the counting convention.*

### W2 — EDS workspace

**Tier 2 — Medium Impact**
11. **Retire the single-element Explore flow**

**Open items: 1** *(everything else in this plan is complete: W1, W3 and
W4 in full, plus W2's item 10. Items 10 + 19 + 20 shipped 2026-08-12.)*

---

## PLAN_4DSTEM.md

*Parent: MAIN_PLAN.md. Status: Active. Tier 1 / Phase 1 (items 1–6) shipped
2026-08-02. Tier 2 (COM/DPC/iDPC) deferred by owner 2026-08-02 in favor of
hardening — a decision, not an oversight; item 7's core math already landed
as a stretch goal. Tier 3 is parked future work; item 14 is the 2026-08-02
live-audit usability follow-up list.*

**Tier 2 — Medium Impact** *(deferred by owner 2026-08-02)*
7. **Per-probe center-of-mass (COMx, COMy)** — the basis for all DPC
8. **Differential phase contrast (DPC) + charge-density / field maps**
9. **Integrated DPC (iDPC)** — light-element phase imaging

**Tier 3 — Nice-to-Have**
10. **Disk-detection strain mapping**
11. **Ptychography (SSB / WDD)**
12. **Orientation / phase mapping (ACOM)**
13. **More 4D formats + async ingest** — Gatan K2/K3, NCEM EMD 4D, blockfile
    `.blo`, job-queued batch virtual-detector

**Open items: 7** *(item 14 closed 2026-08-12 — all five usability
follow-ups from the live audit shipped)*

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
| SPECTRAL_WORKSPACE_PLAN.md | Active | 1 |
| PLAN_4DSTEM.md | Active | 7 |
| ANALYSIS_PRESENTATION_PLAN.md | Active (Tier 3 residue only) | 4 |

**Total open items:** 21

**Counting method:** top-level numbered items (the plan-format.md unit of a
tracked work item) — not nested `- [ ]` sub-task checkboxes. Nested-checkbox
counts by plan, for reference: MAIN_PLAN 5, SPECTRAL_WORKSPACE_PLAN 0,
PLAN_4DSTEM 7, ANALYSIS_PRESENTATION_PLAN 0 (12 total). A checkbox-based
count would disagree with the open-items count above — pick one convention
when reading this table and don't mix the two.

**Last regenerated:** 2026-08-12 (ANALYSIS_PRESENTATION_PLAN booked +12 then
fully shipped −8 across four waves; PLAN_4DSTEM #14 closed −1; plus the
copy-annotations preference and the structure/profiles ceiling extractions)
