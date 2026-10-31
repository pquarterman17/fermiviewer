"""Ctrl+C is an orderly stop: no traceback, exit status 0.

uvicorn shuts down gracefully on SIGINT and then re-raises the signal;
``Server.run()`` (which ``main()`` uses to hand over its pre-bound socket)
lets that surface as a CancelledError/KeyboardInterrupt traceback unless
``main()`` handles it. The subprocess test drives the real entry point;
the unit tests pin the single- vs forced-interrupt split.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from fermiviewer import server


class _FakeServer:
    def __init__(self, exc: BaseException | None, force_exit: bool = False) -> None:
        self.exc = exc
        self.force_exit = force_exit
        self.sockets: list[object] | None = None

    def run(self, sockets: list[object] | None = None) -> None:
        self.sockets = sockets
        if self.exc is not None:
            raise self.exc


def test_single_interrupt_returns_normally(capsys: pytest.CaptureFixture[str]) -> None:
    fake = _FakeServer(KeyboardInterrupt())
    sock = object()
    server._serve_until_interrupted(fake, sock)  # type: ignore[arg-type]
    assert fake.sockets == [sock]
    assert capsys.readouterr().err.strip() == "FermiViewer stopped."


def test_forced_interrupt_exits_130(capsys: pytest.CaptureFixture[str]) -> None:
    fake = _FakeServer(KeyboardInterrupt(), force_exit=True)
    with pytest.raises(SystemExit) as info:
        server._serve_until_interrupted(fake, object())  # type: ignore[arg-type]
    assert info.value.code == 130
    assert "forced" in capsys.readouterr().err


def test_other_errors_still_propagate() -> None:
    fake = _FakeServer(RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        server._serve_until_interrupted(fake, object())  # type: ignore[arg-type]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=1
        ) as r:
            return json.load(r).get("app") == "fermiviewer"
    except OSError:
        return False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SIGINT delivery")
def test_ctrl_c_exits_zero_without_traceback(tmp_path: Path) -> None:
    port = _free_port()
    env = {**os.environ, "FV_CONFIG_DIR": str(tmp_path / "config")}
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "fermiviewer",
            "--no-browser", "--no-auto-shutdown", "--port", str(port),
        ],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # A runner started in the background may hand children an ignored
        # SIGINT; restore the default so the child sees Ctrl+C as a TTY would.
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
    )
    try:
        deadline = time.monotonic() + 60
        while not _healthy(port):
            assert proc.poll() is None, proc.communicate()[1].decode(errors="replace")
            assert time.monotonic() < deadline, "server never became healthy"
            time.sleep(0.2)
        proc.send_signal(signal.SIGINT)
        _, err_bytes = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    err = err_bytes.decode(errors="replace")
    assert proc.returncode == 0, err
    assert "Traceback" not in err
    assert "Application shutdown complete" in err  # lifespan cleanup ran
    assert err.rstrip().endswith("FermiViewer stopped.")
