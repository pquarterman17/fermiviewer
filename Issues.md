# FermiViewer testing audit

**Date:** 2026-10-11  
**Auditor:** ChatGPT

This audit focused on broad analysis reliability, with extra attention to the EDS and AFM workflows. It records confirmed defects, interaction risks, and testing gaps as an implementation-ready to-do list.

## P0 — Restore the quality gate

- [x] Fix Windows mypy failures in `src/fermiviewer/session_fourd.py`.
  - Remove or revise the obsolete `type: ignore` on `msvcrt.locking`.
  - Isolate the Unix `fcntl.flock`, `LOCK_EX`, and `LOCK_NB` implementation so Windows type checking does not evaluate unsupported platform stubs.
  - Rerun the complete backend and frontend quality gate afterward.

## P1 — Confirmed user-facing bugs

- [x] Prevent AFM surface analysis from crashing on one-pixel-wide or one-pixel-high ROIs.
  - Confirmed with a `1 × 4` input: `calc/afm_surface.py` indexes `fy[1]` and raises `IndexError`.
  - The PSD-derived surface-map path in `ops/catalogue_afm.py` makes the same assumption about both axes.
  - Either reject undersized ROIs with a clear validation response or correctly support degenerate dimensions.
  - Add calculation and API regression tests for `1 × N`, `N × 1`, `1 × 1`, and narrow cropped ROIs.

- [x] Add cancellation and request-generation tracking to EDS ROI and sum-spectrum requests.
  - `useEdsSpectrumSource.ts` issues unguarded `fetchSpectrum` requests for ROI and whole-cube spectra.
  - Rapid ROI changes can resolve out of order, allowing an older spectrum to replace the newest result.
  - Switching datasets is unsafe when the original dataset remains open in the library.
  - A stale request can clear the busy indicator while a newer request is still running.
  - Reuse the abort/generation pattern already used by live spectrum probing and element maps.

- [x] Fix stale AFM result labels and exported provenance after changing the analysis region.
  - AFM Surface displays and exports the current region label while retaining the previous calculation's ROI.
  - Roughness has the same mismatch.
  - Noise marks a result stale, but its footer and export metadata still adopt the newly selected label.
  - Capture the region label with each result, or invalidate results whenever their inputs change.

## P2 — Workflow robustness

- [x] Guard AFM force-map processing against closing or switching the source file during analysis.
  - `AfmForceWorkshop.tsx` has no cancellation or request-generation guard around the long-running map request.
  - A response from an old file can ingest derived maps after the user switches files.
  - Closing the source while backend registration finishes may result in an unknown-file failure.
  - Disable conflicting lifecycle controls while processing, or make the operation snapshot-safe and cancellable.

- [x] Improve EDS beam-energy validation.
  - Clearing the beam-energy input immediately converts it to zero.
  - With bremsstrahlung subtraction active, lowering beam energy below the selected energy window can leave an old, now-invalid map visible.
  - Add inline validation, disable invalid recomputation/export, and visibly mark existing results stale when parameters become invalid.

- [x] Expand EDS interaction tests.
  - Cover out-of-order ROI responses.
  - Cover switching between two still-open spectrum images during a request.
  - Cover Sum → ROI → live-probe transitions.
  - Verify that busy state belongs to the newest request.
  - Verify that closing a source cancels pending work.

- [x] Expand AFM interaction tests.
  - Change region or leveling method after an analysis.
  - Switch images during analysis.
  - Close or switch a force file while maps are being calculated.
  - Verify that exported provenance describes the inputs actually used.

## P3 — Coverage gaps

- [ ] Restore the missing AFM real-instrument samples under `C:\Users\patri\git\test-data`.
  - Twenty-four focused AFM tests skipped because expected Bruker, JPK, Asylum, Gwyddion, Nanonis, Nanosurf, NT-MDT, and WSxM samples were unavailable.
  - Synthetic coverage passes, but real vendor parser behavior remains under-tested on this machine.

- [ ] Run the optional parser-oracle dependency group periodically.
  - Four EDS/parser oracle tests skipped because RosettaSciIO was unavailable.
  - Keep it development-only so the application continues to satisfy the no-GPL-runtime-dependency rule.

## Audit verification snapshot

| Check | Result |
|---|---|
| Backend suite | 4034 passed, 29 skipped |
| Focused EDS/realdata | 361 passed, 4 skipped |
| Focused AFM | 102 passed, 24 skipped |
| Ruff | Passed |
| Mypy | Failed: 4 Windows platform-locking errors |
| Frontend test/build gate | Not run because the prescribed full gate stops at the mypy failure |

## Recommended implementation order

1. Repair the Windows mypy failure.
2. Add the AFM narrow-ROI guard.
3. Add EDS spectrum-request cancellation and generation tracking.
4. Correct AFM result labeling and provenance.
5. Harden the AFM force-map lifecycle.
6. Add EDS beam-energy validation.
7. Fill the identified automated and real-instrument coverage gaps.
