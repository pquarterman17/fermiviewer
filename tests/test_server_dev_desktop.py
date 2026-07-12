"""server.py --dev / --desktop CLI-path guards.

Both paths used to leak raw tracebacks when the environment wasn't a
source checkout (--dev, from a wheel install) or lacked a pywebview GUI
backend (--desktop, common on headless/minimal Linux) — this covers the
clear-message-instead-of-crash behavior.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import types
import webbrowser

import pytest
import uvicorn

from fermiviewer import server, server_launch

pytestmark = pytest.mark.api


def test_run_dev_exits_cleanly_without_frontend_checkout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A wheel install has no frontend/ dir; --dev must print a one-liner
    and exit(2), not crash Popen with a raw FileNotFoundError."""
    real_is_dir = pathlib.Path.is_dir

    def fake_is_dir(self: pathlib.Path) -> bool:
        if self.name == "frontend":
            return False
        return real_is_dir(self)

    monkeypatch.setattr(pathlib.Path, "is_dir", fake_is_dir)
    with pytest.raises(SystemExit) as exc:
        server._run_dev()
    assert exc.value.code == 2
    assert "--dev requires a source checkout" in capsys.readouterr().out


def test_run_desktop_reports_missing_webview_backend(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """pywebview missing its native GUI backend must print install
    guidance, not raise ImportError up through main()."""
    monkeypatch.setattr(server, "_frontend_dist", lambda: pathlib.Path("."))
    # None in sys.modules forces the next `import webview` to raise
    # ImportError, regardless of whether the real package is installed.
    monkeypatch.setitem(sys.modules, "webview", None)
    server._run_desktop()  # must not raise
    assert "pywebview" in capsys.readouterr().out


class _ImmediateThread:
    """Synchronous stand-in that makes daemon-thread behavior deterministic."""

    def __init__(self, target, daemon=False) -> None:
        self.target = target
        self.daemon = daemon
        self.joined_with: float | None = None

    def start(self) -> None:
        self.target()

    def join(self, timeout: float | None = None) -> None:
        self.joined_with = timeout


def test_open_browser_later_uses_daemon_timer(monkeypatch) -> None:
    made = []

    class FakeTimer:
        def __init__(self, delay, callback, args) -> None:
            self.delay, self.callback, self.args = delay, callback, args
            self.daemon = False
            self.started = False
            made.append(self)

        def start(self) -> None:
            self.started = True

    monkeypatch.setattr(server_launch.threading, "Timer", FakeTimer)
    server_launch._open_browser_later("http://example.test", delay=1.25)

    assert len(made) == 1
    assert made[0].delay == 1.25
    assert made[0].args == ["http://example.test"]
    assert made[0].daemon is True
    assert made[0].started is True


@pytest.mark.parametrize("healthy", [True, False])
def test_open_when_healthy_success_and_timeout(monkeypatch, healthy: bool) -> None:
    opened: list[str] = []
    clock = iter([0.0, 0.1] if healthy else [0.0, 2.0])
    monkeypatch.setattr(server_launch.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server_launch.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(server_launch.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(server_launch, "_health_ok", lambda *_args: healthy)
    monkeypatch.setattr(webbrowser, "open", opened.append)

    server_launch._open_when_healthy(
        "http://127.0.0.1:8000", "127.0.0.1", 8000, timeout=1.0
    )
    assert opened == ["http://127.0.0.1:8000"]


def test_run_desktop_reports_missing_frontend(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(server, "_frontend_dist", lambda: None)
    server._run_desktop()
    assert "frontend/dist not found" in capsys.readouterr().out


def test_run_desktop_rejects_foreign_port_owner(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(server, "_frontend_dist", lambda: pathlib.Path("."))
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace())
    monkeypatch.setattr(server_launch, "_bind", lambda *_args: None)
    monkeypatch.setattr(server_launch, "_health_ok", lambda *_args: False)

    server._run_desktop()
    assert (
        f"port {server._PORT} is in use by another app" in capsys.readouterr().out
    )


def test_run_desktop_starts_and_stops_owned_server(monkeypatch) -> None:
    calls: dict[str, object] = {}
    sock = object()

    class FakeServer:
        def __init__(self, config) -> None:
            self.config = config
            self.should_exit = False
            calls["server"] = self

        def run(self, *, sockets) -> None:
            calls["sockets"] = sockets

    class TrackingThread(_ImmediateThread):
        def join(self, timeout=None) -> None:
            super().join(timeout)
            calls["joined"] = timeout

    fake_webview = types.SimpleNamespace(
        create_window=lambda *args, **kwargs: calls.update(
            window_args=args, window_kwargs=kwargs
        ),
        start=lambda: calls.update(webview_started=True),
    )
    monkeypatch.setattr(server, "_frontend_dist", lambda: pathlib.Path("."))
    monkeypatch.setattr(server, "_server", None)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(server_launch, "_bind", lambda *_args: sock)
    monkeypatch.setattr(server_launch, "_health_ok", lambda *_args: True)
    monkeypatch.setattr(server_launch.threading, "Thread", TrackingThread)
    monkeypatch.setattr(uvicorn, "Config", lambda *args, **kwargs: (args, kwargs))
    monkeypatch.setattr(uvicorn, "Server", FakeServer)

    server._run_desktop()

    instance = calls["server"]
    assert isinstance(instance, FakeServer)
    assert calls["sockets"] == [sock]
    assert calls["webview_started"] is True
    assert calls["joined"] == 5
    assert instance.should_exit is True


def test_run_dev_terminates_vite_when_backend_stops(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeProcess:
        def terminate(self) -> None:
            calls["terminated"] = True

        def wait(self, timeout) -> None:
            calls["wait_timeout"] = timeout

    def fake_popen(command, cwd):
        calls["command"] = command
        calls["cwd"] = cwd
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        server_launch,
        "_open_browser_later",
        lambda url, delay: calls.update(browser=(url, delay)),
    )
    monkeypatch.setattr(
        uvicorn, "run", lambda *args, **kwargs: calls.update(uvicorn=(args, kwargs))
    )

    server._run_dev()

    assert calls["command"][1:] == ["run", "dev"]
    assert pathlib.Path(calls["cwd"]).name == "frontend"
    assert calls["browser"] == ("http://localhost:5173", 2.0)
    assert calls["terminated"] is True
    assert calls["wait_timeout"] == 10
