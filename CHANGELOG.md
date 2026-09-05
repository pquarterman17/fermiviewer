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

### Fixed
- **The single-scale error named in 0.4.0's *Known limitations* is closed.**
  Every site that list called out now measures with both pixel extents
  (`DataStruct.pixel_spacing`), and square pixels are bit-for-bit unchanged
  at each one:
  - `calc/profiles.py` — the general intensity line profile behind
    `/measure/profile` and the `line_profile` op, including polylines. The
    30-column, 40-row line on 3-wide, 4-tall pixels now reports 183.6, not
    150.0. Sampling stays in pixels; only the distance axis is calibrated.
  - `calc/profile_stats.py::measure_distance` — the tilt-corrected distance's
    calibrated lengths (`/measure/distance-tilted`, `tilted_distance` op).
    The pixel distances are the MATLAB port, untouched.
  - `calc/radial.py` — radial and azimuthal profiles bin by PHYSICAL radius
    when both extents are known, and report calibrated radii. On 2:1 pixels
    a physically round ring spans pixel radii 15 to 30, so scaling pixel
    bins afterwards smeared it over half the profile; the sector angles and
    the inscribed rMax of an azimuthal integration are physical too.
  - `calc/layers.py` and `calc/trace_roughness.py` — thickness,
    `thickness_std`, `sigma_erf` and `sigma_w` scale by the extent along the
    growth axis the analysis chose (a 25-row layer on 4 nm rows is 100 nm,
    not 25), while the trace metrology's correlation length and PSD
    wavelengths scale by the extent along the interface. `LayerResult` and
    the `/analyze/layers` payload report the depth extent as `pixel_size`
    and carry the other as `lateral_size`; `analyze_trace` takes
    `lateral_size=`. The multi-map comparison takes per-map `spacings`.
  - `calc/grain_layers.py` — `lateral_width` and `depth_height` take their
    own extents, the aspect ratio and shape angle are measured on the
    physical grid, and the default pixel area is the product of the two
    extents rather than a length squared.
  - `calc/grains.py` and `calc/particles.py` were audited rather than
    changed: their `pixel_size ** 2` is a documented fallback for a caller
    with only a length, and every route and op passes `pixel_area` and
    `spacing`.

- **Reciprocal space is built from both pixel extents.** `calc/ctf.py`,
  `calc/lattice.py` and `calc/diffraction.py::index_spots` (with
  `index_spots_roi`) derived the frequency step along rows from the COLUMN
  pixel size, so on anisotropic pixels a physically round Thon ring was
  read as an ellipse and smeared out of the radial average, a physically
  square 4 Å lattice measured 4 by 2 Å, and a (200) spot along rows
  indexed as (400). Each now takes a keyword-only `spacing`; the lattice,
  CTF and index routes and ops pass one derived from the image's own
  row-to-column ratio (`calc/calibration.spacing_at_column_scale`), so a
  user-typed pixel size keeps meaning the column scale, as it always has.
  Square pixels are bit-for-bit unchanged.

  Still open under roadmap item 5a: energy-axis profiles and the
  project/UI calibration model. Noted, not changed: the isotropic FFT-mode
  formula in `index_spots` uses the image WIDTH for both axes (verbatim
  `indexDiffraction.m`), so on a non-square image a row-direction spot's d
  is off by H/W even with square pixels; that is a golden-parity decision.
  `calc/diffraction_simulate.py` simulates a CAMERA and keeps its single
  detector pixel size by design.

## [0.4.0] - 2026-09-04

A correctness release. Four measurements that multiplied by a single pixel
extent now use both, so they stop being silently wrong on anisotropically-
sampled data; and opening a folder of large images no longer stalls the
library. The same class of error survives elsewhere in the tree — see
*Known limitations* below before trusting a calibrated number this release
does not name.

### Fixed
- **Strain is dimensionless again.** `calc/gpa.py` converted its
  displacements to physical units and then differentiated them against pixel
  indices, so every strain component came out multiplied by `pixel_size` —
  ten times too large at `pixel_size=10`, and right only at the default of 1,
  which is the one value the MATLAB golden test exercises. Both callers pass
  the value straight from a user parameter, so anyone who entered a real
  calibration got strains scaled by it. Displacements still scale, because
  they are lengths.
- **Four lengths and angles now use both pixel extents.**
  `DataStruct.pixel_size` is the column scale alone, and these multiplied by
  it regardless: the total test-line length behind Ham dislocation density
  (its vertical lines span rows), the distance/profile/polyline labels
  printed onto exported figures, the angle label on exported figures, and
  the distance axis of an EDS line profile. A diagonal of 30 columns and 40
  rows on (3, 4) pixels is 169.7 units, not the 200 that hypot-then-scale
  reported; a 45° line on 1:3 pixels really rises at 71.6°. Square pixels
  are unaffected: with equal extents the two expressions agree to within
  floating-point rounding.
- **An EDS composition profile no longer labels every calibrated map "nm".**
  The route hardcoded the unit, so a µm-calibrated map reported µm-sized
  numbers under an nm label. It now reads `pixel_unit`, matching the
  registered operation.
- **A nonsense calibration no longer voids a GPA result.** Neither the route
  model nor the operation parameter excluded `pixel_size=0`, and it divided
  the gradients: four all-NaN maps, and the four field means silently absent
  from the payload. Strain needs no calibration at all, so an unusable one
  now falls back rather than destroying the answer.

### Changed
- **Library thumbnails are thumbnails.** `/image/{id}/render` had no size
  parameter and every tile requested the full-resolution PNG — about a
  second and 16.8 MB apiece for a 4096² survey image, so opening a dozen
  asked for ~200 MB and ~15 s of encoding to paint tiles a couple of hundred
  pixels wide. That is why small batches loaded and large ones appeared to
  hang. A new `max_dim` caps the longest edge: the same twelve tiles now
  cost 1.3 s and 2.3 MB. Callers that pass no `max_dim` — the Stage texture
  and the export path — are byte-for-byte unchanged.
- Reducing an image for a thumbnail area-averages over the complete source.
  Periodic structure is the subject matter here, and point subsampling made
  a lattice or stripe field resolve to whichever phase the sampling lattice
  landed on. Saved project thumbnails improve for the same reason.

### Added
- `calc/calibration.py`, one definition of how a pixel-space displacement
  becomes a physical length or angle, so the pairing of axis to extent
  cannot drift between call sites.
- A keyword-only `spacing` on the affected calculations, carrying both pixel
  extents. `pixel_size` keeps its position and meaning as the isotropic
  fallback, and an explicit `spacing` wins.

### Known limitations
- **The single-scale error is not gone tree-wide.** This release fixed the
  four sites above; an audit for the tag found the same shape still live
  elsewhere, and these numbers remain wrong on anisotropic pixels (square
  pixels are unaffected everywhere):
  - `calc/profiles.py::line_profile` — the general intensity line profile,
    behind the `measure` operation and `/measure`, still computes
    `hypot(dx, dy) * pixel_size`. Measured: a 30-column, 40-row line on
    pixels 3 wide and 4 tall reports 150.0 where the true length is 183.6.
    This is the same expression the EDS profile fix replaced; only the EDS
    one was changed.
  - `calc/layers.py` and `calc/trace_roughness.py` — layer thickness,
    `thickness_std`, `sigma_erf` and the roughness family (`sigma_w`, its
    CI, `sigma_raw`, `noise_floor`, `xi`, `psd_wavelength`) all scale by
    `pixel_size` whatever the growth axis, which `analyze_layers` detects
    at runtime. Measured: a 25-row layer on 4 nm rows and 1 nm columns
    reports 24.5 nm where the truth is 100 nm.
  - `calc/grain_layers.py` — `lateral_width` and `depth_height` are
    perpendicular to each other and take the same scale; its `pixel_area`
    is `pixel_size ** 2` rather than `DataStruct.pixel_area`.
  - `calc/grains.py` (boundary-network length), `calc/radial.py` (radial
    distance), `calc/profile_stats.py`, and `calc/particles.py`
    (`pixel_size ** 2` as an area).

  Reciprocal- and energy-axis calibration (`calc/ctf.py`,
  `calc/diffraction*.py`, `calc/lattice.py`) is a separate, still-open
  roadmap item and is not counted here.

## [0.3.0] - 2026-09-02

A region of interest becomes a first-class object. Until now each analysis
accepted whatever shape it happened to grow up with — nine different
conventions across the codebase, most of them reducing anything you drew to
its bounding rectangle. This release gives regions one definition, a place in
the project file, a manager and drawing tools in the UI, and puts every major
analysis and batch recipe behind that one definition. It also finishes the
Results & Methods stack with side-by-side comparison, a report composer and a
self-contained export, and corrects three long-standing measurement errors
found in an audit of every formula against its published source.

### Added
- **Named analysis regions.** Draw a rectangle, ellipse, circle, polygon or
  lasso with the existing Stage tools and keep it as a named region in an
  image-scoped set. A region can have holes, several disconnected parts and
  ordered exclusions, and carries a class with a project-wide colour and
  label. Sets save in the project file under a validated schema, come back
  after a browser refresh, and can be converted from existing Saved ROI
  bookmarks. Older projects load unchanged.
- **An Analysis Regions manager.** Name, select, show or hide, duplicate and
  delete sets; classify individual regions; read compound geometry (parts,
  exclusions, holes) in compact rows; load a region back onto the Stage for
  precise vertex editing. Regions render over the image in their class
  colour with even-odd holes and hatched exclusions, and hiding one changes
  the overlay immediately without touching the geometry.
- **Analyses read exact regions, not bounding boxes.** EDS/EELS spectrum
  summation, image and ROI statistics, particle analysis, grain finding,
  trained segmentation, layer profiles and shape similarity all accept a
  region. Sums and statistics use the exact pixel mask; a rectangle
  reproduces its previous numbers bit for bit; and every response says
  whether it used the exact mask or only the box around it. Segmentation
  labels only pixels inside the region and computes its threshold from those
  values alone, while neighbourhood-based methods such as watershed read the
  bounding-box crop so the region edge does not become an invented boundary
  — each op reports which it did.
- **Layer profiles over irregular regions.** Mean and median collapse a
  region depth by depth, dividing by the pixels actually present at each
  depth. Sum is refused for a non-rectangular region because its value would
  follow the width of the outline as faithfully as the intensity: a
  perfectly flat specimen summed through a circle swings more than fourfold.
  Waviness tracing is refused for the same reason. Rectangular regions keep
  every mode.
- **Recipes can name a region.** A batch step may reference a saved set or a
  single region. The reference is resolved to inline geometry per image
  before the step runs, so the recorded parameters replay identically on a
  machine with no project. A misspelt set name fails at submit time, and a
  set bound to a different image skips that image with the reason recorded
  rather than failing the batch.
- **Label images convert to editable regions and back, losslessly.** A
  segmentation label map becomes one region per label, with holes and
  diagonally touching components preserved and the label value kept, so
  deleting label 2 does not renumber label 5. The reverse conversion rebuilds
  the map exactly. Floating-point or out-of-range label values are refused
  rather than rounded.
- **Preview a region's scope before running.** A preview endpoint reports
  the pixel count, the bounding-box pixel count, the physical area and
  whether the two counts differ, using the same resolver the analyses use,
  so what it predicts is what they read.
- **Compare saved results side by side.** A Compare view in Results &
  Methods shows which results can sit together, their calibration confidence
  and shared outputs, and names exactly why any cannot: different analysis,
  different units, a failed run. Scalars compare with uncertainty and units;
  non-scalar outputs are identified as such rather than flattened.
- **Compose a report.** Pick results in order, choose which outputs to
  include, and get methods, calibration and review-note sections assembled
  from the deterministic manifest, with scalar metrics, inline tables and
  vector curves in a print-oriented preview. Export the exact preview as
  standalone HTML or print it to PDF.
- **Export a result bundle that stands alone.** A single archive carries the
  manifest, the methods prose, a README and every cited array, using the
  project's own member layout so a citation that pointed into the project
  resolves inside the archive. Arrays stream rather than buffer, and the
  archive is byte-reproducible apart from its timestamp, so it can be hashed
  and cited.
- Image and ROI statistics report how many pixels were finite as well as how
  many were selected. Physical area follows the selected count — a dead
  detector pixel still occupies specimen area — while mean, standard
  deviation, minimum and maximum use only the finite values.

### Changed
- ROI statistics no longer return NaN for an entire ROI because one pixel is
  NaN; they report the finite pixels and say how many were usable.
- `rasterize`, `bounding_box` and `to_rect_roi` now live in
  `calc.region_mask` and remain importable from `calc.regions`. The ASTM
  E112 grain-size machinery moved from `calc.grains` to `calc.grain_size`.

### Fixed
- **The ASTM E112 grain size number was off its own scale.** The formula
  applied a coefficient constructed for log₁₀ to log₂, so 10 µm grains
  reported G = 40.8 where E112 gives 10.7 — every value for an ordinary
  micrograph fell outside the 00–14 range the scale spans. The grain report
  also inferred the grain count from the mean equivalent diameter, which
  biases G upward whenever grains vary in size (by +0.44 at a 60 % size
  spread); it now counts grains per unit area as E112's planimetric method
  specifies. Grain-size values from the grains analysis change; they were
  wrong before.
- **Areas on non-square pixels were wrong by the ratio of the two scales.**
  Physical area was the pixel count times one axis scale squared. An AFM
  scan with 0.5 nm rows and 2.0 nm columns reported four times its true
  area. Area is now the product of the two spatial scales everywhere it is
  reported — region and ROI statistics, particles, grains, grain layers and
  the region preview — and is left undefined rather than guessed when the
  two axes disagree on their unit or one is uncalibrated. Square pixels are
  numerically unchanged.
- **Particle and grain shapes on non-square pixels were measured in
  distorted pixel space.** A physically circular particle on 3:1 pixels
  reported an aspect ratio of 3.04, an eccentricity of 0.94 and a 73 % error
  in equivalent diameter, and was classified rod-like. Lengths and shape
  descriptors are now computed on the calibrated grid, with a perimeter
  estimator that adapts its sampling directions to the pixel aspect ratio.
  Square pixels are bit-for-bit unchanged, so existing circularity values
  and class thresholds do not move. Other length readouts — GPA
  displacements, exported distance labels, dislocation line intercepts and
  EDS line profiles — still assume square pixels and are tracked separately.
- Particle orientation is measured from the row axis, following
  scikit-image, so a horizontal feature reports π/2 rather than 0. This was
  always the behaviour and is now documented, since plotting it as "from
  horizontal" would draw every particle across its own short axis.

## [0.2.0] - 2026-08-28

Results stop being transient. Until now every analysis lived only as long as
its window was open — this release gives them a schema, a place in the
project file, and a browser, and makes almost every analysis reachable from
a saved recipe instead of only from a mouse.

### Added
- **Analysis results survive save, close and reopen.** A project now carries
  a typed `results` section: the resolved parameters, a calibration snapshot
  taken at compute time, the geometry that was measured, warnings, and the
  outputs themselves. Large arrays are stored as project members, never
  inlined into the manifest, so a project with thousands of particles does
  not become an unreadable JSON file. Older projects load unchanged and
  round-trip losslessly; a result written by a newer build survives an
  older one untouched.
- **A Results & Methods workspace.** Persisted results come back as cards
  showing their primary values, uncertainty, warnings, calibration and the
  images they came from, readable without reopening the workshop that
  produced them. The window is searchable and groups by time, sample,
  source image or analysis, and each card links back to the images it came
  from and forward to any it produced.
- **Reopen, Rerun and Duplicate a saved result.** Reopen restores a
  result's settings and geometry into the workshop that produced it, for
  inspection; Rerun recomputes it exactly as recorded; Duplicate with
  changes reopens it as an editable starting point and captures the run as
  a new result. Reopen and Rerun leave the original untouched.
- **EDS quantification, particle analysis, intensity profiles and
  diffraction indexing can be saved as results.** Each records what it
  actually computed — the fully resolved parameters, not just the ones you
  touched — so a saved result says exactly how to reproduce it. Failures
  are recorded as failures rather than quietly dropped. Saving is opt-in;
  nothing is captured unless asked.
- **88 operations are now scriptable.** Batch recipes, recorded macros and
  the CLI share one operation vocabulary covering imaging, EELS, EDS,
  diffraction, structure, measurement and utility endpoints — 72 of 80
  analysis endpoints, up from a small hand-picked set. Multi-image
  operations (image math, stack alignment, MIP, stitch, montage) work in
  recipes too, through named auxiliary inputs that stay portable across
  sessions instead of freezing an image id into the recipe.
- **A recipe builder that shows you the vocabulary.** Searchable operation
  palette, structured parameter editors, pickers for named and variadic
  inputs, up-front validation and dry-run summaries, plus per-image and
  per-step failure provenance when a batch run goes wrong.
- **Compare results and build a report from them.** A comparison endpoint
  says which saved results can sit beside each other and, for those that
  cannot, exactly why — different analysis, different units, a failed run —
  naming both sides rather than greying a card out. A report endpoint
  assembles a selection into a deterministic manifest with a calibration
  summary, the software version, attributed warnings and generated methods
  prose.

### Fixed
- **Diffraction indexing returned wrong d-spacings for an off-edge ROI.**
  The crop origin was clamped to the image while the effective width came
  from the raw ROI, so an ROI hanging over an edge left the spot
  coordinates unshifted but shrank the width that scales `d` in the
  uncalibrated branch. Measured d-spacings were quietly wrong, with nothing
  to indicate it. A degenerate or out-of-image ROI is now rejected outright.
- Diffraction indexing no longer accepts a spectrum cube as if it were a
  diffraction pattern, and a ragged spot list is a clear error rather than
  a server fault.
- Grain merge/split failures now report what went wrong instead of
  surfacing as a server fault, and a label map whose shape does not match
  its source image is caught with a message naming both shapes.
- Cross-map layer comparison no longer treats an uncalibrated map as
  calibrated at 1.0 px, which had let it compare roughness across maps that
  share no physical scale.
- Whole-number parameters reject fractional values everywhere instead of
  truncating them — asking for pixel 1.5 no longer silently measures pixel 1.

## [0.1.32] - 2026-08-18

### Added
- **Pick the units a measurement displays in.** Right-click any measure →
  Units: Image default / Auto / Å / nm / µm / mm — per measure, with
  "Apply to all measures on this image" for consistency. Covers areas and
  lengths (37990 nm² becomes 0.038 µm²; 850 nm becomes 0.85 µm); Auto
  picks the largest unit that keeps the number readable. Nothing changes
  until you choose: the default remains the image's calibration unit, and
  Image default returns to it. The Measure panel and its CSV log follow
  the same choice as the stage label, so exports never disagree with what
  you see. Diffraction images calibrated in reciprocal units (1/nm) and
  unrecognized calibrations disable the menu with a reason instead of
  mislabeling a conversion; uncalibrated images keep px/px². Unit choices
  save with the project.
- **Vertex editing for polygons and lassos.** Right-click a vertex →
  Delete vertex (disabled at three — a polygon must stay a polygon);
  alt-drag anywhere on an edge to insert a vertex at that spot and place
  it in the same motion. Plain drags are unchanged: body drag still
  moves the whole measure, handle drag still moves one vertex. Undo
  covers each edit as a single step.
- **Simplify outline on demand.** Right-click an existing polygon or
  lasso → Simplify outline, using the same preference at the current
  zoom (zoom in first for a gentler pass). One undo step; if the outline
  is already sparse it says so instead of silently doing nothing.
- Polygon and lasso vertices now render as small round handles instead
  of directional bars (which belong on line and arrow endpoints), with a
  larger invisible hit target so they stay easy to grab.

### Fixed
- **Adjusting a lasso no longer means fighting hundreds of points.** A
  freehand lasso used to store a vertex every ~2 screen pixels — handles
  rendered as fur around the outline, and dragging any single vertex
  among hundreds produced a needle-thin spike instead of reshaping the
  curve. Lassos now capture at full fidelity and simplify when you close
  them (true Douglas–Peucker; the Lasso simplify preference finally does
  what its name says): a typical traced particle drops from ~300 vertices
  to a couple dozen, each owning a real stretch of boundary, so dragging
  one genuinely reshapes the outline. Deliberate spikes survive
  simplification — removing detail is only ever your call. Click-placed
  polygons are untouched: you placed those vertices on purpose.
- **Holes now move with their shape.** Dragging a polygon that had marked
  holes used to leave the holes behind at their old position, detaching
  the voids from the outline and invalidating the holes-subtracted area —
  a long-standing bug surfaced by this release's review pass. Undo
  restores shape and holes together.

## [0.1.31] - 2026-08-16

### Added
- **Find particles shaped like this one — now in the GUI.** Every row of
  the Particles table gains a ≈ action that ranks all particles by shape
  distance to that one (elliptic-Fourier similarity, shipped server-side
  in v0.1.30): distances appear as a sorted dimensionless column with the
  reference first, particles whose outline cannot support the harmonic
  count stay visible with the reason on hover, and the ranking always
  reflects the segmentation you are looking at — it exits automatically on
  re-run or image change rather than showing stale distances.
- **Fit a circle and ellipse to any traced region.** The Regions card
  gains a per-region Fit action showing both least-squares fits with
  their RMS residuals — advisory, nothing auto-picks a winner. Radii,
  axes and RMS display in physical units when the image is calibrated
  (px otherwise); the ellipse angle is shown in degrees with its axis
  convention stated. Disabled below five vertices, where an ellipse fit
  is meaningless.

## [0.1.30] - 2026-08-14

### Fixed
- **Typing during a metadata refresh no longer loses your edit.** If a
  Custom-metadata refetch (e.g. Auto-fill all) was still in flight when
  you started typing, its response silently overwrote the in-progress
  edit — the stale-value guard read a snapshot of the dirty flag from
  when the request started, not its live value when the response landed.
- **Dislocation density now carries dimensionally correct units.** The
  defect-line count reported `lines/nm²` for the per-length density
  (2N/L, which is 1/length) and `lines/nm³` for Ham's foil-thickness
  density (2N/(L·t), which is the classic 1/length² of lines-per-cm²) —
  both exponents were off by one. Values were always correct; the unit
  label on them was not. Pinned by a scaling-law test independent of the
  label.
- **Three malformed-input 500s are now proper 422s**: `/api/filter` with
  a zero bin size or zero CLAHE tile size, `/api/diffraction/calibrate`
  with a negative angle count, and `/analyze/layers/multi` with a
  comparison map containing non-finite pixels (which now names the
  offending image).
- **One bad particle no longer kills shape-similarity ranking.**
  `/analyze/efd-similarity` skips regions that cannot support the
  requested harmonic count and reports them in a `skipped` list with
  reasons, instead of failing the whole query on the first tiny speck.
  A reference region that cannot be described is still a 422 — there is
  nothing to rank against, and the error now says so.
- A false derivation comment on the noise estimator's MATLAB-verbatim
  √20 divisor was corrected (the Laplacian kernel energy is 36, not 20;
  the divisor itself is golden-pinned and deliberately unchanged).

### Added
- **Particles now have a shape identity (SHAPE_ANALYSIS_PLAN Wave 1).**
  `/analyze/particles` measures each particle's circularity, aspect ratio,
  eccentricity, orientation, solidity and maximum Feret diameter
  (calibrated twin included), through the same `skimage.regionprops` path
  grain analysis already uses, and assigns an advisory shape class —
  sphere-like / rod-like / intermediate / aggregate — with visible,
  caller-tunable thresholds. Classes describe the 2D projection only (a
  rod viewed end-on projects as a disk) and nothing is auto-corrected or
  filtered by class; low solidity flags probable touching-particle
  aggregates the watershed missed. The Particles table shows the new
  columns and per-class counts, the size-distribution feed gains a metric
  picker (equivalent ⌀ / circularity / aspect ratio / Feret max —
  dimensionless metrics carry no unit, and null aspect ratios are
  excluded and counted, never coerced to 0), and a new orientation
  half-rose answers "are my rods aligned?" at a glance — axial over
  (-90°, 90°], never mirrored into a full circle, with near-circular
  particles excluded from the rose since a circle's orientation is noise.
  Circularity is defined against the Crofton perimeter; calibration work
  during the build measured that an axis-aligned square scores ≈0.874 on
  that scale (not the textbook π/4, which belongs to the naive
  perimeter), so the sphere-like circularity cutoff is 0.92 — between
  the square's 0.874 and a disk's ≈0.99 — keeping cube projections out
  of sphere-like, pinned by an end-to-end square→intermediate test.
- **Find particles shaped like this one (`POST /analyze/efd-similarity`).**
  Elliptic Fourier descriptors (Kuhl & Giardina 1982) of each particle's
  traced outline, normalized for scale, rotation and starting point, rank
  every particle by shape distance to a chosen reference — invariances
  pinned by tests (a scaled/rotated copy ranks at distance ≈0). Backend
  ships now; the workshop "find similar" control follows in Wave 2.
- **Circle and ellipse fitting on contour points (`POST /analyze/fit-shape`)**
  for pores and core-shell shells: least-squares circle and ellipse fits
  with per-fit RMS residuals, reusing the diffraction-calibration ellipse
  math rather than a second implementation. Backend ships now; GUI wiring
  follows in Wave 2.

## [0.1.29] - 2026-08-14

### Changed
- **Internal decomposition only — no user-facing or API changes.** The two
  source files closest to the 500-line module ceiling were split along
  natural seams. Backend: `routes/eds_advanced.py` (493→289 lines) gives up
  the `/eds/zeta` endpoint to a new `routes/eds_zeta.py` and its shared
  peak-fit machinery to `routes/_eds_common.py` (mirroring the existing
  `_fourd_common.py` pattern); the HTTP surface is unchanged. Frontend:
  `EdsSpectrumImage.tsx` (480→404 lines) moves two self-contained lifecycles
  into hooks — `useEdsPinnedRegions` (pin/restore with species re-creation
  and reset-on-cube-change) and `useEdsStatusReporter` (the
  status-must-not-outlive-the-file contract).

## [0.1.28] - 2026-08-14

### Added
- **Integrated DPC (iDPC) for 4D-STEM (`POST /api/fourd/{id}/idpc`,
  PLAN_4DSTEM #9 — closes Tier 2).** New `calc/fourd/idpc.py` performs the
  Fourier-space integration that turns a `/dpc`-style calibrated COM field
  into a single light-element phase-contrast image, reimplemented from
  Lazić, Bosch & Lazar, "Phase contrast STEM for thin samples: Integrated
  differential phase contrast", Ultramicroscopy 160 (2016) 265-280. The
  integration is a Frankot-Chellappa-style least-squares gradient inversion
  in Fourier space (`F[psi] = -1j*(omega_y*F[field_y] + omega_x*F[field_x])
  / (omega_y**2+omega_x**2)`), with `F[psi](0,0)` pinned at exactly 0 — the
  DC/mean term of a reconstructed phase image is not, and cannot be,
  recovered from a gradient field, so every iDPC image is a phase map up to
  an unknown additive constant, by construction, not as an approximation.
  A documented Gaussian high-pass (`high_pass_cutoff`, default `0.02`
  cycles per scan pixel, always caller-overridable — never a hidden magic
  number) suppresses the classic iDPC low-frequency "bowl" artifact the
  `1/omega` reconstruction kernel is known to amplify. The image is in
  MILLIRADIAN-SCAN-PIXELS, proportional to the projected potential — not an
  absolute potential in volts, and not even an absolute phase in radians:
  that would additionally need the accelerating voltage (electron
  wavelength, via the interaction constant) and the physical scan-pixel
  pitch along both scan axes, neither of which this module invents. The
  unit carries a scan pixel because the integration is with respect to the
  scan-pixel index — the mirror of `/dpc`'s divergence, which divides by
  one — so the values scale with how finely the scan was sampled: imaging
  the same region at half the scan step doubles every value. That is a
  property of the measurement, not a defect, but it is the reason the map
  is not labelled plain "mrad", which would read as a sampling-independent
  physical quantity. `POST /api/fourd/{id}/idpc`
  (thin, in `routes/fourd_com.py`, reusing `/com`/`/dpc`'s
  center-resolution/streaming step) registers the ONE resulting map —
  unlike `/com` (two images) and `/dpc` (three) — recording the resolved
  descan center, the `mrad_per_px` calibration and the `high_pass_cutoff`
  applied in its metadata. `routes/fourd_com.py` grew 276→354 lines (pin
  500, still comfortable). 38 new backend tests (18 pure in
  `test_fourd_idpc.py`, 20 route-level in `test_api_fourd_idpc.py`): the
  pure suite reconstructs a hand-built sinusoidal potential — an exact DFT
  bin, so the reconstruction is checked to near machine precision after
  removing the mean from both sides (the required "up to an additive
  constant" property) — and separately proves the high-pass filter actually
  suppresses a deliberately low-frequency signal by a known, analytically
  predicted factor; the route suite checks registration/metadata/units and
  that the endpoint's wiring (center resolution, calibration and cutoff
  pass-through) matches calling the calc layer directly on the same COM
  field. Frontend: `FourDWorkshop`'s aperture-mode segmented control gains
  three new buttons (COM/DPC/iDPC) alongside BF/ABF/ADF/Custom, each
  routing to its own endpoint via a new `computeComOutput` store action
  (`store/fourdComOutput.ts`, split out to keep `store/fourd.ts` under its
  500-line ceiling) instead of the aperture path's `computeMap` — the two
  families share the descan-center controls but not radii/shape, which are
  hidden for com/dpc/idpc since those routes don't take them. A new
  `FourDComOutputFields` control exposes the required `mrad_per_px`
  calibration (dpc/idpc) and `high_pass_cutoff` (idpc only), showing but
  never auto-filling the detector's own calibration when available — same
  "never invent a physical constant" line the backend holds. 42 new
  frontend tests across three files. Along the way, found and fixed a
  latent bug in `setApertureMode`: switching directly into "custom" (or now
  com/dpc/idpc) via the mode buttons silently failed to update the stored
  mode, because `apertureRadiiForMode`'s pass-through case returns the
  *entire* previous aperture object (needed for its own, deliberate,
  reference-equality contract) including its own stale `mode` field, which
  a spread-order bug then let win over the intended new mode; fixed by
  spreading the new `mode` last, unconditionally.
- **Differential phase contrast (DPC) for 4D-STEM (`POST /api/fourd/{id}/dpc`,
  PLAN_4DSTEM #8).** New `calc/fourd/dpc.py` turns a `/com`-style COM shift
  field into the standard DPC products: magnitude and direction of the
  beam-deflection field, and the field's divergence — projected charge
  density by Gauss's law, via a documented `numpy.gradient` finite-difference
  scheme (central differences at interior scan positions, one-sided at the
  boundary; both exact for a linear field). The detector's milliradians-per-
  pixel calibration is what turns a COM shift in detector pixels into a
  physical deflection angle, and it is NOT reliably available on every
  `FourDDataset` (a bare `.mib` with no `.hdr` sidecar is uncalibrated) — so
  `mrad_per_px` is a required argument on every calc function and a required
  (`Field(gt=0)`) request field on the route, never silently defaulted to
  `1.0`. `POST /api/fourd/{id}/dpc` is a separate route from `/com` (not a
  response extension of it — #9's iDPC also lands in `routes/fourd_com.py`
  and would otherwise share the same response schema), reusing `/com`'s
  center-resolution/streaming step and registering magnitude/direction/
  divergence as three ordinary derived 2D images, each recording the
  resolved descan center and the calibration used. The divergence map is
  named for what it measurably is — mrad per scan pixel — rather than
  "charge density": it is *proportional* to projected charge density, but
  the constant relating the two needs the specimen thickness, the
  accelerating voltage and the physical scan pitch, none of which this
  route has. That interpretation, and its caveat, ride in the map's
  metadata instead of in a display name that would overstate the number. Tested against analytic
  fields: a uniform field gives a constant magnitude/direction and EXACTLY
  zero divergence; a linear ("radial", point-charge-like) field gives a
  known non-zero constant divergence, exercising the charge-density path
  itself rather than only its null case.
- **Per-probe center-of-mass mapping for 4D-STEM (`POST /api/fourd/{id}/com`,
  PLAN_4DSTEM #7).** Registers COMy and COMx as two ordinary derived 2D
  images — the basis for the DPC/iDPC work that follows — through the same
  `add_derived` path `/nav` and `/virtual-detector` use, so they inherit
  LUT/measure/export for free. The actual per-probe intensity-centroid math
  (Müller-Caspary et al., Ultramicroscopy 178 (2017)) already shipped in
  `calc/fourd/virtual.py`'s `com_shift_maps` as part of #6; the new
  `calc/fourd/com.py` adds only the center-resolution policy on top —
  caller-supplied descan reference center when given, else auto-seeded from
  `geometry.pattern_center(mean_pattern)` (the same auto-center policy
  `/virtual-detector` uses) — then delegates. The route shares its
  both-or-neither/in-bounds center validation with `/virtual-detector` via a
  new `_validate_optional_center` helper. Both maps record the descan
  reference center they were measured against — the *resolved* value, so an
  auto-centred map stays reproducible instead of storing the request's null.
- **Two more synthetic presets, for testing composition profiles and ZAF
  absorption correction.** `tools/make_synthetic_si.py --preset eds-diffusion`
  plants a linear Cu → Ni composition gradient with a per-row ground truth, so
  `/analyze/composition-profile` has a known straight line to recover.
  `--preset eds-thickness` plants a thickness-dependent absorption bias from
  the app's own ZAF forward model, so `method="zaf"` quantification has a
  real bias to correct instead of the zero-thickness no-op every other
  preset exercises. The Z/A math ZAF quantification and this preset both use
  now lives in one place (`calc/eds_absorption.py`), extracted out of
  `zaf_correction` so the generator imports it instead of keeping a second
  copy.

### Fixed
- **A ⚠ badge warns when two species' windows interfere.** The Elements list
  (both EDS and EELS Maps tabs) now flags a pair when their integration
  windows overlap, when their lines sit closer together than the detector
  can resolve regardless of how the windows are drawn, or — on EELS — when
  one edge's background-fit window runs through another edge's onset.
  Hovering the badge explains which species and why. It is advisory only:
  nothing is narrowed, refused, or auto-corrected, and every row keeps
  working exactly as before — the fix (a different window, a different
  beam energy, or Model fit for lines the detector genuinely cannot
  separate) is yours to make.

### Changed
- **The Explore tabs now tune the species list directly — one set of
  windows everywhere.** Clicking a species row in Maps (or a chip in the
  new species strip at the top of Explore) selects that species, and the
  window you drag, nudge, preset, fit or type in Explore IS the window
  Maps extracts with, the composite blends, and the figure export
  legends — for both EDS and EELS. Species rows now show a live net ± σ
  that tracks the window as you tune it, instead of a number frozen at
  identification time. Background model and beam energy are per-image
  settings shared between Explore and Maps, so bremsstrahlung-background
  maps are now reachable from the Maps workflow and E₀ is no longer a
  hardcoded 30 kV. The single-element picker in EDS Explore is retired —
  pick species in Maps (auto-identify or the periodic table), tune them
  in Explore. Restoring a pinned integration region re-selects its
  species, recreating it if it was removed.

## [0.1.27] - 2026-08-12

### Added
- **The combined colour overlay can be saved to the library.** Save to
  library, beside Export figure on both Maps tabs, registers the composite
  exactly as you see it — colours, per-species gains, survey underlay — as
  a first-class image. It appears in the filmstrip in colour, opens on the
  Stage and in both compare modes, inherits the cube's spatial calibration
  so the scale bar keeps working, survives project save/load, and records
  its species list and windows as provenance. Colour is colour, not data:
  intensity readouts see a standard luminance of it, and the Adjust card
  says so instead of offering a contrast window that means nothing for
  colour. One caveat: a project containing a saved composite needs this
  version or newer — an older build refuses the project by name rather
  than opening it wrong.
- **Tell FermiViewer what shape your Merlin scan was.** A `.mib` file records
  its frames and nothing about the raster that produced them, so every
  headerless Merlin acquisition opened as a single-row line scan — a
  ten-pixel navigation strip. The 4D-STEM Viewer now has a scan-shape control:
  type rows × columns, or click one of the suggested factorisations (squarest
  first, since STEM scans usually are), and the file re-opens under that
  raster with the dataset, probe and aperture selection intact. A file that
  records its own scan axes, like HyperSpy 4D, does not offer this.
- **Log intensity on the diffraction pattern**, on by default. A 4D pattern
  runs from a saturated direct beam to Bragg disks a thousand times fainter;
  on the previous linear ramp everything but the direct beam was black. This
  changes the display only — computed virtual-detector maps are unaffected.
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
- **The synthetic test-data generator was not a valid quantification oracle.**
  `tools/make_synthetic_si.py` planted EDS line areas from an invented
  energy-dependent weighting unrelated to Cliff–Lorimer, so quantifying its
  own cubes returned carbon at 21 at% against a planted 9.4. Line and edge
  intensities now come from the application's own models — Cliff–Lorimer
  weights for EDS, the same differential cross-section the EELS model fit
  refines for EELS — so both EELS quantifiers now recover a four-edge
  composition to within 0.4 at% and agree with each other. Three further bugs
  fell out: the cube silently wrapped `uint16` for bright heavy elements
  (tantalum's 6.2 at% came back as 0.7); the EELS preset's energy axis started
  too close to its lowest edge for that edge's background fit window to fit on
  it (silicon's 46 at% came back as 3); and the planted core-loss edges sat
  twenty orders of magnitude below the background, so the cube was effectively
  a bare power law.
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
