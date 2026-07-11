# Frontend module decomposition

This note records the first step in applying the backend's god-module discipline
to the React/TypeScript frontend. It is intentionally both an implementation map
and a review handoff: future maintainers should be able to understand why files
were split without reconstructing the change from Git history.

## Scope of this change

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

## Remaining decomposition order

The next highest-value splits are:

1. `store/viewer.ts`: extract persisted preferences, image/session actions, and
   display/overlay slices while keeping selectors stable.
2. `components/Shell/MenuBar.tsx`: extract menu definitions and command handlers
   by menu group.
3. `components/Stage/Stage.tsx`: separate render lifecycle, pointer interaction,
   overlays, and context-menu wiring.
4. Large workshops: split calculation state, request orchestration, plots, and
   result panels one workshop at a time.

These should be separate PRs. Mixing store, stage, and workshop refactors makes
behavioral regressions difficult to isolate and review.

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
