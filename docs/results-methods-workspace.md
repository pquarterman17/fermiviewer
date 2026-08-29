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

## Comparing results

The **Compare** view chooses one completed result as a reference and asks the
backend's canonical compatibility rules which saved runs can be placed beside
it. Compatible records can be included or removed from a shared-output matrix.
Scalar outputs retain their uncertainty and units; tables, curves and other
outputs are identified by kind without pretending that unlike payloads are
scalar values. Calibration is labelled as matched, different, or not verified.

Rejected records remain inspectable under **Compatibility review**, with the
specific scientific reason (analysis, status, output kind, unit, or shared-
output mismatch) rather than an unexplained disabled control.

## Composing a report

The **Report** view lets the author select and order saved results, then choose
individual scalar, table, curve, fit, map, overlay, or figure outputs. Methods,
calibration summary, and review notes can be included independently. The
generated paper preview is the same self-contained HTML document used by
**Export HTML** and **Print / Save PDF**, so page output does not inherit the
application window's dark theme or controls.

Curves with embedded values render as vector SVG; inline tables and scalar
uncertainties remain selectable text. If a large member-backed output is only
cited by the report manifest, the report says that it remains stored in the
project rather than silently truncating it.

## Reproduction actions

- **Reopen** selects the source and restores the saved geometry/settings in the
  originating workshop for inspection, with result saving off. An exact live
  profile overlay is reused rather than duplicated.
- **Rerun** executes the recorded reproduction key unchanged and saves the new
  run as a separate result. Derived maps/labels are added to the image library.
- **Duplicate with changes** opens an editable copy of the saved settings. The
  original record is never mutated. For workshop analyses, **Save result** is
  armed so the edited run becomes a new record; profiles receive a separate
  editable overlay.

If the source image is unavailable, actions fail honestly in the status bar;
the card and its metadata remain inspectable. Failed and cancelled records do
not offer reproduction actions because they may not have usable outputs.

## Scope boundary

The workspace consumes the compare and report-manifest backend delivered by
roadmap item 2B. **Manifest JSON** remains explicitly labelled as a manifest,
not a self-contained data bundle: large member-backed arrays still live in the
project container. Packaging those member payloads beside the manifest remains
a separate backend/export item.
