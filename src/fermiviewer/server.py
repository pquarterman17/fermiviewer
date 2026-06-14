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
from urllib.parse import urlparse

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from fermiviewer import __version__

if TYPE_CHECKING:
    import uvicorn

_HOST = "127.0.0.1"
_PORT = 8000
_SHUTDOWN_GRACE_S = 4.0


def _origin_allowed(origin: str) -> bool:
    """True for the app's own origins — any localhost-family host (the
    served SPA on :8000, the Vite dev server on :5173, a pywebview window)
    and the Tauri desktop shell. Everything else (a real web origin like
    https://evil.example) is a cross-origin caller and is rejected — this
    is the localhost-CSRF / DNS-rebinding guard for the API."""
    if origin.startswith("tauri://") or origin.endswith("tauri.localhost"):
        return True
    try:
        host = urlparse(origin).hostname
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}

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
    """frontend/dist — repo layout in dev, bundled data when frozen
    (PyInstaller sidecar packs the SPA under <bundle>/frontend/dist)."""
    import sys

    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:  # PyInstaller: one-dir puts datas under _internal
        candidates.append(Path(meipass) / "frontend" / "dist")
        candidates.append(
            Path(sys.executable).resolve().parent / "frontend" / "dist"
        )
    candidates.append(
        Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )
    for dist in candidates:
        if (dist / "index.html").is_file():
            return dist
    return None


def create_app() -> FastAPI:
    """Build the FastAPI app. Routers attach here as they land (W5)."""
    from fermiviewer.routes.analysis import router as analysis_router
    from fermiviewer.routes.analysis_wireups import router as wireups_router
    from fermiviewer.routes.calibration import router as calibration_router
    from fermiviewer.routes.dev import router as dev_router
    from fermiviewer.routes.export import router as export_router
    from fermiviewer.routes.export_batch import router as export_batch_router
    from fermiviewer.routes.filter import router as filter_router
    from fermiviewer.routes.images import router as images_router
    from fermiviewer.routes.imaging_ops import router as imaging_ops_router
    from fermiviewer.routes.jobs_api import router as jobs_router
    from fermiviewer.routes.measure import router as measure_router
    from fermiviewer.routes.session_io import router as session_io_router
    from fermiviewer.routes.structure import router as structure_router
    from fermiviewer.routes.usermeta import router as usermeta_router

    app = FastAPI(title="fermiviewer", version=__version__)

    @app.middleware("http")
    async def _csrf_guard(request: Request, call_next):
        """Reject cross-origin calls to /api/* so a malicious web page in
        the user's browser can't drive the localhost API (open/read/write
        files) via the user's session. Requests with no Origin header
        (same-origin navigations, the desktop shell, curl, tests) pass."""
        if request.url.path.startswith("/api"):
            origin = request.headers.get("origin")
            if origin and not _origin_allowed(origin):
                return JSONResponse(
                    {"detail": "cross-origin API request blocked"}, status_code=403
                )
        return await call_next(request)

    for _router in (
        images_router, analysis_router, wireups_router, measure_router,
        filter_router, export_router, export_batch_router, session_io_router,
        imaging_ops_router, structure_router, jobs_router, calibration_router,
        dev_router, usermeta_router,
    ):
        app.include_router(_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # logging ring buffer + bug-report payload (checklist O)
    from fermiviewer import logbuf
    from fermiviewer.session import store as _store

    logbuf.install()

    @app.get("/api/debug/report")
    def debug_report() -> dict[str, object]:
        import platform
        import sys

        return {
            "version": __version__,
            "python": sys.version,
            "platform": platform.platform(),
            "open_images": [
                {"id": i, "name": _store.name(i)} for i in _store.ids()
            ],
            "server_log": logbuf.entries(),
        }

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


def _run_desktop() -> None:
    """Desktop standalone (handoff §11 option B): uvicorn in a thread,
    pywebview native window on top — pure Python, no Rust toolchain.
    Closing the window stops the server."""
    import threading

    import uvicorn
    import webview

    if _frontend_dist() is None:
        print(
            "frontend/dist not found — build it once with:\n"
            "    cd frontend && npm run build"
        )
        return

    global _server
    server = uvicorn.Server(
        uvicorn.Config(app, host=_HOST, port=_PORT, log_level="warning")
    )
    _server = server
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    webview.create_window(
        "FermiViewer",
        f"http://{_HOST}:{_PORT}",
        width=1440,
        height=920,
        background_color="#16141d",
    )
    try:
        webview.start()
    finally:
        server.should_exit = True
        t.join(timeout=5)


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
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="run as a desktop app in a native window (pywebview)",
    )
    args = parser.parse_args()

    if args.dev:
        _run_dev()
        return
    if args.desktop:
        _run_desktop()
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
