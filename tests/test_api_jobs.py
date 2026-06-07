"""Background-job system: async grains end-to-end + error paths."""

from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

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
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise TimeoutError("job did not finish")


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
