"""Background-job system: async grains end-to-end + error paths."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.jobs import JobQueueFullError, JobStore, jobs
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.imaging]


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _poll(client: TestClient, job_id: str, timeout_s: float = 30) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.05)
    raise TimeoutError("job did not finish")


def _wait_status(store_: JobStore, job_id: str, wanted: str, timeout_s: float = 30) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = store_.get(job_id)
        if job is not None and job.status == wanted:
            return
        time.sleep(0.01)
    raise TimeoutError(f"job never reached {wanted!r}")


def test_async_grains_matches_sync(client, tmp_path) -> None:
    r = np.arange(1, 49, dtype=np.float64)[:, None]
    c = np.arange(1, 65, dtype=np.float64)[None, :]
    img = np.hstack(
        [
            np.broadcast_to(np.sin(r / 7) * np.cos(c[:, :32] / 11), (48, 32)),
            np.sin(13 * r + 7 * c[:, 32:]) * 0.5 + 2.0,
        ]
    )
    f = write_mini_dm4(
        tmp_path / "g.dm4", dims=[64, 48], data=(img * 100).ravel(),
        cal=[{"scale": 1, "origin": 0, "units": "nm"}] * 2,
    )
    img_id = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]

    sync = client.post(
        "/api/analyze/grains", json={"image_id": img_id, "k": 2}
    ).json()

    start = client.post(
        "/api/analyze/grains",
        json={"image_id": img_id, "k": 2, "run_async": True},
    )
    assert start.status_code == 200
    job_id = start.json()["job_id"]
    final = _poll(client, job_id)
    assert final["status"] == "done"
    assert final["progress"] == 1.0
    result = final["result"]
    # same partition characteristics as the synchronous run
    assert result["n_grains"] == sync["n_grains"]
    assert sorted(result["areas_px"]) == sorted(sync["areas_px"])
    # the async result's label image is registered and renderable
    assert (
        client.get(f"/api/image/{result['labels']['id']}/render").status_code
        == 200
    )


def test_job_error_paths(client) -> None:
    assert client.get("/api/jobs/nope").status_code == 404
    # async submit with unknown image fails SYNCHRONOUSLY (validated up front)
    assert (
        client.post(
            "/api/analyze/grains",
            json={"image_id": "nope", "k": 2, "run_async": True},
        ).status_code
        == 404
    )


# ── admission control: queued state, pending bound, cancel, shutdown ─


def test_job_lifecycle_states_bound_and_cancel() -> None:
    store_ = JobStore(max_workers=1, max_pending=2)
    started = threading.Event()
    release = threading.Event()

    def blocker(progress) -> str:
        started.set()
        release.wait(timeout=30)
        return "ok"

    try:
        running = store_.submit(blocker)
        assert started.wait(timeout=30)
        _wait_status(store_, running, "running")

        # with the single worker busy, further submits sit queued
        queued = store_.submit(lambda p: "fast")
        extra = store_.submit(lambda p: "fast")
        assert store_.get(queued).status == "queued"

        # admission bound: max_pending queued jobs → refused
        with pytest.raises(JobQueueFullError):
            store_.submit(lambda p: "never")

        # queued jobs cancel; running/finished/unknown ones don't
        assert store_.cancel(extra) is True
        snap = store_.get(extra).snapshot()
        assert snap["status"] == "error"
        assert snap["error"] == "cancelled"
        assert store_.cancel(running) is False
        assert store_.cancel("nope") is False
    finally:
        release.set()

    _wait_status(store_, running, "done")
    _wait_status(store_, queued, "done")
    assert store_.get(running).snapshot()["result"] == "ok"


def test_job_shutdown_cancels_queued_then_restarts() -> None:
    store_ = JobStore(max_workers=1)
    started = threading.Event()
    release = threading.Event()

    def blocker(progress) -> str:
        started.set()
        release.wait(timeout=30)
        return "survived"

    try:
        running = store_.submit(blocker)
        assert started.wait(timeout=30)
        queued = store_.submit(lambda p: "never runs")

        store_.shutdown()
        snap = store_.get(queued).snapshot()
        assert snap["status"] == "error"
        assert snap["error"] == "cancelled at shutdown"
    finally:
        release.set()

    # the already-running job still completes on its worker thread
    _wait_status(store_, running, "done")
    assert store_.get(running).snapshot()["result"] == "survived"

    # a store reused after shutdown starts a fresh pool transparently
    again = store_.submit(lambda p: "fresh pool")
    _wait_status(store_, again, "done")
    store_.shutdown()


def test_grains_returns_429_when_queue_full(client, tmp_path, monkeypatch) -> None:
    from fermiviewer.routes import structure as structure_routes

    f = write_mini_dm4(tmp_path / "q.dm4", dims=[8, 8], data=np.arange(64))
    img_id = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]

    def full(fn):
        raise JobQueueFullError("32 jobs already queued — retry when some finish")

    monkeypatch.setattr(structure_routes.jobs, "submit", full)
    r = client.post(
        "/api/analyze/grains",
        json={"image_id": img_id, "k": 2, "run_async": True},
    )
    assert r.status_code == 429
    assert "queued" in r.json()["detail"]


def test_job_cancel_endpoint(client) -> None:
    assert client.delete("/api/jobs/nope").status_code == 404

    # block both global workers so a third job stays queued, then cancel
    # it through the API (the route and the store share the singleton)
    release = threading.Event()
    gates = [threading.Event(), threading.Event()]

    def blocker(gate):
        def run(progress) -> None:
            gate.set()
            release.wait(timeout=30)

        return run

    try:
        blockers = [jobs.submit(blocker(g)) for g in gates]
        for g in gates:
            assert g.wait(timeout=30)
        queued = jobs.submit(lambda p: "never runs")

        r = client.delete(f"/api/jobs/{queued}")
        assert r.status_code == 200
        assert r.json() == {"cancelled": queued}
        assert client.get(f"/api/jobs/{queued}").json()["status"] == "error"

        # a job that already started (or finished) can't be cancelled
        assert client.delete(f"/api/jobs/{blockers[0]}").status_code == 409
    finally:
        release.set()
    for jid in blockers:
        _wait_status(jobs, jid, "done")
