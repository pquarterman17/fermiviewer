"""Direct unit tests for fermiviewer.netprobe — the port-probe/bind/health
helpers consumed by server.py's launch sequence.

test_launch_dir.py already exercises the "everything is free" happy paths
via `server._health_ok`/`_port_listening`/`_find_free_port`/`_bind`/
`_await_health`. This file fills the remaining branch gaps — port-in-use
stepping, exhaustion, _health_ok's payload-shape branches, the
non-Windows SO_REUSEADDR path, and _await_health's success/retry paths —
using monkeypatched sockets/urlopen so it stays fast and deterministic.

Deliberately imports fermiviewer.netprobe directly (never fermiviewer's
server module) and never touches test_server_dev_desktop.py — a parallel
session is mid-refactor on server.py's --desktop/--dev launch internals.
"""

from __future__ import annotations

import json
import os
import socket

import pytest

from fermiviewer import netprobe
from fermiviewer.netprobe import (
    _await_health,
    _bind,
    _find_free_port,
    _health_ok,
    _port_listening,
)

pytestmark = pytest.mark.api


# ── _find_free_port ─────────────────────────────────────────────────────


def test_find_free_port_steps_past_busy_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two ports right after `start` are busy; the scan must step past
    both and land on the first free one."""
    busy = {19001, 19002}
    monkeypatch.setattr(
        netprobe, "_port_listening", lambda host, port: port in busy
    )
    assert _find_free_port("127.0.0.1", 19001) == 19003


def test_find_free_port_gives_up_after_scan_when_all_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All 50 candidate ports busy -> returns `start` unchanged (per the
    docstring: "give up gracefully; uvicorn will report the bind error"),
    never raises and never scans past the bounded window."""
    seen: list[int] = []

    def always_busy(host: str, port: int) -> bool:
        seen.append(port)
        return True

    monkeypatch.setattr(netprobe, "_port_listening", always_busy)
    assert _find_free_port("127.0.0.1", 19100) == 19100
    assert seen == list(range(19100, 19150))  # exactly the bounded scan


# ── _health_ok ───────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_health_ok_true_on_valid_ok_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    def fake_urlopen(url: str, timeout: float | None = None) -> _FakeResponse:
        assert "/api/health" in url
        return _FakeResponse(200, json.dumps({"status": "ok"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert _health_ok("127.0.0.1", 19200) is True


def test_health_ok_false_on_non_200_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda url, timeout=None: _FakeResponse(
            500, json.dumps({"status": "ok"}).encode()
        ),
    )
    assert _health_ok("127.0.0.1", 19201) is False


def test_health_ok_false_when_payload_is_not_a_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda url, timeout=None: _FakeResponse(200, b"[1, 2, 3]"),
    )
    assert _health_ok("127.0.0.1", 19202) is False


def test_health_ok_false_when_status_field_is_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda url, timeout=None: _FakeResponse(
            200, json.dumps({"status": "starting"}).encode()
        ),
    )
    assert _health_ok("127.0.0.1", 19203) is False


def test_health_ok_false_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """json.loads raising is caught by the broad `except Exception`."""
    import urllib.request

    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda url, timeout=None: _FakeResponse(200, b"not json at all"),
    )
    assert _health_ok("127.0.0.1", 19204) is False


# ── _bind ────────────────────────────────────────────────────────────────


def test_bind_sets_reuseaddr_on_non_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SO_REUSEADDR is set on non-Windows only (on Windows it behaves like
    SO_REUSEPORT and would let us steal a foreign server's port) — force
    the non-Windows branch to execute regardless of the host OS."""
    monkeypatch.setattr(os, "name", "posix")
    sock = _bind("127.0.0.1", 19400)
    assert sock is not None
    try:
        opt = sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)
        assert opt != 0
    finally:
        sock.close()


def test_bind_skips_reuseaddr_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `os.name == "nt"` branch: no setsockopt call, but bind still
    succeeds normally."""
    monkeypatch.setattr(os, "name", "nt")
    sock = _bind("127.0.0.1", 19401)
    assert sock is not None
    sock.close()


# ── _port_listening ──────────────────────────────────────────────────────


def test_port_listening_true_when_something_is_bound() -> None:
    sock = _bind("127.0.0.1", 19402)
    assert sock is not None
    try:
        assert _port_listening("127.0.0.1", 19402) is True
    finally:
        sock.close()


# ── _await_health ────────────────────────────────────────────────────────


def test_await_health_returns_true_immediately_when_already_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def fake_health_ok(host: str, port: int) -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr(netprobe, "_health_ok", fake_health_ok)
    assert _await_health("127.0.0.1", 19300, timeout=1.0) is True
    assert calls["n"] == 1  # no unnecessary polling once healthy


def test_await_health_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unhealthy on the first poll, healthy on the second — exercises the
    sleep-then-retry loop body distinct from both the instant-True and
    the always-False (timeout) cases."""
    results = iter([False, True])
    monkeypatch.setattr(
        netprobe, "_health_ok", lambda host, port: next(results)
    )
    assert _await_health("127.0.0.1", 19301, timeout=2.0) is True
