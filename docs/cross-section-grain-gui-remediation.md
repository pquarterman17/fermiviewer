# Cross-section and grain GUI remediation

**Status:** active

**Created:** 2026-07-19

**Owner:** progressive Codex PR stack; each PR is held for Claude review before merge

## Progress

- PR 1: implemented in [#78](https://github.com/pquarterman17/fermiviewer/pull/78);
  awaiting Claude review.
- PR 2: implemented in [#79](https://github.com/pquarterman17/fermiviewer/pull/79);
  awaiting Claude review after PR 1.
- PR 3: implemented in [#80](https://github.com/pquarterman17/fermiviewer/pull/80);
  awaiting Claude review after PR 2.
- PR 4: implemented in [#81](https://github.com/pquarterman17/fermiviewer/pull/81);
  awaiting Claude review after PR 3.
- PR 5: guided shared-ROI cross-section workflow implemented in the current
  stacked change; awaiting Claude review after publication.

## Outcome

Turn the existing layer and grain analysis engines into a trustworthy
cross-section TEM/STEM workflow:

1. start from the obvious menu command;
2. keep the original micrograph as the analysis source while parameters are
   tuned;
3. restrict calculations to the film/ROI instead of vacuum and substrate;
4. distinguish a plausible detection from an algorithm result that merely ran;
5. review boundaries on the source image before committing derived data; and
6. measure grains within detected film layers.

This plan deliberately improves the workflow around the existing pure
`calc/` implementations before adding another segmentation algorithm.

## Evidence from the live-app audit

A diagnostic 512 x 512 cross-section with five intended interfaces and
columnar film texture exposed the following failures:

- `Analysis > Grain Segmentation` opened a legacy K-means-only parameter
  dialog, while the complete gradient/RAG/orientation/trained workflow was
  hidden under `Window > Structure Workshop > Grains`.
- Legacy K-means reported 24 grains dominated by whole intensity bands and
  small fragments. The default gradient workflow reported 1,976 grains and
  2,994 junctions. Both results were presented without a plausibility warning.
- The layer workflow reported seven interfaces, included outer image regions
  as layers, and did not offer the ROI already supported by the API.
- Grain completion activated the label image. A subsequent run then received
  the active label-image id rather than an explicit original-source id.
- The 360 px workshop frame clipped controls and introduced horizontal
  scrolling; the results window rendered every one of the 1,976 table rows.
- Trained-mode preview reported class percentages but did not show the spatial
  class/confidence result, although the calculation produces confidence data.

## Progressive PR sequence

Every PR must lower or preserve the frontend line-count ratchet, include focused
tests, pass the full repository gate, and state its dependency in the PR body.

### PR 1 - Entry point and source lifecycle

- Replace the legacy K-means-only menu action with a deep link to the complete
  Structure/Grains workshop.
- Preserve the original `grain_source` id after a label map becomes active.
- Ensure every retry targets the original raster, not the previous label map.
- Make the current analysis source visible in the workshop.
- Cover direct-menu navigation and source-preserving reruns.

Acceptance: the obvious Grain Segmentation command opens the full Grains mode,
and two consecutive runs both submit the original image id.

### PR 2 - ROI-scoped analysis

- Add a shared, tested conversion from stage ROI measurements/saved ROIs to the
  backend's 1-based inclusive rectangle.
- Surface `whole image` versus named/latest ROI in Layers and Grains.
- Thread ROI through `GrainRequest`; segment the crop and embed labels back into
  a source-sized map so overlays and edits remain aligned.
- Pass the same ROI through layer analyze/edit operations.

Acceptance: vacuum, substrate, scale bars, and damaged margins can be excluded
without destructively cropping the source.

### PR 3 - Quality and review states

- Add pure quality assessment helpers rather than burying thresholds in React.
- Layer checks: orientation coherence, interface fit R-squared, edge proximity,
  minimum separation, and disagreement with an optional layer-count hint.
- Grain checks: extreme count/density, fraction at the minimum-area cutoff,
  implausibly small median area, dominant border components, and low trained
  confidence.
- Present `good / review / poor` with reasons and corrective suggestions.
- Require explicit acceptance for poor results; never label "algorithm ran" as
  "detection is trustworthy".

Acceptance: the diagnostic failure modes receive visible warnings and a useful
next action.

### PR 4 - Workshop layout and result scalability

- Give Structure and Layers responsive/resizable working room and remove
  horizontal overflow at supported viewport widths.
- Keep controls and the source/result comparison visible during tuning.
- Paginate or virtualize large result tables while exporting the complete data.
- Make repeated attempts replace a preview instead of silently filling the
  filmstrip with derived images.

Acceptance: a 2,000-row result does not create 2,000 live table rows, and the
grain/layer controls remain usable at 1280 x 720 and the compact breakpoint.

### PR 5 - Cross-section assistant foundation

- Add a guided entry point that shares one ROI across the existing Layers and
  Grains workflows without duplicating either analysis implementation.
- Preserve reviewed results while moving among Region, Layers, Grains, and
  Report steps, including explicit acceptance of poor-quality detections.
- Export one provenance-rich report with source, calibration, ROI, layer, grain,
  quality-acceptance, and current-limitation metadata.
- State clearly that grain statistics currently cover the shared ROI and are
  not yet partitioned by layer.

Acceptance: a user can run and review both analyses in one assistant; report
export remains blocked until poor results are acknowledged, and revisiting a
step restores its result and review state.

### PR 6 - Per-layer grain measurements

- Let the user choose which detected bands are film layers rather than vacuum,
  protective cap, or substrate.
- Partition accepted grain labels by the reviewed layer interfaces.
- Report per-layer lateral grain width, through-film height, aspect ratio,
  boundary orientation, count/density, and grain size versus depth.
- Overlay the layer/grain assignment on the source for visual confirmation.

Acceptance: the report contains reviewed, spatially assigned grain metrics for
the selected film layers without counting vacuum or substrate.

### Follow-up - Spatial trained confidence

If it does not fit cleanly in PR 3, register/return the trained class and
confidence rasters as non-committing previews, add a low-confidence overlay,
and only create an editable grain-label image after acceptance.

## Scientific validation

The layer pipeline is net-new relative to the frozen MATLAB reference and its
current ground truth is synthetic. Before publication-grade claims, assemble a
small annotated, local-only `realdata` corpus covering:

- HAADF-STEM monotonic stacks;
- BF/DF-TEM diffraction contrast and thickness fringes;
- FIB curtaining and tilted interfaces;
- EELS/EDS maps with diffuse chemical interfaces; and
- columnar, equiaxed, and poorly resolved grains.

Record expected interface bands and acceptable grain-boundary regions rather
than pretending manual outlines are exact pixel truth. True crystallographic
orientation mapping remains a separate 4D-STEM/ACOM capability; structure-
tensor orientation must not be described as equivalent.

## Review checklist for Claude

For each PR, verify:

- `calc/` and `io/` remain pure and below 500 lines;
- no new frontend legacy cap or cap increase is introduced;
- source ids cannot silently change to a derived label id;
- coordinate conventions are explicit at ROI/API boundaries;
- failed/low-quality detection stays editable and is not presented as fact;
- full exports preserve rows hidden by pagination/virtualization; and
- `uv run pytest -q`, Ruff, mypy, frontend tests, and production build pass.
