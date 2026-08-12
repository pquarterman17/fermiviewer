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
- **Window width presets, on both spectroscopies.** Narrow / standard / wide
  now sit under the spectrum in Explore. On EDS they are multiples of the
  detector's own resolution at that line (1.0 / 1.5 / 2.0 × FWHM, capturing
  76 / 92 / 98 % of the peak), so "standard" means the same thing at carbon
  and at copper — a fixed ±85 eV does not. On EELS they are integration
  widths past the edge onset (30 / 50 / 100 eV), and the pre-edge background
  window re-places itself underneath.
- **Fit width** measures the peak's real width in the spectrum you are
  looking at and fits the window to it — useful when the detector is not
  performing to spec or the line is an unresolved pair. If there is no
  resolved peak to measure it says so and leaves your window alone.
- **Lock to line.** With an element picked, the EDS window stays centred on
  its line: dragging an edge widens it symmetrically instead of walking it
  off the peak, and the element stays selected. Fitting re-anchors to the
  line as measured here, so a later resize does not snap back to a tabulated
  energy this spectrum disagrees with. Untick it and the window moves freely,
  exactly as before.
- **The exported elemental figure now carries a scale bar.** Export figure
  bakes a round scale bar onto the combined overlay panel — or onto the first
  map when you export the montage-only view, which previously produced a
  figure with no bar at all. A cube with no spatial calibration gets no bar
  rather than one asserting a length nobody measured. The bar is worded by
  the same rule as the on-screen Stage bar, so a 0.2 nm length reads "2 Å" in
  both places.
- **EELS figures caption their maps.** The EELS export used to drop the
  net-counts / at% detail the on-screen legend was showing; both modalities
  now export exactly the legend you selected.
- **Drag the energy window on the spectrum.** Grab either edge of the
  highlighted window to resize it, or its middle to slide it — the
  integration readout follows live, and the element map refreshes once on
  release rather than per frame. With the plot focused, arrow keys nudge the
  window one channel (Shift: ten). Plain drag-zoom, shift-drag to draw a
  fresh window, and wheel zoom all behave exactly as before; the resize and
  grab cursors show which gesture you are about to get.
- **One window model over both spectroscopies.** EDS's single window with
  inferred flanking background and EELS's explicit pre-edge + signal pair
  now expose the same integration call and the same drag handles, so window
  editing never branches on modality. The EELS half is a client-side port of
  the backend's power-law background fit — the readout is the same quantity
  the elemental map integrates, with a σ that includes the fit's
  extrapolation uncertainty.

- **The EELS Maps workflow now exists end to end.** Open an EELS cube and
  the Maps tab identifies every core-loss edge the energy axis supports,
  lists them with net ± σ and a confidence band — one row per edge, so
  Si K and Si L2,3 stay distinct — and ticking rows produces the montage
  of per-edge maps plus the combined colour overlay with its legend and
  one-click figure export: the same deliverable the EDS side has, from the
  same shared components. Background windows auto-place just below each
  onset (the same pre-edge region the identifier fits) and stay fully
  adjustable.
- **EELS Explore is direct manipulation now.** The Explore tab shows both
  the signal window (blue) and the pre-edge background window (amber) on
  the spectrum itself — drag an edge to resize, the middle to slide, with
  wheel/drag zoom and the zoom bar, and a live net ± σ readout computed
  client-side from the same power-law model the backend fits. The four
  typed bounds remain as synced precision inputs, the Fit button's curves
  draw over the spectrum, and edge-onset markers carry each element's
  registry colour.
- **EELS elemental maps no longer require a quantification.** `POST
  /api/eels/maps` extracts N edge maps in one request — per-species signal
  and optional pre-edge background windows, per-row error reporting so a
  hand-picked edge never vanishes unexplained — and returns inline rasters
  a montage or overlay can consume directly, unlike `/eels/map`'s
  registered-image reply.
- **EELS edge auto-identification.** `POST /api/eels/auto-assign` scores
  every tabulated core-loss edge the cube's energy axis can support
  (pre-edge power-law fit, post-onset integration on the sum spectrum) and
  returns net, σ, significance and the same confidence bands the EDS
  identifier uses — the missing half of an EELS Maps workflow.

### Fixed
- **The synthetic test-data generator was not a valid quantification oracle.**
  `tools/make_synthetic_si.py` planted EDS line areas from an invented
  energy-dependent weighting unrelated to Cliff–Lorimer, so quantifying its
  own cubes returned carbon at 21 at% against a planted 9.4. Line and edge
  intensities now come from the application's own models. Two further bugs
  fell out: the cube silently wrapped `uint16` for bright heavy elements
  (tantalum's 6.2 at% came back as 0.7), and the EELS preset's energy axis
  started too close to its lowest edge for that edge's background fit window
  to fit on it (silicon's 46 at% came back as 3).
- `calc/eels.extract_map` no longer casts the whole SI cube to float64:
  only the signal- and background-window channels are promoted, so
  extracting one edge map from a multi-GB cube allocates a few channels'
  worth of memory rather than a second copy of the cube. Guarded by a
  tracemalloc allocation-delta test.
- `POST /api/eds/element-maps` builds its per-row `error` string itself
  rather than stringifying a caught exception, so the reason an element could
  not be mapped is the curated one and nothing incidental can ride along with
  it. `calc.eds_maps.element_window` is the non-raising form the route uses;
  `resolve_element_window` keeps raising for the callers that want that.

### Security
- **Every path that arrives over the local API now goes through one policy.**
  `io/user_paths.py` canonicalises a request-supplied path once — resolving
  `..`, symlinks and `~` — so the path that gets checked is the path that
  gets opened, instead of each caller re-resolving a string that could mean
  something different by the time it is used. Opening a file you picked in an
  OS dialog is unchanged; this is about where the decision is made.

  Two things are newly refused. A data path may no longer resolve inside
  FermiViewer's own config directory: saved workspaces, the calibration DB
  and the workspace index are reached through their own endpoints, and
  `/session/open` or `/project/save` must not be a second, unguarded way to
  read or overwrite them. And a workspace slug is now *structurally* confined
  to the workspaces directory, so a slug that ever got past `slugify` and the
  route's `[a-z0-9-]` check still could not address a file outside it.

  Refused paths are a 422 naming the field (and, for a list, the index),
  never a 500.

- **`FV_DATA_ROOTS` confines the API to specific trees.** Unset — the default
  — the API may open anything on the volume, which is what a desktop app that
  opens files you pick is for. Set it (os.pathsep-separated, like `PATH`) on
  a shared or unattended lab machine and every request-supplied path must
  resolve inside one of the listed roots. Containment is per path component,
  so a root of `/data` never claims `/database`.

## [0.1.26] - 2026-08-10

### Added
- **Your element list now survives switching cubes.** The Elemental Analysis
  Maps tab held its list in view state and rebuilt it from scratch on every
  image change, so ticking elements, adding one the identifier missed, or
  tuning a window were all lost the moment you looked at another cube and
  came back. The list is now kept per image, and re-running identification
  refreshes the measured numbers — net counts, σ, confidence — without
  reticking a row you had turned off.

  Picking elements is a multi-select on the periodic table rather than one at
  a time, and a hand-added element keeps its row even when nothing detected a
  peak for it, showing `added` instead of a confidence it has not earned.

  Extraction is also one request for the whole list instead of one per
  element, so a five-element montage is a single round trip and a single read
  of the cube. Ticking a sixth element still fetches only the sixth. An
  element that cannot be mapped now says why in the status bar rather than
  going quietly missing from the montage.

- **Element maps no longer require a quantification you did not ask for.**
  `POST /api/eds/element-maps` takes N element symbols and returns N maps
  directly. The multi-element extraction had existed all along, but the only
  route to it was `/eds/quantify`, so asking for five maps forced a
  Cliff–Lorimer/ZAF quantification and its whole result table. Each species
  may carry its own `e_lo`/`e_hi` window override, so a tuned window is
  integrated as given rather than recomputed from the element's line.

  A species that cannot be mapped — no known X-ray line, or a line outside
  the cube's energy axis — comes back as its own row with `map: null` and a
  plain-language reason, keeping request order, rather than being dropped
  the way `/eds/quantify` drops it. An entirely unmappable request is still
  a `200` with per-row reasons, so one rendering path covers both.

  This is the HTTP API only. The Elemental Analysis workspace still issues
  one request per element and does not call the batch route yet.

- **You can save a project and reload it.** The `.fvp` container
  (ADR 0002) existed as a library nothing called — no menu entry, no
  endpoint, no UI — so the state of a study could not actually be kept.
  The File menu now has four commands: **Save Project…** (light — embeds
  derived images and every measurement, references the source files, so an
  everyday save is megabytes), **Export Project Bundle…** (self-contained,
  needs no source folders, for moving a study to another machine),
  **Open Project…** and **Locate Data Folder…**. Behind them,
  `POST /api/project/{save,load,relocate}`.
  - Samples with their **parameter values and units**, and every
    measurement and region, are now schema-validated sections of the
    manifest instead of an opaque blob — a parameter value is scientific
    data, and the format can finally check it.
  - **Opening a project whose data has moved cannot destroy it.** Those
    images load as placeholders in the library that keep their name,
    sample membership, parameters and measurements, and saving writes
    their references straight back. The references are carried
    server-side, so this holds even if the client never mentions them.
  - **Locate folder…** re-links every image found under a folder you pick,
    and can be used again for samples that moved somewhere else. The
    folder is *appended* to the resolution order rather than replacing the
    project's recorded hint, so a remounted drive takes over again by
    itself. If a re-pointed file's size differs from the one recorded at
    save, that is reported rather than silently accepted.
  - **Existing workspaces keep working.** A v1 `.json` + `.npz` pair —
    including a named workspace saved by an older build — is upgraded on
    load with nothing lost, and the next save writes a `.fvp`.

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
  - **Gatan DigitalMicrograph** private tags 65003–65010, written by a direct
    DM TIFF export (scale, axis origin, and the intensity unit). Without them
    a DM export looks uncalibrated, because its baseline `XResolution` is a
    bare 72 dpi.
  - **ImageJ/Fiji** `unit=` plus X/YResolution — how a Gatan DM image exported
    through Fiji keeps its nm/px.
  - **Baseline TIFF** X/YResolution when ResolutionUnit is inch or cm, and
    only when the value is not a screen/print default (72 or 96 dpi) and the
    file carries no vendor tag of its own. All three FEI navcam images in the
    corpus stamp `XResolution = 96/1 INCH` — Windows desktop DPI, including on
    the one whose real field width FEI *also* states — so honouring it
    reported 264.583 µm/px for a navigation-camera image, only coincidentally
    near the true 263.974.

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

### Changed
- **v1 workspaces are read-only.** Nothing writes the two-file format any
  more: `Save Session…` / `Load Session…` and `POST /api/session/{save,load}`
  are replaced by the project commands above, and a named workspace is now a
  single `<slug>.fvp`. `io/session_file.py` keeps only its reader, so existing
  pairs still open.

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
- **TIA `.ser` diffraction patterns were labelled in metres.** A `.ser` states
  a `CalibrationDeltaX` and nothing about what it measures; for a TEM
  diffraction pattern that field is a reciprocal spacing, so the corpus's
  64×64 pattern reported 1.0e8 **metres** per pixel — a hundred thousand
  kilometres. Only the paired `.emi` distinguishes them, via the rule
  rosettasciio's TIA reader uses: a "Diffraction" projector mode means
  reciprocal, *except* under STEM, where the projector is in diffraction mode
  while the image formed is a real-space scan. There it needs corroboration —
  a camera recorded the frame (`CameraNamePath`), or the first navigation
  dimension is a genuine multi-position scan rather than a plain image stack
  (which TIA marks with a zero-length unit string). Affected images now report
  `1/m` and carry `metadata["spatial_domain"]`; the number is unchanged, since
  the SER delta already *was* the reciprocal spacing. Real-space images, and
  any `.ser` with no `.emi` to consult, are untouched.
- **Zeiss pixel size was half the truth on sub-1024 images.** SmartSEM writes
  two pixel sizes: `ap_image_pixel_size` describes the stored image, while
  `ap_pixel_size` (and the tag's unlabelled SI value) is referenced to a
  1024-wide display. They coincide only at 1024 px wide, and the 512-wide
  corpus file omits `ap_image_pixel_size` entirely — so falling back to
  `ap_pixel_size` reported 5.825 nm where the truth is 11.65 nm, halving every
  measurement on the image. The reader now applies the 1024/width correction,
  and prefers the unlabelled full-precision value when a labelled one
  corroborates it (12.3262 nm rather than the displayed 12.33).
- **A 180° FEI scan rotation was reported as 3.14°.** The FEI angle
  conversion guarded with "|v| > π cannot be radians, so it must already be
  degrees". That guard is safe for stage tilt, which never reaches 180°, but
  FEI applies the same radian convention to `ScanRotation`, where a half-turn
  is an ordinary setting — and at float32 precision π reads back as
  3.1415927410125732, a hair *above* `math.pi`, so the guard returned 3.14
  "degrees" for 180°, off by 57×. NIST's Quanta reference file sits at
  179.9947°, 0.005° from tripping it. FEI angles are now converted
  unconditionally; the magnitude heuristic survives only in
  `io.metadata.get_stage_tilt`, for metadata of unknown provenance.
- **A 1×N EELS acquisition opened as an image.** DM stores a spectrum
  extracted or cropped from a line scan as a 2-D dataset with one dimension
  of length 1. `dm.py`/`dm5.py` routed on rank alone, so `openNCEM_carbon.dm3`
  (1×2048, eV axis) became a `DataKind.IMAGE` whose reported "pixel size" was
  0.1 eV — not a pixel size at all, and out of reach of every EELS tool. Both
  readers now squeeze the degenerate dimension and return a SPECTRUM, matching
  rosettasciio (which reads the same file as an EELS signal with an "Energy
  loss" axis) and recovering an energy range of 240–445 eV, which brackets the
  carbon K edge at 284 eV. Deliberately conservative: the surviving axis must
  be calibrated in energy, so a 1×N image row in nm stays an image. The
  original shape is kept in `metadata["squeezed_from_shape"]`.

  This is a departure from the frozen MATLAB reference, which recorded the
  file as 2-D. The golden values are left untouched — they are the parity
  baseline — and the divergence is asserted explicitly instead, via
  `DIVERGES_FROM_MATLAB` in `tests/test_dm_golden.py`, alongside every pixel
  value that did *not* change. The same applies to `EDW087-1.tif`, whose
  golden entry records `pixelSize: null`: it now calibrates from its ImageJ
  tags, pinned in `test_simple_parsers.py`.
- **Dimensionless HDF5 axes counted as a calibration.** NCEM EMD writes `[]`
  for an index-only axis; `AxisCal.calibrated` only tests `units != ""`, so
  `rosettasciio_example_image.emd` reported a pixel size of 1.0 `[]` and would
  have drawn a scale bar measured in `[]`. `axiscal_from_offset_scale` now
  treats `[]`, `none`, `dimensionless`, `a.u.` and friends as uncalibrated.
- **MRC pixel size divided by the wrong header field.** MRC2014 defines the
  sampling as CELLA / MX, and is explicit that MX "need not be the same as NX
  … if the map doesn't cover exactly a single unit cell"; we divided by NX, so
  a cropped sub-volume came out wrong by exactly the crop factor. Now CELLA/MX
  per axis (rosettasciio uses `Xlen / MX` likewise), falling back to NX/NY for
  the writers that leave MX at 0, with CELLA_Y/MY calibrating the row axis
  independently. Every corpus file has MX == NX, so no pinned value moves.

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
