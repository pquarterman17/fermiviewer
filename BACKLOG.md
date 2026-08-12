# BACKLOG

**Derived from the plans in `plans/` — never edit this file in isolation.**
Regenerate it from `plans/MAIN_PLAN.md`, `plans/SPECTRAL_WORKSPACE_PLAN.md`
and `plans/PLAN_4DSTEM.md` whenever an item opens, closes, or moves (see the
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
10. **Composite → library** — register the combined map as an RGB image
    (gate resolved 2026-08-11: first-class library image). Needs a data-model
    decision + ADR first: the library is grayscale-only today
11. **Retire the single-element Explore flow**

### W4 — Test data and verification

**Tier 2 — Medium Impact**
23. **Synthetic edge SHAPES from `calc/eels_model`** — opened 2026-08-12 by
    item 18; without them `/eels/fit` has nothing to match and cannot be
    golden-tested against the synthetic truth

**Tier 3 — Nice-to-Have**
19. **More presets** — diffusion-couple gradient, thickness ramp
20. **Window overlap detection** (deselected 2026-07-29; revisit only if a
    real case produces a silently wrong answer)

**Open items: 5** *(W1 — shared spectrum core — and W3 — EELS workspace —
are both complete: items 1–7 on 2026-08-12, items 12–16 + 22 on 2026-08-11.
Item 18 closed 2026-08-12 and opened item 23 in doing so, so the count is
unchanged.)*

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
14. **4D usability follow-ups** — scan-shape GUI for `.mib` (top item for
    real Merlin users), log-intensity toggle, aperture radii in mrad,
    main-Stage probe picking, dataset-list live refresh

**Open items: 8**

---

## Dashboard

| Plan | Status | Open items |
|---|---|---|
| MAIN_PLAN.md | Active (root) | 9 |
| SPECTRAL_WORKSPACE_PLAN.md | Active | 5 |
| PLAN_4DSTEM.md | Active | 8 |

**Total open items:** 22

**Counting method:** top-level numbered items (the plan-format.md unit of a
tracked work item) — not nested `- [ ]` sub-task checkboxes. Nested-checkbox
counts by plan, for reference: MAIN_PLAN 5, SPECTRAL_WORKSPACE_PLAN 2,
PLAN_4DSTEM 14 (21 total). A checkbox-based count would disagree with the
open-items count above — pick one convention when reading this table and
don't mix the two.

**Last regenerated:** 2026-08-12
