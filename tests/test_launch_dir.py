"""Launch-folder default + startup network helpers.

Covers the /api/session/launch-dir route (which lets the SPA default its
Open dialog to the folder `fermiviewer <dir>` was started in) and the
server-side health/port helpers that gate the browser open and pick a
free port when 8000 is taken.
"""

from __future__ import annotations

import pathlib
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


def test_launch_dir_skips_unreadable_entry_keeps_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single is_file() failure (e.g. a OneDrive cloud-only file) must
    skip that entry, not discard the whole already-collected list."""
    ext = next(iter(supported_extensions()))
    (tmp_path / f"good{ext}").write_bytes(b"x")
    (tmp_path / f"bad{ext}").write_bytes(b"x")

    real_is_file = pathlib.Path.is_file

    def flaky(self: pathlib.Path) -> bool:
        if self.name == f"bad{ext}":
            raise OSError("cloud-only placeholder")
        return real_is_file(self)

    monkeypatch.setattr(pathlib.Path, "is_file", flaky)
    launch.set_launch_dir(tmp_path)
    body = TestClient(create_app()).get("/api/session/launch-dir").json()
    assert [f["name"] for f in body["files"]] == [f"good{ext}"]


def test_launch_dir_reports_truncation(tmp_path: Path) -> None:
    ext = next(iter(supported_extensions()))
    for i in range(501):
        (tmp_path / f"f{i:04d}{ext}").write_bytes(b"x")
    launch.set_launch_dir(tmp_path)
    body = TestClient(create_app()).get("/api/session/launch-dir").json()
    assert len(body["files"]) == 500
    assert body["truncated"] is True


def test_ws_rejects_cross_origin() -> None:
    """The CSRF guard is HTTP-only; /api/ws must enforce origin itself."""
    client = TestClient(create_app())
    with pytest.raises(Exception):  # noqa: B017 — Starlette WS reject
        with client.websocket_connect(
            "/api/ws", headers={"origin": "https://evil.example"}
        ):
            pass


def test_ws_allows_localhost_origin() -> None:
    client = TestClient(create_app())
    with client.websocket_connect(
        "/api/ws", headers={"origin": "http://127.0.0.1:8000"}
    ) as ws:
        ws.close()


def test_workspace_delete_rejects_bad_slug() -> None:
    client = TestClient(create_app())
    assert client.delete("/api/workspaces/Bad_Slug!").status_code == 422
    # a clean slug passes validation (no such workspace → deleted False)
    r = client.delete("/api/workspaces/no-such-workspace")
    assert r.status_code == 200
    assert r.json() == {"deleted": False}


def test_health_ok_false_when_nothing_listening() -> None:
    # an almost-certainly-free port: no server, so health must be False
    assert server._health_ok("127.0.0.1", 8723) is False


def test_port_listening_false_when_free() -> None:
    assert server._port_listening("127.0.0.1", 8724) is False


def test_find_free_port_returns_free_port() -> None:
    port = server._find_free_port("127.0.0.1", 8725)
    assert 8725 <= port < 8775
    assert server._port_listening("127.0.0.1", port) is False


def test_bind_claims_free_port_and_rejects_taken() -> None:
    """The launch fix hinges on _bind turning a busy port into None (a value
    to branch on) instead of an 'address already in use' crash."""
    sock = server._bind("127.0.0.1", 8726)
    assert sock is not None
    try:
        # port is ours now — a second bind must return None, never raise
        assert server._bind("127.0.0.1", 8726) is None
        assert server._port_listening("127.0.0.1", 8726) is True
    finally:
        sock.close()


def test_await_health_times_out_without_hanging() -> None:
    import time

    start = time.monotonic()
    assert server._await_health("127.0.0.1", 8727, timeout=0.3) is False
    # returns at ~the timeout, not the process-lifetime
    assert time.monotonic() - start < 2.0
