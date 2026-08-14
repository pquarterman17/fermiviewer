# Spectral workspace plan — EDS + EELS

Make the spectrum-image workspaces genuinely usable for routine analysis: pick
a handful of species, tune their integration windows by direct manipulation,
and get single or combined colour maps out — with EDS and EELS sharing one
implementation so a feature cannot land in one and rot in the other.

**Status:** Active
**Parent:** MAIN_PLAN.md
**Created:** 2026-07-29
**Updated:** 2026-08-12 — items 10 and 19 shipped. Item 10 forced the
data-model decision it was gated on, recorded as **ADR 0003**
(`DataKind.RGB_IMAGE`, uint8 [H,W,3] with spatial axes only, luma at one
raster boundary); en route the 13 copied `_raster` adapters consolidated
onto `calc/raster.py`. Item 19 added the diffusion-gradient and
thickness-ramp presets, extracting `zaf_correction`'s Z/A math into
`calc/eds_absorption.py` so the generator imports the app's own absorption
model rather than transcribing it. **1 item open: #11 (retire Explore), whose precondition is not met.** Item 20 closed the last standing owner gate by measuring the Ta M / Si K silent failure rather than asserting it, and ships as a non-blocking advisory

---

## Context

### How the pieces fit together

Both workspaces are the same shape — a spectrum, a set of species, an energy
window per species, and maps derived from those windows — but they were built
separately and only EDS has been maintained.

| | EDS | EELS |
|---|---|---|
| Species source | `calc/eds.py` `line_energy()` K/L/M by overvoltage | `calc/eels.py` `EELS_EDGES` onsets |
| Window model | one peak window; flanking background inferred | explicit background window + signal window |
| Species picking | periodic table / dropdown, **one at a time** | text filter over an edge list |
| Multi-species maps | only via `/eds/quantify` (welded to Cliff–Lorimer/ZAF) | `/eels/quantify-map` (welded to quant) |
| Window editing | numeric fields + shift-drag | four typed numbers |
| Zoom / colours / integration | yes (2026-07-29) | none |
| Composite | yes | **none** |

The asymmetry is the problem, not the feature gap: `extract_element_maps()`
already exists in `calc/eds_maps.py` and does exactly the multi-species job,
but the only route to it is `/eds/quantify`, so asking for five maps forces a
quantification the user may not want.

### Data / control flow (target)

```
  species list  ──┬─> window model ──> integration readout (client, per species)
  (symbol +       │                     │
   transition)    │                     └─> live net ± σ in the species row
                  │
                  └─> batch map request ──> per-species raster ──┬─> single map view
                       (/eds/element-maps, /eels/maps)           └─> composite (N × colour)
                                                                       └─> library image
  colour registry ──────────────────────────────────────────────────────┘
      (already shared; drives every surface)
```

### Dependency map

- All of W1 (items 1–7), all of W3, and item 10 are complete
- Item 8 unblocks 9; item 14 unblocks 15 (both 8 and 14 have now shipped)
- Item 10's data-model question is answered by **ADR 0003**
  (docs/adr/0003-rgb-composite-images.md): a fourth `DataKind.RGB_IMAGE`,
  chosen over a metadata sidecar (persistence brings the cost back anyway)
  and over a FourDDataset-style separate store (filmstrip/compare/export all
  read the one library)
- W4 item 17 is done and is the verification substrate for everything else
- Item 11 is last: retiring the old flow needs the new one proven
- Items 18 and 23 shipped together: the synthetic cubes now invert the app's
  own forward models, so both EELS quantifiers recover the planted composition
  to 0.4 pp and agree with each other

### Resolved decisions

- (2026-07-29) **Species list panel**, not a batch button on the single-element
  flow — multi-select builds a persistent list with per-row window, colour,
  visibility and net.
- (2026-07-29) **Window editing = drag edges + width presets/FWHM auto +
  numeric steppers with live net.** All three, not one.
- (2026-07-29) **Shared spectrum core** parameterised by modality, rather than
  porting features twice or keeping two copies in sync.
- (2026-07-29) **Synthetic data as real `.hspy` files**, opened through the
  normal file path, with a `.truth.json` sidecar.
- (2026-07-29) Peak/edge positions in synthetic data come from the app's own
  tables, never a second copy.
- (2026-07-30) **One "Elemental Analysis" workspace**, not two windows — the
  only arrangement that structurally prevents a feature landing in one
  modality and not the other.
- (2026-07-30) **Three-tier code split** (spectrum / elemental / modality), not
  a blanket "elemental" rename: `zoomRange.ts` serves any spectrum and EDS
  background models serve only EDS.
- (2026-07-30) Backend `calc/` and `routes/` keep their EDS/EELS names — the
  physics genuinely differs and a shared name would hide that. Sharing happens
  at the interface (item 2), not the filename.
- (2026-08-11) **Composite becomes a first-class library image** (item 10
  gate resolved): registered as an RGB image reaching filmstrip, comparison
  and export — matching the figure convention MAIN_PLAN books for the
  sample montage.
- (2026-08-11) **EELS background window auto-places from the onset,
  user-adjustable** (item 16 gate resolved): the DM/HyperSpy convention.
  Wrong-guess risk is mitigated by the window staying visible and draggable
  (item 4), never hidden.

### Owner gates

- Overlap detection (item 20) was explicitly deselected. Revisit only if the
  Ta M / Si K case in real work produces a wrong answer silently.

---

## Cross-cutting priorities

| # | Item | Workstream | Why first |
|---|------|------------|-----------|
| ~~1~~ | ~~Species model~~ | W1 — Core | Shipped 2026-08-10 |
| ~~8~~ | ~~`/eds/element-maps` endpoint~~ | W2 — EDS | Shipped 2026-08-10 — item 9 is now unblocked |
| ~~4~~ | ~~Draggable window edges~~ | W1 — Core | Shipped 2026-08-11, with item 2 under it |
| ~~3~~ | ~~SpectrumWorkspace shell~~ | W1 — Core | Shipped 2026-08-11 — EELS is no longer second-class (all of W3 landed with it) |

---

## W1 — Shared spectrum core

**COMPLETE 2026-08-12** — every item (1–7) shipped; see Completed. The
shared core is the species model, the modality-blind window model and its
drag/nudge surface, the SpectrumWorkspace shell, the width-preset/fit/lock
strip, and one composite + one figure export for both modalities.

---

## W2 — EDS workspace

*Tier 1 is empty — items 8 and 9 both shipped 2026-08-10, so the EDS Maps
workflow is complete end to end. Item 10 shipped 2026-08-12; what remains
is retirement.*

### Tier 2 — Medium Impact

11. **Retire the single-element Explore flow** — once the species list covers
    it, remove the duplicate controls rather than leaving both

---

## W3 — EELS workspace

**COMPLETE 2026-08-11** — every item (12–16, 22) shipped; see Completed.
EELS now has the full Maps workflow (auto-ID → species list → montage +
composite overlay + figure export) and direct-manipulation Explore, from
the same shared components as EDS.

---

## W4 — Test data and verification

*Tier 2 is empty — items 18 and 23 both shipped 2026-08-12; see Completed.*

**COMPLETE 2026-08-12** — items 17, 18, 19, 20 and 23 all shipped; see
Completed. The synthetic cubes invert the app's own forward models, and the
last of them (item 20) closed the standing overlap-detection gate by
measurement.

---

## Completed

- ~~**#20 Window overlap detection**~~ (2026-08-12) — a non-blocking
  advisory closes the owner gate this item was deselected under. Owner gate
  status: revisit condition MEASURED, not asserted — `tests/test_quant_golden.py`
  had never actually built the eds-overlap cube, so the case had never been
  run. Built at the golden suite's own shape/counts, `/eds/quantify` returns
  Ta at 0.00 at% against a truth of 6.67, sigma 0.000, no warning field
  anywhere in the response — a silent wrong answer, on synthetic data,
  in exactly the case the gate named. New pure `lib/elemental/windowConflicts.ts`
  (three rules: signal-window overlap for both modalities; EDS unresolvable
  lines via the existing `fanoFwhmKev` port, independent of where the windows
  are drawn; EELS background-through-edge) renders as a ⚠ badge in the SHARED
  `ElementList`, so both EDS and EELS Maps tabs get it from one implementation
  with zero per-tab changes. Nothing is narrowed, refused, or filtered —
  verified by mutation: a "disable the row's controls when conflicted" creep
  reddens the non-blocking-guarantee test.
  **A real defect found while writing the module's own tests.** The initial
  implementation built each conflict's `aId`/`bId` from a stable
  species-id sort, but built its `detail` tooltip text from the raw (a, b)
  call-order parameters — so two species could report the SAME conflicting
  pair with a DIFFERENT tooltip wording ("Ta M ... and Si K ..." vs "Si K
  ... and Ta M ...") depending purely on which one `detectWindowConflicts`'
  internal loop happened to visit first, which itself depends on the input
  array's order. None of the plan's own listed mutations would have caught
  this; it surfaced only from writing an explicit "the result must not
  depend on input array order" test and hitting a real, non-deterministic-
  looking failure. Every rule now sorts its pair before building anything
  from it.
  Backend: one golden test (`test_eds_overlap_quantifies_ta_to_zero_silently`)
  pins the measured silent failure — including a correction to the item's own
  opening measurement: Si is measurably wrong but DEFLATED, not inflated as
  first guessed, because carbon's already-documented light-element bias (see
  `test_eds_light_element_bias_is_bounded_and_documented`) dominates the
  renormalisation Ta's near-total absence gets folded into. That numeric
  assertion proved extremely robust — neither a 6x wider default window, nor
  disabling background subtraction entirely, nor a 57x k-factor override
  moved Ta off ~0, which is itself evidence for how completely buried the
  signal is, not a weak test. 11 new tests (8 pure `windowConflicts` + 2
  `ElementList` + 1 golden), all verified red by mutation; frontend gate
  1299 vitest / 172 files, tsc + build clean; backend gate 1900 passed.

- ~~**#19 More presets: diffusion-couple gradient + thickness ramp**~~
  (2026-08-12) — `eds-diffusion` (a linear Cu -> Ni composition `Gradient`
  along y) and `eds-thickness` (a per-pixel `ThicknessRamp` that scales
  signal AND plants absorption via a new `calc/eds_absorption.py` —
  `zaf_correction`'s Z/A math extracted so the generator can import it
  instead of transcribing it; `zaf_correction` now calls the extraction and
  the full backend suite stayed green with zero test edits, confirming the
  move was behaviour-preserving).
  **The planned preset didn't work, and measuring it — not the plan's
  a-priori physics — is what this item shipped.** The plan's own NiO/50-400 nm
  choice was tried first: this app's MAC formula has no absorption edges to
  cap Z^4 growth, so O's z*a factor for a Ni matrix exceeds 100 within a few
  nm, saturating plain Cliff-Lorimer to a near-single-element answer and
  defeating ZAF's iterative refinement (verified directly against
  `zaf_correction`, both planting directions tried, both fail). Al2O3 over a
  10-100 nm ramp keeps z*a in the 1-5x range, where Cliff-Lorimer shows a
  real, growing bias and ZAF genuinely removes most of it — and the bias
  runs the OPPOSITE direction from the plan's guess (O is increasingly
  OVER-reported with thickness under this app's own forward-model
  convention, not under-reported; Al carries the mirrored deficit).
  **Results, measured and asserted as ceilings** (golden module's
  convention): eds-thickness plain Cliff-Lorimer shows a +21 pp thick-minus-
  thin O bias (bounded 15-30 pp); `method="zaf"` at the true mid-column
  thickness cuts the max |at% error| from ~18 pp to <1 pp on the same cube.
  eds-diffusion's row-recovered profile matches the truth's per-row array to
  <1 pp at the pure ends and the middle, and the `/analyze/composition-profile`
  route reproduces the graded zone as a straight line to within 0.6 pp.
  The four original presets are untouched (`total_counts` pinned byte-for-
  byte; `profile`/`thickness` keys omitted from their truth files).
  Two mutation-testing gaps found and closed while verifying: a row-mean-only
  check for the gradient's row/col axis could not tell a correctly-oriented
  gradient from one interpolated along the wrong axis (both average out to
  the same per-row numbers) — closed with a within-row spatial-uniformity
  assertion. And `zaf_factors`' own formula is invisible to a mutation
  (dropping `csc` from χ) because the generator and the route both import
  the SAME function — planting and correcting drift together, not apart —
  so ZAF's mutation instead targets the route's thickness/take-off wiring,
  which the shared-import property cannot protect. 9 new tests (1 extraction
  lockstep, 4 generator-invariant, 4 golden); backend gate 1899 passed (was
  1890), frontend unaffected (no frontend changes) at 1289 vitest / 171 files.

- ~~**#10 Composite → library**~~ (2026-08-12) — the combined colour overlay
  registers as a first-class library image reaching the filmstrip, compare
  stages, project save and export. The data-model gate became **ADR 0003**:
  a fourth `DataKind.RGB_IMAGE` (uint8 [H,W,3], SPATIAL axes only — a
  channel axis has no calibration semantics), chosen over a metadata
  sidecar (a first-class composite must survive `.fvp` round-trip as
  colour, so persistence brings the schema cost back anyway and a sidecar
  only adds a path that can forget it) and over a FourDDataset-style
  disjoint store (the owner's three surfaces all read the ONE library —
  a second namespace means every one of them merges two sources).
  **The "~69 assertion sites" defused to a bounded cost**: 13 of the ~30
  consumers were near-verbatim copies of the same `_raster()` helper,
  consolidated FIRST as a behaviour-preserving refactor onto
  `calc/raster.py::raster_of` (gated green alone, before the new kind
  existed); the 8 strict rejecters use `is not IMAGE` and rejected the new
  kind with zero edits; the 7 spectral gates flipped to a positive
  `kind not in SPECTRAL_KINDS` check so future kinds are excluded from
  spectral math by default. RGB collapses to BT.601 luma at that one
  boundary — measure/FFT/histogram see a defensible scalar with no
  per-site decision, and `io/metadata.to_grayscale` now delegates to the
  same weights instead of carrying its own copy.
  **Composed once, client-side.** The registration endpoint
  (`POST /composite/register`, new `routes/composite.py`) stores the
  pixels of the SAME overlay canvas the figure export reads — one blend
  implementation, "what the user was looking at" — with the parent cube's
  spatial calibration inherited (422 on dim mismatch rather than a
  dishonest scale) and the recipe as provenance metadata. Serving:
  `/render` returns colour PNG (filmstrip/gallery colour with zero client
  changes), new `/rgb8` is the raw colour sibling of `/data16`, and
  data16/tiles REFUSE the kind rather than silently de-colouring — the
  looks-right-and-is-wrong trap called out in the ADR. One `u_rgb` shader
  branch covers Stage, CompareStage and SideBySideStage because all three
  load through the new `gl/loadPixels.ts`; AdjustPanel replaces its
  controls with an explanation (no window/level story for colour is a
  deliberate scope fence, like the parsers still collapsing file colour
  at load). Save-to-library buttons on BOTH Maps tabs. Old builds reject
  a composite-bearing project loudly by schema (`images[i].kind`) —
  accepted, identical for any kind ever added. Backend 1935 passed
  (+10), frontend 1296 vitest (+21), tsc + build clean, luma weights and
  the stale-upload race both mutation-pinned.

- ~~**#18 Quantification golden tests against truth + #23 synthetic edge
  shapes from `calc/eels_model`**~~ (2026-08-12) — `tests/test_quant_golden.py`
  runs `/eds/quantify`, `/eels/quantify` and `/eels/fit` on cubes of known
  composition. **Every EELS number below is a same-day correction of a first
  pass that shipped wrong**, which is recorded here rather than tidied away:
  the first attempt scaled the planted edges to their own physical
  cross-section magnitude (~1e-25 m²) against a background normalised to ~1e-2,
  burying every edge twenty-odd orders of magnitude under it. The "EELS
  quantifies to 26 pp" figure that first booked this item was measuring
  background residue, not edges.
  **The oracle did not work and had to be made to — four defects.** (1) EDS
  line areas came from an invented `1 + 0.5·log1p(E)` weighting unrelated to
  anything the quantifier inverts: C came back at 21 at% against a truth of
  9.4, Al at 5.0 against 10.0. Areas now come from the app's own Cliff-Lorimer
  model (`I ∝ f·M/k`) and EELS edges from `eels_model.edge_shape_fn` — item
  23's deliverable, and the rule that already governed peak POSITIONS applied
  to their shapes and areas. (2) `astype(np.uint16)` WRAPS: with correct
  weights, Ta's per-pixel peak mean reached ~2.6e5 and most of its peak wrapped
  to near zero, quantifying 6.2 at% as 0.7. Sampling now rescales into range
  first — a global factor, so every ratio survives, where a clip would have
  truncated the brightest element. (3) `eels-layers` started its axis at 80 eV,
  leaving Si L23 at 99 eV only 19 eV of pre-edge against the 52 eV its
  background fit asks for; the truncated fit over-extrapolated and Si came back
  at 3 at% against 46. (4) The planted edges needed ONE global scale to a
  realistic edge jump (0.6 of the background at the lowest onset) — one factor,
  so the cross-section ratios that make the cube an oracle are untouched.
  **And a comparison error in the test itself:** it compared against
  `field_mean_atomic_percent`, which averages over the whole raster including
  vacuum, while a quantifier measures the MATERIAL and normalises to 100. That
  is a silent bias of exactly the empty fraction (6.25 % of eds-layers). The
  sidecar now carries `material_atomic_percent` too, and a test asserts the two
  are one scale factor apart so they cannot drift.
  **Results, all measured and asserted as ceilings** so an improvement fails
  the test and forces the docstring's table to be tightened. EDS: Al and O land
  within **0.02 pp** on eds-layers, which is what makes the remaining carbon
  error attributable to carbon rather than to a loose pipeline. That error —
  C 21.2 vs 10.0 — is the flanking LINEAR background under a steep convex
  Kramers continuum, and the `bremsstrahlung` alternative was measured and is
  WORSE (25.6 pp), so it is a floor of window integration, not a hardcoded
  wrong model. EELS: BOTH quantifiers now recover the four-edge composition to
  **0.4 pp**, and agree with each other to 0.5 pp — the check that the cube is
  a real oracle rather than two methods failing the same way.
  Scope stated in the docstring rather than implied: planting and inverting
  with the same table cannot test the table, so the k-factors and
  cross-sections themselves are NOT under test; everything between the cube and
  the answer is. Verified by mutation — restoring the old intensity weighting,
  the uint16 wrap, the edge-jump scale, or the field-vs-material comparison
  each reddens the suite. 11 tests; backend gate 1890 passed.

- ~~**#5 Width presets and FWHM auto-fit + #6 Numeric steppers with live
  net**~~ (2026-08-12) — shipped together because they are one control strip:
  `components/spectrum/WindowPresetBar.tsx` (narrow / standard / wide, Fit
  width, Lock to line) sits under the plot in BOTH Explore tabs, with every
  number coming from `lib/spectrum/windowPresets.ts`.
  **The presets are physics, not three arbitrary numbers.** EDS widths are
  multiples of the DETECTOR resolution at that line (1.0 / 1.5 / 2.0 × FWHM
  total = 76 / 92 / 98 % of a Gaussian peak), because a fixed ±85 eV is 1.3
  FWHM at C-Kα and 0.65 FWHM at Mn-Kα — the same number meaning two different
  things is what the item was about. EELS widths are absolute (30 / 50 / 100
  eV past the onset): an edge is a step, there is nothing to bracket, and
  `standard` IS `EELS_SIGNAL_WIDTH_EV` rather than a copy of 50, so the preset
  row and a fresh species' default cannot drift.
  **The resolution curve is a documented port, pinned by numbers in both
  suites.** `lib/eds/resolution.ts` ports `calc/eds_calib.py::fano_fwhm` (a
  preset click must not need a round trip), and
  `test_fano_fwhm_matches_frontend_port` + `resolution.test.ts` assert the
  SAME five sample values — change a constant on either side and one suite
  goes red. That is the only lockstep two languages can have here, and it is
  stronger than the prose lockstep the EELS constants have.
  **"Refine on the data" refuses rather than guesses.** `fitPeakWindow`
  measures the peak's real FWHM against a baseline joining the search span's
  ends, and returns null — leaving the window exactly as the user had it —
  when the span holds no interior maximum, when a half-maximum crossing runs
  off the end, or when the peak stands less than 5 % of its own counts above
  that baseline. That last guard came out of a test: a peak far broader than
  the span reads as 0.14 keV wide instead of 2.0, because the span's ends sit
  on the peak's own flanks. A silently TOO-NARROW window would have been the
  worst possible outcome of a button labelled "Fit".
  **Item 6's lock is where the two items meet.** EDS keeps the tabulated line
  in `useEdsEnergyWindow` (the `Species.energy` split, for the reason item 1
  recorded), and while locked a commit re-centres the window on it: an edge
  drag widens symmetrically, a body drag cannot walk the window off its peak,
  and the element stays bound — dropping to "(custom)" while locked would
  silently undo the lock. Fitting re-anchors to the MEASURED centre so a later
  resize does not snap back to an energy this spectrum's calibration disagrees
  with. EELS gets no toggle on purpose: its window starts at the onset by
  definition, so the presets are onset-following unconditionally and a toggle
  could only offer to make the window wrong.
  Typed bounds already showed live net ± σ in both tabs (EDS via
  `IntegrationPanel`, EELS via item 13's readout); the EDS steppers moved from
  a 50 eV step to 5 eV — a 50 eV nudge is a third of a window — and now show
  the width in eV beside them.
  Sizes: EdsSpectrumImage 473 → 408 (new `useEdsEnergyWindow.ts` 168 +
  `EdsWindowControls.tsx` 155), so the strip was paid for by extraction, and
  the lock/preset/fit rules are unit-tested rather than reachable only by
  driving a React tree. 34 new tests; the lock's re-centring verified by
  mutation. Frontend gate 1275 vitest / 170 files, tsc + build clean.

- ~~**#7 Shared composite**~~ (2026-08-12) — the composite itself was already
  shared: `EdsComposite` no longer exists (item 21 renamed the generic
  surface to `ChannelComposite` in 2026-07-30), `lib/composite.ts` is the one
  blend both it and `MapOverlay` call, and item 15 landed the EELS caller by
  reusing `MapOverlay` whole. `ChannelComposite` stays separate on purpose —
  its channel is a filename, not an element, and its own header records the
  bug that conflating the two caused. So this item closed as a **verification
  plus the residue that verification exposed**, which was real:
  **the figure export had already forked.** Both Maps tabs carried a ~40-line
  copy, and the copies had drifted — the EDS figure captioned at% and only
  at%, the EELS figure captioned nothing, while both on-screen legends showed
  net counts. The one rule now lives in `lib/elemental/mapLegend.ts` and the
  one assembly in `lib/elemental/figureExport.ts`; EELS gained the caption
  detail it never had, and both modalities now honour the legend selector the
  user actually set.
  **The exported figure gained its scale bar** — `renderFigure` had supported
  one since it was written and neither caller passed it, so the deliverable
  this plan exists to produce was going out unpublishable. It is drawn on the
  combined panel, or on the first tile when the montage-only view is exported
  (previously that view silently produced no bar at all — mutation-verified).
  An uncalibrated cube gets NO bar rather than a default-scaled one: a bar is
  an assertion about physical length and there is nothing to assert.
  `formatScaleLength` moved out of `ScaleBarOverlay` into `lib/geometry.ts`
  beside `niceScaleLength`, so the Stage bar and the figure bar cannot word a
  length differently.
  Also: `MapTile`/`tileKey` moved to `lib/elemental/mapTile.ts` (a `lib/`
  module must not import from `components/`, which the extraction would
  otherwise have forced), the export reads the overlay through a ref instead
  of a global `document.querySelector(".fvd-eds-overlay-canvas canvas")`, and
  the shared components lost their EDS names — `EdsMapOverlay`/`EdsMapMontage`
  /`EdsElementList` → `MapOverlay`/`MapMontage`/`ElementList`, since the EELS
  tab was importing all three under an EDS name. 17 new tests; frontend gate
  1241 vitest / 167 files, tsc + build clean.

- ~~**#3 Modality-driven species list + #12 Edge picker + #15 EELS composite
  + #16 Background auto-place**~~ (2026-08-11, merged `bc3e8b3`; sonnet
  worktree agent) — the EELS Maps tab is real: `/eels/auto-assign` evidence
  feeds the SHARED list/store/montage/overlay/figure pipeline, so the EDS
  deliverable (montage + colour overlay with legend + one-click figure) now
  exists for EELS from the same components.
  **The type split did the heavy lifting:** `IdentifiedElement` became a
  modality-neutral `Evidence` base + EDS extension, `speciesRows` keys by
  `symbol|transition` (Si-K and Si-L23 are distinct rows), and
  `seedSpeciesFrom` was RENAMED to `seedEdsSpeciesFrom` so the compiler
  found every call site — the narrowing-a-shared-type rule applied by the
  agent unprompted. Montage/overlay React keys and per-tile gain moved to
  `tileKey()` (`symbol-line`) for the same one-element-two-edges reason.
  **Edge choice** (#12): auto-assign scores EVERY in-range edge, so the
  table needs no separate line lookup — clicking an element adds each of
  its in-range edges as its own row, disambiguated by the transition cell;
  choice is per-row visibility/removal. **#16**: `eelsDefaultWindows`
  auto-places background `[onset−52, onset−2]` eV, constants in documented
  lockstep with `calc/eels_identify.py`. **#15 delivered by reuse:**
  MapOverlay's blend/max compositing, legend, survey underlay and per-tile
  gain all worked for EELS after the collision-safety fix.
  Known benign gap: montage tile-focus resolves a two-edge element to its
  first row (nothing consumes the callback today). Merged-tree gate: 1224
  vitest / 165 files, tsc + build clean.

- ~~**#13 EELS zoom, colours and integration**~~ (2026-08-11, merged
  `927dab3` + fix `694812e`; sonnet worktree agent) — the Explore tab now
  drives BOTH windows by direct manipulation on a generalised SpectrumPlot:
  optional `background` window (amber, the old fit-series colour), full
  `SpeciesWindows` live/commit callbacks coexisting with the EDS pair
  contract (unchanged when background is absent — all prior tests pass
  unmodified), and an `overlays` prop for the Fit button's power-law curves.
  Live net ± σ via `integrateEdge`, zoom bar + wheel zoom, edge-onset
  markers in registry colours, four typed bounds kept as synced steppers.
  New `eels/EelsExploreTab.tsx` (327); EelsWorkshop 422 → 345, its bespoke
  uPlot now serves only Quantify/Model-fit.
  **Review caught one real defect before merge:** the agent's `overlays = []`
  default parameter sat in the build-effect dependency array — a fresh array
  per render, so every live-drag frame would have destroyed and rebuilt the
  uPlot and killed the drag mid-gesture (invisible to jsdom). Fixed with a
  module-level `NO_OVERLAYS` constant (stable-snapshot rule, prop form) and
  a regression test verified by mutation. Frontend gate: 1205 vitest, tsc +
  build clean.

- ~~**#14 `/eels/maps` batch endpoint + #22 EELS edge identification**~~
  (2026-08-11, merged `bb572ca`; sonnet worktree agent) — the backend half of
  the EELS Maps workflow. `POST /api/eels/maps` (`routes/eels_maps.py`, 180):
  N species → N inline rasters with per-species signal + optional background
  windows and per-row error reporting (a hand-picked edge never vanishes
  unexplained; a wholly-failed list is still 200 — item 8's contract,
  mirrored). `POST /api/eels/auto-assign` (`routes/eels_identify.py`, 110 +
  pure `calc/eels_identify.py`, 165): edge-jump significance for every
  `EELS_EDGES` entry the axis supports — pre-edge power-law fit (50 eV window,
  2 eV gap below onset so the rising edge cannot bias the fit), 50 eV
  post-onset integration, net/σ/significance with the SAME confidence
  thresholds (100/30/10) as the EDS identifier, kept in numeric lockstep
  since calc/ cannot import from frontend/. Also fixed `extract_map`'s
  float64 whole-cube cast — only windowed channels are promoted now, guarded
  by a tracemalloc allocation-delta test. 32 new tests, edges planted via
  `EELS_EDGES` itself. Gate on the merged tree: 1892 passed / 0 skipped.

- ~~**#4 Draggable window edges**~~ (2026-08-11) — grab an edge to resize, the
  body to slide, arrows to nudge (shift ×10, commit on key-up). The gesture is
  claimed by a CAPTURE-phase mousedown on the plot HOST: uPlot binds its
  zoom-select directly on `.u-over` and same-element listener order cannot be
  beaten, but an ancestor's capture phase runs first — that one line of DOM
  mechanics is the whole "must not fight drag-zoom" requirement. Shift-drag,
  right-click, wheel and plain zoom-drags away from the window fall through
  untouched. Live frames drive only the client-side readout (new
  `onDragWindowLive` prop); the element-map refetch stays on the commit
  callback, once per gesture, and arrow-key nudge commits on key-up so a held
  key streams frames but requests one map. `ew-resize`/`grab` cursors carry
  the discoverability. 9 gesture tests + 2 plot-integration tests.

- ~~**#2 Window model abstraction**~~ (2026-08-11) —
  `lib/spectrum/windowModel.ts`: `integrateWindows()` returns one readout
  (net ± σ) over both window shapes, dispatching to `lib/eds/integrate.ts`
  and a NEW `lib/eels/integrate.ts` — a deliberate client-side port of
  `calc/eels.py::background` (power-law / exponential pre-edge fit) whose σ
  includes the fit's extrapolation variance via the delta method.
  `dragTargets` / `applyDrag` / `nudge` / `hitTest` are the modality-blind
  editing surface item 4 consumes: edges before bodies, pixel-space grab
  tolerance, nearest-edge tie-break so a 3-px-wide window can still be
  resized from either side. Same honesty rules as the EDS port: net is
  UNCLAMPED (an over-subtracted window is information), and a degenerate fit
  window degrades to a noted direct sum instead of raising, because mid-drag
  windows pass through every bad state on the way to a good one. Verified
  against constructed truths — an exact power law must integrate to ~zero
  net and recover its own (A, r). 29 tests across the two modules.

- ~~**#9 Species list wired to EDS**~~ (2026-08-10) — the species store now has
  its consumer, and every loose end item 1 left is closed.
  **The user-visible win:** switching cubes and back restores your list.
  `MapsTab` held it in component-local `useState` and wiped it on every image
  change; it now holds only *evidence* (transient, re-measured each identify)
  while decisions live per-image in the store. Re-identifying refreshes every
  measured number without reticking a row the user untucked.
  **The second source of truth is gone.** `IdentifiedElement.selected` →
  `recommended`, a rename so the compiler found all five call sites — it was
  never state, only auto-ID's above-trace hint, and it now seeds `visible`
  once instead of competing with it. The merge rules live in a pure
  `lib/elemental/speciesRows.ts` (84 lines): rows are built from SPECIES, so a
  removed element stays removed even though auto-ID still finds it, and a
  hand-added one still shows even with nothing measured for it (evidence is
  nullable, rendering "added" rather than a fake confidence).
  **One batch request, cache kept.** `useElementMaps.ts` sends only the cache
  MISSES to `/eds/element-maps`, so five elements are one round trip instead of
  five, and ticking a sixth still fetches one. An unmappable species reports
  its reason to the status bar rather than going quietly missing from the
  montage.
  `pruneClosed` is wired into `viewerCloseImage.ts` — the one place the whole
  per-image teardown is auditable, which that file's own header argues for.
  `PeriodicTable` takes `string | string[] | null` rather than gaining a
  second multi-select flag that could contradict the first.
  **Item 1's type gained `energy`**, surfaced by wiring it: the window and the
  line diverge the moment the user tunes one, and both the row label and item
  6's planned window-lock need the anchor kept.
  Sizes all under the 500 ceiling (MapsTab 367, ElementList 198). 22 new tests.

- ~~**#1 Species model**~~ (2026-08-10) — `lib/spectrum/species.ts` (the
  modality-neutral tier, since both workspaces use it unchanged) plus a
  per-image `store/species.ts`. **Foundation only: it has no UI consumer yet
  — item 9 is the wiring, and carries that as an explicit sub-task.**
  Kept separate from `identify.ts`'s `IdentifiedElement` on purpose: that type
  is what auto-ID *measured* (net, σ, significance, confidence, δ-from-line),
  it has no EELS analogue, and a user's decisions must survive a
  re-identification that changes every one of those numbers. Evidence in,
  decision out.
  `Species` carries **no colour** — it resolves from the symbol registry, so
  "Carbon is green" holds on montage, overlay, legend and spectrum labels at
  once; a stored colour would be a second source of truth, which this repo has
  already paid for. `splitEdgeLabel` exists for the same reason: "Fe-L2,3" must
  reach the registry as `Fe`, not as an unrecognised key.
  `modality` fixes the window shape AND the unit (EDS keV, EELS eV) from one
  field, so the two cannot contradict. EELS `background` is deliberately left
  UNSET — auto-placing it is item 16 and an open owner gate; guessing here
  would answer that question by accident and a wrong background window yields
  a quantification that looks fine and is not.
  Per-image state is keyed by image id rather than cleared, so switching cubes
  and back restores the list instead of wiping it (today `MapsTab` discards
  every tick and manual addition). `NO_SPECIES` is a module-level constant for
  the zustand stable-snapshot rule, matching `MeasureOverlay`'s `NO_MEASURES`.
  27 tests.

- ~~**#8 `/eds/element-maps` endpoint**~~ (2026-08-10) — `extract_element_maps()`
  is no longer reachable only through a Cliff–Lorimer/ZAF quantification the
  user may not want. N species → N rasters inline, `save_derived` optional,
  per-species `e_lo`/`e_hi` override so the endpoint serves the species list
  instead of recomputing default windows (item 9 is unblocked).
  **The rule moved, it was not copied:** picking an element's line and judging
  whether it is usable now lives once in `calc/eds_maps.resolve_element_window`,
  raising a domain `UnusableElementError`. `extract_element_maps` catches it and
  warn-and-skips exactly as before; the route catches it and reports the reason
  **per row** — a species the user picked by hand must never vanish unexplained,
  which is the one behaviour the batch route deliberately does not inherit. A
  wholly-failed list is still 200, so the caller needs no second branch.
  New module (`routes/eds_maps.py`, 205) rather than growing
  `analysis_wireups.py` at 432/500 — the ratchet forcing a module again.
  Tested on a cube with real spatial structure (Fe left, Cu right): a
  uniform cube cannot distinguish per-element windows from one window applied
  N times. Verified by mutation — pinning a fixed window fails 2 of the 9
  tests. Peaks are planted via `line_energy()`, never transcribed.

- ~~**#21 Elemental Analysis workspace**~~ (2026-07-30) — EDS and EELS merged
  into one shell owning a single tab strip and a modality badge;
  `EelsWorkshop` lost its own tab state; the Inspector's two tabs became one
  launcher; the redundant Composite tab was removed and the generic
  compositor kept as `ChannelComposite`. Frontend split into
  `spectrum` / `elemental` / `eds` tiers. Ratchet pins lowered
  (EelsWorkshop 685→677, MenuBar 1539→1495).

- ~~**#17 Synthetic SI generator**~~ (2026-07-29) — `tools/make_synthetic_si.py`
  writes real `.hspy` cubes (4 presets: `eds-layers`, `eds-overlap`,
  `eds-particles`, `eels-layers`) plus a `.truth.json` oracle. Peak and edge
  positions come from `calc.eds.line_energy` / `calc.eels.EELS_EDGES`, so they
  cannot drift from the windows the GUI snaps to. `.hspy` reader gained
  `metadata/Sample/elements` so declared elements reach the picker.
  `tests/test_synthetic_si.py` (7 tests) round-trips generator → loader →
  `element_map` and asserts maps localize where the truth says.
