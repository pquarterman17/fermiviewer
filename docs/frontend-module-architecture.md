# Frontend module decomposition

This note records the ongoing application of the backend's god-module discipline
to the React/TypeScript frontend. It is intentionally both an implementation map
and a review handoff: future maintainers should be able to understand why files
were split without reconstructing the change from Git history. Update it as
splits land — the point is that the reasoning outlives the diff.

## First step: the API client split

The 2,240-line `frontend/src/lib/api.ts` client was split by existing API domain.
The original file remains as a stable barrel, so every current consumer continues
to import from `lib/api`. This is a structural refactor only: endpoint paths,
payloads, response types, macro recording, and public export names are unchanged.

| Module | Responsibility |
| --- | --- |
| `api/core.ts` | Shared wire types, session/image reads, and measurement primitives |
| `api/transport.ts` | Internal response decoding and macro-aware JSON POST transport; deliberately not exported by the public barrel |
| `api/eels.ts` | EELS background, maps, thickness, deconvolution, quantification, and model fitting |
| `api/eds.ts` | EDS quantification, continuum/peak fitting, artifacts, recalibration, and spectrum-image maps |
| `api/diffraction-export.ts` | Diffraction detection/indexing types plus the base image-export request |
| `api/imaging.ts` | Filters, FFT/GPA/VDF/radial operations, particles, grains, jobs, and trained segmentation |
| `api/metadata-export.ts` | User metadata, calibration management, raw import, rename, and composite/batch/GIF export |
| `api/structure.ts` | Atoms, strain, stitching, CTF, lattice, montage, simulation, ELNES, and advanced measurement endpoints |
| `api/workspace.ts` | Session/workspace persistence and render URL construction |
| `api/layers.ts` | Cross-section layer and interface-roughness endpoints |

The domain modules may import the shared `json()` and `post()` helpers from
`transport.ts`. Feature code outside `lib/api/` should continue using the public
`lib/api.ts` barrel unless it has a measured bundle-boundary reason not to.

## Size ratchet

`tests/test_repo_integrity.py` now applies a 500-line default to production `.ts`
and `.tsx` modules. Existing files already above that ceiling are listed with
their current line counts. Those entries are temporary debt allowances: they may
shrink, but cannot grow. Remove an allowance when its file is split below 500.

Tests are excluded because long fixture-driven test modules do not have the same
runtime coupling and ownership risk as production modules.

## Extractions since the API split

Workshop-level extractions have landed opportunistically, driven by the offset
rule rather than as a planned campaign: `EelsWorkshop.tsx` sat exactly at its
cap, so each change that added lines had to pay for them by extracting at least
as many. That is the ratchet working as designed — "raise the cap" is meant to
feel wrong and "extract a module" is meant to feel natural.

| Module | Extracted from | Why it is cohesive |
| --- | --- | --- |
| `workshops/eelsWindows.ts` | `EelsWorkshop` | Seeds background/signal fit windows from an energy range; pure function, no React |
| `workshops/EelsEdgeEditor.tsx` | `EelsWorkshop` | One editable edge row (element, Z, shell, onset, signal window); presentational only |
| `workshops/useProbeRegionToken.ts` | `EelsWorkshop` | One-shot marker for the region the live probe published, so the region-load effect skips exactly one redundant fetch |

`EelsWorkshop.tsx` is 813 → 732 lines across these, with the cap lowered each
time. `useProbeRegionToken` is the instructive one: the dedup logic had been
inline and therefore untestable, and it was wrong — the marker was written but
never consumed, so it silently became a permanent filter that served stale
spectrum and quantification data under a correct-looking region label. Pulling
it into a named module with stated semantics is what made the bug expressible
as a test.

## Remaining decomposition order

The three structural targets are untouched; line counts as of 2026-07-19:

1. `store/viewer.ts` (1778): extract persisted preferences, image/session
   actions, and display/overlay slices while keeping selectors stable. The
   undo/redo slice (`UndoEntry`, `undoLabel`, `UNDO_CAP`, `applyUndoEntry`,
   `HistoryStep`, `describePatch`) is the most self-contained first group.
2. `components/Shell/MenuBar.tsx` (1583): extract menu definitions and command
   handlers by menu group.
3. `components/Stage/Stage.tsx` (1234): separate render lifecycle, pointer
   interaction, overlays, and context-menu wiring.
4. Large workshops (`StructureWorkshop` 1353, `DiffractionWorkshop` 1090):
   split calculation state, request orchestration, plots, and result panels one
   workshop at a time.

These should be separate PRs. Mixing store, stage, and workshop refactors makes
behavioral regressions difficult to isolate and review.

Two constraints bind every split here and are easy to violate silently:

- **Stable Zustand snapshots.** A selector must not construct a fresh value
  (`?? []`, an object literal) without `useShallow`; under React 19 that
  re-renders forever and presents as a black screen. Prefer one selector
  returning an already-stable reference and destructure in the component body.
- **Lazy-loading boundaries.** Overlays and workshops are `React.lazy` chunks
  with one Suspense boundary each. After a split, confirm the expected
  per-overlay chunks still appear in `frontend/dist/assets/` — a stray static
  import silently folds a chunk back into the main bundle.

## Reviewer checklist

For Claude or another reviewer vetting this refactor:

- Compare the barrel's exported symbol set with the pre-split `api.ts` exports.
- Confirm every original source line appears once in a domain module, apart from
  the two shared helpers becoming exports and adjusted relative imports.
- Confirm `record()` remains in the shared POST path and `recordPathOp()` remains
  on the FFT endpoint.
- Run frontend type-check, unit tests, and production build.
- Run `tests/test_repo_integrity.py` to verify all new API modules are below the
  default ceiling and the legacy caps match current production files.
- Treat any endpoint or payload change as out of scope for this refactor.
