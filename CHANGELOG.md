# Changelog

All notable changes to FermiViewer are documented here, newest first.

This file is the **source of the GitHub Release notes**. The `release`
workflow (`.github/workflows/release.yml`) extracts the section whose header
matches the pushed `vX.Y.Z` tag and sets it as that release's body. When you
cut a release, add a `## [X.Y.Z] - YYYY-MM-DD` section here **in the same
`chore(release): vX.Y.Z` commit** that bumps the seven version sources. If no
section matches a tag, the workflow falls back to GitHub's auto-generated
commit list.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to adhere to [Semantic Versioning](https://semver.org/).

## [0.1.18] - 2026-07-23

Part 2 of the BCF/EDS element-navigation work: read peaks off the spectrum by
name.

### Added
- **Characteristic X-ray peak labels on the spectrum.** Peaks are marked with
  the element line they correspond to — auto-detected peaks (matched to K/L/M
  lines) as dashed grey markers, plus the selected element's lines in solid
  blue. A "Label peaks" toggle (on by default) hides them when the spectrum
  gets busy. New `GET /eds/lines` returns the characteristic lines within an
  energy window.

## [0.1.17] - 2026-07-23

Part 1 of the BCF/EDS element-navigation work: making spectrum-image cubes
easy to explore instead of scrolling thousands of raw energy channels.

### Added
- **EDS cubes open into the Spectrum-Image Explorer.** Loading a Bruker BCF
  (or any EDS spectrum-image) now opens the Explorer automatically — landing
  you on the sum spectrum and element maps instead of a ~4096-channel frame
  stepper. It opens once per cube; the Stage's raw channel stepper stays
  available for per-channel views.

## [0.1.16] - 2026-07-23

A large usability release, pairing a ground-up keyboard-accessibility and
UI-polish wave with a new guided cross-section layer & grain analysis
workflow (PRs #55–#84).

### Added
- **Guided cross-section workflow** — a step-by-step guide walks you through
  cross-section layer analysis (orient → identify layers → measure grains)
  instead of hunting for the right controls. (#78–#84)
- **Per-layer grain measurement** — grain statistics can be scoped to an
  individual film layer, so a multilayer stack reports grains layer-by-layer.
- **Region-of-interest scoping** — layers and grains can be restricted to a
  drawn ROI, keeping analysis off substrate, glue lines, and foil edges.
- **Spatial confidence preview for trained grains** — the trained-grain
  classifier shows a per-pixel confidence map before you commit a
  segmentation. (#84)
- **Questionable-detection flagging** — low-confidence detections are flagged
  for review rather than trusted silently.
- **Live spectrum explorer** — probe EELS/EDS spectra live by scrubbing the
  stage, with the probe debounced and cancellable. (#70, #73)
- **Live Appearance preview** — colormap / window–level changes preview on the
  image in real time, and the theme toggle stays in sync with the preview.
  (#68, #72)
- **Empty-stage welcome card** and graceful compact-window handling.
- **Full keyboard operation** across desktop menus, popup menus, the library,
  and the command palette, with proper ARIA semantics. (#55, #57, #61)
- **Standardized modal dialogs** and **descriptive workflow tooltips**.
  (#62, #69)
- **SVG toolbar icons** replacing the previous glyph font.
- Documented keyboard & accessibility operation in the README. (#66)

### Changed
- Workshop styles are split out and workshops/modal overlays are lazy-loaded,
  trimming the initial bundle so the app opens faster. (#59, #64)

### Fixed
- Tooltips no longer strand on screen (a click-focus path re-armed the dwell
  timer on self-removing buttons); also fixed label overflow and a dead probe
  CSS selector. (#77)
- The grains panel now refreshes after a stage edit (previously it could show
  stale results from the prior stage).
- The grain workflow preserves source lineage and is source-aware. (#78)
- EELS probe fixes: keep the stage probe live and the region picker working,
  consume the probe-region token instead of leaving it set, and queue
  overlapping parameter dialogs instead of clobbering them. (#74–#76)
- Workshops and large result tables scale correctly; disabled-menu hover
  styling and assorted review-flagged a11y/harness defects resolved.
  (#65, #67, #71)

**Full changelog:** https://github.com/pquarterman17/fermiviewer/compare/v0.1.15...v0.1.16

## [0.1.15] and earlier

Releases up to and including v0.1.15 predate this changelog; see the
[GitHub Releases page](https://github.com/pquarterman17/fermiviewer/releases)
for their notes.
