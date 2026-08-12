# 4D-STEM Support

Adds pixelated-detector (4D-STEM) support to fermiviewer — the single biggest
structural gap in the 2026-06-21 feature audit (items #7–9 Tier-1, #23–25
Tier-3). A 4D scan is `[scan_y, scan_x, det_ky, det_kx]`: a 2D diffraction
pattern recorded at every probe position. This plan extends the data model to a
fourth dimension, ingests at least one 4D format, ships a dual real-space ↔
reciprocal-space viewer with virtual-detector imaging (Phase 1), then center-of-
mass / DPC / iDPC (Phase 2), with strain mapping, ptychography, and ACOM parked
as future work (Phase 3+). The defining constraint is **memory**: a single 4D
dataset routinely exceeds RAM, so the architecture is lazy/chunked from day one
and never assumes the whole cube is resident. py4DSTEM is **AGPL** and must NOT
become a runtime dependency — all math is reimplemented from primary references.

**Status:** Active (Tier 1 / Phase 1 COMPLETE 2026-08-02 — items #1–#6
all shipped + live-verified same day, `f6141b2..b4826b0`; remaining:
Tier 2 #7–#9 COM/DPC/iDPC — note #7's core math `com_shift_maps`
already landed in calc/fourd/virtual.py as a stretch goal — and parked
Tier 3. Item #14's first two usability follow-ups — the .mib scan-shape
GUI and the pattern-panel log toggle — shipped 2026-08-12; three remain)
**Parent:** MAIN_PLAN.md
**Created:** 2026-06-21
**Updated:** 2026-08-12 — item #14's top two usability follow-ups shipped:
the `.mib` scan-shape GUI (`POST /fourd/{id}/reshape` + a workshop control
with ranked factorisation suggestions — the parser always accepted a
`scan_shape` and nothing exposed it, so every headerless Merlin file opened
as a 10-px nav strip) and the pattern panel's log-intensity toggle.

**Previously, 2026-08-02** — REAL CORPUS SECURED (owner gate cleared: "no
point building if we don't have real data"): `../test-data/4dstem/` now
holds the pyxem demo set (Zenodo 10.5281/zenodo.15490547, CC BY 4.0):
`test_data.mib` (Merlin RAW R64 quad, 132 frames, 768-byte MQ1 headers)
PAIRED with `test_data.h5` holding the same 132 frames decoded to
(132,512,512) uint8 — real ground truth for a from-scratch MIB
descramble with no GPL reader in the loop; `twinned_nanowire.hdf5`
(HyperSpy SPED (100,30,144,144) u8); `smallPtychography.hspy`
((246,246,8,8) f32); `au_xgrating_100kX.hspy` (2D calibration
companion). CONSEQUENCE for #2: first parsers are **MIB + HyperSpy-4D**
(real data in hand); EMPAD/.blo DEFERRED — no public small EMPAD .raw
exists (known sets are multi-GB), blockfile candidates were 278 MB+.
Build started same day.

---

## Context

### How the pieces fit together

The entire 4D-STEM cluster hangs off **one decision**: how to represent a 4D
dataset given that `DataStruct` is hard-capped at 3D and `SessionStore` holds
fully-decoded arrays in RAM.

The slice of the codebase this plan touches:

- `src/fermiviewer/datastruct.py` — `DataKind` enum (`IMAGE`/`SPECTRUM`/
  `SPECTRUM_IMAGE`), `_EXPECTED_NDIM` map, and `__post_init__` ndim validation
  cap the contract at 3D. The frozen buffer (`data.setflags(write=False)`) and
  "energy axis always last" conventions assume an in-memory ndarray.
- `src/fermiviewer/session.py` — `SessionStore` keeps every image as a decoded
  `DataStruct` in a dict. A 256×256×128×128 float32 scan is ~4 GB; loading that
  whole-array breaks this model. The store is the second load-bearing change.
- `src/fermiviewer/io/registry.py` — single-registration extension dispatch.
  4D formats (EMPAD `.raw`+`.dm`, blockfile `.blo`, MIB `.mib`) register here.
- `src/fermiviewer/calc/` — pure libraries. `radial.py`
  (`radial_profile`/`azimuthal_integrate`), `eds_maps.element_map` (the
  scan-position integration loop), and `diffraction.py` are directly reusable
  for detector geometry and disk/center finding.
- `src/fermiviewer/routes/imaging_ops.py` — note the **existing** `analyze/vdf`
  endpoint is FFT-aperture masking over a *single 2D image*, unrelated to a 4D
  virtual detector. New 4D routes must NOT reuse the name `vdf` (see #5).
- `src/fermiviewer/routes/images.py` — `/image/{id}/spectrum` already supports a
  1-based region rect → region-summed spectrum. The 4D navigator↔pattern link is
  the exact same pattern one dimension up (probe position → diffraction pattern).
- `frontend/src/components/Stage/Stage.tsx` — WebGL stage + LUT; `CaptureBanner`
  / capture-mode picking; `DockPlot` for the linked secondary panel. The EELS/EDS
  `specnav` click→spectrum capture mode is the template for click→pattern.

### The big architectural decision (read this first)

`DataStruct` must NOT grow a 4D in-memory variant that follows the existing
"decode whole array into the frozen buffer" path — that guarantees OOM on real
data. Instead introduce a **lazy 4D dataset** that holds an open handle (HDF5 /
memmap) plus a precomputed, small **navigation image** (and optional mean
diffraction pattern), and fetches diffraction patterns / computes virtual maps
on demand by streaming over chunks. Two viable shapes (decide in #1):

- **Option A — new `DataKind.DIFFRACTION_STACK` on `DataStruct`** with a
  lazy-array `data` (h5py dataset or `np.memmap`, never `setflags(write=False)`
  on a memmap). Pro: one type everywhere, reuses session/metadata plumbing. Con:
  every `DataStruct` consumer assumes an in-RAM ndarray with frozen-buffer
  semantics; 4D would violate `__post_init__`, the spectral conveniences, and the
  render/raster paths — lots of `if kind is …` special-casing leaks out.
- **Option B (recommended) — a separate `FourDDataset` class** in a new
  `calc/fourd/` (or `io/fourd/`) module, NOT a `DataStruct`. It owns the lazy
  handle, the chunked-iteration helpers, the nav image, and the detector-geometry
  math. `SessionStore` gains a parallel registry (or a small wrapper) so 4D
  datasets get ids and metadata without pretending to be 2D/3D images. **Virtual
  detector / COM outputs ARE ordinary 2D `DataStruct` images** that register in
  the normal store and flow through the entire existing pipeline (LUT, measure,
  export, compare) for free. Pro: keeps `DataStruct`'s invariants intact (the
  500-line/frozen-buffer/3D contract stays honest), isolates all 4D complexity,
  and the *products* of 4D analysis are first-class 2D images. Con: a second
  store path + a 4D-specific metadata DTO.

Recommendation: **Option B.** It contains the blast radius, keeps the pure-layer
guards meaningful, and matches the natural data flow (4D in → 2D maps out). The
4D dataset is a *source*, like a file on disk; its outputs are images.

### Data / control flow (Option B)

```
  .raw/.blo/.mib (+sidecar)          on disk, GBs
        │  io/fourd/<format>.py  (lazy open: shape, dtype, calibration)
        ▼
  FourDDataset  ──holds──►  open handle (h5py / memmap)   [never fully in RAM]
        │                   nav image  [scan_y × scan_x]  ◄─ precomputed, small
        │                   mean DP    [det_ky × det_kx]  ◄─ precomputed, small
        │
        ├─ registered in SessionStore (4D registry) → id + FourDMeta
        │
   ┌────┴───────────────────────── routes/fourd.py (THIN) ─────────────┐
   │  GET  /fourd/{id}/nav            → nav image PNG/data16            │
   │  GET  /fourd/{id}/pattern?y=&x=  → single DP at a probe position   │
   │  POST /fourd/{id}/virtual-det    → BF/ABF/ADF/annular scan map     │
   │  POST /fourd/{id}/com            → COMx, COMy, DPC, iDPC (Phase 2) │
   └────┬──────────────────────────────────────────────────────────────┘
        │   each calc call streams the cube in chunks (scan-row blocks),
        │   integrating a reciprocal aperture per probe position
        ▼
  2D DataStruct (virtual-detector map / COM map / DPC)  ── add_derived ──►
        normal SessionStore → existing LUT / measure / export / compare
```

Frontend dual viewer:

```
  ┌──────────────────────┐        click / drag aperture        ┌──────────────────────┐
  │  REAL-SPACE (nav)     │  ──── probe (y,x) ───────────────►  │  RECIPROCAL (pattern) │
  │  scan map, WebGL LUT  │                                     │  diffraction DP        │
  │  draggable detector   │  ◄─── virtual-det map ───────────   │  draggable aperture    │
  │  ring overlay         │        recompute on aperture move   │  (BF/ABF/ADF/annular)  │
  └──────────────────────┘                                     └──────────────────────┘
        Stage.tsx instance                                     DockPlot / 2nd Stage panel
```

### Dependency map

- **#1 (data model decision) gates everything.** Do first.
- #2 (one 4D parser) requires #1. #3 (nav image + lazy handle) requires #1.
- #4 (dual viewer) requires #2 + #3. #5 (virtual detectors) requires #3.
- #6 (detector-geometry calc) is independent pure math; can land before #5 wires
  it to a route.
- Tier 2 (#7–9 COM/DPC/iDPC) requires the Phase-1 cube-streaming helper from #5.
- Tier 3 (#10–13) all require Phase 1 + 2; parked, not scheduled.
- The 500-line ceiling forces `calc/fourd/` and `routes/fourd.py` to be split by
  concern from the start (geometry / virtual-det / com as separate modules).

### Constraints (hard rules, enforced by tests)

- **Memory:** never `np.fromfile`/`h5py[...]` the whole cube. Stream in
  scan-row blocks; precompute only the nav image + mean DP eagerly. On-demand
  single-pattern fetch for the viewer. Document worst-case RAM per route.
- **Layering** (`tests/test_repo_integrity.py`): `io/fourd/` and `calc/fourd/`
  stay pure (numpy/scipy/h5py only — h5py is not GPL). `routes/fourd.py` is a
  thin adapter. No fastapi/pydantic in the pure layers.
- **License (Apache-2.0):** py4DSTEM and pyxem are **AGPL** → NOT runtime deps,
  not even an extra. Reimplement virtual-detector summation, COM, and DPC
  integration from primary literature (Müller-Caspary COM-DPC; Lazić iDPC). h5py
  (BSD) and a permissively-licensed `.blo`/MIB reader (or hand-rolled header
  parse) are fine. Keep py4DSTEM out of even the `oracle` dev group unless a
  clean-room cross-check is needed — prefer hand-computed fixtures.
- **500-line module ceiling:** split `calc/fourd/` by concern; no single module
  over 500 lines.
- **Single parser registration:** 4D formats register once in
  `io/registry.py`; `.raw` is ambiguous (already reserved for explicit-geometry
  raw images) → needs a content sniffer / sidecar-driven route, NOT a bare
  `.raw` map entry.

---

## Tier 1 — High Impact

*(Phase 1 — foundational: data model + one parser + dual viewer + virtual
detectors. Ship-blocking; nothing else in this plan works without these.)*

~~**1. 4D data-model decision + `FourDDataset` foundation**~~ (2026-08-02) —
   Option B chosen + ADR at `docs/adr/0001-fourd-data-model.md`;
   `calc/fourd/dataset.py` (lazy handle, iter_scan_rows, pattern(y,x),
   streamed nav_image + mean_pattern); `session_fourd.py` FourDStore with
   its own `4d-<n>` id namespace; `FourDMeta` DTO in models.py; layering
   covered by existing PURE_LAYERS walk. 67 new tests in the wave.

~~**2. One 4D parser**~~ (2026-08-02) — TWO shipped, driven by the real
   corpus (EMPAD/.blo deferred, no public small data): `io/fourd/mib.py` —
   from-scratch Merlin RAW reader; descramble reverse-engineered
   empirically (8-col word reversal → 2×2 chip split → 180° rotation of
   the bottom chip row; derived by signature-matching across all 132
   frames, 0 contradictions) and verified BYTE-EXACT vs the paired
   ground-truth h5 for all 132 frames — note rosettasciio CANNOT read
   RAW mib (raises NotImplementedError), so this exceeds the oracle.
   `io/fourd/hspy4d.py` — lazy HyperSpy-4D via content sniffer; 2D/3D
   hspy routing untouched. Both behind a parallel `_FOURD_LOADERS` /
   `load_fourd_auto` dispatch; `/session/open` registers 4D files in the
   FourD store. Realdata tests run via the NEW `FV_TEST_DATA` conftest
   override (also fixes the worktree realdata-skip trap repo-wide).
   Known bounds: single-chip MIB path unvalidated (no sample), no .hdr
   sidecar auto scan-shape, /session/upload (browser picker) not wired
   for 4D, no workspace save/load of FourD store.

~~**3. Lazy nav image + mean-pattern precompute + on-demand pattern
   fetch**~~ (2026-08-02) — streamed nav_image + mean_pattern cached on
   the dataset; `routes/fourd.py`: GET /api/fourd (list), /nav (registers
   a NORMAL 2D DataStruct → existing LUT/measure/export for free),
   /pattern?y=&x= and /mean-pattern (reuse the extracted
   `encode_raster_u16` helper from images.py). RAM stays O(row block +
   nav + DP), documented per route.

~~**4. Dual real-space ↔ reciprocal-space viewer**~~ (2026-08-02) —
   FourDWorkshop shipped as a lazy tool window ("4D-STEM Viewer" in
   Analysis + Window menus, unconditional like siblings): dataset picker,
   nav minimap canvas (probe click → debounced /pattern fetch), pattern
   canvas reusing the encode_raster_u16 wire format
   (ChannelComposite precedent, NOT a second WebGL Stage) with an SVG
   aperture ring (FftMaskWorkshop precedent), BF/ABF/ADF/Custom presets
   sized from det_shape, auto-center toggle, Compute → ingests the
   derived map through the standard path. Dataset selection deliberately
   does NOT hijack the main Stage — only "Show nav image"/Compute
   surface images. +30 vitest. LIVE-VERIFIED end-to-end on the real
   nanowire corpus (mean SPED pattern renders, BF map lands on the
   Stage with 10 nm/px calibration + scale bar, 0 console errors after
   backend-ready). Flagged v2: probe-picking on the MAIN Stage via a
   specnav-style capture mode (v1 probes the workshop minimap).

~~**5. Virtual-detector imaging (BF / ABF / ADF / annular)**~~
   (2026-08-02) — `POST /api/fourd/{id}/virtual-detector` in
   routes/fourd.py (250 lines): streams via iter_scan_rows at a 64 MiB
   block cap computed from shape/dtype; center null ⇒ auto from
   pattern_center(mean_pattern) (note: auto streams the cube twice —
   documented); registers the map via add_derived with scan-axis
   calibration; named virtual_detector everywhere (the analyze/vdf
   collision is called out in three docstrings). Realdata test asserts
   EXACT equality vs an independent h5py-streamed reference (provably
   exact: uint8 corpus keeps sums in float64's exact-integer range).
   Additive contract guards: center fields both-or-neither (422),
   inner_r genuinely ignored for circles.

~~**6. Detector-geometry calc module (pure)**~~ (2026-08-02) —
   `calc/fourd/geometry.py` (aperture_mask, pattern_center w/ degenerate
   fallback, radial_coverage) + `calc/fourd/virtual.py` (streamed
   `virtual_detector` over the iter_scan_rows protocol, BF/ABF/ADF
   presets, and `com_shift_maps` — Phase-2 #7's core landed early as a
   stretch goal, Müller-Caspary first-moment from the definition).
   DELIBERATE: 0-based (ky,kx) coords, NOT delegating to calc/radial.py's
   1-based MATLAB-port convention (documented inline — don't "fix").
   29 pure unit tests, block-size invariant vs dense.

---

## Tier 2 — Medium Impact

*(Phase 2 — center-of-mass / DPC / iDPC. Requires the Phase-1 cube-streaming
helper from #5. Headline STEM phase-contrast techniques.)*

> **DEFERRED by owner 2026-08-02** ("I think we can defer that") in favor
> of edge-case hardening + usability audit of the shipped surface. When
> picked up: #7's core math (`com_shift_maps`) is ALREADY in
> calc/fourd/virtual.py — remaining work is route wiring, the analytic
> tests below, idpc.py, and a workshop mode selector.

7. **Per-probe center-of-mass (COMx, COMy)** — the basis for all DPC.
   - [ ] `calc/fourd/com.py` — stream the cube; per pattern compute the intensity
     centroid → two scan maps (COMx, COMy). Optional descan/center subtraction
     using `geometry.pattern_center`. Reimplement from Müller-Caspary et al.
     (no py4DSTEM)
   - [ ] `POST /fourd/{id}/com` (THIN) → registers COMx/COMy as derived 2D images
   - [ ] Tests: synthetic shifted-disk cube → COM tracks the known shift

8. **Differential phase contrast (DPC) + charge-density / field maps** —
   from the COM vector field.
   - [ ] In `calc/fourd/com.py` (or a sibling, watch the 500-line ceiling):
     DPC magnitude/direction, divergence (→ charge density), curl-free
     integration setup. Calibrate COM→mrad→field with the detector calibration
   - [ ] Extend the `/com` route response (or a `/dpc` route) to return the
     derived field maps as 2D images
   - [ ] Tests vs an analytic field (e.g. uniform E-field → constant COM shift)

9. **Integrated DPC (iDPC)** — light-element phase imaging via 2D integration of
   the COM field.
   - [ ] `calc/fourd/idpc.py` — Fourier-space integration of (COMx, COMy) →
     iDPC image (Lazić/Bosch method); high-pass to suppress low-freq artifacts.
     Reimplement from the primary paper
   - [ ] Route + derived 2D image; frontend exposes BF/ABF/ADF/COM/DPC/iDPC as
     selectable virtual-output modes in `FourDWorkshop`
   - [ ] Tests: iDPC of a known potential reconstructs its phase up to a constant

---

## Tier 3 — Nice-to-Have

*(Phase 3+ — future / parked. Audit items #23–25. Each is multi-week and
AGPL-adjacent in the reference ecosystem — all math must be reimplemented. Listed
for completeness and to record the architectural runway; not scheduled.)*

10. **Disk-detection strain mapping** — *audit #23.* Detect/track Bragg-disk
    positions per probe (cross-correlation against a probe template), fit the
    lattice, map strain (εxx/εyy/εxy/θ). Reuses #6 center finding + a new
    template-match module. Reimplement (no py4DSTEM).

11. **Ptychography (SSB / WDD)** — *audit #24.* Single-side-band and
    Wigner-distribution-deconvolution phase reconstruction from the 4D set.
    Heavy compute; design a job/async path (existing `jobs.py`) since this can't
    be a synchronous request.

12. **Orientation / phase mapping (ACOM)** — *audit #25.* Diffraction template
    matching against simulated patterns (the TEM counterpart to EBSD). Depends on
    the diffraction-simulation work and a template library; reuse `calc/crystal.py`
    + `calc/diffraction.py` for pattern simulation.

13. **More 4D formats + async ingest** — additional readers (Gatan K2/K3,
    NCEM EMD 4D, EMPAD when real data exists — MIB shipped in #2), folder-watch
    ingest, and a job-queued virtual-detector batch for very large scans (ties
    into audit #34 batch-over-analysis).

14. **4D usability follow-ups** — from the 2026-08-02 live audit (the five
    objective defects it found were fixed same day: modal z-layering,
    nav contain-fit, true auto-center preview, watch-folder guidance,
    DELETE /api/fourd/{id}); these remain, in value order:
    - [x] **Scan-shape GUI for .mib** — shipped 2026-08-12, see Completed
    - [x] Log-intensity toggle on the pattern panel — shipped 2026-08-12,
      see Completed
    - [ ] Aperture radii in mrad when detector calibration allows.
    - [ ] Main-Stage probe picking via a specnav-style capture mode (the
      flagged v2 of #4).
    - [ ] Dataset-list live refresh (a dataset closed server-side only
      self-heals on next select/remount — flagged by the hardening pass).

---

## Completed

- ~~**#14 Scan-shape GUI for `.mib`**~~ (2026-08-12) — the top item for real
  Merlin users, and it was never a missing capability: `load_mib` has always
  accepted a `scan_shape`, and nothing anywhere exposed it. Every headerless
  acquisition therefore opened as a 1×N line-scan whose nav image is a
  ten-pixel strip.
  `POST /api/fourd/{id}/reshape` RE-OPENS the file under the requested raster
  rather than mutating the dataset: the scan shape reaches into the handle's
  frame indexing, the cached nav image and the cached mean pattern, and a
  partial update leaves a dataset that disagrees with itself. The 4D **id is
  kept** — the workshop selection, the probe and the registered nav image are
  all keyed by it, and a fresh id would silently deselect the dataset the user
  is looking at — while `FourDStore.replace` closes the old memmap (a reshape
  that leaked one per attempt would fail exactly on the large files this
  exists for) and drops the stale nav-image association, since that raster
  described the old shape.
  **`scan_shape_from_file` is the discriminator, set by the parsers**, not
  sniffed from a parser name in the route: `.mib` records no raster, `.hspy`
  has its navigation axes in the file, and re-rastering the latter would
  invite the user to contradict the acquisition (422). `FourDMeta` gained
  `n_frames` and `scan_shape_options` — `calc/fourd/scanshape.py` ranks the
  exact factorisations by squareness, because STEM scans overwhelmingly are,
  so 16384 frames offers 128×128 first rather than the 1×16384 the user came
  here to change. Both orientations are offered (nothing in the file
  distinguishes a 64-row scan from a 64-column one) and the 1×N line-scan
  always survives the list cap, being both a real acquisition mode and the
  parser default.
  The workshop control takes typed rows × cols with a live "must multiply to
  N frames (got M)" readout — naming the product so the user can see WHICH
  number to change — plus one-click suggestion chips that keep the typed
  fields in sync. Pinned by a value check, not a shape check: frame k must
  land at `(k // cols, k % cols)`, because a transposed re-raster produces a
  nav image that looks entirely plausible and is wrong. 14 backend + 10
  frontend tests.

- ~~**#14 Log-intensity toggle on the pattern panel**~~ (2026-08-12) —
  display ∝ log(1 + 1000·I), on by default. A 4D pattern runs from a
  saturated direct beam to Bragg disks three decades fainter; on the linear
  ramp the panel shipped with, everything except the direct beam is black.
  A pure `logStretchRaster` (display-only — the virtual-detector maps the
  server computes are untouched) that clamps negative/non-finite samples to
  zero rather than emitting a NaN LUT index, and copies rather than mutating
  the fetched raster. 5 tests, including monotonicity: a stretch that
  reordered intensities would be a lie about the diffraction pattern.
