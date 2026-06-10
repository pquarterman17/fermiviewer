# Feature triage — DECIDED 2026-06-09

Companion to `docs/gui_audit.md` (full button-by-button tables).
The user triaged all pending items on 2026-06-09; outcomes below.
Execution is tracked as plan workstream **W9** (items #38–#45, plus
moved #33/#34/#37).

## Decisions — absent features (A1–A10)

| Pick | ID | Feature | Outcome |
|---|---|---|---|
| ✔ | A1 | Toggle Scale Bar | **BUILD** — folded into #33 (scale-bar card + ctx menu) |
| ✔ | A2 | Fixed Size Zoom | **BUILD** — #41 |
| ✔ | A3 | Back Project (FBP) | **BUILD** — #39 (wire-up only) |
| ✔ | A4 | Composition Profile | **BUILD** — #39 (wire-up only) |
| ✔ | A5 | ELNES fingerprint | **BUILD** — #39 (wire-up only) |
| ✘ | A6 | EELS Navigate Pixel (live hover) | **DECLINED** — region explorer's click navigation suffices |
| ✔ | A7 | Manual Click Spots | **BUILD** — #41 |
| ✔ | A8 | Kinematic Simulate UI | **BUILD** — #39 (wire-up only) |
| ✔ | A9 | Measurement end symbols | **BUILD** — #42 |
| ✘ | A10 | Export Profile → BosonPlotter DP | **DECLINED** — CSV export suffices |

## Decisions — different by design (D1–D13)

| Pick | ID | Outcome |
|---|---|---|
| keep | D1 | undo/redo service over derived images — **keep ours** |
| keep | D2 | derived crop, display-only invert — **keep ours** |
| keep | D3 | Batch Export ZIP — **keep ours** |
| ✔ | D4 | **ADD single rename** (filmstrip ctx + F2) — #43 |
| keep | D5 | live FFT of the ROI — **keep ours** (A6 declined removes the revisit) |
| keep | D6 | watershed as particles option — **keep ours** |
| keep | D7 | 4 preset buttons in Export — **keep ours** |
| keep | D8 | per-call ROI scoping — **keep ours** |
| keep | D9 | quantify-driven channels + Color Overlay — **keep ours** |
| ✔ | D10 | **ADD auto-assign elements** from peak energies — #44 |
| ✔ | D11 | **ADD in-image stepper, with keyboard step**, alongside explode — #40 |
| ✔ | D12 | **Contextual right-click** (user design): hit-test the click — scale bar → scale-bar menu; measurement/annotation → their existing menus; empty image → the as-is radial menu **plus a default Copy entry** — #38 |
| ✔ | D13 | **ADD prefs**: auto-contrast %, export DPI, inspector size — #45 |

## Other parked items (unchanged)

- Code signing for the installer (cert purchase — user decision).
- Goldens manifest still pins `36fb8a5`; re-pin to `6b1e6b7+` at the
  next golden regeneration (both upstream changes since are additive).
- #31 human side-by-side MATLAB session — the final parity sign-off.
- #34 open sub-question: distance labels show raw + corrected
  side-by-side, or corrected only? (decide during implementation)
