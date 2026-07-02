"""Localhost server-probe + socket-bind helpers for the launcher.

Split out of server.py (god-module ceiling) to group the "is a FermiViewer
already on this port / can I claim it" networking in one place. Pure stdlib
— no fastapi/uvicorn import, so it stays cheap and cycle-free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import socket as _socket


def _health_ok(host: str, port: int, timeout: float = 0.4) -> bool:
    """True iff a *FermiViewer* server answers /api/health with 200 — used
    to tell our own running instance apart from a foreign app on the port
    and to gate the browser/window open on the server actually being up."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}/api/health", timeout=timeout
        ) as r:
            if r.status != 200:
                return False
            data = json.loads(r.read())
            return bool(isinstance(data, dict) and data.get("status") == "ok")
    except Exception:
        return False


def _port_listening(host: str, port: int) -> bool:
    """True iff something is accepting TCP connections on host:port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def _find_free_port(host: str, start: int) -> int:
    """First free port at or above ``start`` (small bounded scan)."""
    for port in range(start, start + 50):
        if not _port_listening(host, port):
            return port
    return start  # give up gracefully; uvicorn will report the bind error


def _bind(host: str, port: int) -> _socket.socket | None:
    """Bind + listen on host:port, returning the live socket, or None if the
    port is taken. Binding up front (vs. letting uvicorn bind inside .run())
    turns a busy port into a value we can branch on — float, reuse, or fail
    readably — instead of an 'address already in use' traceback; the socket
    is handed to Server.run(sockets=[...]), closing the check->bind race."""
    import os
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # SO_REUSEADDR everywhere EXCEPT Windows, where it acts like
        # SO_REUSEPORT and would let us bind a port a foreign server owns.
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen()
        return s
    except OSError:
        s.close()
        return None


def _await_health(host: str, port: int, timeout: float = 0.5) -> bool:
    """Poll /api/health up to ``timeout`` s — True iff a FermiViewer answers.
    Absorbs the window where a sibling has bound the port but is still
    importing numpy, so a second launch reuses it rather than racing it."""
    import time

    deadline = time.monotonic() + timeout
    while True:
        if _health_ok(host, port):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
