# ADR 0008 — Calibration is per-axis in the project and the UI; `pixel_size` is a view of it

**Status:** Proposed (two owner gates, §Gates)
**Date:** 2026-09-05
**Modules:** `src/fermiviewer/datastruct.py`, `src/fermiviewer/models.py`, `src/fermiviewer/routes/calibration.py`, `src/fermiviewer/io/calibration_db.py`, `frontend/src/components/Inspector/CalibrationCard.tsx`
**Plan:** `plans/MICROSCOPY_FEATURE_ROADMAP.md` item 5a, second box ("per-axis spatial/scan/energy/reciprocal calibration; do not assume square pixels in the project/UI model")
**Builds on:** ADR 0002 (project file format), ADR 0004 (results carry calibration snapshots)

## Context

Between 2026-09-01 and 2026-09-05 every measurement in the tree stopped
assuming square pixels (PRs #202–#210: lengths, angles, areas, profiles,
radial averages, layer thicknesses, grain slices, Thon rings, lattice
vectors, spot indexing). The calcs now read `DataStruct.pixel_spacing`,
the `(row, column)` extent of one pixel, and `pixel_size` is by
definition the COLUMN scale alone (`pixel_cal` returns `axes[1]`).

The storage side was never the problem:

* `DataStruct.axes` is one `AxisCal(scale, origin, units)` per data
  dimension, so an image already carries two independent spatial scales
  (`io/nanoscope` sets them from `y_nm / ny` and `x_nm / nx`; 0.5 nm rows
  against 2.0 nm columns is an ordinary AFM scan).
* The `.fvp` manifest stores `images[].axes` per axis (ADR 0002), and
  every persisted result snapshots `calibration[].axes` per source at
  compute time (ADR 0004), so a later edit cannot rewrite what a stored
  number meant. The schema already says roadmap item 5 extends those
  entries.

The **edit** and **display** sides are where square pixels are still
assumed, and they are the only places a user touches:

* `routes/calibration.py::recalibrate(ds, pixel_size, unit)` builds ONE
  `AxisCal` and writes it to BOTH spatial axes. Every path into it —
  `/calibration/apply` with a manual value or a stored key,
  `auto_apply_calibration` on import, the scale-bar detector — therefore
  destroys any anisotropy the file had. A user who corrects a wrong
  magnitude on an AFM scan silently squares its pixels.
* `io/calibration_db.py` stores `{pixel_size, unit, note}` under an
  `instrument|magnification` key. A stored calibration cannot describe a
  scan whose two axes differ.
* `models.ImageMeta` exposes `pixel_size` and `pixel_unit` only. The
  Inspector's calibration card shows "2.0 nm/px" for the AFM scan above,
  and nothing in the UI can tell the user the rows are 0.5 nm. The
  drawn-line flow (`CalibrationCard.tsx`: draw a line, type its real
  length) yields one number and applies it to both axes.
* The energy axis is the same record (`AxisCal` on the last dimension of
  a spectrum image, the only dimension of a spectrum) and already has a
  per-dataset editor (`/eds/recalibrate`, anchor-based linear fit). It
  is not affected by this ADR beyond being named as the same model.

So the measurements are right on anisotropic data only until the first
time someone edits the calibration, and the user cannot see that the
data was anisotropic in the first place.

## Decision

1. **The calibration record is `AxisCal` per axis; there is no new type.**
   A spatial calibration edit is an edit to the two spatial `AxisCal`s.
   `pixel_spacing` and `pixel_area` stay the consumers' inputs;
   `pixel_size` stays the column scale — a display and single-length
   compatibility view, never a measurement input on its own. Named
   profiles (5a first box) will later WRAP per-axis records; they do not
   replace them.

2. **The wire exposes both axes.** `ImageMeta` gains
   `pixel_spacing: [row, column] | null`, null unless both spatial axes
   are calibrated in the same unit (the `DataStruct.pixel_spacing`
   refusal, ADR 0004). `pixel_size` is kept and equals `pixel_spacing[1]`
   whenever the latter exists; a test pins that identity so the two
   names cannot drift. The frontend `ImageMeta` type mirrors it, and
   "anisotropic" is derived (`row !== column`), not a third field.

3. **Edits take either one length or two.** `recalibrate()` gains a
   per-axis form, `recalibrate_axes(ds, (row, col), unit)`, and the
   isotropic form calls it with `(px, px)`. `/calibration/apply` accepts
   `pixel_spacing: [row, column]` as an alternative to `pixel_size`
   (exactly one of the two). When a caller supplies ONE length to an
   image that is already anisotropic, the row extent follows the image's
   existing ratio — `calc/calibration.spacing_at_column_scale`, the rule
   every calc already applies to a typed pixel size — rather than
   squaring the pixels. Clearing resets both axes, as today.

4. **Stored calibrations become per-axis, backward compatibly.** A DB
   entry gains optional `pixel_spacing: [row, column]`; `pixel_size`
   stays as the column scale (and the only field for square pixels).
   Readers of an entry without `pixel_spacing` treat it as isotropic, so
   existing per-user JSON files keep working unchanged. Keys are
   unchanged; a key names an instrument state, and whether that state
   has square pixels is a property of the entry.

5. **The calibration card edits per axis when asked.** Default mode is
   "square pixels" (one value, today's flow). A "per axis" mode shows
   rows and columns separately; the drawn-line flow assigns the typed
   length to the axis the line runs along (within 15° of horizontal →
   columns, of vertical → rows; a diagonal line is refused in this mode
   with a one-line reason) and leaves the other axis alone. The card
   always DISPLAYS both extents and their unit when they differ, so an
   anisotropic image is visibly anisotropic before anyone edits it.

6. **Provenance stays one string.** `metadata.calibration_source` keeps
   its convention (`manual`, `db:<key>`, vendor ids); per-axis manual
   edits write `manual`. Results already snapshot the axes they used,
   which is the audit trail that matters (ADR 0004).

## Non-goals

* Named microscope/detector/acquisition profiles, validity ranges,
  operator notes and version history (5a boxes 1, 3, 4, 5). They wrap
  the per-axis record; this ADR makes sure there is one to wrap.
* Reciprocal-space calibration as a stored quantity. Reciprocal spacing
  is DERIVED from the real-space per-axis record (PR #209/#210); a
  diffraction pattern loaded as an image carries its own `1/nm` axes
  through the same `AxisCal`.
* Any change to what a calc computes. PRs #202–#210 finished that; this
  ADR is about not undoing it at the edit surface.

## Alternatives considered

* **Keep isotropic editing, only display anisotropy.** Cheaper, but a
  user with an anisotropic scan and a wrong magnitude still cannot fix
  it without squaring the pixels — the exact case the edit surface
  exists for.
* **Make `pixel_size` the geometric mean for anisotropic images.** Every
  calc contract and every exported number defines it as the column
  scale; changing its meaning changes results silently, which is the
  failure class the whole thread was closing.
* **Introduce a `Calibration` object with profiles now.** Premature:
  profiles need detector, dose and standards fields that are not
  designed yet, and shipping the wrapper before its contents would fix a
  schema around guesses. Per-axis `AxisCal` is the stable core either
  way.

## Gates

* **G1 — one length on an anisotropic image.** Decision 3 keeps the
  existing ratio. The alternative is today's behaviour (square the
  pixels). Recommendation: keep the ratio; it matches how every calc
  already treats a typed pixel size, and the user who WANTS square
  pixels has the per-axis mode.
* **G2 — what the Inspector headline shows.** "2.0 nm/px" (column, as
  today) with a second line "rows 0.5 nm · columns 2.0 nm" when they
  differ, versus a single "0.5 × 2.0 nm/px" headline. Recommendation:
  the first; the headline is what the scale bar and every export label
  print, and those are column-scale by contract.

## Implementation stack (book under roadmap 5a)

* **5a-A backend (Claude PR).** `ImageMeta.pixel_spacing` + identity
  test; `recalibrate_axes`; `/calibration/apply` with `pixel_spacing`
  and the ratio rule for a single length; DB entries with optional
  `pixel_spacing`; `auto_apply_calibration` honours it. Tests: an AFM
  fixture (0.5 × 2.0 nm) round-trips an edit without losing anisotropy;
  an old-format DB entry still applies; every existing calibration test
  unchanged.
* **5a-B frontend (Codex PR, per the roadmap ownership model).**
  `ImageMeta.pixel_spacing` in the client type; CalibrationCard per-axis
  mode and the always-on two-extent display; CalibrationManager shows
  per-axis entries; nothing else in the UI changes meaning because
  `pixel_size` keeps its meaning.
* **5a-C correctness review (Claude).** Grep every frontend read of
  `pixel_size` and classify each as display (fine) or geometry (must use
  `pixel_spacing`); the measure overlay labels already use both extents
  since v0.4.0, so the expected finding is zero, but the list is the
  deliverable.
