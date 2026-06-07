"""FastAPI app assembly + uvicorn entry point (`uv run fv`).

One-command launch: when frontend/dist exists it is mounted at `/`, so
`uv run fv` serves both the API and the SPA on :8000 and opens the
browser. `uv run fv --dev` runs the Vite dev server (HMR, :5173) and a
reloading uvicorn side by side in a single terminal.

Desktop-style lifecycle: the SPA holds a WebSocket open; when the last
tab disconnects (and stays gone past a refresh-safe grace period) the
server exits instead of lingering in the terminal. Armed only by
main()'s non-dev path — never under tests or --dev.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from fermiviewer import __version__

if TYPE_CHECKING:
    import uvicorn

_HOST = "127.0.0.1"
_PORT = 8000
_SHUTDOWN_GRACE_S = 4.0

# lifecycle state (single-process desktop deployment)
_auto_shutdown = False
_server: uvicorn.Server | None = None
_clients = 0
_ever_connected = False


def _request_shutdown() -> None:
    if _server is not None:
        _server.should_exit = True  # graceful uvicorn exit
    else:  # pragma: no cover — fallback when run outside main()
        import os

        os._exit(0)


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
    from fermiviewer.routes.jobs_api import router as jobs_router
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
    app.include_router(jobs_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.websocket("/api/ws")
    async def lifecycle_ws(ws: WebSocket) -> None:
        """Client-presence socket: the SPA connects on load; when the
        last connection drops and stays gone for the grace period, the
        server shuts down (if armed by main())."""
        global _clients, _ever_connected
        await ws.accept()
        _clients += 1
        _ever_connected = True
        try:
            while True:
                await ws.receive_text()  # idles until disconnect
        except WebSocketDisconnect:
            pass
        finally:
            _clients -= 1
            if _auto_shutdown and _clients == 0:
                asyncio.get_running_loop().create_task(_grace_check())

    # serve the built SPA at / — routes are matched before mounts, so
    # /api/* keeps working; html=True gives index.html fallback
    dist = _frontend_dist()
    if dist is not None:
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=dist, html=True), name="spa")

    return app


async def _grace_check() -> None:
    """Shut down unless a client reconnected within the grace window
    (a tab refresh disconnects and reconnects within ~1 s)."""
    await asyncio.sleep(_SHUTDOWN_GRACE_S)
    if _auto_shutdown and _ever_connected and _clients == 0:
        print("last tab closed — shutting down")
        _request_shutdown()


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
    parser.add_argument(
        "--no-auto-shutdown",
        action="store_true",
        help="keep the server running after the last tab closes",
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

    # hold the Server object so the lifecycle watchdog can stop it
    global _auto_shutdown, _server
    _auto_shutdown = dist is not None and not args.no_auto_shutdown
    server = uvicorn.Server(uvicorn.Config(app, host=_HOST, port=_PORT))
    _server = server
    server.run()


if __name__ == "__main__":
    main()
