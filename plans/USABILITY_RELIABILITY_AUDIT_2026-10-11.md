# Usability and reliability audit — EDS, AFM, and analysis workflows

**Status:** Active — items 1–7 shipped; item 8 implemented, awaiting review

**Owner:** Codex (lead implementation); Claude reviews each pull request

**Created:** 2026-10-11

**Source baseline:** `main` at `882fb3d` after PR #264

This plan records the post-implementation audit requested while the next
release is being prepared. It concentrates on observed bugs and difficult
workflows rather than adding new analysis families. EDS and AFM receive first
priority because they have had the least sustained usability testing.

## Audit evidence

- Backend: 4,065 passed, 8 skipped.
- Ruff: passed.
- mypy: passed across 310 source files.
- Frontend: 2,000 tests passed across 248 files.
- Production build: passed; the main minified bundle is approximately 584 kB
  and still triggers Vite's chunk-size warning.
- Real-data suite: 128 passed, 4 skipped (optional oracle dependencies).
- Live EDS testing used the real Bruker BCF fixture
  `rosettasciio_bcf_v2_50x50px.bcf`.
- Live AFM testing used the TopoStats SPM fixture. ISO 25178 values and plots
  appeared internally coherent.

Passing gates do not invalidate the findings below: several are state-ownership
or interaction problems that the current unit tests do not exercise.

## Delivery rules

1. Ship one focused pull request at a time, in the order below unless a newly
   discovered data-loss or correctness bug takes priority.
2. Codex implements and tests each change; Claude reviews before merge.
3. Preserve access to expert controls while improving safe defaults.
4. Every async-state fix needs a regression test that changes the active image
   before the first request resolves.
5. Run the complete repository quality gate before pushing each PR.

## Tier 1 — correctness and stale-state prevention

### 1. Reject impossible EDS auto-identification candidates

On the real BCF sum spectrum, automatic identification offered U and Be with
negative background-subtracted net counts (roughly -7,600 and -33,000) and
large negative significance, labelled both as `trace?` and included in the
"found" count. A line-location match is not positive evidence when its measured
window is below the estimated background.

Acceptance criteria:

- Automatically identified candidates with `net <= 0` are omitted.
- Positive low-significance candidates remain visible as unticked `trace`
  rows, preserving the ability to inspect genuine trace elements.
- Manually added elements remain visible even if their measured net is not
  positive; explicit user intent differs from an automatic recommendation.
- Unit tests cover negative, zero, and positive trace integrations.

### 2. Give long-running analysis requests shared ownership semantics

EDS Quantify can complete after the user changes cubes, writing the old result
and maps into the newly visible workspace. Auto-assign and composition-profile
have the same structural risk. AFM Roughness and Noise can similarly attach an
old result to a new active image and then export it under the new image name.

Acceptance criteria:

- A shared latest-request/generation helper owns cancellation and stale-result
  suppression instead of each panel maintaining an ad-hoc boolean.
- EDS Quantify, auto-assign, composition-profile, AFM Roughness, and AFM Noise
  do not commit status, results, or derived images after their source image has
  changed.
- Switching images aborts abortable network requests.
- Deferred-response tests prove stale successes and stale failures are ignored.

## Tier 2 — EDS usability

### 3. Open spectra at a useful energy range

The tested BCF advertises approximately -0.473–40.460 keV, so the initial
full-axis view compresses all useful peaks into the left side of the plot.

Acceptance criteria:

- Initial and one-click "fit useful spectrum" views use the occupied signal
  range, bounded by available beam-energy metadata when appropriate.
- A clearly labelled reset action restores the complete acquired axis.
- Manual zoom remains untouched by background updates to the same spectrum.
- Tests cover negative starting energies, long empty tails, and spectra without
  beam-energy metadata.

### 4. Explain accepted and rejected element candidates

The current element list conflates detected elements, weak possibilities, and
rejected matches, making a line-tolerance hit look more authoritative than it
is.

Acceptance criteria:

- Detected/recommended elements are visually separate from possible or
  rejected candidates.
- Rejection reasons are concise and concrete (for example, "below estimated
  background" or "line overlap").
- Counts and summary copy distinguish accepted elements from candidates.
- Re-identifying preserves evidence for manually added species, including
  non-positive measurements, until the user removes or re-measures them.
- Keyboard and screen-reader users receive the same status information.

### 5. Make the elemental workspace coexist with the image

The elemental modal can obscure the source image, and key controls are placed
below an internal scroll region. Add a collapsible inspector or full-workspace
mode and remember the user's preferred size without hiding the image context.

## Tier 2 — AFM usability and reliability

### 6. Surface multichannel AFM data at import time

"Open Other Channels" is buried under Analysis → AFM/SPM, while library rows
primarily show the shared filename. Users cannot easily tell which height,
phase, error, or auxiliary channel they are viewing.

Acceptance criteria:

- Import presents an unobtrusive channel summary/selector when multiple
  channels are available.
- Library entries and relevant titles include the channel identity.
- Existing open-other-channels behavior remains available for incremental use.

### 7. Clarify the two AFM pixel-size readouts

The stage showed 0.552 nm/px while calibration showed 0.7401 nm/px during the
same session. The former is a zoom-adjusted on-screen scale; the latter is the
physical sampling calibration. Rename and explain both so they cannot be read
as contradictory calibrations.

### 8. Improve ISO 25178 result navigation

Twenty metrics and three plots currently form one long scroll. Add a compact
summary and collapsible metric groups while retaining the complete table and
exportability.

## Tier 3 — repository and runtime quality

### 9. Centralize canvas behavior in frontend tests

jsdom's repeated `HTMLCanvasElement.getContext` warnings make it difficult to
notice new console errors despite a green test suite. Install one intentional
canvas mock in the shared test setup and fail on unexpected console errors.

### 10. Split the production bundle

The main minified JavaScript bundle is approximately 584 kB. Introduce route or
workshop-level lazy loading, then verify that loading/error states remain
coherent and common analysis workflows do not regress.

### 11. Make Ctrl+C shutdown quiet and successful

`uv run fv --no-auto-shutdown` shuts services down but prints a full
`CancelledError`/`KeyboardInterrupt` traceback and exits with status 1. Treat a
single interactive interrupt as an orderly shutdown.

### 12. Audit remaining async analysis panels

After item 2 establishes the shared primitive, search all analysis workshops
for requests that can outlive their source image, ROI, or parameter generation.
Migrate them systematically and add only targeted regressions; do not perform a
blind mechanical rewrite.

## Deferred observations

- 4D-STEM and tomography enhancements remain deliberately last in the broader
  roadmap because they are comparatively rare workflows.
- New analysis families are out of scope for this bug/usability pass.

## Progress log

- 2026-10-12 — Item 8 implemented: ISO 25178 results now open with a compact
  five-metric surface summary, keep all 21 parameters in collapsible standard
  families with definitions, and present the PSD, height distribution, and
  slope distribution in one keyboard-accessible tabbed plot area. CSV/JSON
  export and measurement provenance are unchanged. Verified live against the
  real TopoStats minicircle fixture; the test tab and server were closed after
  verification. Awaiting Claude review.

- 2026-10-12 — Item 7 shipped in PR #273 after review and the complete CI
  matrix. Item 8 started on the next focused branch.

- 2026-10-11 — Item 7 implemented: the zoom-dependent stage readout is now
  explicitly labelled **Displayed scale** and uses physical-unit/screen-pixel
  notation, while the fixed acquisition calibration is labelled **Image
  sampling** with a concise explanation that it is independent of display
  zoom. Anisotropic data calls out the displayed column scale, and
  uncalibrated images say the value is unavailable rather than showing an
  unexplained dash. Verified live with the real TopoStats AFM fixture; the two
  formerly conflicting values are now clearly distinguished.

- 2026-10-11 — Item 6 implemented: active multi-channel AFM/SPM imports now
  show a compact library channel inventory and selector. Closed channels can
  be opened individually, all remaining channels can still be opened in one
  action, bulk opening preserves the channel currently on stage, and library
  cards plus the Inspector identify the channel independently of the shared
  filename. The legacy Analysis → AFM/SPM → Open Other Channels action remains
  available. Full gate: 4,069 backend tests passed (8 skipped), Ruff and mypy
  passed, 2,038 frontend tests passed, and the production build passed.

- 2026-10-11 — Item 5 implemented: the shared Elemental Analysis window now
  remembers its preferred size across EDS/EELS, can collapse to reveal the
  source image or expand into a full-workspace view, and keeps long candidate
  lists in a bounded scroll region so map mode and export controls stay
  reachable. Awaiting Claude review.

- 2026-10-11 — Item 2 AFM half implemented: Roughness and Noise analysis now
  use the shared source-scoped request lease, as does Noise's recommended-filter
  action. Switching images aborts pending work, clears local busy/results, and
  cannot display or export the old analysis under the new filename, ingest the
  old derived filter, or switch the viewer back to the old source. Deferred
  response regressions cover all three paths. Awaiting Claude review.
- 2026-10-11 — Item 2 EDS half implemented on a focused follow-up branch:
  shared abortable latest-request ownership plus active-source checks now guard
  Quantify, auto-assign, and composition-profile success, failure, and cleanup.
  Deferred-response regressions switch cubes before each request resolves. AFM
  Roughness and Noise remain the second item-2 PR after this one is reviewed.
  Claude's first review caught a tab-remount reset that could erase a valid
  at% legend; the redundant reset was removed and both panel-mount and full
  Quantify → Maps → Quantify → Maps regressions now preserve the result.
- 2026-10-11 — Audit recorded. Item 1 implemented by Codex with regressions
  for negative, zero, positive-trace, and manual negative-net cases. Claude's
  review found that choosing the nearest line before measuring could hide an
  element whose other matched line was strongly positive; all matched lines
  are now measured and the highest positive significance wins. Full revised
  gate: 4,065 backend tests passed (8 skipped), Ruff and mypy passed, 2,004
  frontend tests passed, and the production build passed. Awaiting re-review.
