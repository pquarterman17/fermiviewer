# ADR 0001 — 4D-STEM data model: a separate `FourDDataset`, not a `DataKind`

**Status:** Accepted
**Date:** 2026-08-02

## Context

A 4D-STEM acquisition is `(scan_y, scan_x, det_ky, det_kx)` — one full
diffraction pattern per scanned probe position. Real acquisitions are large:
even a modest 256x256 scan of a 256x256 detector at uint16 is 8 GiB; the
Merlin/HyperSpy files in this project's test corpus range from a 132-frame
line-scan up to a 100x30 scan of a 144x144 detector.

The existing `fermiviewer.datastruct.DataStruct` contract is 3D-capped
(`DataKind.IMAGE` / `SPECTRUM` / `SPECTRUM_IMAGE`, `_EXPECTED_NDIM` enforces
it) and, critically, **freezes its entire buffer eagerly**:
`DataStruct.__post_init__` calls `self.data.setflags(write=False)` on
construction. Every existing consumer (routes, calc modules, the frontend
render pipeline) assumes a DataStruct's `.data` is already fully resident
and immutable.

## Options considered

### Option A — extend `DataKind` with a fourth, 4D member

Add `DataKind.FOURD_STEM` and let `DataStruct.data` be 4D.

Rejected:

- `__post_init__` would have to materialize (or at least fully read) the
  array to call `setflags(write=False)` on it — exactly the whole-cube load
  this data model exists to avoid. A `FourDDataset` needs to hand back one
  diffraction pattern or one row of the scan at a time; a frozen dataclass
  wrapping a fully-loaded ndarray cannot do that.
- Every existing `match`/`if ds.kind is DataKind.X` site (dozens, across
  calc/ and routes/) would need a new branch it has no way to handle
  correctly — a 4D kind is not "a bigger image", it needs a completely
  different API (`pattern(y, x)`, streamed reductions), not `.data` sliced
  differently.
- `_EXPECTED_NDIM` and `DataStruct.__post_init__`'s shape/axes validation
  are deliberately simple because the type is deliberately narrow. Bending
  that to fit a fourth, structurally different kind is exactly the kind of
  scope creep the frozen 3-kind contract was designed to resist.

### Option B — a separate `FourDDataset` class (chosen)

`calc/fourd/dataset.py`'s `FourDDataset` wraps a lazy handle (an
`h5py.Dataset` for HyperSpy-4D files, a memmap-backed accessor for Merlin
`.mib`) and exposes exactly the operations a 4D-STEM workflow needs:

- `pattern(y, x)` — one diffraction pattern, on demand.
- `iter_scan_rows(block_rows=...)` — stream `(row_start, block)` pairs, one
  block of scan rows at a time; nothing above `calc/fourd/` ever sees the
  whole cube.
- `nav_image` / `mean_pattern` — the two reductions every 4D-STEM workflow
  needs first (detector-summed intensity per scan position; scan-averaged
  pattern), computed by streaming `iter_scan_rows` once and cached.

It is a **plain, mutable class**, not a frozen dataclass: caching a
computed reduction is exactly the kind of in-place state a frozen
`DataStruct` is deliberately built to prevent (the whole point of freezing
`DataStruct.data` is that a *parsed, already-real* array must not silently
change under a consumer). A `FourDDataset` is closer to a file handle than
to parsed data — it never claims to already hold a value, only a way to
compute one lazily.

## Consequence: 4D *products* are ordinary 2D `DataStruct`s

The nav image, a mean pattern, or a future virtual/annular-detector map are
each a single 2D array once computed — there is no reason for them to be
anything other than a normal `DataKind.IMAGE` `DataStruct`, registered in
the existing `SessionStore` (`session.py`). This is why
`routes/fourd.py`'s `/nav` endpoint registers its result as a derived image
and returns an `ImageMeta`, not a `FourDMeta`: it flows through the
existing render/measure/export/LUT pipeline completely unchanged, with zero
new frontend code required to *display* a nav image.

Only the raw 4D cube itself — the thing that cannot be safely or
affordably materialized whole — lives behind `FourDDataset`, in its own
`FourDStore` (`session_fourd.py`) with a disjoint id namespace (`"4d-<n>"`
vs the image store's hex ids) so a 2D-image route can never be handed a 4D
id (or vice versa) and silently misbehave.

## Memory constraint (why streaming, concretely)

`FourDDataset`'s worst-case RAM for any one route is one row-block:
`block_rows * scan_x * det_ky * det_kx * itemsize` bytes, plus (for
`nav_image`) the `scan_y * scan_x` float64 output array — negligible next
to the cube. With the default `block_rows=8` and a 512x512 uint8 Merlin
detector, that's a few tens of MB per block regardless of how many total
scan positions the acquisition has; RAM usage is a function of the
detector and block size, never of the scan size.

## Also decided here: routes/images.py's `/session/open` wiring

A 4D file opened via `POST /api/session/open` registers into `FourDStore`
and comes back as a `FourDMeta` entry (see `models.py`) carrying an
`is_fourd: Literal[True]` discriminator — deliberately NOT shaped like an
`ImageMeta` (no `kind: DataKind`), so a frontend that doesn't yet render 4D
datasets can filter them out (`store/viewer.ts`'s `openPaths`) instead of
mis-treating one as a normal image with a broken thumbnail.
