# Results & Methods workspace

The Results & Methods window is the user-facing side of persisted analysis
records (ADR 0004). It keeps a scientific run separate from transient workshop
state: a record is an immutable snapshot of what ran, while reopening creates
editable working state.

## Saving a run

Saving is always explicit. Supported analyses expose **Save result** beside
their primary action:

- EDS quantification;
- particle analysis;
- intensity profile and polyline profile; and
- diffraction indexing.

Exploratory runs remain transient when the option is off. A saved run refreshes
the Results workspace immediately and retains resolved parameters, source and
derived image IDs, calibration, geometry, warnings, outputs and status.

## Finding and inspecting results

The workspace can search labels, analysis names, sources and products. It can
filter to the active image (including an image produced by the result), analysis
type and status, and group by creation time, sample, source or analysis.

Cards put scientific context before provenance: primary values and uncertainty,
warnings/failure state, source links, region/calibration summary, produced-image
links and saved outputs. Full parameters and stable IDs remain under the
Provenance disclosure.

## Reproduction actions

- **Reopen** selects the source and restores the saved geometry/settings in the
  originating workshop for inspection.
- **Rerun** executes the recorded reproduction key unchanged and saves the new
  run as a separate result. Derived maps/labels are added to the image library.
- **Duplicate with changes** opens an editable copy of the saved settings. The
  original record is never mutated.

If the source image is unavailable, actions fail honestly in the status bar;
the card and its metadata remain inspectable. Failed and cancelled records do
not offer reproduction actions because they may not have usable outputs.

## Scope boundary

This workspace consumes the compare and report-manifest backend delivered by
roadmap item 2B, but item 2C owns their visual comparison/report builder. A
report manifest is not a self-contained export bundle: large member-backed
arrays still live in the project container, so the structured-bundle roadmap
item remains open.
