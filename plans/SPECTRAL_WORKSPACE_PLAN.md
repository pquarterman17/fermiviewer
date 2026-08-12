# Spectral workspace plan — EDS + EELS

Make the spectrum-image workspaces genuinely usable for routine analysis: pick
a handful of species, tune their integration windows by direct manipulation,
and get single or combined colour maps out — with EDS and EELS sharing one
implementation so a feature cannot land in one and rot in the other.

**Status:** Active
**Parent:** MAIN_PLAN.md
**Created:** 2026-07-29
**Updated:** 2026-08-12 — item 7 closed: the composite was already shared,
but verifying that exposed a forked figure export (fixed, one path now) and
a figure shipping with no scale bar (fixed). 7 items open (W1 polish, W2
retirement, W4 verification); W1 Tier 1 and W3 are both complete

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

- The W1 foundation (items 1–4, 7) and all of W3 are complete
- Items 5 and 6 are independent of each other (both build on item 2's core)
- Item 8 unblocks 9; item 14 unblocks 15 (both 8 and 14 have now shipped)
- Item 10 (composite → library) is the one open item with an unanswered
  architectural question: `DataStruct` is grayscale-only (`_to_gray` collapses
  every RGB input on load) and `DataKind.IMAGE` is asserted in ~69 places, so
  "register the composite as an RGB library image" needs a data-model decision
  and an ADR before code — not a wiring job
- W4 item 17 is done and is the verification substrate for everything else
- Item 11 is last: retiring the old flow needs the new one proven

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

*Tier 1 is empty — item 7 shipped 2026-08-12; see Completed.*

### Tier 2 — Medium Impact

5. **Width presets and FWHM auto-fit** — narrow / standard / wide, or fit the
   window to the measured peak width
   - [ ] EDS: seed from the detector-resolution curve, refine on the data
   - [ ] EELS: an integration width past the onset, which is the real control

6. **Numeric steppers with live net** — typed bounds that show net ± σ as they
   change, plus a lock so the window follows the species' line/onset

---

## W2 — EDS workspace

*Tier 1 is empty — items 8 and 9 both shipped 2026-08-10, so the EDS Maps
workflow is complete end to end. What remains is polish and retirement.*

### Tier 2 — Medium Impact

10. **Composite → library** — register the combined map as an RGB image so it
    reaches the filmstrip, comparison and export (gate resolved 2026-08-11:
    first-class library image)

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

### Tier 2 — Medium Impact

18. **Quantification golden tests against truth** — assert `/eds/quantify` and
    `/eels/quantify` recover the synthetic composition within tolerance
    - [ ] Uses the `.truth.json` sidecar as the oracle
    - [ ] Documents the tolerance each method actually achieves

### Tier 3 — Nice-to-Have

19. **More presets** — a diffusion-couple gradient and a thickness ramp, for
    testing profiles and absorption corrections

20. **Window overlap detection** — flag species whose windows interfere
    (deselected 2026-07-29; see Owner gates)

---

## Completed

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
