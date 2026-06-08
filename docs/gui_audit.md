# MATLAB GUI button-by-button audit

Every menu item, toolbar button, panel control, context-menu entry and
dialog in fermi-viewer (`FermiViewer.m` + `+fermiViewer/` @ `6b1e6b7`)
mapped against this port. Plan item #35, 2026-06-08.

**Status legend:** ✅ present · ⚠ present but different · ❌ absent

## Triage summary — the gaps (decide what to incorporate)

### ❌ Absent (10)

| # | Control (MATLAB) | What it does | Effort here |
|---|---|---|---|
| A1 | Image ▸ **Toggle Scale Bar** | hide/show the burned scale-bar overlay | trivial (View toggle like minimap) |
| A2 | Transform ▸ **Fixed Size Zoom** (zoom-to-dimensions) | user types W×H, click places a fixed box, Enter zooms | small |
| A3 | Analysis ▸ **Back Project** | FBP reconstruction (calc `back_project` IS ported — no endpoint/UI) | small (wire-up only) |
| A4 | Analysis/EDS ▸ **Composition Profile** | element-fraction line profile across an SI cube (calc ported — no endpoint/UI) | small (wire-up only) |
| A5 | EELS panel ▸ **ELNES** | fine-structure fingerprint comparison (calc `elnes` ported — no endpoint/UI) | small (wire-up only) |
| A6 | EELS panel ▸ **Navigate Pixel** (hover-navigate) | spectrum follows the cursor over the SI live | medium (region explorer covers click; live hover is new) |
| A7 | Diffraction panel ▸ **Click Spots** (manual mode) | hand-pick diffraction spots when auto-detect fails | small (Preview click pattern exists) |
| A8 | Diffraction panel ▸ **Simulate** | kinematic pattern simulation for a chosen phase/zone (calc ported — no UI) | small (wire-up only) |
| A9 | Measurement panel ▸ **End symbol** (circle/cross/square/none) | marker glyphs on measurement endpoints | small |
| A10 | File ▸ **Export Profile to DP** | profile in BosonPlotter interop format | small (CSV exists; needs the DP header format) |

### ⚠ Present but different (12)

| # | Control | MATLAB behaviour | Ours | Keep ours? |
|---|---|---|---|---|
| D1 | Edit ▸ Undo Filters | reverts destructive pixel edits | nothing is destructive — undo removes derived images | ours is strictly better |
| D2 | Image ▸ Crop / Invert | destructive, in place | derived image / display-only invert chip | ours safer; MATLAB-style "apply in place" could be added |
| D3 | File ▸ Batch Convert | converts loaded images to a chosen format in place | Batch Export ZIP | equivalent outcome |
| D4 | Edit ▸ Rename Selected (single) | rename one image | batch rename only (prefix_NNN) | add single-rename to filmstrip ctx menu? |
| D5 | View ▸ Live FFT | FFT refreshes as the view pans | live FFT of the current ROI | hover-live is A6-adjacent |
| D6 | Image ▸ Watershed (standalone) | watershed as its own menu op | watershed only as a particles option | expose standalone? |
| D7 | Journal/Publication Presets | per-journal annotation presets dialog | 4 fixed preset buttons in Export | enough? |
| D8 | Analysis ▸ Set/Clear Analysis ROI (rect+circle) | a persistent named ROI that scopes ALL analyses | ROI measures scope FFT/template/crop/histogram per-call | formalise a global analysis ROI? |
| D9 | EDS ▸ Add/Remove Channel | compose a composite from ANY loaded maps | channels auto-populate from quantify; Color Overlay window covers arbitrary images | probably covered |
| D10 | EDS ▸ Assign Elements | auto-assign element labels from peak energies | manual element symbols input | auto-assign would be nice |
| D11 | Stack strip ◀ ▶ MIP `1/1` | in-image frame stepper | Stack→Frames explode + filmstrip `[ ]` | in-place stepper still desirable? |
| D12 | Image right-click menu | zoom/copy/save/scale-bar actions | radial menu = capture tools only | add actions to radial or a ctx menu? |
| D13 | Preferences | colormap + auto-contrast percentiles + export DPI + inspector size | colormap, profile width, minimap, custom cmap | add percentiles/DPI/inspector-size? |

Everything not listed above is ✅ — full tables follow.

---

## Menu bar

### File
| Control | Status | Notes |
|---|---|---|
| Open Files… (⌘O) | ✅ | native picker + drag-drop + Open by Path |
| Batch Convert… | ⚠ D3 | Batch Export ZIP |
| Batch Rename… | ✅ | |
| Save / Load Session… | ✅ | |
| Save Image… | ✅ | Export… ⌘E |
| Copy to Clipboard | ✅ | |
| Save with Overlays… | ✅ | export includes measurements/bar/colorbar |
| Batch Export… | ✅ | |
| Journal Export… | ⚠ D7 | preset row in Export dialog |
| Create GIF… | ✅ | |
| Export Profile to DP… | ❌ A10 | profile CSV exists; DP header format missing |
| Export EDS Composite… | ✅ | Save PNG in composite |
| Preferences… | ⚠ D13 | fewer settings |
| Close (⌘W) | ✅ | |

### Edit
| Control | Status | Notes |
|---|---|---|
| Undo Filters (⌘Z) | ⚠ D1 | full undo/redo service |
| Reset Contrast | ✅ | Adjust Reset |
| Reset Zoom | ✅ | Fit / 0 |
| Clear Overlays | ✅ | all / by type, undoable |
| Rename Selected… | ⚠ D4 | batch only |
| Remove Selected | ✅ | ⌘W + filmstrip ctx |
| Edit Metadata… | ✅ | |
| Set Pixel Size… | ✅ | Calibrate Pixel Size |
| Calibration Database… | ✅ | Manage Calibrations |

### View
| Control | Status | Notes |
|---|---|---|
| Auto Contrast | ✅ | A |
| Reset Contrast | ✅ | |
| Show FFT | ✅ | |
| Live FFT (toggle) | ⚠ D5 | live ROI FFT |
| Toggle Colorbar | ✅ | |
| Toggle Histogram Log | ✅ | |
| Toggle Pixel Inspector | ✅ | window |
| Toggle Minimap | ✅ | |
| Toggle Theme | ✅ | ⌘⇧L |
| Compare Toggle | ✅ | split/flicker/subtract + overlay |
| Flicker Compare | ✅ | |
| Thumbnail Grid | ✅ | gallery (V) |
| Stack MIP | ✅ | |

### Image
| Control | Status | Notes |
|---|---|---|
| Crop… | ⚠ D2 | crop-to-ROI, derived |
| Rotate / Flip… | ✅ | menu + toolbar |
| Invert | ⚠ D2 | display chip |
| Bin Image… | ✅ | |
| Image Math… | ✅ | |
| Stitch Images… | ✅ | menu + Structure workshop |
| Montage… | ✅ | stitch grid / figure panel |
| Custom Colormap… | ✅ | prefs hex stops |
| Gaussian / Median / CLAHE / Sharpen / Butterworth | ✅ | param dialogs |
| Plane Level | ✅ | |
| Morphology… | ✅ | |
| Multi-Otsu | ✅ | |
| Watershed | ⚠ D6 | particles option only |
| Calibrate Scale Bar… | ✅ | auto-detect + from-measurement |
| Toggle Scale Bar | ❌ A1 | always shown when calibrated |
| Place Arrow / Circle / Line / Rect | ✅ | line ≈ arrow |
| Surface Plot… | ✅ | window |
| Figure Builder… | ✅ | |
| Publication Presets… | ⚠ D7 | |

### Analysis
| Control | Status | Notes |
|---|---|---|
| Line Profile | ✅ | + width averaging |
| Box Profile | ✅ | = width-averaged profile |
| Radial Profile | ✅ | |
| Distance / Angle / Polyline | ✅ | tilt correction = plan #34 |
| Az. Integrate | ✅ | |
| Particle Count… | ✅ | + live threshold preview |
| Grain ID… | ✅ | workshop mode w/ progress |
| Atom Columns… | ✅ | workshop mode |
| Defect Count… | ✅ | |
| Roughness | ✅ | |
| Interface Fit… | ✅ | fits the dock profile |
| CTF Estimate | ✅ | workshop w/ fit plot |
| GPA (Strain) | ✅ | menu + 2-click picks |
| Composition Profile | ❌ A4 | calc ported, unexposed |
| Template Match… | ✅ | ROI-as-template |
| Noise Estimate | ✅ | + filter recommendation |
| Batch Measurement… | ✅ | batch profile |
| Measurement Stats | ✅ | |
| ROI Manager… | ✅ | measurements list + log/CSV |
| Set Rect / Circular ROI · Clear | ⚠ D8 | per-call ROI scoping |
| Enter / Exit EDS Mode | ✅ | workshop / tab |
| EDS Spectrum Image… | ✅ | region explorer |
| Quantify EDS (CL / ZAF) | ✅ | |
| EELS Action… / Advanced… | ✅ | |
| Quantify EELS (at%)… | ✅ | + composition maps |
| EELS Navigate (toggle) | ⚠ A6 | region explorer (click), no hover |
| Diffraction Action… | ✅ | |
| Back Project | ❌ A3 | calc ported, unexposed |
| Virtual Dark Field | ✅ | |
| Stack Navigation… | ⚠ D11 | explode + filmstrip |
| Align Stack… | ✅ | |
| Macro Record (toggle) | ✅ | |

### Help
| Control | Status |
|---|---|
| Keyboard Shortcuts | ✅ |
| Report a Bug… | ✅ |

## Toolbar
| Control | Status | Notes |
|---|---|---|
| Open (accent) · Recent dropdown | ✅ | recents in File menu |
| Remove | ✅ | |
| Fit · 1:1 · Zoom Out | ✅ | toolbar + zoom chip |
| Compare · Grid · EDS | ✅ | |
| Filename label | ✅ | title bar |
| Prefs · Theme · ? | ✅ | |

## Transform panel
| Control | Status | Notes |
|---|---|---|
| Rot CW/CCW · Flip H/V | ✅ | |
| Zoom Box · Reset Zoom | ✅ | |
| Crop · Save Crop · Batch Crop | ✅/⚠ | save-crop = crop→export |
| Bin Image · Set Pixel Size | ✅ | |
| Fixed Size Zoom | ❌ A2 | |

## Filter panel
Gaussian · Median · CLAHE · Sharpen · Morph Op · Butterworth ·
FFT Mask · Threshold (live) — **all ✅**.

## Measurement panel
| Control | Status | Notes |
|---|---|---|
| Line/Box Profile · Distance · Angle | ✅ | |
| Export CSV · Export Table · Clear All · Remove | ✅ | |
| Diff Rings · d-Spacing · ROI Manager · Calibrate Bar | ✅ | |
| Draw ROI · Invert · Meas Stats · Batch Meas | ✅ | |
| Profile → BosonPlotter | ❌ A10 | |
| Label font · Line color | ✅ | overlay style + per-item |
| End symbol (circle/cross/square) | ❌ A9 | |

## Contrast panel
Low · High · Auto · Reset · Gamma — **all ✅** (+ log/equalize, invert,
transform chips beyond MATLAB).

## Annotations panel
Place Text/Arrow/Line/Rect/Circle · Clear All · Undo Last — **all ✅**.

## EELS panel
| Control | Status |
|---|---|
| Enter EELS · Fit Background · Show Edges | ✅ |
| Extract Map · Thickness Map · Align ZLP | ✅ |
| Deconvolve (Fourier-log) · Kramers-Kronig · SVD | ✅ |
| ELNES | ❌ A5 |
| Navigate Pixel | ⚠ A6 |

## EDS panel
| Control | Status |
|---|---|
| Enter EDS · Color/Visible/Intensity per channel | ✅ |
| Export RGB · Quantify CL/ZAF | ✅ |
| Add/Remove Channel (arbitrary images) | ⚠ D9 |
| Assign Elements (auto from energy) | ⚠ D10 |
| Composition Profile · ROI Composition | ❌ A4 / ⚠ |

## Diffraction panel
| Control | Status |
|---|---|
| Auto-detect Spots · Clear · spot count | ✅ |
| Camera Length · Voltage · Match Phases | ✅ |
| Overlay Rings · Zone Axis readout · VDF | ✅ |
| Click Spots (manual) | ❌ A7 |
| Simulate | ❌ A8 |
| ROI Rect/Circle/Clear | ⚠ D8 |

## Stack strip (single-view panel)
◀ ▶ frame stepper · MIP · `n / N` label — ⚠ D11 (explode model).

## Status bar
dims · bit depth · pixel size · count · zoom · mouse readout · mode ·
load status — **all ✅** (+ LOCAL/connected beyond MATLAB).

## Context menus
| Menu | Status | Notes |
|---|---|---|
| Image right-click (zoom/fit/1:1/copy/save/scale-bar/pan/clear) | ⚠ D12 | ours = radial capture menu |
| List right-click (open/rename/remove/auto/copy/save) | ⚠ D4 | ours: show/compare/close |
| Measurement right-click (color/font/edit/delete) | ✅ | |
| Annotation right-click | ✅ | |

## Preferences dialog
| Setting | Status |
|---|---|
| Default Colormap | ✅ |
| Auto-Contrast Low/High % | ❌ D13 |
| Export DPI | ❌ D13 |
| Pixel Inspector Size | ❌ D13 |

## Capture interaction modes (captureModeTable)
All click/drag capture flows (distance, angle, polyline, profile, box,
ROI rect/ellipse, zoom box, text/arrow/line/rect/circle placement,
crop, calibrate-bar drag) — **all ✅**; "click to place fixed-size
box" (Fixed Size Zoom) is the one absent flow (A2).
