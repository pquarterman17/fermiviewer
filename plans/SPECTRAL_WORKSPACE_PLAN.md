# Spectral workspace plan — EDS + EELS

Make the spectrum-image workspaces genuinely usable for routine analysis: pick
a handful of species, tune their integration windows by direct manipulation,
and get single or combined colour maps out — with EDS and EELS sharing one
implementation so a feature cannot land in one and rot in the other.

**Status:** Active
**Parent:** MAIN_PLAN.md
**Created:** 2026-07-29
**Updated:** 2026-08-11

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

- Items 1–3 are the foundation; nothing else in W1–W3 lands cleanly before them
- Items 4, 5, 6 are independent of each other once 2 exists (parallelizable)
- Item 8 unblocks 9; item 14 unblocks 15
- Item 7 (shared composite) is a generalisation of the existing EDS composite —
  do it with 15, not before, so it is written against two real callers
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
| 1 | Species model | W1 — Core | Every other item reads or writes it |
| ~~8~~ | ~~`/eds/element-maps` endpoint~~ | W2 — EDS | Shipped 2026-08-10 — item 9 is now unblocked |
| 4 | Draggable window edges | W1 — Core | The single biggest usability win per line of code |
| 3 | SpectrumWorkspace shell | W1 — Core | Where EELS stops being second-class |

---

## W1 — Shared spectrum core

### Tier 1 — High Impact

2. **Window model abstraction** — one interface over two different window
   shapes
   - [ ] EDS: one signal window; flanking background inferred (`_side_windows`)
   - [ ] EELS: explicit background window + signal window
   - [ ] Both expose the same `integrate()` and the same drag targets, so the
         editing UI does not branch on modality

3. **Species list wiring into the shared shell** — the shell exists (item 21);
   what remains is making the species list itself modality-driven
   - [ ] One list component fed by either K/L/M lines or edge onsets

4. **Draggable window edges** — grab an edge to resize, the middle to slide
   - [ ] Hit-testing with a grab tolerance in pixels, not energy units
   - [ ] Cursor feedback (`ew-resize` on edges, `grab` in the middle)
   - [ ] Arrow-key nudge / shift+arrow coarse nudge for keyboard parity
   - [ ] Must not fight the existing drag-zoom or shift-drag gestures

7. **Shared composite** — N species → one RGBA raster, for either modality
   - [ ] Generalise `EdsComposite` once item 15 gives it a second caller

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

The shared shell now shows EELS a **Maps** tab that states plainly what is
missing rather than faking it. These four items are what fills it.

### Tier 1 — High Impact

12. **Edge picker** — species list backed by `EELS_EDGES`
    - [ ] Element + edge choice (Si L23 vs Si K), not just element
    - [ ] Same periodic-table affordance as EDS, filtered to elements with an
          edge inside the cube's energy range

13. **EELS zoom, colours and integration** — via the shared core from W1
    - [ ] Replaces the four typed `bgLo/bgHi/sigLo/sigHi` fields

14. **`/eels/maps` batch endpoint** — N edges → N rasters, mirroring item 8
    - [ ] Built on `calc/eels.extract_map`, decoupled from `quantify_map`
    - [ ] Return inline rasters; `/eels/map` returns a registered ImageMeta,
          which the montage and overlay cannot consume directly
    - [ ] Fix `extract_map`'s `np.asarray(cube, dtype=np.float64)` — it
          materialises a float64 copy of the whole cube, the exact memory bug
          the EDS path already fixed. Making EELS maps a primary workflow
          would expose it on multi-GB cubes.

22. **EELS edge identification** — the auto-ID half of the Maps workflow
    - [ ] There is no `/eels/auto-assign`; EDS gets its element list for free
          and EELS cannot
    - [ ] Edge-jump significance over every `EELS_EDGES` entry inside the
          cube's range gives the same net/σ confidence banding the EDS list
          already uses

15. **EELS composite** — the capability EELS has never had

### Tier 2 — Medium Impact

16. **Background-window auto-placement** — derive a sensible pre-edge fit
    region from the onset, user-adjustable (gate resolved 2026-08-11: yes,
    auto-place; the window stays visible and draggable)

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
