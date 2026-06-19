# GUI Parity Audit — MATLAB fermi-viewer vs React fermiviewer

Control-by-control comparison of every clickable/draggable/typeable UI surface
in the MATLAB reference (`../fermi-viewer/`) against the React port
(`frontend/src/`). Goal: enumerate **gaps** (MATLAB controls with no reachable
port equivalent). No implementation here — findings only.

**Status:** Findings only (no changes made)
**Created:** 2026-06-15
**Method:** 4 parallel region audits (menus/palette/shortcuts; toolbar/adjust/
display; workshops; stage/measurement/capture). MATLAB control surface
enumerated from the decomposed `+fermiViewer/` package (188 `.m` files —
`build*Panel.m`, `*Dispatch.m`, `mouseOps.m`, `captureModeTable.m`,
`onKeyPress.m`). Port verified against current `frontend/src` (post-W9 + AFM +
grains + metadata + box-integration). Supersedes the 2026-06-08
`docs/gui_audit.md` (#35), which predates all of that work.

**Reconciliation note:** Two items first flagged "absent" were downgraded after
cross-checking regions — the histogram log-scale toggle exists in AdjustPanel,
and zoom-to-dimensions exists as the Fixed-Size Zoom "⊞" stage tool. Both are
surface/keybinding divergences, not missing capabilities.

**Not deeply audited** (flagged for a follow-up pass): the standalone
`buildPreferencesDialog.m` vs `PrefsWindow.tsx`, the dedicated
`+annotation/AnnotationWorkshop.m` window, and `+contrast/ContrastWorkshop.m`
as a separate window (its controls overlap the audited AdjustPanel).

---

> **Update 2026-06-18 — Tier 1 + Tier 2 SHIPPED.** All three Tier-1 capability
> gaps and four of five Tier-2 gaps are ported and merged to main.
> Tier 1: EDS spectrum-image explorer (`4dff1b4`), atom-column depth (`1d39b7d`),
> matched-phase rings + analysis-ROI (`7da914a`).
> Tier 2: per-workshop CSV/PNG export (`602c771` + the Tier-1 commits), ROI
> Manager (`506fd62`), Measurement Stats (`c8b3b32`), Montage (`3e9bb00`).
> Full gate green (410 pytest / 196 vitest / ruff / mypy / build).
> **NOT built: #8 Grain "Trained" mode** — a deliberate design divergence (the
> port replaced the scribble-classifier with 3 scikit-image auto-methods +
> interactive merge/split); building it needs a user decision. The remaining
> backlog is Tier 3 (smaller controls) + the behavioral divergences.

## Verdict

The port is at high functional parity. **No physics/calc capability is missing**
— every gap is a missing or simplified *UI control*. Gaps cluster into five
themes, in rough priority order:

1. **EDS spectrum-image explorer** — the largest single gap (~8 controls).
2. **Atom-column analysis depth** — sublattices, peak-pair strain, strain
   overlays, readouts (~5 controls).
3. **Per-workshop CSV / PNG export** — pervasive in MATLAB, broadly absent in
   the port (atoms, grains, EELS-quant, EDS maps/spectrum).
4. **Grain "Trained" (scribble-classifier) mode** — absent; port chose 3 modern
   auto-methods + interactive merge/split instead.
5. **A scatter of smaller controls** — matched-phase diffraction rings,
   analysis-ROI scoping, colorbar tick-count/font, scale-bar color/unit-override,
   compare flicker-rate, a few stage/toolbar buttons.

Plus two **behavioral divergences** (not gaps, but worth a decision): the
**D-key conflict** (zoom-to-dims vs distance) and the **split command registry**
(⌘K palette is a strict subset of the MenuBar actions).

---

## Headline gaps (prioritized)

### Tier 1 — Capability gaps a power user would notice

1. ~~**EDS Spectrum-Image explorer**~~ ✅ SHIPPED 2026-06-18 (`4dff1b4`) (`+spectrumImage/openSpectrumImageWorkshop.m`)
   — the port never ported this interactive window. Missing: element dropdown →
   snap energy window to the X-ray line; energy window lo/hi spinners (keV);
   background-mode toggle (linear/none); **drag-to-set-window directly on a live
   spectrum plot**; sum-spectrum view; pixel-click / ROI-drag → spectrum; element-
   map CSV export; spectrum CSV export. Port has only the RGB-composite blend
   canvas (`EdsComposite.tsx`); SI region selection is partially covered by the
   EELS `RegionPicker`.

2. ~~**Atom-column workshop depth**~~ ✅ SHIPPED 2026-06-18 (`1d39b7d`) (`+atomcolumns/openAtomColumnWorkshop.m`) —
   backend returns the data, but the UI to drive/show it is absent: sublattice
   count (1–4) selector; **peak-pair-analysis (PPA) strain** button; overlay
   selector (Markers / Sublattice / εxx / εyy / εxy / Rotation — port only draws
   plain markers); Gaussian fit-window radius; R²/strain-median readout; column
   CSV export; overlay PNG export.

3. ~~**Matched-phase diffraction rings**~~ ✅ SHIPPED 2026-06-18 (`7da914a`) (`+diffraction/drawMatchedRings.m`) — the
   port's "Rings" checkbox draws rings from *detected-spot radius clusters*, not
   the *indexed phase's theoretical d-spacing rings*. Also absent: manual
   typed-d-spacing ring overlay; analysis-ROI (rect/circle/clear) to scope
   detect/index/CTF/defect to a drawn region.

### Tier 2 — Workflow / export gaps

4. ~~**Per-workshop CSV / PNG export**~~ ✅ SHIPPED 2026-06-18 (`4dff1b4` EDS, `1d39b7d` atoms, `602c771` grains+EELS) — MATLAB workshops are export-heavy; the
   port leans on derived-image registration + the global Export dialog instead.
   Missing buttons: atom-columns CSV + overlay PNG; grain CSV + overlay PNG;
   EELS composition-table CSV; EDS map CSV + spectrum CSV. (Note: line/box-profile
   CSV export *was* added 2026-06-15 — this theme is the analysis-table analog.)

5. ~~**ROI Manager**~~ ✅ SHIPPED 2026-06-18 (`506fd62`) (`+measurement/buildROIManager.m`) — name/save/recall multiple
   named ROIs. Port draws ROIs ad-hoc (R key / radial), one live set per image,
   with no manager to persist/recall them.

6. ~~**Measurement Stats**~~ ✅ SHIPPED 2026-06-18 (`c8b3b32`) (`+analysis/displayMeasurementStats.m`) — aggregate
   stats summary across *all* measurements on an image. Port reports each measure
   inline only.

7. ~~**Montage**~~ ✅ SHIPPED 2026-06-18 (`3e9bb00`) (`+visualization/executeMontage.m`) — labeled-tile montage as a
   derived image. Distinct from Stitch (mosaic registration) and Export Figure
   Panel (export-time grid). No port equivalent.

8. **Grain "Trained" mode** (`+grains/openGrainWorkshop.m`) — ⚠️ NOT BUILT (deliberate design divergence — needs a user decision, see below) — scribble-painting
   classifier (paint class, brush radius, clear scribbles, Softmax/Forest
   dropdown), multiscale "scales" input, min-area filter. Port replaced this with
   3 scikit-image auto-methods + interactive stage merge/split — arguably a better
   direction, but the trained workflow is gone. **Decision, not an obvious gap.**

### Tier 3 — Smaller controls

9.  **Colorbar:** tick-*count* control (port has tick-*step* interval only),
    tick-label font-size, and `bottom` placement (port has left/right only).
10. **Scale bar:** color control (bar/label color — absent); explicit length-unit
    *override* dropdown (port auto-derives unit from calibration, can't force
    e.g. Å on a nm-calibrated bar); discrete 4-corner picker (port uses free drag).
11. **Stage toolbar:** "Reset all transforms" (reload original pixels — port's
    Adjust reset only resets the display window, not geometry/filters);
    "Delete last annotation" button.
12. **Annotations:** per-annotation font size (port has one global overlay size);
    whole-body drag for box/circle annotations (port drags only the 2 corners).
13. **Bin Image:** sum-vs-average mode selector (port exposes bin size only).
14. **Surface plot:** colormap + colorbar on the surface; interactive 3D rotate
    (port is a fixed-isometric wireframe).
15. **Compare:** user-settable flicker rate + explicit A/B index pair (port flicks
    the whole set at a fixed ~1.7 Hz); active-panel focus + Tab-switch.
16. **Save Cropped Region** capture (drag box → save that region to a new file —
    port crops in place only). **Batch-crop** drag-capture exists as a menu item
    ("Batch Crop to ROI") but not as a stage marquee.
17. **EELS quant params** in the UI: beam energy E0 (kV) and collection
    semi-angle β (mrad) are backend-default only — no spinner. Plus EELS
    background-model dropdown (power-law vs exponential — port hard-codes
    power-law) and edge-element filter dropdown.
18. **GPA rotation map** + **lattice unit-cell area** readouts: computed backend,
    not surfaced in the StructureWorkshop result panels.

---

## Behavioral divergences (decide, don't necessarily "fix")

- **D-key conflict.** MATLAB `d` = zoom-to-dimensions; port `d` = distance
  measure. The *capability* exists both sides (port's zoom-to-dims is the
  Fixed-Size Zoom "⊞" tool), but the binding diverges — a user switching tools
  will be surprised.
- **Split command registry.** The ⌘K palette (`App.tsx` `actions`, ~30 entries)
  is a strict subset of the MenuBar dropdown actions. Roughness, Reset Contrast,
  Defect Count, Back Project, etc. are reachable only from the menu, not ⌘K. No
  single source of truth → discoverability + drift risk.
- **N/A by design:** "Export Profile to DP" (`runExportProfileToDP.m`) is a
  BosonPlotter/DiraCulator handoff with no target app in the port — the new
  profile-CSV export is the equivalent. F5 "Refresh State" is moot in a reactive
  SPA.

---

## Per-region detail

### Region A — Menus / Command Palette / Radial / Shortcuts
~95 controls enumerated; ~64 present (many workshop-consolidated), ~21
different, ~13 absent/partial.
- **Absent:** Montage, ROI Manager, Measurement Stats, Export-Profile-to-DP (N/A).
- **Partial:** Figure Builder (port auto-grids, no manual composer), Publication
  Presets (one hardcoded Journal preset, no manager), Batch Measurement (port has
  narrower Batch Profile/Crop), Reset Zoom (folded into Fit).
- **Divergence:** D-key, split ⌘K registry, several session/save shortcuts unbound.
- **Port-only:** Window menu, Recent files, Redo, granular Clear commands,
  Calibrate-from-Measurement, Auto-detect Scale Bar, Gallery, radial Copy.

### Region B — Toolbar / Transform-Adjust / Scale bar / Display
~37 controls; ~24 present (mostly relocated), 7 different, ~11 absent/partial.
- **Absent:** colorbar tick-count, colorbar font-size, scale-bar color, colorbar
  `bottom` placement, "Reset all transforms" toolbar button, delete-last-annotation
  button, save-crop-to-file.
- **Partial:** scale-bar 4-corner picker (drag substitutes), Bin sum/avg mode.
- **Port-only (richer):** live histogram + draggable window/transfer-ramp +
  clip-% + log-scale toggle; linear/log/equalize transform cycle; numeric
  color-range min/max in physical units; colorbar `left` side; scale-bar unit
  dropdown + auto-nice length + thickness/font spinners; auto-contrast percentile.

### Region C — Workshops
~120 controls across 9 workshops; ~34 absent (true gaps). Detail above. EELS-
advanced, FFT-mask, Particles, CTF, Stitch, Template are at parity or richer.
Concentrated gaps: EDS SI explorer (8), Atoms (5+), Grains trained mode (8+),
matched-phase rings + analysis-ROI (3), surface colormap/rotate (2).

### Region D — Stage / Measurement / Capture / Overlays / Compare / Filmstrip
~38 controls; ~22 present, ~9 different, ~11 absent/partial.
- **Absent/partial:** save-cropped-region capture, batch-crop marquee, scale-bar
  unit-override dropdown, on-stage known-length calibration capture (partly
  covered by CalibrationManager), per-annotation font, whole-body box/circle
  drag, compare flicker-rate + A/B picker + active-panel focus/Tab, stage
  right-click Save/Clear (reachable via MenuBar).
- **Port-only (richer):** fixed-size zoom, box-profile, polyline, marquee
  multi-select, subtract + N-way compare, minimap, gallery, stack stepper,
  interactive grain editor, ROI histogram, per-measure color + end-symbols +
  label drag, profile CSV.

---

## Suggested next step

If we act on this, the highest-value single item is the **EDS spectrum-image
explorer** (Tier 1 #1) — it's the one place a whole MATLAB window has no port
analog, and it unlocks interactive EDS map building. The **per-workshop CSV/PNG
export** theme (Tier 2 #4) is broad but mechanically simple and high-utility.
Everything else is incremental polish or a deliberate design divergence.
