# fermiviewer

Electron-microscopy image analysis: TEM/STEM image viewing, EELS / EDS /
diffraction analysis, measurements, and image processing. Python (FastAPI)
backend + React frontend + Tauri desktop shell.

Ground-up port of [fermi-viewer](https://github.com/pquarterman17/fermi-viewer)
(MATLAB), which remains the reference implementation during the port —
this repo verifies against frozen MATLAB reference outputs in
`tests/golden/`.

## Development

```bash
# backend
uv sync --group dev
uv run fv                 # FastAPI on :8000
uv run pytest             # tests (golden-verified; realdata tests skip if corpus absent)
uv run ruff check src tests && uv run mypy src

# frontend
cd frontend
npm install
npm run dev               # Vite on :5173, /api proxied to :8000
```

## Project docs

| Doc | Purpose |
|---|---|
| `PORT_PLAN.md` | Execution order — workstreams W1–W8 |
| `PORT_CHECKLIST.md` | ~150-item feature inventory from the MATLAB version |
| `design/handoff/` | Frontend spec + interactive prototype (visual source of truth) |
| `tests/golden/` | Frozen MATLAB reference values (see `tools/matlab/`) |

## License

Apache-2.0. No GPL runtime dependencies — enforced by
`tests/test_repo_integrity.py` (rosettasciio is a dev-only test oracle).
