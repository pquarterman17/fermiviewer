# CLAUDE.md — fermiviewer

Python/FastAPI + React port of fermi-viewer (MATLAB EM image analysis).

## Commands

```bash
uv sync --group dev                  # install backend deps
uv run fv                            # ONE command: API + SPA on :8000, opens browser
                                     #   ONCE /api/health answers, exits when last tab closes
                                     #   (--no-auto-shutdown to keep). `fermiviewer` == `fv`
uv tool install --from . fermiviewer # expose `fermiviewer` on PATH; `fermiviewer <dir>`
                                     #   defaults the in-app Open dialog to <dir> (launch cwd)
uv run fv --desktop                  # desktop standalone: native window (pywebview), exits on close
uv run fv --dev                      # dev: Vite HMR (:5173) + reloading backend, one terminal
uv run pytest                        # all backend tests
uv run pytest -m "eels and golden"   # marker-scoped
uv run ruff check src tests
uv run mypy src
cd frontend && npm test              # frontend unit tests (vitest + jsdom)
cd frontend && npm run build         # (re)build the SPA that `uv run fv` serves
uv run python tools/offline/make_bundle.py
                                     # air-gapped source-install kit (wheel w/
                                     #   baked SPA + dep wheelhouse + installer)
```

## Architecture & hard rules

- **Layering:** `io/` and `calc/` are pure libraries (ndarray/DataStruct
  in → results out). They NEVER import fastapi/pydantic/routes — enforced
  by `tests/test_repo_integrity.py`. `routes/` is thin adapters only.
- **License:** Apache-2.0. NO GPL runtime deps (rosettasciio/hyperspy/
  exspy). rosettasciio is allowed ONLY in `[dependency-groups].oracle`
  as a test-time parser cross-validation oracle. Enforced by test.
- **God-module ceiling:** 500 lines per source module, enforced by test.
  Split before merging; never raise the ceiling casually — the MATLAB
  predecessor hit 14k lines in one file and the decomposition took weeks.
- **Physics constants port verbatim** from fermi-viewer. Annotated
  do-not-"fix" items (ZAF C=1.0e22, diffraction 0.5 px center offset,
  R-centering obverse rule) are calibrated/intentional.
- **Parsers:** single registration in `io/registry.py`; ambiguous
  extensions get content sniffers.

## Verification model

- `tests/golden/` — frozen MATLAB outputs (source commit in
  `manifest.json`). Regenerate via MATLAB:
  `run('tools/matlab/freeze_reference_values.m')` (needs ../fermi-viewer).
- Markers: `golden` (compares vs goldens), `realdata` (needs local-only
  corpus; auto-skips), `oracle` (needs rosettasciio dev group).
- The MATLAB repo `../fermi-viewer` is the reference implementation;
  its real-instrument corpus is shared via the conftest fixtures.

## Planning docs (gitignored — per-machine, like fermi-viewer's plans/)

Live plans in `plans/`:
- `CROSS_SECTION_LAYERS.md` — layer & interface-roughness analysis
- `DESIGN_GUI_ENHANCEMENTS.md` — workshop redesign + UI polish
- `FEATURE_AUDIT_2026-06-21.md` — parity vs MATLAB, gaps analysis
- `GUI_V2_PHASE4.md` — GUI iteration phase 4
- `PLAN_4DSTEM.md` — 4D-STEM data model support
- `PLAN_DATA_FORMATS.md` — file format parser coverage
- `PLAN_DIFFRACTION.md` — diffraction analysis & calibration
- `PLAN_QUICK_WINS.md` — high-impact quick features
- `PLAN_SCRIPTING_WORKFLOW.md` — Python scripting API
- `PLAN_SPECTRAL_QUANT.md` — EELS/EDS quantification methods
- `PORT_CHECKLIST.md` — full feature inventory; check items only
  when ported AND tested
- `PORT_PLAN.md` — port phases W1–W8, tiered items, Completed log
- `REPO_HEALTH_2026-07-07.md` — codebase health audit
- `plans/archive/` — completed plans

- `design/handoff/` — frontend spec HTML + extracted text; the prototype
  is the visual and behavioural source of truth for all UI work

These exist only on machines where they've been copied; if absent, ask
the user rather than recreating from scratch.
