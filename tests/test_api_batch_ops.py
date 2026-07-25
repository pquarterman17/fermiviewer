from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.jobs import JobQueueFullError, jobs
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _image(name: str, offset: float = 0) -> str:
    data = np.arange(64 * 64, dtype=np.float64).reshape(64, 64) + offset
    ds = DataStruct(
        data=data,
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0, "nm"), AxisCal(0.5, 0, "nm")),
        metadata={"source": name},
    )
    return store.add_parsed(ds, name)


def _poll(client, job_id: str, timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.01)
    raise AssertionError("batch job did not finish")


def test_batch_operation_schema_exposes_analysis_and_filters(client) -> None:
    response = client.get("/api/batch/operations")
    assert response.status_code == 200
    operations = {item["name"]: item for item in response.json()["operations"]}
    assert {
        "gaussian", "plane_level", "morph", "multiotsu",
        "image_stats", "noise", "roughness",
    } <= operations.keys()
    assert operations["noise"]["produces"] == "analysis"
    method = operations["noise"]["params"][0]
    assert method["choices"] == ["mad", "localvar", "both"]


def test_batch_recipe_produces_images_and_values(client) -> None:
    first = _image("first.dm4")
    second = _image("second.dm4", 10)
    response = client.post("/api/batch/run", json={
        "image_ids": [first, second],
        "steps": [
            {"op": "gaussian", "params": {"sigma": 1}},
            {"op": "image_stats", "params": {}},
            {"op": "noise", "params": {"method": "both"}},
        ],
    })
    assert response.status_code == 200, response.text
    final = _poll(client, response.json()["job_id"])
    assert final["status"] == "done"
    result = final["result"]
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert len(result["outputs"]) == 2
    for output in result["outputs"]:
        assert output["status"] == "done"
        assert [value["op"] for value in output["values"]] == [
            "image_stats", "noise",
        ]
        derived_id = output["derived"]["id"]
        assert client.get(f"/api/image/{derived_id}/render").status_code == 200


def test_batch_retains_other_inputs_when_one_operation_fails(client) -> None:
    good = _image("good.dm4")
    too_small = DataStruct(
        data=np.ones((2, 2)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    bad = store.add_parsed(too_small, "too-small.dm4")
    response = client.post("/api/batch/run", json={
        "image_ids": [good, bad],
        "steps": [{"op": "bin", "params": {"bin_size": 4}}],
    })
    final = _poll(client, response.json()["job_id"])["result"]
    assert final["succeeded"] == 1
    assert final["failed"] == 1
    assert [item["status"] for item in final["outputs"]] == ["done", "error"]
    assert final["outputs"][0]["derived"] is not None


def test_batch_rejects_bad_recipe_before_queueing(client) -> None:
    image_id = _image("source.dm4")
    response = client.post("/api/batch/run", json={
        "image_ids": [image_id],
        "steps": [{"op": "gaussian", "params": {"sgima": 2}}],
    })
    assert response.status_code == 422
    assert "unknown param" in response.json()["detail"]


def test_batch_rejects_unknown_image_before_queueing(client) -> None:
    response = client.post("/api/batch/run", json={
        "image_ids": ["missing"],
        "steps": [{"op": "image_stats", "params": {}}],
    })
    assert response.status_code == 404


def test_batch_queue_saturation_is_429(client, monkeypatch) -> None:
    image_id = _image("source.dm4")

    def full(_fn):
        raise JobQueueFullError("queue full")

    monkeypatch.setattr(jobs, "submit", full)
    response = client.post("/api/batch/run", json={
        "image_ids": [image_id],
        "steps": [{"op": "image_stats", "params": {}}],
    })
    assert response.status_code == 429
    assert response.json()["detail"] == "queue full"
