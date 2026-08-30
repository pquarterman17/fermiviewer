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


def test_on_file_error_count_accumulates_not_just_the_last_message(
    tmp_path: Path,
) -> None:
    """A burst of on_file failures (e.g. hundreds of files tripping the
    shared job queue's admission bound) must be visible as a COUNT, not
    just the single most-recently-overwritten last_error string — the
    caller has no other way to tell "3 files failed" from "300 files
    failed" if only the last message survives."""
    watcher = FolderWatcher(
        tmp_path, on_file=lambda p: (_ for _ in ()).throw(RuntimeError("boom")),
        interval=999,
    )
    for i in range(3):
        (tmp_path / f"f{i}.png").write_bytes(_png_bytes())
    watcher.poll_once()  # first sighting of all three — candidates only
    watcher.poll_once()  # stable now — all three fire on_file and fail
    status = watcher.status()
    assert status["seen"] == 3
    assert status["processed"] == 0
    assert status["errors"] == 3
    assert "boom" in status["last_error"]


def test_stale_candidate_is_pruned_not_leaked(tmp_path: Path) -> None:
    """A file that never stabilizes because it's deleted/renamed away
    first (an aborted transfer, an editor swap file) must not sit in the
    pending-fingerprint map forever — only _processed (paths that DID
    fire) is meant to grow unbounded for the watch's lifetime."""
    target = tmp_path / "aborted.png"
    target.write_bytes(_png_bytes()[:20])
    watcher = FolderWatcher(tmp_path, on_file=lambda p: None, interval=999)

    watcher.poll_once()  # first sighting — recorded as a candidate
    assert str(target) in watcher._candidates

    target.unlink()
    watcher.poll_once()  # gone from this scan — its candidate entry must go too
    assert watcher._candidates == {}


def test_replaced_file_same_name_and_size_is_never_reprocessed(
    tmp_path: Path,
) -> None:
    """Pinning the documented policy: _processed tracks PATHS, not content
    fingerprints, so a file overwritten in place after it already fired —
    even with an identical size but a new mtime — does not fire again."""
    target = tmp_path / "sample.png"
    target.write_bytes(_png_bytes(value=1))
    processed: list[Path] = []
    watcher = FolderWatcher(tmp_path, on_file=processed.append, interval=999)

    watcher.poll_once()
    watcher.poll_once()
    assert processed == [target]

    time.sleep(0.01)
    target.write_bytes(_png_bytes(value=2))  # same name+size, new content/mtime
    watcher.poll_once()
    watcher.poll_once()
    assert processed == [target]  # NOT re-fired


def test_stop_when_never_started_is_a_noop(tmp_path: Path) -> None:
    watcher = FolderWatcher(tmp_path, on_file=lambda p: None, interval=999)
    watcher.stop()  # must not raise even though start() was never called
    assert watcher._thread is None


def test_watched_directory_removed_mid_poll_surfaces_error_not_crash(
    tmp_path: Path,
) -> None:
    watch_dir = tmp_path / "incoming"
    watch_dir.mkdir()
    watcher = FolderWatcher(watch_dir, on_file=lambda p: None, interval=999)
    watcher.poll_once()
    assert watcher.status()["last_error"] is None

    watch_dir.rmdir()
    watcher.poll_once()  # os.scandir raises OSError — must not raise here
    status = watcher.status()
    assert status["last_error"] is not None

    watch_dir.mkdir()
    watcher.poll_once()  # directory is back — resumes cleanly, no crash/spin
    assert watcher.status()["seen"] == 0


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
@pytest.mark.parametrize("interval", [0, -1, -0.5])
def test_watch_start_rejects_non_positive_interval(
    client: TestClient, tmp_path: Path, interval: float
) -> None:
    r = client.post("/api/watch/start", json={
        "dir": str(tmp_path), "steps": _gaussian_recipe(), "interval": interval,
    })
    assert r.status_code == 422


@pytest.mark.api
def test_watch_start_accepts_a_relative_directory(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative --dir resolves against the server process's cwd rather
    than crashing — exercised since only the pure FolderWatcher's own
    tests otherwise ever pass it an absolute tmp_path."""
    watch_dir = tmp_path / "incoming"
    watch_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    r = client.post("/api/watch/start", json={
        "dir": "incoming", "steps": _gaussian_recipe(),
    })
    assert r.status_code == 200, r.text
    status = client.get("/api/watch/status").json()
    assert status["watching"] is True


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
def test_recipe_output_never_lands_back_in_the_watched_directory(
    client: TestClient, tmp_path: Path
) -> None:
    """The recursion trap: a derived image from a recipe run on a dropped
    file must never be written to disk INTO the watched directory itself
    (it's only ever registered into the in-memory session store), or a
    watch over its own output directory would re-trigger itself forever.
    Pinned by asserting the directory holds exactly the one file dropped
    into it, after the job that processed it has finished."""
    watch_dir = tmp_path / "incoming"
    watch_dir.mkdir()
    client.post("/api/watch/start", json={
        "dir": str(watch_dir), "steps": _gaussian_recipe(), "interval": 0.02,
    })
    (watch_dir / "drop.png").write_bytes(_png_bytes())
    job_id = _wait_for_job(client)
    final = _poll_job(client, job_id)
    assert final["status"] == "done"

    assert [p.name for p in watch_dir.iterdir()] == ["drop.png"]


@pytest.mark.api
def test_job_queue_backpressure_is_visible_in_status_not_silently_lost(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the shared job queue is saturated (thousands of files landing
    at once, say), FolderWatcher.on_file's JobQueueFullError must not just
    vanish into a single overwritten last_error string — status must show
    HOW MANY files were dropped, not just the most recent one."""
    from fermiviewer.jobs import JobQueueFullError, jobs

    def full(_fn):
        raise JobQueueFullError("queue full")

    monkeypatch.setattr(jobs, "submit", full)

    watch_dir = tmp_path / "incoming"
    watch_dir.mkdir()
    r = client.post("/api/watch/start", json={
        "dir": str(watch_dir), "steps": _gaussian_recipe(), "interval": 60,
    })
    assert r.status_code == 200

    from fermiviewer.routes import watch as watch_routes

    for i in range(3):
        (watch_dir / f"f{i}.png").write_bytes(_png_bytes())
    watch_routes._watcher.poll_once()  # candidates only
    watch_routes._watcher.poll_once()  # stable — all 3 hit the full queue

    status = client.get("/api/watch/status").json()
    assert status["seen"] == 3
    assert status["processed"] == 0
    assert status["errors"] == 3
    assert "queue full" in status["last_error"]


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


# ── named regions in a watch recipe (4C-5) ───────────────────────────


def _gradient_png() -> bytes:
    """A LEFT-HEAVY 8x8 image: the left half and the whole frame have
    different means, so a region that is ignored is visible in the number
    rather than only in the shape of the response."""
    from PIL import Image

    data = np.zeros((8, 8), dtype=np.uint8)
    data[:, :4] = 200
    data[:, 4:] = 10
    buf = io.BytesIO()
    Image.fromarray(data).save(buf, format="PNG")
    return buf.getvalue()


def _left_half_set():
    from fermiviewer.calc.regions import Part, Region, Shape
    from fermiviewer.io.regions_model import RegionSet

    return RegionSet(
        id="s1",
        regions=(
            Region(
                id="r1",
                parts=(Part(Shape(kind="rect", bounds=(0.0, 0.0, 7.0, 3.0))),),
            ),
        ),
    )


@pytest.mark.api
def test_a_watch_recipe_honours_a_named_region(
    client: TestClient, tmp_path: Path
) -> None:
    """`run_recipe` is pure and reads only `step["params"]`, so a
    `region_ref` the watch runner forgot to substitute is not an error —
    the new file is silently analyzed over the whole frame. Only a number
    that differs from the whole-image one can catch that, which is why
    the fixture is deliberately left-heavy.
    """
    from fermiviewer.project_session import project

    project.current()
    project.replace_regions((_left_half_set(),), ())

    watch_dir = tmp_path / "incoming"
    watch_dir.mkdir()
    response = client.post("/api/watch/start", json={
        "dir": str(watch_dir),
        "steps": [{"op": "image_stats", "region_ref": "s1/r1"}],
        "interval": 0.02,
    })
    assert response.status_code == 200, response.text
    (watch_dir / "drop.png").write_bytes(_gradient_png())

    final = _poll_job(client, _wait_for_job(client))
    assert final["status"] == "done", final
    stats = next(
        v for v in final["result"]["values"] if v["op"] == "image_stats"
    )
    assert stats["value"]["n_finite"] == 8 * 4, "the left half only"
    assert stats["value"]["mean"] == pytest.approx(200.0), "not the 105 mean"
    assert stats["value"]["region"]["rows"] == [[1, 1, 8, 4]]
    # ADR 0005: the recorded params carry the RESOLVED geometry
    assert stats["params"]["region"]
    assert "s1" not in repr(stats["params"])
