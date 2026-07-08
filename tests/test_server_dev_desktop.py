"""server.py --dev / --desktop CLI-path guards.

Both paths used to leak raw tracebacks when the environment wasn't a
source checkout (--dev, from a wheel install) or lacked a pywebview GUI
backend (--desktop, common on headless/minimal Linux) — this covers the
clear-message-instead-of-crash behavior.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

from fermiviewer import server

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
