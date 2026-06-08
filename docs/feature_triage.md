# Feature triage — pending user decisions

Companion to `docs/gui_audit.md` (full button-by-button tables).
This is the come-back-later decision sheet: everything currently
queued or awaiting a pick, in one place. 2026-06-08.

## Already queued (plan items, no decision needed)

- **#33 Scale-bar interactivity** — drag to reposition, resize
  (length/thickness/font), controls in BOTH the right panel and a
  right-click menu on the bar; export baking honours the custom
  position. *Goes beyond MATLAB — even the original's bar is fixed.*
- **#34 Tilt-corrected distance measurements** — port
  `measureDistance.m`: in-tilt-axis component × 1/sin θ (FIB
  cross-section) or × 1/cos θ (plan-view), TiltAxis X|Y,
  θ ∈ (−90°, 90°). Math already ported in `calc/profiles.line_profile`;
  `io/metadata.get_stage_tilt` can auto-seed the angle from file
  metadata. **Open sub-question:** show corrected value only, or raw +
  corrected side by side?

## User-reported gaps (queued, no decision needed)

- **#37 Collapsible right-panel sections — everywhere** (user,
  2026-06-08): only the three Measure cards collapse today
  (`<details>` in MeasurePanel); Adjust, Image, Metadata and the
  workshop-tab content do not. Make every inspector card collapsible
  with the same summary affordance, and persist the collapsed state
  per card.

## Absent from the port — pick which to build (A1–A10)

| Pick | ID | Feature | Effort | Notes |
|---|---|---|---|---|
| ☐ | A1 | Toggle Scale Bar (hide/show) | trivial | View-menu toggle like minimap |
| ☐ | A2 | Fixed Size Zoom (type W×H, click to place, Enter) | small | new capture flow |
| ☐ | A3 | Back Project (FBP) | small | **calc ported & tested — wire-up only** |
| ☐ | A4 | Composition Profile (SI element-fraction line) | small | **calc ported & tested — wire-up only** |
| ☐ | A5 | ELNES fingerprint comparison | small | **calc ported & tested — wire-up only** |
| ☐ | A6 | EELS Navigate Pixel (live hover spectrum) | medium | region explorer covers click; hover is new |
| ☐ | A7 | Manual Click Spots (diffraction) | small | Preview-click pattern exists |
| ☐ | A8 | Kinematic pattern Simulate UI | small | calc ported — wire-up only |
| ☐ | A9 | Measurement end symbols (circle/cross/square) | small | overlay + export baking |
| ☐ | A10 | Export Profile → BosonPlotter format | small | CSV exists; needs the DP header |

## Different by design — confirm or change (D1–D13)

| Pick | ID | MATLAB | Ours | Default recommendation |
|---|---|---|---|---|
| ☐ | D1 | destructive Undo Filters | undo/redo service over derived images | keep ours |
| ☐ | D2 | destructive crop/invert | derived crop, display-only invert | keep ours |
| ☐ | D3 | Batch Convert in place | Batch Export ZIP | keep ours |
| ☐ | D4 | single Rename Selected | batch rename only | **add single rename** (filmstrip ctx) |
| ☐ | D5 | Live FFT follows the view | live FFT of the ROI | revisit with A6 |
| ☐ | D6 | standalone Watershed op | particles option only | expose as filter kind? |
| ☐ | D7 | per-journal preset dialog | 4 preset buttons in Export | enough? |
| ☐ | D8 | persistent analysis ROI scoping all ops | per-call ROI scoping | formalise global ROI? |
| ☐ | D9 | compose composite from any images | quantify-driven channels + Color Overlay window | covered |
| ☐ | D10 | auto Assign Elements from peak energies | manual symbols | **worth adding** |
| ☐ | D11 | in-image stack stepper ◀ ▶ | explode → filmstrip | stepper still wanted? |
| ☐ | D12 | image right-click: zoom/copy/save actions | radial capture menu only | add an actions ring/menu? |
| ☐ | D13 | prefs: contrast %, export DPI, inspector size | not in prefs | **add the three settings** |

## Other parked items

- Code signing for the installer (cert purchase — user decision).
- Goldens manifest still pins `36fb8a5`; re-pin to `6b1e6b7+` at the
  next golden regeneration (both upstream changes since are additive).
- #31 human side-by-side MATLAB session — the final parity sign-off.
