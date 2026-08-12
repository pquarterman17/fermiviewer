# ADR 0003 — RGB composites are a fourth `DataKind`, collapsed to luma at one raster boundary

**Status:** Accepted
**Date:** 2026-08-12
**Schema:** [`docs/schema/fvp-v2.schema.json`](../schema/fvp-v2.schema.json) (enum widened in place, version stays 2)

## Context

The elemental composite — N element maps blended into one colour overlay
(`frontend/src/lib/composite.ts`) — is the figure this whole workspace
exists to produce, and today it is a panel-local canvas. The owner
decision of 2026-08-11 (SPECTRAL_WORKSPACE_PLAN item 10) is that it
becomes a **first-class library image reaching the filmstrip, comparison
and export**. First-class includes surviving a project save: a composite
that degrades to grayscale after save/reload is not first-class.

The data model has no colour. `DataStruct` (`datastruct.py`) admits
exactly `image` (2D), `spectrum` (1D) and `spectrum_image` (3D), with
`len(axes) == data.ndim` enforced in `__post_init__`. The one place
colour enters the app, `io/images.py::_to_gray`, collapses it by channel
mean at load. `DataKind.IMAGE` is referenced at ~69 sites; a survey
(2026-08-12) grouped them:

- **13 near-verbatim copies of the same `_raster()` adapter** (`if
  IMAGE: data; elif SPECTRUM_IMAGE: sum(axis=2); else raise`) across
  `routes/`, `ops/catalogue.py`, `calc/thumbnail.py`, `api/__init__.py`.
  These are the sites that would *silently* pass a 3-channel array into
  scalar math.
- **8 strict rejecters** using `is not DataKind.IMAGE` + 400 — these
  reject any new kind with zero changes.
- **7 spectral gates** (`if IMAGE: raise "no energy axis"`) that a new
  kind must be added to.
- Producers (parsers + 18 `add_derived` callers) — all genuinely 2D,
  untouched.
- The render/serve path (`routes/images.py`, `calc/render.py`) and the
  WebGL viewer (`gl/render.ts`) — strictly single-channel: the shader's
  RGBA texture carries one 16-bit intensity in R/G bytes and every
  output pixel is a colormap LUT lookup.

The session store itself is kind-agnostic (`session.py` holds
`dict[str, DataStruct]`) and needs no changes at all.

## Options considered

### Option A — carry RGB beside the model (metadata payload or a store sidecar)

Keep `DataStruct` mono; register a 2D luma image and attach the colour
array as `metadata["rgb"]` or a parallel `dict[str, ndarray]` in the
store, consulted by the render paths.

Rejected:

- Persistence brings the cost back anyway. A first-class composite must
  round-trip through `.fvp`, so the manifest/pixels format learns about
  the colour payload either way — the sidecar avoids nothing except
  honesty in the type system.
- Every serve/save/export path must *remember* to carry the attachment;
  a path that forgets degrades silently to the luma stand-in — the
  looks-right-and-is-wrong failure, unfindable by tests that only check
  the DataStruct.
- This repo has already paid for second-sources-of-truth twice (stored
  species colours, forked figure export); an attachment shadowing the
  payload is the same shape.

### Option B — a separate `RgbImage` type and store, the `FourDDataset` analogue

ADR 0001 kept 4D data outside `DataStruct` in a disjoint store with a
disjoint id namespace, surfaced by its own wire model.

Rejected — 0001's own reasoning predicts it is wrong here:

- The 4D split worked because the *lazy, huge source* was separable from
  its *2D displayable products*. An RGB composite has no such split: it
  **is** the displayable product, it is cheaply materializable (uint8,
  map-sized), and it wants exactly the normal library pipeline —
  filmstrip, compare grid, project embed, export.
- Filmstrip, comparison and export all read the one image library. A
  disjoint namespace means every one of those surfaces grows a second
  source to merge, which is precisely what `is_fourd` filtering *avoids*
  by keeping 4D datasets OUT of those surfaces. The composite must be IN
  them.

### Option C — a fourth `DataKind.RGB_IMAGE` (chosen)

`rgb_image`: uint8 `[H, W, 3]`, axes = `(y, x)`. The survey defused the
"~69 sites" number: consolidating the 13 duplicated raster adapters
first turns the silent-wrong group into one edit; the 8 strict
rejecters come along for free (`is not IMAGE` already excludes a new
kind); the 7 spectral gates are one-line additions. The honest cost is
the render path (server PNG + one shader branch) and the schema enum —
both bounded, both listed under Consequences.

## Decision

### 1. Shape invariant becomes kind-aware

`_EXPECTED_NDIM` becomes per-kind `(ndim, n_axes)`: `image` (2, 2),
`spectrum` (1, 1), `spectrum_image` (3, 3), `rgb_image` (3, **2**).
There is no channel `AxisCal` — a channel axis has no calibration
semantics, and `pixel_cal = axes[1]` keeps meaning the spatial x axis.
`__post_init__` additionally requires `rgb_image` to be uint8 with
`shape[-1] == 3` (no alpha; producers drop it at the boundary).

### 2. RGB is a product, not a source

The narrowing in §1 is deliberate: colour in this app is
**presentation-grade output** composed from scalar rasters, not
measurement data — the measurements stay in the parent cube. Therefore:

- The composite is composed **once, client-side** (`lib/composite.ts`
  is the single blend implementation) and POSTed as pixels to a new
  registration endpoint, which stores them verbatim via
  `store.add_derived`. The server never recomputes the blend — a
  server-side port would be a second implementation kept in lockstep
  forever, and the export philosophy is already "what the user was
  looking at" (`figureExport.ts`).
- Spatial axes are inherited from the parent cube's calibration, so the
  scale bar works everywhere it works for any image.
- The recipe (species, colours, blend mode, legend selection) rides in
  `metadata` as provenance — enough to caption a figure, not enough to
  be a second rendering path.
- Parsers keep collapsing file colour to grayscale at load
  (`_to_gray`, the ported MATLAB rule). The `was_rgb` breadcrumb stays
  a breadcrumb; "reload as RGB" is explicitly out of scope.

### 3. One raster boundary for every analysis consumer

The 13 copied `_raster` adapters consolidate onto one shared helper
(`calc/raster.py::raster_of`), preserving each site's current semantics
for the existing kinds, and collapsing `rgb_image` to **BT.601 luma**
(the rule `io/metadata.py` already uses). Every analysis endpoint that
reaches pixels through the boundary — measure readouts, FFT, filters,
histogram — therefore sees a defensible scalar without a per-site
decision. Sites whose math is genuinely image-only keep their explicit
400 (`is not DataKind.IMAGE` — unchanged); the 7 spectral gates gain
the kind; `routes/calibration.py`'s axes rebuild becomes kind-aware.

### 4. Serving pixels

- `GET /image/{id}/render` returns `mode="RGB"` PNG for the new kind —
  no window/level, no LUT. The filmstrip, gallery grid and minimap get
  colour with no client changes.
- A binary `GET /image/{id}/rgb8` (X-Shape `H,W,3`) is the interactive
  path, the colour sibling of `data16`. `data16`, tiles and pyramid
  levels return 400 for `rgb_image` — composites are map-sized, and a
  silent luma fallback on the interactive path is the trap §Option A
  describes.
- `calc/thumbnail.py` gains an RGB branch so `.fvp` thumbnails are
  colour rather than silently absent (today `ndim != 2` → `None`).

### 5. One shader branch, not a parallel viewer

`gl/render.ts` gains `setImageRgb8` and a `u_mode` uniform: mode 0 is
today's 16-bit-scalar-through-LUT; mode 1 samples the texture as
colour, bypassing window/level/LUT/transform. One renderer already
serves `Stage`, `CompareStage` and `SideBySideStage`, so one branch
covers all three, and pan/zoom/measure geometry is untouched. The
display panel (window/level, colormap, transform, invert) is disabled
for `rgb_image` — those controls have no meaning the app is prepared
to define for colour, and a disabled control is honest where a
quietly-ignored one is not. `ImageMeta`'s spectral classification
becomes kind-aware (`kind in (SPECTRUM, SPECTRUM_IMAGE)`) — today's
`is not IMAGE` would classify the new kind as spectral and crash on
`energy_axis`.

### 6. Persistence: enum widening, version stays 2

`fvp-v2.schema.json`'s `kind` enum gains `"rgb_image"`, and the `axes`
description is amended (spatial axes only for `rgb_image`). Derived
images are always embedded (ADR 0002 §2), and `pixels/<id>.npy` holds
`[H,W,3]` uint8 natively, so the container needs nothing new. New
builds read old projects unchanged. An **old build opening a project
containing a composite fails schema validation loudly**, naming
`images[i].kind` — unknown-key preservation (ADR 0002 §6) cannot cover
an unknown enum value, and this cost is identical for any kind ever
added; accepted.

## Consequences

**Good.** The composite reaches every surface the owner named through
the pipeline that already serves every other image — one library, one
id namespace, one save path. The 13-site silent-wrong group becomes one
audited boundary that future kinds also pass through. The strict
rejecters keep rejecting with zero edits. `session.py` is untouched.

**Costs.** A shader branch and a second binary endpoint. A schema enum
change that locks composites out of old builds (loudly). The
consolidation refactor must preserve 13 sites' exact semantics —
mitigated by doing it as a separate no-behavior-change commit gated by
the full suite before the new kind exists. Frontend `DataKind` union
widens and each consumer surface must branch or disable deliberately.

**Rejected alternatives.** *Recipe-only persistence* (store the species
list and recompose on load) — already rejected by the owner gate: that
is the panel-local canvas restated. *Widening `DataKind.IMAGE` to admit
3D* — forfeits the 8 free rejecters and makes every `is IMAGE` site
ambiguous. *Per-channel window/level for RGB* — nothing in the app
wants it; the tuning surface is the species list, before composition.

## Verification

- `DataStruct` round-trip: `rgb_image` construct/validate (uint8,
  `[H,W,3]`, 2 axes), and rejection of float RGB, RGBA, and 3-axes.
- Raster boundary: `raster_of` on all four kinds; mutation check that
  the luma constants are BT.601 (not channel mean).
- Consolidation is behavior-preserving: full suite green on the
  refactor commit alone, before the new kind exists.
- Registration: POST → library list shows `rgb_image` with parent
  lineage → `/render` PNG decodes to the posted pixels → `/rgb8`
  round-trips exactly; `data16` and tiles return 400.
- Project round-trip: save → load preserves pixels, axes, recipe
  metadata; thumbnail entry is colour; a v2 project *without*
  composites still validates against the widened schema.
- Frontend: FilmCard shows the PNG; Stage/Compare render via mode 1
  (jsdom-level: the mode/branch selection is unit-tested; shader output
  is not jsdom-testable); display controls disabled for the kind.
- Spectral gates: each of the 7 returns 400 for `rgb_image`, not a
  crash.
