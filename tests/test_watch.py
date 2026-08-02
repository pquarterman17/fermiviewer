"""Folder-watch (Scripting #7): pure debounce/threading behavior of
FolderWatcher plus the thin routes/watch.py API — single-active-watch
semantics, validation, end-to-end recipe execution on a dropped file, the
FastAPI lifespan wiring, and the desktop auto-shutdown interaction."""

from __future__ import annotations

import asyncio
import io
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app
from fermiviewer.session import store
from fermiviewer.watch import FolderWatcher, default_is_openable

pytestmark = pytest.mark.parser


def _png_bytes(value: int = 5) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.full((8, 8), value, dtype=np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


# ── FolderWatcher: pure debounce + processed-once behavior ──────────────


def test_stable_file_triggers_on_file_exactly_once(tmp_path: Path) -> None:
    target = tmp_path / "sample.png"
    target.write_bytes(_png_bytes())
    processed: list[Path] = []
    watcher = FolderWatcher(tmp_path, on_file=processed.append, interval=999)

    watcher.poll_once()  # first sighting — recorded as a candidate only
    assert processed == []
    watcher.poll_once()  # same (mtime, size) as last poll — stable now
    assert processed == [target]
    watcher.poll_once()  # already processed — never retried
    assert processed == [target]

    status = watcher.status()
    assert status["seen"] == 1
    assert status["processed"] == 1
    assert status["last_error"] is None


def test_partial_write_is_not_processed_until_stable(tmp_path: Path) -> None:
    data = _png_bytes()
    half = len(data) // 2
    target = tmp_path / "incoming.png"
    processed: list[Path] = []
    watcher = FolderWatcher(tmp_path, on_file=processed.append, interval=999)

    target.write_bytes(data[:half])
    watcher.poll_once()  # first sighting of the half-written file
    assert processed == []

    with open(target, "ab") as fh:
        fh.write(data[half:])
    watcher.poll_once()  # size changed since the last poll — still unstable
    assert processed == []

    watcher.poll_once()  # unchanged since the previous poll — stable now
    assert processed == [target]


def test_non_openable_file_is_seen_but_not_processed(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("hello")
    processed: list[Path] = []
    watcher = FolderWatcher(tmp_path, on_file=processed.append, interval=999)

    watcher.poll_once()
    watcher.poll_once()
    assert processed == []
    status = watcher.status()
    assert status["seen"] == 1
    assert status["processed"] == 0


def test_on_file_error_is_recorded_but_does_not_stop_the_loop(tmp_path: Path) -> None:
    target = tmp_path / "sample.png"
    target.write_bytes(_png_bytes())

    def boom(_path: Path) -> None:
        raise RuntimeError("recipe blew up")

    watcher = FolderWatcher(tmp_path, on_file=boom, interval=999)
    watcher.poll_once()
    watcher.poll_once()
    status = watcher.status()
    assert status["seen"] == 1
    assert status["processed"] == 0
    assert "recipe blew up" in status["last_error"]


def test_default_is_openable_matches_io_registry(tmp_path: Path) -> None:
    assert default_is_openable(tmp_path / "a.png") is True
    assert default_is_openable(tmp_path / "a.dm4") is True
    assert default_is_openable(tmp_path / "a.txt") is False


def test_start_stop_joins_thread_cleanly(tmp_path: Path) -> None:
    triggered = threading.Event()
    watcher = FolderWatcher(
        tmp_path, on_file=lambda p: triggered.set(), interval=0.02
    )
    watcher.start()
    try:
        (tmp_path / "drop.png").write_bytes(_png_bytes())
        assert triggered.wait(timeout=5), "on_file was never called"
    finally:
        watcher.stop()
    assert watcher._thread is None
    assert not any(t.name == "fv-watch" for t in threading.enumerate())

    # stop() is safe to call again, and start()/stop() again works cleanly
    watcher.stop()
    watcher.start()
    watcher.stop()


def test_second_start_on_a_running_watcher_is_a_noop(tmp_path: Path) -> None:
    watcher = FolderWatcher(tmp_path, on_file=lambda p: None, interval=999)
    watcher.start()
    first_thread = watcher._thread
    watcher.start()
    assert watcher._thread is first_thread
    watcher.stop()


# ── routes/watch.py: thin API over FolderWatcher ─────────────────────────


@pytest.fixture(autouse=True)
def _clean_state():
    from fermiviewer.routes.watch import shutdown_watch

    store.clear()
    yield
    shutdown_watch()
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _gaussian_recipe() -> list[dict]:
    return [{"op": "gaussian", "params": {"sigma": 1}}]


def _wait_for_job(client: TestClient, timeout: float = 10) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job_ids = client.get("/api/watch/status").json()["job_ids"]
        if job_ids:
            return job_ids[0]
        time.sleep(0.01)
    raise AssertionError("no job was submitted by the watch")


def _poll_job(client: TestClient, job_id: str, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.01)
    raise AssertionError("watch job did not finish")


@pytest.mark.api
def test_watch_start_rejects_missing_directory(client: TestClient, tmp_path: Path) -> None:
    r = client.post("/api/watch/start", json={
        "dir": str(tmp_path / "does-not-exist"),
        "steps": _gaussian_recipe(),
    })
    assert r.status_code == 404


@pytest.mark.api
def test_watch_start_rejects_a_file_as_directory(client: TestClient, tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("x")
    r = client.post("/api/watch/start", json={"dir": str(f), "steps": _gaussian_recipe()})
    assert r.status_code == 422


@pytest.mark.api
def test_watch_start_rejects_bad_recipe(client: TestClient, tmp_path: Path) -> None:
    r = client.post("/api/watch/start", json={
        "dir": str(tmp_path),
        "steps": [{"op": "gaussian", "params": {"sgima": 1}}],
    })
    assert r.status_code == 422
    assert "unknown param" in r.json()["detail"]


@pytest.mark.api
def test_watch_second_start_is_409(client: TestClient, tmp_path: Path) -> None:
    body = {"dir": str(tmp_path), "steps": _gaussian_recipe()}
    assert client.post("/api/watch/start", json=body).status_code == 200
    second = client.post("/api/watch/start", json=body)
    assert second.status_code == 409
    assert client.post("/api/watch/stop").status_code == 200


@pytest.mark.api
def test_watch_status_reflects_lifecycle(client: TestClient, tmp_path: Path) -> None:
    idle = client.get("/api/watch/status").json()
    assert idle["watching"] is False

    body = {"dir": str(tmp_path), "steps": _gaussian_recipe()}
    assert client.post("/api/watch/start", json=body).status_code == 200
    active = client.get("/api/watch/status").json()
    assert active["watching"] is True
    assert active["dir"] == str(tmp_path)

    assert client.post("/api/watch/stop").status_code == 200
    stopped = client.get("/api/watch/status").json()
    assert stopped["watching"] is False


@pytest.mark.api
def test_watch_stop_without_an_active_watch_is_a_noop(client: TestClient) -> None:
    assert client.post("/api/watch/stop").status_code == 200


@pytest.mark.api
def test_watch_end_to_end_processes_dropped_file(client: TestClient, tmp_path: Path) -> None:
    watch_dir = tmp_path / "incoming"
    watch_dir.mkdir()
    r = client.post("/api/watch/start", json={
        "dir": str(watch_dir), "steps": _gaussian_recipe(), "interval": 0.02,
    })
    assert r.status_code == 200, r.text

    (watch_dir / "drop.png").write_bytes(_png_bytes())
    job_id = _wait_for_job(client)
    final = _poll_job(client, job_id)
    assert final["status"] == "done", final
    derived_id = final["result"]["derived"]["id"]
    assert client.get(f"/api/image/{derived_id}/render").status_code == 200

    status = client.get("/api/watch/status").json()
    assert status["watching"] is True
    assert status["processed"] >= 1
    assert job_id in status["job_ids"]


@pytest.mark.api
def test_watch_ignores_a_non_openable_file_dropped_alongside(
    client: TestClient, tmp_path: Path
) -> None:
    watch_dir = tmp_path / "incoming"
    watch_dir.mkdir()
    client.post("/api/watch/start", json={
        "dir": str(watch_dir), "steps": _gaussian_recipe(), "interval": 0.02,
    })
    (watch_dir / "notes.txt").write_text("not an image")
    (watch_dir / "drop.png").write_bytes(_png_bytes())

    job_id = _wait_for_job(client)
    final = _poll_job(client, job_id)
    assert final["status"] == "done"
    assert final["result"]["name"] == "drop.png"

    status = client.get("/api/watch/status").json()
    assert status["seen"] >= 2  # both files stabilized...
    assert status["processed"] == 1  # ...only the PNG ran a recipe


@pytest.mark.api
def test_lifespan_shutdown_stops_the_watcher_thread(tmp_path: Path) -> None:
    """FastAPI lifespan shutdown must stop the watch (never atexit) — the
    same wiring test_api_jobs.py uses for jobs.shutdown()."""
    from fermiviewer.routes import watch as watch_routes

    with TestClient(create_app()) as client:
        r = client.post("/api/watch/start", json={
            "dir": str(tmp_path), "steps": _gaussian_recipe(),
        })
        assert r.status_code == 200
        assert watch_routes.is_watch_active() is True
    assert watch_routes.is_watch_active() is False


@pytest.mark.api
def test_active_watch_defers_desktop_auto_shutdown(monkeypatch, tmp_path: Path) -> None:
    """An active folder watch must hold the desktop session open even
    with zero browser tabs connected; ordinary shutdown resumes once the
    watch is stopped.

    ``_grace_check`` reschedules itself via ``create_task`` for as long as
    a watch is active — correct against uvicorn's persistent event loop,
    but TestClient's ``websocket_connect`` tears its own loop down at the
    end of its ``with`` block, cancelling any not-yet-awaited follow-up
    task. So this drives one persistent loop directly (mirroring
    production) instead of going through the websocket test harness."""
    import fermiviewer.server as srv

    monkeypatch.setattr(srv, "_SHUTDOWN_GRACE_S", 0.02)
    monkeypatch.setattr(srv, "_auto_shutdown", True)
    monkeypatch.setattr(srv, "_ever_connected", True)
    monkeypatch.setattr(srv, "_clients", 0)
    requested = threading.Event()
    monkeypatch.setattr(srv, "_request_shutdown", requested.set)

    client = TestClient(create_app())
    r = client.post("/api/watch/start", json={
        "dir": str(tmp_path), "steps": _gaussian_recipe(),
    })
    assert r.status_code == 200
    try:
        async def driver() -> None:
            await srv._grace_check()  # kicks off the self-rescheduling chain
            await asyncio.sleep(0.3)  # let it run several cycles
            assert not requested.is_set(), "an active watch must inhibit auto-shutdown"

            client.post("/api/watch/stop")
            await asyncio.sleep(0.3)  # give the chain a chance to notice

        asyncio.run(driver())
        assert requested.is_set(), "shutdown must resume once the watch stops"
    finally:
        client.post("/api/watch/stop")
