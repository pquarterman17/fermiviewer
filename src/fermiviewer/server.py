"""FastAPI app assembly + uvicorn entry point (`uv run fv`).

One-command launch: when frontend/dist exists it is mounted at `/`, so
`uv run fv` serves both the API and the SPA on :8000 and opens the
browser. `uv run fv --dev` runs the Vite dev server (HMR, :5173) and a
reloading uvicorn side by side in a single terminal.

`uv run fv --script recipe.json inputs...` (Scripting #10) is a fourth,
fully headless mode: it never reaches any of the server/browser code
below at all, delegating straight to `cli_script.run_script` and exiting
with its return code — see that module for the recipe format and output
layout.

Desktop-style lifecycle: the SPA holds a WebSocket open; when the last
tab disconnects (and stays gone past a refresh-safe grace period) the
server exits instead of lingering in the terminal. Armed only by
main()'s non-dev path — never under tests or --dev.

An ACTIVE folder watch (routes/watch.py, Scripting #7) is a deliberate
exception to "last tab closed": watching a folder unattended means having
NO browser tab open by design, so the grace-check must not treat that as
abandonment. While `routes.watch.is_watch_active()` is true, the grace-check
reschedules itself instead of exiting; ordinary last-tab-closed shutdown
resumes as soon as the watch is stopped.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from fermiviewer import __version__
from fermiviewer.netprobe import (
    _await_health,
    _bind,
    _find_free_port,
    _port_listening,
)

if TYPE_CHECKING:
    import uvicorn

_HOST = "127.0.0.1"
_PORT = 8000
_SHUTDOWN_GRACE_S = 4.0

# Hostnames (port ignored) this server answers to — the DNS-rebinding
# guard. Production has NO "testserver"; tests/conftest.py extends this
# set once for the suite (TestClient sends `Host: testserver`).
ALLOWED_HOSTS: set[str] = {"127.0.0.1", "localhost", "::1"}


def _host_allowed(host_header: str | None) -> bool:
    """Host header (port/IPv6-brackets stripped) names our own hostname.

    Unlike `_origin_allowed`, this also catches DNS rebinding: a browser
    tricked into resolving evil.example to 127.0.0.1 sends NO Origin
    header (same-origin, from its view) but still `Host: evil.example`.
    """
    if not host_header:
        return False
    v = host_header.strip()
    if v.startswith("["):
        v = v[1 : v.find("]")] if "]" in v else v
    elif v.count(":") == 1:  # "host:port" — a bare IPv6 literal has 2+
        v = v.split(":", 1)[0]
    return v.lower() in ALLOWED_HOSTS


def _origin_allowed(origin: str) -> bool:
    """CSRF guard: True for this app's own origins (served SPA, Vite dev
    server, pywebview, Tauri). Only ever sees requests carrying an Origin
    header — same-origin/curl/desktop-shell calls send none and rely on
    `_host_allowed` instead, which is what actually covers DNS rebinding.
    """
    # exact Tauri origins only — `endswith` would also pass a crafted
    # `evil.tauri.localhost` from another local app
    if origin.startswith("tauri://") or origin in {
        "https://tauri.localhost",
        "http://tauri.localhost",
    }:
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
    (PyInstaller sidecar packs the SPA under <bundle>/frontend/dist),
    or fermiviewer/_spa package data in a wheel install (hatch_build.py
    bakes frontend/dist in at build time — the offline-install path)."""
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
    candidates.append(Path(__file__).resolve().parent / "_spa")
    for dist in candidates:
        if (dist / "index.html").is_file():
            return dist
    return None


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """On server stop, cancel still-queued background jobs so exit never
    waits behind a queue backlog (running jobs finish on their thread), and
    stop any active folder watch so its poll thread is always joined
    cleanly (never left to an atexit hook — see jobs.py's shutdown
    docstring for why that ordering matters)."""
    yield
    from fermiviewer.jobs import jobs
    from fermiviewer.routes.watch import shutdown_watch

    shutdown_watch()
    jobs.shutdown()


def create_app() -> FastAPI:
    """Build the FastAPI app. Routers attach here as they land (W5)."""
    from fermiviewer.routes.analysis import router as analysis_router
    from fermiviewer.routes.analysis_wireups import router as wireups_router
    from fermiviewer.routes.batch_ops import router as batch_ops_router
    from fermiviewer.routes.calibration import router as calibration_router
    from fermiviewer.routes.defect_ops import router as defect_ops_router
    from fermiviewer.routes.dev import router as dev_router
    from fermiviewer.routes.diffraction_setup import router as diffraction_setup_router
    from fermiviewer.routes.eds_advanced import router as eds_advanced_router
    from fermiviewer.routes.eds_maps import router as eds_maps_router
    from fermiviewer.routes.eds_quant import router as eds_quant_router
    from fermiviewer.routes.eels_advanced import router as eels_advanced_router
    from fermiviewer.routes.eels_identify import router as eels_identify_router
    from fermiviewer.routes.export import router as export_router
    from fermiviewer.routes.export_batch import router as export_batch_router
    from fermiviewer.routes.export_table import router as export_table_router
    from fermiviewer.routes.filter import router as filter_router
    from fermiviewer.routes.folders import router as folders_router
    from fermiviewer.routes.fourd import router as fourd_router
    from fermiviewer.routes.grains_trained import router as grains_trained_router
    from fermiviewer.routes.images import router as images_router
    from fermiviewer.routes.imaging_ops import router as imaging_ops_router
    from fermiviewer.routes.jobs_api import router as jobs_router
    from fermiviewer.routes.layers import router as layers_router
    from fermiviewer.routes.measure import router as measure_router
    from fermiviewer.routes.montage_compare import router as montage_compare_router
    from fermiviewer.routes.project_io import router as project_io_router
    from fermiviewer.routes.regions import router as regions_router
    from fermiviewer.routes.session_io import router as session_io_router
    from fermiviewer.routes.spectral_fit import router as spectral_fit_router
    from fermiviewer.routes.structure import router as structure_router
    from fermiviewer.routes.usermeta import router as usermeta_router
    from fermiviewer.routes.watch import router as watch_router

    app = FastAPI(title="fermiviewer", version=__version__, lifespan=_lifespan)

    @app.middleware("http")
    async def _security_guard(request: Request, call_next):
        """Host check (all paths, defeats DNS rebinding) then Origin
        check (/api/* only, the CSRF guard) — see `_host_allowed` /
        `_origin_allowed` for exactly what each one does and doesn't
        cover."""
        if not _host_allowed(request.headers.get("host")):
            return JSONResponse(
                {"detail": "unrecognized Host header"}, status_code=403
            )
        if request.url.path.startswith("/api"):
            origin = request.headers.get("origin")
            if origin and not _origin_allowed(origin):
                return JSONResponse(
                    {"detail": "cross-origin API request blocked"}, status_code=403
                )
        return await call_next(request)

    for _router in (
        images_router, analysis_router, wireups_router, batch_ops_router, measure_router,
        filter_router, export_router, export_batch_router, export_table_router, session_io_router,
        imaging_ops_router, defect_ops_router, structure_router, grains_trained_router,
        jobs_router, calibration_router, dev_router, usermeta_router,
        diffraction_setup_router, spectral_fit_router, eds_advanced_router,
        eds_quant_router, eds_maps_router, eels_advanced_router,
        eels_identify_router,
        layers_router, watch_router,
        fourd_router, folders_router, regions_router, montage_compare_router,
        project_io_router,
    ):
        app.include_router(_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        # "app" is the identity field the launchers key on: the sibling
        # quantized serves the same {"status": "ok"} shape on the same
        # default port (8000), and a probe that checks status alone adopts
        # it — rendering the wrong app's UI in a FermiViewer window.
        return {"status": "ok", "app": "fermiviewer", "version": __version__}

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

    app.websocket("/api/ws")(_lifecycle_ws)

    # serve the built SPA at / — routes are matched before mounts, so
    # /api/* keeps working; html=True gives index.html fallback
    dist = _frontend_dist()
    if dist is not None:
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=dist, html=True), name="spa")

    return app


async def _lifecycle_ws(ws: WebSocket) -> None:
    """Client-presence socket: the SPA connects on load; when the last
    connection drops and stays gone for the grace period, the server shuts
    down (if armed by main()). Module-level so its branches don't inflate
    create_app's complexity."""
    global _clients, _ever_connected
    # the HTTP middleware doesn't run on the WS upgrade — enforce the same
    # Host + Origin checks here (closing before accept() → HTTP 403).
    if not _host_allowed(ws.headers.get("host")):
        await ws.close(code=1008)  # policy violation
        return
    origin = ws.headers.get("origin")
    if origin and not _origin_allowed(origin):
        await ws.close(code=1008)  # policy violation
        return
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


async def _grace_check() -> None:
    """Shut down unless a client reconnected within the grace window
    (a tab refresh disconnects and reconnects within ~1 s) OR a folder
    watch is actively running (see this module's docstring): in that case
    reschedule another check instead of exiting, so ordinary shutdown
    resumes the moment the watch stops."""
    await asyncio.sleep(_SHUTDOWN_GRACE_S)
    if not (_auto_shutdown and _ever_connected and _clients == 0):
        return
    if _watch_active():
        asyncio.get_running_loop().create_task(_grace_check())
        return
    print("last tab closed — shutting down")
    _request_shutdown()


def _watch_active() -> bool:
    from fermiviewer.routes.watch import is_watch_active

    return is_watch_active()


app = create_app()

# --desktop (pywebview) and --dev (Vite HMR) launch paths live in
# server_launch.py — split out to respect the 500-line ceiling — and are
# re-exported here so main() below and existing tests/monkeypatches keep
# working unchanged.
from fermiviewer.server_launch import (  # noqa: E402 — re-export
    _open_browser_later,  # noqa: F401
    _open_when_healthy,
    _run_desktop,
    _run_dev,
)


def main() -> None:
    import argparse
    import os

    import uvicorn

    from fermiviewer import launch

    parser = argparse.ArgumentParser(
        prog="fermiviewer", description="FermiViewer — EM image analysis"
    )
    parser.add_argument(
        "dir",
        nargs="?",
        default=None,
        help="folder to default the in-app Open dialog to "
        "(default: the directory you launched from)",
    )
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
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="bind port (default 8000). Given explicitly, the port is "
        "pinned — it is never floated to a fallback, even if busy (the "
        "Tauri/Start-Menu shell relies on this to spawn the headless "
        "sidecar on a port it already chose and knows to poll).",
    )
    parser.add_argument(
        "--script",
        metavar="RECIPE",
        help="run RECIPE (.fvbatch.json preset export, or a bare "
        "{'steps': [...]} recipe) headlessly over the given inputs, "
        "then exit — no server, no browser. The 'dir' positional above "
        "and 'inputs' below are both taken as inputs in this mode "
        "(files, directories, or glob patterns); see --out",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        default=[],
        help="with --script: additional files/directories/glob patterns "
        "to process (ignored otherwise)",
    )
    parser.add_argument(
        "--out",
        default="fv-script-out",
        metavar="DIR",
        help="with --script: output directory for derived images (TIFF), "
        "value tables (CSV/JSON), and provenance (default: ./fv-script-out)",
    )
    args = parser.parse_args()

    if args.script:
        import sys

        from fermiviewer.cli_script import run_script

        script_inputs = ([args.dir] if args.dir else []) + args.inputs
        sys.exit(run_script(args.script, script_inputs, args.out))

    # the Open dialog defaults here; an explicit dir always wins, otherwise
    # the launch cwd (but not for the headless sidecar, which runs
    # --no-browser from an install dir that holds no images)
    if args.dir:
        launch.set_launch_dir(args.dir)
    elif not args.no_browser:
        launch.set_launch_dir(os.getcwd())

    if args.dev:
        _run_dev()
        return
    if args.desktop:
        _run_desktop()
        return

    # The browser CLI may float to a free port; the headless sidecar
    # (--no-browser, spawned by the Tauri/Start-Menu shell) must stay on the
    # FIXED port the shell navigates to, so it never floats. An explicit
    # --port (the shell's ephemeral-port fallback when the sibling quantized
    # holds 8000 — the shell picks the port and must be able to trust it)
    # is pinned the same way regardless of --no-browser: floating would move
    # the server to a port the shell never learns and can't navigate to.
    host = _HOST
    explicit_port = args.port is not None
    port = args.port if explicit_port else _PORT

    # If a healthy FermiViewer already owns the port, REUSE it instead of
    # starting a second server — the browser CLI opens it; the sidecar exits
    # so the shell connects to the running instance. This is the common
    # "launched twice" / "orphaned sidecar" case (--no-auto-shutdown means a
    # crashed shell leaves the sidecar holding :8000) and must never crash
    # with 'address already in use'. The sidecar waits a few seconds since
    # the shell's own 800 ms probe may have raced a still-starting sibling.
    if _port_listening(host, port) and _await_health(
        host, port, timeout=5.0 if args.no_browser else 0.5
    ):
        print(f"FermiViewer already running — using http://{host}:{port}")
        if not args.no_browser:
            import webbrowser

            webbrowser.open(f"http://{host}:{port}")
        return

    # Bind ourselves so a taken port floats (browser, default port only) or
    # fails readably (sidecar, or any explicit --port) here — not as an
    # OSError traceback inside uvicorn.run().
    sock = _bind(host, port)
    if sock is None and not args.no_browser and not explicit_port:
        port = _find_free_port(host, _PORT + 1)
        sock = _bind(host, port)
        print(f"port {_PORT} is in use by another app — using {port}")
    if sock is None:
        print(
            f"Cannot start FermiViewer: port {port} is in use by another "
            "program (or a stuck FermiViewer process). Close it and relaunch."
        )
        raise SystemExit(1)

    dist = _frontend_dist()
    if dist is None:
        print(
            "frontend/dist not found — API only on "
            f"http://{host}:{port}. Build the UI once with:\n"
            "    cd frontend && npm run build\n"
            "or run `fermiviewer --dev` for the hot-reloading dev setup."
        )
    elif not args.no_browser:
        _open_when_healthy(f"http://{host}:{port}", host, port)

    # hold the Server object so the lifecycle watchdog can stop it
    global _auto_shutdown, _server
    _auto_shutdown = dist is not None and not args.no_auto_shutdown
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port))
    _server = server
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
