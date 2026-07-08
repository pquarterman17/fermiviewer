"""Desktop (--desktop, pywebview) and dev (--dev, Vite HMR) launch paths.

Split out of server.py to respect the 500-line god-module ceiling —
``main()`` and the FastAPI app assembly stay in server.py (the `fv` /
`fermiviewer` console-script entry point is ``fermiviewer.server:main``);
these two subprocess/window launch paths are self-contained and only
reached from ``main()``'s ``--dev`` / ``--desktop`` branches. Re-exported
from server.py so existing imports (and tests that monkeypatch
``server._frontend_dist``) are unaffected.

Distinct from ``fermiviewer/launch.py``, which tracks the app's *launch
directory* (the in-app Open dialog default) — unrelated to these
process-launch code paths, despite the similar name.

``_frontend_dist``, the lifecycle ``_server`` global, ``app``, ``_HOST``
and ``_PORT`` stay owned by server.py; this module reaches them through a
deferred (function-body) ``import fermiviewer.server`` rather than a
module-level one, so the two modules can be imported in either order
without a circular-import error, and so tests that monkeypatch
``server._frontend_dist`` are observed correctly.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fermiviewer.netprobe import _bind, _health_ok

if TYPE_CHECKING:
    import uvicorn

__all__ = ["_open_browser_later", "_open_when_healthy", "_run_desktop", "_run_dev"]


def _open_browser_later(url: str, delay: float = 0.8) -> None:
    """Fixed-delay browser open — used only for the dev path, where the
    target is the Vite server (no /api/health to poll)."""
    import webbrowser

    timer = threading.Timer(delay, webbrowser.open, [url])
    timer.daemon = True  # don't keep the process alive on Ctrl+C in --dev
    timer.start()


def _open_when_healthy(url: str, host: str, port: int, timeout: float = 30.0) -> None:
    """Open the browser only once the server answers — replaces the old
    fixed-delay timer, which raced a cold numpy/scipy import and showed
    'can't reach this page'. Polls /api/health in a daemon thread."""
    import webbrowser

    def _wait_then_open() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _health_ok(host, port):
                webbrowser.open(url)
                return
            time.sleep(0.25)
        webbrowser.open(url)  # last resort: open anyway after the timeout

    threading.Thread(target=_wait_then_open, daemon=True).start()


_WEBVIEW_BACKEND_HINT = (
    "pywebview needs a native GUI backend. On Linux, install PyGObject + "
    "WebKitGTK (e.g. `sudo apt install python3-gi gir1.2-webkit2-4.1`) or "
    "PyQt5/PySide2, then retry."
)


def _run_desktop() -> None:
    """Desktop standalone (handoff §11 option B): uvicorn in a thread,
    pywebview native window on top — pure Python, no Rust toolchain.
    Closing the window stops the server."""
    import uvicorn

    from fermiviewer import server as _srv

    if _srv._frontend_dist() is None:
        print(
            "frontend/dist not found — build it once with:\n"
            "    cd frontend && npm run build"
        )
        return

    try:
        import webview
    except ImportError as e:
        print(f"--desktop: {_WEBVIEW_BACKEND_HINT}\n(import error: {e})")
        return

    # Bind up front so a taken port is a clean branch, not a crashed server
    # thread: reuse our own healthy instance (point the window at it), or
    # refuse a foreign app instead of hanging 30 s on a dead window.
    sock = _bind(_srv._HOST, _srv._PORT)
    server: uvicorn.Server | None = None
    t: threading.Thread | None = None
    if sock is None:
        if not _health_ok(_srv._HOST, _srv._PORT):
            print(f"port {_srv._PORT} is in use by another app — close it and retry")
            return
    else:
        server = uvicorn.Server(
            uvicorn.Config(_srv.app, host=_srv._HOST, port=_srv._PORT, log_level="warning")
        )
        _srv._server = server
        s = sock  # bound socket handed to uvicorn — closes the bind race
        t = threading.Thread(target=lambda: server.run(sockets=[s]), daemon=True)
        t.start()

    # wait for the server to bind before pointing the window at it, else
    # the webview shows a connection-refused page and never retries
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline and not _health_ok(_srv._HOST, _srv._PORT):
        time.sleep(0.25)

    try:
        webview.create_window(
            "FermiViewer",
            f"http://{_srv._HOST}:{_srv._PORT}",
            width=1440,
            height=920,
            background_color="#16141d",
        )
        webview.start()
    except Exception as e:
        print(f"--desktop: {_WEBVIEW_BACKEND_HINT}\n(error: {e})")
    finally:
        if server is not None:
            server.should_exit = True
        if t is not None:
            t.join(timeout=5)


def _run_dev() -> None:
    """Vite dev server (HMR) + reloading uvicorn in one terminal."""
    import os
    import subprocess

    import uvicorn

    from fermiviewer.server import _HOST, _PORT

    frontend = Path(__file__).resolve().parents[2] / "frontend"
    if not frontend.is_dir():
        print(f"--dev requires a source checkout; frontend/ not found at {frontend}")
        raise SystemExit(2)
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
