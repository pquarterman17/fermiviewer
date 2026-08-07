# Changelog

All notable changes to FermiViewer are documented here, newest first.

This file is the **source of the GitHub Release notes**. The `release`
workflow (`.github/workflows/release.yml`) extracts the section whose header
matches the pushed `vX.Y.Z` tag and sets it as that release's body. When you
cut a release, add a `## [X.Y.Z] - YYYY-MM-DD` section here **in the same
`chore(release): vX.Y.Z` commit** that bumps the seven version sources. If no
section matches a tag, the workflow falls back to GitHub's auto-generated
commit list.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to adhere to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **TIFF files now carry their instrument calibration.** A `.tif` was read as
  a bare raster: pixel size, stage tilt and acquisition settings were dropped
  even when the file stated them, so a Thermo Fisher (FEI) dual-beam image
  opened uncalibrated and measurements came out in pixels. `io/tiff_meta.py`
  now reads, in priority order:
  - **Thermo Fisher / FEI** tags 34682 (`FEI_HELIOS` — Helios/Scios/Quanta/
    Apreo) and 34680 (`FEI_SFEG`): `[Scan] PixelWidth/PixelHeight` in metres,
    falling back to `[EScan]`/`[IScan]` for single-column exports and then to
    a field width (`HorFieldsize`, or a column block's `HFW`/`VFW`) divided by
    `[Image] ResolutionX/Y`. Stage tilt comes from `[Stage] StageT` (radians —
    a 52° FIB lift-out reads 0.9076 in the file), and the active column is
    taken from `[Beam] Beam`. Beam energy, working distance, scan rotation,
    system type and databar height are recorded too.
  - **Zeiss SmartSEM** tag 34118 (`CZ_SEM`): `ap_image_pixel_size` with its
    unit, and `ap_stage_at_t` in degrees.
  - **ImageJ/Fiji** `unit=` plus X/YResolution — how a Gatan DM image exported
    through Fiji keeps its nm/px.
  - **Baseline TIFF** X/YResolution when ResolutionUnit is inch or cm.

  Axes come back in nm, or µm above 1 µm/px so an SEM overview does not read
  "2000 nm". A ResolutionUnit of NONE is deliberately *not* honoured — that
  combination means "aspect ratio only", and treating a 72-dpi formatting
  default as a calibration would be worse than reporting none.

  None of these vendor layouts is a published standard, so the unit
  conventions were cross-checked against independent readers: Bio-Formats,
  NIST's NexusLIMS and rosettasciio all read `[Scan] PixelWidth` as metres;
  NexusLIMS converts FEI's `ScanRotation` with `degrees()` and Thermo
  Fisher's AutoScript API uses the same metres/radians convention for stage
  position; the Zeiss labels and units match published LEO1550/Merlin tag
  dumps; and ImageJ's own `TiffDecoder` computes `1/XResolution` and treats
  ResolutionUnit 1 as no unit at all.

### Fixed
- **Stage tilt was never reported, for any format.** `get_stage_tilt` searched
  for bare keys (`StageT`, `Tilt`), but every parser stores the angle behind a
  dotted path or a differently-spelled key, so the lookup returned NaN for
  every one of the 171 loadable files in the instrument corpus (16 of which
  do record a tilt) and the viewer's tilt hint never seeded.
  Each parser now normalizes the angle to `metadata["stage_tilt_deg"]` using
  its own format's convention, and that key outranks the guesswork:
  - Gatan DM3/DM4/DM5 — `Microscope Info.Stage Position.Stage Alpha`, degrees.
  - Velox EMD (Thermo Fisher) — `Stage.AlphaTilt`, radians. `Stage` was also
    missing from the Velox metadata branches that get flattened, so the tag
    was not even harvested.
  - TIA `.ser` — the `.emi` sibling's `Stage A` field, degrees (a lone `.ser`
    carries no stage state at all).
  - Bruker `.bcf` — `io/bcf.py` writes `stage_tilt_deg` but the lookup table
    listed only the MATLAB-era `stageTilt_deg`, so the two spellings never met.
  - TIFF — as above.

  The old magnitude heuristic (|v| < π ⇒ radians) survives only as a fallback
  for metadata of unknown provenance; it silently turns a genuine 2° tilt into
  114°, so no parser relies on it now.

## [0.1.25] - 2026-08-06

### Fixed
- **Sibling-instance collision on port 8000.** fermiviewer and the sibling
  `quantized` app both default to `127.0.0.1:8000` and previously answered
  `/api/health` with a byte-identical payload, so each app's shell could
  adopt the *other* app's running server as "our own instance" and render
  the wrong UI. Health now carries an `app: fermiviewer` field and both the
  Tauri shell's health probe and `netprobe.py` require it before treating a
  server as reusable; a server too old to send the field is treated as
  foreign and fails safe.
- **Ephemeral-port fallback.** Completes the identity fix above: when port
  8000 is held by a foreign server (typically the sibling `quantized`), the
  shell now picks a free ephemeral port, passes it to the sidecar via the
  (newly-added) `--port` flag, and navigates the window there instead of
  timing out after 60 s waiting for a port it could never own. A mismatched-
  version sibling (no `app` field) now opens as a working second instance
  instead of an error dialog.
- Installed-app sidecar lookup hardcoded the Windows `fv-server.exe` name
  and `.venv/Scripts/python.exe` dev path; both now branch by target OS, so
  macOS and Linux installed builds can find their own backend.
- `ParamDialog` reset its form values in a `useEffect`, which could lose a
  fast field edit that landed between the effect's reset and the next
  paint. Values now reset synchronously during render, keyed on request
  identity; `coerceParams` also now falls back to a field's default instead
  of writing `undefined` for a key missing from `values`.

## [0.1.24] - 2026-08-02

### Changed
- **CI/toolchain: Node 22.** Node 20 is EOL; `.nvmrc` (repo root) is now the
  single source of truth for the Node version and every workflow reads it
  via `node-version-file` instead of a hardcoded version — a repo-integrity
  test now guards against that drifting apart again.
- Dev dependencies: `jsdom` 30 and `@testing-library/jest-dom` 7.

### Fixed
- The generated API reference (`docs/api-reference.md`) no longer embeds
  the release version. Embedding it meant every `chore(release)` version
  bump staled the file against its own drift-guard test.

### Docs
- New wiki page **[4D-STEM](https://github.com/pquarterman17/fermiviewer/wiki/4D-STEM)** —
  a practical walkthrough of opening `.mib`/HyperSpy-4D datasets, probing,
  BF/ABF/ADF/custom virtual detectors, and current limits.
- Wiki: **Supported Formats**, **Analysis Workshops**, and **Home** refreshed
  for the merged Elemental Analysis workspace, 4D-STEM support, and the
  JEOL/EDAX/Lispix/DM5 parsers that had shipped undocumented.
- README: format and feature enumeration synced to include 4D-STEM and the
  newer parsers; corrected the Node version requirement (22+, not 20+).

## [0.1.23] - 2026-08-02

### Added
- **4D-STEM support (Phase 1).** Open pixelated-detector datasets — Quantum
  Detectors Merlin `.mib` (a from-scratch RAW reader whose quad-chip
  descramble is validated byte-exact against decoded reference data) and 4D
  HyperSpy `.hspy`/`.h5`/`.hdf5` cubes — through the normal Open flow. The
  data model is lazy and memory-safe: the full cube is never loaded; a
  navigation image and mean diffraction pattern are streamed at open. The new
  **4D-STEM Viewer** (Analysis menu) links a real-space nav minimap to the
  diffraction pattern at the probed position (click/drag to probe), with
  BF / ABF / ADF / custom virtual-detector apertures — auto-centred on the
  pattern's intensity centroid, previewed truthfully — and **Compute map**
  produces the virtual-detector image as an ordinary image with the scan's
  calibration, so measuring and exporting just work. Datasets can be closed
  to release their file handles.
- **Batch recipes now run spectral analysis**, not just filters: EELS
  background-subtracted maps and core-loss quantification, EDS element maps
  and Cliff-Lorimer/ZAF quantification, and radial intensity profiles are
  all available as recipe steps (and to the Python API).
- **Folder watch.** Pick a saved recipe and a directory in the Batch dialog;
  new files dropped there are processed automatically as they land. An
  active watch keeps the desktop app alive.
- **Recorded macros are now batch recipes.** Recording captures analysis
  operations (not raw requests), replays through the batch engine with
  provenance, and converts to/from saved presets; steps with no batch
  equivalent still record and replay, with the dialog reporting how many.
- **Headless batch runs:** `fv --script recipe.json inputs... --out DIR`
  runs a saved recipe (the exact `.fvbatch.json` the GUI exports) with no
  server or browser — per input it writes the derived image (TIFF), every
  value result (CSV + JSON) and a provenance log, with per-input failure
  isolation and meaningful exit codes.
- **Structured table export**: `POST /api/export/table` returns quant
  tables as CSV/JSON matching the client exporter's conventions;
  `Result.to_csv()` / `.to_json()` on the Python API.
- **Scripting on-ramp:** worked examples in `examples/`, a README
  *Scripting* section, and a generated API reference
  (`docs/api-reference.md`) covering the whole public surface and every
  batch operation's parameters.
- **Custom Metadata, made legible.** The card now says exactly where values
  go — naming the real sidecar file (e.g. `scan1.dm4.fvmeta.yaml`) — and
  images with no file on disk (uploads, derived results) get a **Download
  metadata file** button producing the identical sidecar to place next to
  the original. An in-card *How this works* explains the config file, the
  filename auto-fill pattern with a worked example, and the precedence
  rule; the no-fields-yet state includes a copy-pasteable starter.
- **File ▸ Recent Images** submenu — recents moved out of the top level of
  the File menu, and all eight remembered files are listed (the flat list
  capped at five).
- **Synthetic spectrum-image generator** (`tools/make_synthetic_si.py`). Writes
  real `.hspy` cubes that open through the normal file path, with a
  `.truth.json` sidecar recording the composition and geometry that produced
  them. Four presets: `eds-layers` (200 kV cross-section), `eds-overlap`
  (10 kV, where Ta M sits 0.030 keV from Si K), `eds-particles`, and
  `eels-layers` (Si L23 / C K / Ti L23 / O K over a power-law background).
  Peak and edge positions come from the app's own `line_energy` /
  `EELS_EDGES` tables, so synthetic peaks cannot drift from the windows the
  GUI snaps to.
- `.hspy` files now expose `metadata/Sample/elements` and
  `metadata/General/title`, so a HyperSpy cube's declared elements reach the
  EDS element picker.
- **EDS spectrum zoom.** Drag on the spectrum to zoom the energy axis, wheel to
  zoom about the cursor, double-click to reset. A zoom bar under the plot adds
  numeric view bounds, pan/zoom buttons and a Reset, and "Zoom to window"
  frames the current energy window.
- **Per-element colours.** Pick an element and set its colour once — from the
  element picker or a composite channel row — and it applies to composite
  channels, the single-element map tint, the spectrum's characteristic-line
  markers, the model-fit peak curves and the composition profile. Colours
  persist across sessions; each element also has a distinct default.
- **Spectrum integration.** A live readout under the spectrum reports the
  current window's gross, background, net ± 1σ and share of the spectrum,
  under the same background model the element map uses. Windows can be pinned
  to a region table (click to restore and frame, with CSV export).

### Fixed
- **A single NaN detector pixel poisoned every virtual-detector map**, even
  sitting far outside the aperture; masked-out pixels are now ignored.
- **HDF5 files holding several signals could hide their 4D data** — if a
  smaller 2D/3D signal sorted first the whole file went to the 2D loader.
- 4D dataset lifecycle on Windows: closing now really releases file
  handles (files are deletable), and use-after-close raises a clear error
  instead of an opaque h5py one.
- Non-finite energy calibration no longer produces JSON the frontend
  cannot parse (the whole response used to fail, not just one field).
- Long-running folder watches no longer grow memory for files that vanish
  before stabilising; watch status now counts errors instead of showing
  only the last one.
- The CLI runner exits cleanly (code 2) on recipes that are not valid
  UTF-8/JSON instead of tracebacking.
- Aperture inputs are validated client-side — an invalid manual centre
  used to serialise to *null* and silently become "auto-center".
- JSON table export silently dropped all but the last of duplicate column
  names; export filenames with non-Latin-1 characters no longer 500.
- **Modal dialogs always stack above floating tool windows** (the Batch and
  Export dialogs could open partly hidden behind the 4D viewer); the
  z-layer ladder is now defined in one tested module.
- The 4D nav minimap contains itself to the panel (a tall scan used to
  push the workshop past the window height, hiding the pattern panel after
  a compute), and the auto-centre aperture preview shows the centre that
  will actually be used.
- **The colour-overlay tool lost its palette.** Removing the stored colour from
  a composite channel left it resolving colours from the element registry keyed
  on truncated image names; TypeScript allowed the now-extraneous `color`
  through `.map()` so nothing failed loudly.
- **The EDS energy-window drag never worked inside the plot.** Its handlers
  were bound to the `<canvas>`, but uPlot's `.u-over` sits above the canvas and
  absorbs every pointer event in the plot area, so the drag only fired in the
  axis gutters — where its coordinate math also mixed CSS pixels with uPlot's
  device-pixel `bbox`.
- Moving the EDS energy window or recolouring an element no longer destroys and
  rebuilds the spectrum plot on every frame; the overlay redraws in place.

### Changed
- **EDS and EELS are one workspace: Elemental Analysis.** They were separate
  windows, which is how EDS accumulated zoom, per-element colours, integration
  and the Maps workflow while EELS got none of them. Maps and Explore are now
  the same components for both; only Quantify and Model fit swap their
  internals. The modality comes from the cube (metadata → filename → format →
  energy range) and is shown, with its reason, in a badge that can re-route an
  ambiguous dataset.
- Frontend code split three ways so "can this be shared?" has an answer:
  `lib/spectrum/` + `components/spectrum/` (any spectrum), `lib/elemental/` +
  `components/elemental/` (element-centric, modality-agnostic), and
  `lib/eds/` (genuinely EDS physics). Most of what was in `lib/eds/` was never
  EDS-specific.
- The Inspector's EDS and EELS tabs became one **Elemental** tab. EELS mounted
  a whole second workshop inline while EDS only launched one — the asymmetry
  the merge removes.
- The EDS Composite tab is gone; the Maps overlay supersedes it. The generic
  compositor survives as `ChannelComposite` for the colour-overlay tool.
- **The EDS energy window is now set with shift+drag**, freeing a plain drag
  for zoom.
- Element-map "Add to library" can carry the element's colour onto the derived
  image, published through the shared `custom` colormap slot.

## [0.1.22] - 2026-07-26

A large analysis-workflow release: four new workshop surfaces, a rebuilt EDS
workspace, smarter routing of spectrum-image cubes, saved batch recipes, and
consistent right-click actions on every analytical plot.

### Added
- **Noise diagnostics workspace.** Classifies the dominant noise regime
  (Poisson / Gaussian / mixed) from variance-vs-mean evidence over a region,
  with the fitted model, R², and CSV/JSON export.
- **Interface width fit workspace.** Fits an erf profile across a chosen
  interface and reports width with uncertainty.
- **Visual defect analysis workspace.** Finds and catalogues defect candidates
  with per-defect statistics.
- **Roughness workspace.** Areal roughness metrics (Ra, Rq, Rz, Rsk, Rku, …)
  with leveling options and a material-ratio bearing curve.
- **Server-backed batch analysis recipes.** Ordered multi-step recipes now run
  on the backend as bounded jobs with per-step progress and JSON-safe results.
- **Saved batch recipe presets.** Name and save recipes on this device, reload
  them in one click, and share them as portable `.fvbatch.json` files; imports
  are validated against the live operation schema.
- **EELS/EDS routing for spectrum-image cubes.** Opening a cube now classifies
  it (metadata → filename → format → calibrated energy range) and lands in the
  right workshop; ambiguous cubes ask once, remember the answer, and can be
  re-routed from a new "Spectrum workflow" card in the inspector. Previously
  every spectral cube opened as EDS.
- **EELS composition maps run as jobs** with progress and cancellation instead
  of blocking the interface.
- **Context menus on every analytical plot.** Right-click (or Shift+F10) any
  spectrum, fit, depth-profile, PSD, CTF, noise, bearing-curve, or line-profile
  chart for Reset view, Copy plot, Save PNG, and CSV export where available —
  with full keyboard navigation.
- **Multi-map interface comparison** in the cross-section layer workshop:
  compare an interface across per-element maps side by side.
- **Reset all corrections.** A new "↺ Opened" button in the Adjust card
  returns the display (window, gamma, colormap, invert) to the image as it
  was opened — undoable from the History card.
- **A face for the app.** FermiViewer now has a black-cat icon and repository
  logo, drawn procedurally at build time.

### Changed
- **The EDS workspace was rebuilt around one resizable analysis surface**: a
  first-class spectrum explorer with peak labels, a usable element-map viewer,
  and clearer API error messages.
- **Analysis navigation reorganized.** The Analysis and Window menus group
  workshops by topic, and the spectroscopy workspaces share consistent
  navigation.

### Fixed
- **EDS element maps could render blank for eV-calibrated cubes** (DM/SER
  spectrum images): energy windows are keV throughout, but the axis was
  compared in its native unit. All EDS routes now convert at the boundary;
  recalibration converts back when writing.
- **Element-map requests failed outright** after a NaN background width was
  serialized as `null`; the API also returns readable validation errors now.
- **Lattice calibration survives** structure-workshop reloads.
- **Watershed splitting for touching particles** is available again from the
  Particles mode.
- **Spectrum energy units and axis gutters normalized** across the EDS plots.
- **Tooltips**: chips near the window edge no longer clip off screen; screen
  readers no longer announce control names twice; the four transform buttons
  gained explanatory details; and a disabled Compare button now explains why
  it is unavailable.

### Performance
- **Large-cube interactivity**: element-map and spectrum requests are bounded
  and debounced, and the remaining full-cube float64 materializations were
  eliminated — multi-GB spectrum images stay responsive while exploring.

## [0.1.21] - 2026-07-23

Follow-up to the BCF/EDS element-navigation work: build a colour composite
straight from the periodic-table picker.

### Added
- **"+ Composite" in the Spectrum-Image Explorer.** After picking an element
  in the periodic table, one click adds that element's window map to the
  composite overlay with an auto-assigned colour — no full Cliff-Lorimer/ZAF
  quantification pass required. Re-adding an element re-points its channel at
  the fresh map while keeping the colour, intensity, visibility, and ramp you
  set. This closes the last deferred item from the element-navigation series:
  element colour no longer has to be routed through Quantify.

## [0.1.20] - 2026-07-23

Part 4 of the BCF/EDS element-navigation work: element maps that keep up with
big cubes.

### Performance
- **~14× faster element maps on large cubes.** Switching an element used to
  convert the entire spectrum-image cube to float64 before summing a narrow
  energy window — an ~8 GB allocation per click on a 4 GB BCF cube. It now sums
  only the channels the window needs; a typical line touches ~0.2% of the data.
  Results are numerically unchanged.

## [0.1.19] - 2026-07-23

Part 3 of the BCF/EDS element-navigation work: pick elements by name.

### Added
- **Periodic-table element picker.** The EDS explorer's element selector is now
  a periodic table by default — any element (Si, Fe, Al, …) is one click away
  instead of being limited to the acquisition-header dropdown, with elements
  present in the sample highlighted. A toggle switches to the compact dropdown,
  and the preference is remembered across sessions.

## [0.1.18] - 2026-07-23

Part 2 of the BCF/EDS element-navigation work: read peaks off the spectrum by
name.

### Added
- **Characteristic X-ray peak labels on the spectrum.** Peaks are marked with
  the element line they correspond to — auto-detected peaks (matched to K/L/M
  lines) as dashed grey markers, plus the selected element's lines in solid
  blue. A "Label peaks" toggle (on by default) hides them when the spectrum
  gets busy. New `GET /eds/lines` returns the characteristic lines within an
  energy window.

## [0.1.17] - 2026-07-23

Part 1 of the BCF/EDS element-navigation work: making spectrum-image cubes
easy to explore instead of scrolling thousands of raw energy channels.

### Added
- **EDS cubes open into the Spectrum-Image Explorer.** Loading a Bruker BCF
  (or any EDS spectrum-image) now opens the Explorer automatically — landing
  you on the sum spectrum and element maps instead of a ~4096-channel frame
  stepper. It opens once per cube; the Stage's raw channel stepper stays
  available for per-channel views.

## [0.1.16] - 2026-07-23

A large usability release, pairing a ground-up keyboard-accessibility and
UI-polish wave with a new guided cross-section layer & grain analysis
workflow (PRs #55–#84).

### Added
- **Guided cross-section workflow** — a step-by-step guide walks you through
  cross-section layer analysis (orient → identify layers → measure grains)
  instead of hunting for the right controls. (#78–#84)
- **Per-layer grain measurement** — grain statistics can be scoped to an
  individual film layer, so a multilayer stack reports grains layer-by-layer.
- **Region-of-interest scoping** — layers and grains can be restricted to a
  drawn ROI, keeping analysis off substrate, glue lines, and foil edges.
- **Spatial confidence preview for trained grains** — the trained-grain
  classifier shows a per-pixel confidence map before you commit a
  segmentation. (#84)
- **Questionable-detection flagging** — low-confidence detections are flagged
  for review rather than trusted silently.
- **Live spectrum explorer** — probe EELS/EDS spectra live by scrubbing the
  stage, with the probe debounced and cancellable. (#70, #73)
- **Live Appearance preview** — colormap / window–level changes preview on the
  image in real time, and the theme toggle stays in sync with the preview.
  (#68, #72)
- **Empty-stage welcome card** and graceful compact-window handling.
- **Full keyboard operation** across desktop menus, popup menus, the library,
  and the command palette, with proper ARIA semantics. (#55, #57, #61)
- **Standardized modal dialogs** and **descriptive workflow tooltips**.
  (#62, #69)
- **SVG toolbar icons** replacing the previous glyph font.
- Documented keyboard & accessibility operation in the README. (#66)

### Changed
- Workshop styles are split out and workshops/modal overlays are lazy-loaded,
  trimming the initial bundle so the app opens faster. (#59, #64)

### Fixed
- Tooltips no longer strand on screen (a click-focus path re-armed the dwell
  timer on self-removing buttons); also fixed label overflow and a dead probe
  CSS selector. (#77)
- The grains panel now refreshes after a stage edit (previously it could show
  stale results from the prior stage).
- The grain workflow preserves source lineage and is source-aware. (#78)
- EELS probe fixes: keep the stage probe live and the region picker working,
  consume the probe-region token instead of leaving it set, and queue
  overlapping parameter dialogs instead of clobbering them. (#74–#76)
- Workshops and large result tables scale correctly; disabled-menu hover
  styling and assorted review-flagged a11y/harness defects resolved.
  (#65, #67, #71)

**Full changelog:** https://github.com/pquarterman17/fermiviewer/compare/v0.1.15...v0.1.16

## [0.1.15] and earlier

Releases up to and including v0.1.15 predate this changelog; see the
[GitHub Releases page](https://github.com/pquarterman17/fermiviewer/releases)
for their notes.
