"""Launch-folder default + startup network helpers.

Covers the /api/session/launch-dir route (which lets the SPA default its
Open dialog to the folder `fermiviewer <dir>` was started in) and the
server-side health/port helpers that gate the browser open and pick a
free port when 8000 is taken.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fermiviewer import launch, server
from fermiviewer.io.registry import supported_extensions
from fermiviewer.server import create_app

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _reset_launch_dir():
    """Keep the module-global launch dir from leaking between tests."""
    launch.set_launch_dir(None)
    yield
    launch.set_launch_dir(None)


def test_launch_dir_unset_returns_null() -> None:
    client = TestClient(create_app())
    body = client.get("/api/session/launch-dir").json()
    assert body == {"dir": None, "files": []}


def test_launch_dir_lists_only_supported(tmp_path: Path) -> None:
    ext = next(iter(supported_extensions()))  # e.g. ".tif"
    (tmp_path / f"alpha{ext}").write_bytes(b"x")
    (tmp_path / f"beta{ext}").write_bytes(b"x")
    (tmp_path / "notes.unsupported").write_bytes(b"x")
    (tmp_path / "subdir").mkdir()  # directories excluded

    launch.set_launch_dir(tmp_path)
    client = TestClient(create_app())
    body = client.get("/api/session/launch-dir").json()

    assert body["dir"] == str(tmp_path.resolve())
    names = [f["name"] for f in body["files"]]
    assert names == [f"alpha{ext}", f"beta{ext}"]  # sorted, filtered
    assert all(Path(f["path"]).is_absolute() for f in body["files"])


def test_launch_dir_empty_when_no_supported_files(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_bytes(b"x")
    launch.set_launch_dir(tmp_path)
    client = TestClient(create_app())
    body = client.get("/api/session/launch-dir").json()
    assert body["dir"] == str(tmp_path.resolve())
    assert body["files"] == []


def test_launch_dir_missing_dir_reports_null(tmp_path: Path) -> None:
    launch.set_launch_dir(tmp_path / "does-not-exist")
    client = TestClient(create_app())
    body = client.get("/api/session/launch-dir").json()
    assert body == {"dir": None, "files": []}


def test_health_ok_false_when_nothing_listening() -> None:
    # an almost-certainly-free port: no server, so health must be False
    assert server._health_ok("127.0.0.1", 8723) is False


def test_port_listening_false_when_free() -> None:
    assert server._port_listening("127.0.0.1", 8724) is False


def test_find_free_port_returns_free_port() -> None:
    port = server._find_free_port("127.0.0.1", 8725)
    assert 8725 <= port < 8775
    assert server._port_listening("127.0.0.1", port) is False
