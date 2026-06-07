"""FastAPI app assembly + uvicorn entry point (`uv run fv`).

One-command launch: when frontend/dist exists it is mounted at `/`, so
`uv run fv` serves both the API and the SPA on :8000 and opens the
browser. `uv run fv --dev` runs the Vite dev server (HMR, :5173) and a
reloading uvicorn side by side in a single terminal.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from fermiviewer import __version__

_HOST = "127.0.0.1"
_PORT = 8000


def _frontend_dist() -> Path | None:
    """frontend/dist relative to the repo layout, if built."""
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return dist if (dist / "index.html").is_file() else None


def create_app() -> FastAPI:
    """Build the FastAPI app. Routers attach here as they land (W5)."""
    from fermiviewer.routes.analysis import router as analysis_router
    from fermiviewer.routes.export import router as export_router
    from fermiviewer.routes.filter import router as filter_router
    from fermiviewer.routes.images import router as images_router
    from fermiviewer.routes.imaging_ops import router as imaging_ops_router
    from fermiviewer.routes.measure import router as measure_router
    from fermiviewer.routes.session_io import router as session_io_router
    from fermiviewer.routes.structure import router as structure_router

    app = FastAPI(title="fermiviewer", version=__version__)
    app.include_router(images_router)
    app.include_router(analysis_router)
    app.include_router(measure_router)
    app.include_router(filter_router)
    app.include_router(export_router)
    app.include_router(session_io_router)
    app.include_router(imaging_ops_router)
    app.include_router(structure_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # serve the built SPA at / — routes are matched before mounts, so
    # /api/* keeps working; html=True gives index.html fallback
    dist = _frontend_dist()
    if dist is not None:
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=dist, html=True), name="spa")

    return app


app = create_app()


def _open_browser_later(url: str, delay: float = 0.8) -> None:
    import threading
    import webbrowser

    threading.Timer(delay, webbrowser.open, [url]).start()


def _run_dev() -> None:
    """Vite dev server (HMR) + reloading uvicorn in one terminal."""
    import os
    import subprocess

    import uvicorn

    frontend = Path(__file__).resolve().parents[2] / "frontend"
    npm = "npm.cmd" if os.name == "nt" else "npm"
    vite = subprocess.Popen([npm, "run", "dev"], cwd=frontend)
    _open_browser_later("http://localhost:5173", delay=2.0)
    try:
        uvicorn.run(
            "fermiviewer.server:app", host=_HOST, port=_PORT, reload=True
        )
    finally:
        vite.terminate()
        vite.wait(timeout=10)


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(prog="fv", description="FermiViewer")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="run Vite dev server (HMR) alongside a reloading backend",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the browser automatically",
    )
    args = parser.parse_args()

    if args.dev:
        _run_dev()
        return

    dist = _frontend_dist()
    if dist is None:
        print(
            "frontend/dist not found — API only on "
            f"http://{_HOST}:{_PORT}. Build the UI once with:\n"
            "    cd frontend && npm run build\n"
            "or run `fv --dev` for the hot-reloading dev setup."
        )
    elif not args.no_browser:
        _open_browser_later(f"http://{_HOST}:{_PORT}")
    uvicorn.run("fermiviewer.server:app", host=_HOST, port=_PORT)


if __name__ == "__main__":
    main()
