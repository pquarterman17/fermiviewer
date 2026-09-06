# ADR 0009 — Named, versioned calibration profiles; results snapshot the profile they used

**Status:** Accepted
**Date:** 2026-09-06
**Modules:** `src/fermiviewer/io/profiles_model.py`, `src/fermiviewer/io/profiles_db.py`, `src/fermiviewer/routes/profiles.py`, `src/fermiviewer/io/results_model.py`, `src/fermiviewer/models.py`
**Plan:** `plans/MICROSCOPY_FEATURE_ROADMAP.md` item 5a, boxes 1, 4 and 5 (named profiles; validity, source, date, operator note, uncertainty, version history; snapshot the applied profile into each result)
**Builds on:** ADR 0004 §5 (results snapshot calibration; item-5 keys extend the same entries), ADR 0008 (calibration is per-axis `AxisCal`; profiles wrap that record)

## Context

Every quantitative analysis in the tree depends on numbers the pixels do
not carry: beam energy, take-off angle, camera length, detector pixel
pitch, live time, probe current. Today each is a request-body field or an
`OpParam` with a hard-coded default (`200` kV, `20°`, `1.0` mm/px,
`100` s) and not one of them is ever read from a file's metadata, even
where a parser records it (`beam_kv`, `live_time_s`, `elevation_angle_deg`
are written by the FEI, JEOL, EDAX and Bruker readers and read by
nothing). The user types the same instrument facts into every workshop,
a result records whatever was typed, and two results computed a month
apart under "the same detector" cannot say whether it was the same
detector.

The spatial half is solved. ADR 0008 made the record per-axis `AxisCal`
and ADR 0004 §5 snapshots it into every result, deliberately leaving room
for "detector/profile/standard identity, efficiency, dose and live-time
provenance, factor sets and their uncertainties" as further keys on the
same snapshot entry. The per-user calibration DB
(`~/.fermiviewer/calibrations.json`) already stores one instrument-state
fact — a pixel size under an `instrument|magnification` key — with a
note and a save time, but no version, no validity, no uncertainty, and
no way to carry anything but a length.

## Decision

1. **A profile is a named, versioned record of one kind.** Four kinds:
   `microscope`, `detector`, `camera`, `acquisition`. A profile has a
   stable id (`uuid4().hex[:12]`, the repo convention), a `name`, an
   integer `version` starting at 1, `created_at`/`updated_at`
   timestamps, and a per-record `schema` integer (1) so a later build can
   migrate one profile at a time, as `results[]` records do. Editing a
   profile never mutates a version: the store bumps `version`, appends
   the previous body to that profile's `history`, and writes the new
   body. History is store-only; it is never part of a snapshot.

2. **Physical fields are `{value, unit, sigma}`.** The same shape as a
   result's scalar output (ADR 0004 §3): `sigma` is absent, not zero,
   when no honest uncertainty exists. Descriptive facts (make, model,
   serial number, window material, detector type) are strings under
   `text`. `FIELD_UNITS` in `profiles_model.py` names the fields each
   kind is expected to carry and their canonical unit — `beam_energy` in
   `keV`, `take_off_angle` in `deg`, `probe_current` in `pA` — and a
   known field must state that unit, because "beam energy in eV where
   every consumer reads keV" is exactly the silent error profiles exist
   to remove. Unknown fields are accepted as given: the table is a
   vocabulary, not a schema, and a lab's own quantity must not be
   refused.

3. **Applicability is data, checked on apply, never a refusal.**
   `validity` carries optional `valid_from`/`valid_to` dates and
   inclusive `[low, high]` ranges for beam energy (keV), magnification
   and camera length (mm). Applying a profile to an image compares those
   against what the image's metadata states (`beam_kv`, `voltage_kV`,
   `acceleration_voltage_v`, `magnification`, plus the nested vendor
   keys the calibration DB already searches) and returns the reasons it
   falls outside as `applicability` on the response. The apply proceeds:
   the user may know the range is stale. The reasons are recorded in the
   image's applied snapshot so a result computed from it carries the
   caveat, not just the number.

4. **Provenance is one object per profile.** `provenance.source` (a
   datasheet, a measured standard, "manual"), `provenance.date` (when
   the calibration was established, distinct from `updated_at`),
   `provenance.operator` and `provenance.note`. ADR 0008 §6's single
   `calibration_source` string keeps its convention for the SPATIAL
   axes and gains one value: applying an acquisition profile that states
   a pixel spacing writes `profile:<id>@<version>`.

5. **An image carries the profiles applied to it as snapshots, one per
   kind.** `DataStruct.metadata["profiles"]` is `{kind: snapshot}` where
   a snapshot is the profile's JSON body (the `profile_to_json` shape —
   one shape, so a snapshot always reads back as a `Profile`) plus
   `applied_at` and `applicability`. Metadata already rides the `.fvp`
   manifest's `images[].metadata` and the project's existing
   unknown-key rule, so a project carries its applied profiles across
   machines without the per-machine profile store — the same reason
   ADR 0004 copies calibration values rather than keying into
   `calibrations.json`. An acquisition profile that states
   `pixel_size_row`/`pixel_size_column` (same unit, both positive) also
   writes the spatial axes through `recalibrate_axes`; a profile that
   states neither leaves the axes alone; one that states one of the two
   is refused as malformed, because half a spacing is not a spacing.

6. **Results snapshot the applied profiles.** `CalibrationSnapshot`
   gains a modelled `profiles` key — a copy of the source image's
   `metadata["profiles"]` at compute time — taken by the same
   `snapshot_calibration` every capture goes through, so every adopter
   of `capture_result` records its profiles with no per-route change.
   `CAL_KEYS` grows by `profiles`; an older build carries the key
   verbatim through `extra`, exactly as ADR 0004 §5 promised. A later
   edit to the profile in the store bumps its version and cannot touch
   the copy: the record says which version it used. Result comparison
   (`results_calibration.py`) reports a profile difference on a shared
   source as a note beside the pixel-size notes, never as a rejection.

7. **The store is a per-user JSON file beside the calibration DB.**
   `~/.fermiviewer/profiles.json` (`FV_PROFILES_PATH` overrides, for
   tests), shape `{"schema": 1, "profiles": {id: {...body..., history:
   [...]}}}`, written temp-then-replace, a corrupt file preserved as
   `.corrupt-<epoch>` and warned about — the `calibration_db` rules. A
   store whose `schema` is higher than this build reads is refused, not
   downgraded (the regions rule, ADR 0006).

8. **The legacy calibration DB is imported, not replaced.** Each
   `instrument|magnification` entry becomes an `acquisition` profile
   named by its key, carrying `pixel_size_row`/`pixel_size_column` in
   the entry's unit (a legacy single-length entry becomes square, as
   ADR 0008 decided for applying it), `magnification` when the key
   states one, the note as `provenance.note`, the save time as
   `provenance.date`, `provenance.source = "legacy calibration DB"`, and
   `text.legacy_key` so the import is idempotent: re-running it updates
   nothing and creates nothing for a key already imported. A malformed
   entry is skipped and named in the response, never fatal. The legacy
   file stays as it is and `/calibration/apply` with a key keeps
   working; the import is `POST /api/profiles/import-calibrations`, run
   when the user asks.

## Non-goals

* Consumers. No quant route reads a profile in this ADR. `profile_quantity(metadata, kind, field)` is the resolver they will call; wiring `beam_kv`, `take_off_angle_deg`, `live_time_s`, `camera_length_mm` defaults from the applied profiles is roadmap 5a box 3 and follows per consumer, each with a test that the typed value still wins.
* Detector efficiency curves and window models as computed quantities. A `detector` profile may carry an `efficiency` scalar and `window_thickness`; a curve is a future field, not a schema change.
* Named quantitative standards and factor sets (5b). They will reference a detector profile id and version, which is why the id and version are stable now.
* A profile editor. Per the roadmap ownership model the UI is a separate (Codex) piece; this ADR ships the wire (`ImageMeta.profiles`, the `/api/profiles` surface) it needs.

## Alternatives considered

* **Store profiles in the project file.** A profile describes an instrument, not a dataset; a lab's profiles are shared across projects and must outlive any one of them. What a project needs — which profile, which version, what it said — is the snapshot on each image and each result, and those do travel with the project.
* **One profile with four sections.** A microscope outlives its detectors and a detector serves several acquisition conditions; a combined record would version all four together and could not say which changed. Separate kinds keep the version history meaningful.
* **Refuse an apply outside the validity range.** The range is the profile author's best statement, and the user on the day may know better (a range typed conservatively, a magnification the file reports wrongly). Recording the reasons into the snapshot keeps the caveat in the result; refusing would push the user to delete the range.
* **Reference profiles from results by id and version.** The store is per-machine (ADR 0004's argument); a project opened elsewhere would have results pointing at profiles that do not exist. Copy, and let the id/version say where the copy came from.

## Verification

`tests/test_profiles.py` (pure layer): quantity/validity/provenance
validation, canonical-unit refusal, unknown-field acceptance, JSON
round-trip identity, unknown-key carry, versioned edits with history,
corrupt-store backup, higher-schema refusal, legacy import (square,
per-axis, malformed skipped, idempotent), applicability reasons against
image metadata in each spelling, `spatial_spacing` refusals.
`tests/test_api_profiles.py`: CRUD and history over the wire; apply
writes the snapshot and (for a spatial acquisition profile) the axes
with `calibration_source = profile:<id>@<version>`; unapply restores;
`ImageMeta.profiles`; a captured result carries the profiles it was
computed with and a later profile edit leaves it untouched; the record
round-trips through `.fvp` save and load with `profiles` modelled; a
snapshot written under a key this build does not model rides through
`extra`; result comparison notes a profile difference.
