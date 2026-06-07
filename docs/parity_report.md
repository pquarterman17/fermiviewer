# Parity report — 2026-06-07

Three-way assessment: (1) feature parity vs the MATLAB reference
(`../fermi-viewer` @ `36fb8a5`), (2) design parity vs the Claude Design
prototype (screenshots from the handoff extract), (3) verification
state. Companion documents: `plans/PORT_CHECKLIST.md` (item-level,
per-machine) and `docs/w3_imaging_audit.md` (algorithm decisions).

## 1 · Feature parity vs MATLAB (checklist: 166/183 checked, 91 % —
sweep #4, 2026-06-08)

The headline number undersells the state: parity is split sharply by
layer.

| Layer | Parity | Notes |
|---|---|---|
| Parsers (A) | **12/12 — 100 %** | All formats; cross-validated three ways (goldens, rsciio oracle 25/25 @ 1e-9, MATLAB suite 77/77) |
| Imaging algorithms (B) | **33/36 — 92 %** | Open: colorbar baking, figure-panel builder (export-era); accessors DONE post-sweep |
| EELS / EDS / Diffraction calc (C/D/E) | **100 %** | Every algorithm incl. constants, crystal DB, do-not-"fix" items |
| Atom columns / grains / ML (F-adjacent) | **100 % calc** | Verbatim LM fits; partition-level k-means goldens |
| API surface | **100 % of handoff §8** + 14 endpoints beyond it | tiles, jobs, calibration, fft-mask, session save/load, upload |
| Infrastructure (O) | 4/6 | Open: undo-as-a-service, logging/bug-report capture |
| Verification (P) | **7/7 — 100 %** | incl. oracle harness + fetch script |
| UI workflows (F–N) | ~45 % | The remaining gap is concentrated HERE — see §3 |

**Found-by-the-port upstream bugs (6):** stale golden manifest pin,
radialProfile NumBins validator, morphOp logical rejection,
templateMatch FFT lag selection (PR #23, merged), templateMatch
N-vs-N−1 NCC quirk (documented, preserved), backProject OutputSize
validator (PR #24, open).

## 2 · Design parity vs the prototype (screenshots reviewed 2026-06-07)

Aligned in the design pass (`d3c58ce`):

- Menu structure File · View · Image · Analysis · Window · Help with
  WINDOW badges and the Search actions… box (⌘K) in the menu bar
- Titlebar: brand icon + app name, coloured traffic lights, centred
  doc title with dimmed extension, keyboard/theme/panel toggles
- Status bar: x,y/I readout, CAL px-size, zoom %, amber capture hint
  centred, N-of-M
- Adjust panel: Auto/Reset/colormap row → histogram with handles →
  Black/White sliders with live values → γ + invert chips
- Measure: 2×2 capture-button grid (Profile/Distance/Angle/ROI)
- Zoom chip bottom-left with ⊖/⊕; readout bottom-right; DOCS header

Known remaining design deltas (intentional or future):

| Prototype | Ours today | Status |
|---|---|---|
| Inspector tabs Image · EELS · EDS · Diff | Workshops as floating windows only | Handoff §4 sanctions windows; tabs are a nice-to-have duplication |
| Edit menu (undo/redo) | absent | blocked on undo service (checklist O) |
| EDS Composite channel list (per-element colour/intensity/visibility, additive blend) | quant table + at% maps as derived images | **biggest workshop gap** |
| Polyline measure button | not implemented | checklist G open item |
| Histogram handles embedded as thick rounded bars | thin lines | cosmetic |
| Toolbar icon set (rotate/flip/crop icons w/ separators) | glyph buttons incl. measure modes | rotate/flip/crop UI not yet wired (calc exists for nothing — rotate/flip are trivial np ops, crop is checklist G) |
| Export dialog format cards w/ descriptions + Measurements/Bake/Transparent includes | simpler seg controls; scale-bar include only | overlay baking of measurements is the functional gap |
| "connected/LOCAL/VIEW HRSTEM" status segments | LOCAL-equivalents absent | cosmetic |
| WOFF2 embedded font (JetBrains Mono served) | system mono fallback stack | could vendor the font |

## 3 · Top remaining work, ranked (updated 2026-06-08)

The 2026-06-07/08 runs closed every previously-ranked item: EDS
composite, overlay baking + SVG/PDF, FFT mask editor, EELS advanced
(endpoints + dialog), rotate/flip/crop, undo/redo + Edit menu,
polyline + width profiles, calibration manager, annotations + minimap,
pixel inspector, batch apply, macro record/replay, GIF builder, and
the Structure workshop (first UI for atoms / template match / CTF /
lattice / stitch).

The finish-everything run (2026-06-08) closed the long tail: image
math, stack alignment, MIP, ellipse ROI, batch crop, color overlay,
colorbar, recents, RAW dialog, batch export/rename, measurement
log/CSV/stats, profile CSV, circle annotations + captions + clear
overlays, SI region spectra, EELS edge-ID overlay, live ROI FFT,
particle threshold preview, prefs, metadata editor, GPA 2-click,
diffraction rings, calibrate-from-measurement, interface/noise/
defect analyses, batch profile, logging + bug report.

What remains (17 checklist lines, all inline-noted partials):

1. Tauri shell — blocked on Rust toolchain; `fv --desktop`
   (pywebview) delivers the desktop experience meanwhile
2. Human side-by-side MATLAB session before declaring parity (user)
3. Multi-frame in-image stacks (frame slider) + stack nav dialog
4. Partial halves: histogram transfer ramp, log/equalize transforms,
   custom colormap parser, marquee multi-select + per-item styling,
   annotation context menus, ROI histogram figure, surface plot,
   morphology/multi-otsu dialogs, full-window thumbnail grid,
   scale-bar auto-detect, journal presets, figure-panel builder,
   collapsible panels

## 4 · Verification state

- Python: **177 pytest** (10 realdata on the lunar corpus, 2 oracle),
  ruff + mypy + tsc clean
- Oracle: rsciio agrees on **25/25** corpus files + the real EELS cube
  at rel 1e-9
- MATLAB reference: **77/77 suites** at `36fb8a5`
- E2E: real 512×512 dm3 through open → render → FFT → CLAHE →
  particle analysis (78 found) → screenshot-verified UI
- Desktop: `fv --desktop` native window verified (launch + clean exit)
- 247 goldens-backed comparisons across 9 golden files, manifest
  pinned to the live reference commit
