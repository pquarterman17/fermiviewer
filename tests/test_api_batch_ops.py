from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.eds import line_energy
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


def _eds_cube(name: str) -> tuple[str, float]:
    """A small SI cube with a single Fe Ka peak (energy from the app's own
    line_energy() table, per the fixtures-derive-from-production-tables
    convention)."""
    ny, nx, ne = 6, 6, 800
    scale = 0.015
    energy_kev = np.arange(ne) * scale                    # 0 – 11.985 keV
    fe_e, _ = line_energy("Fe", beam_kv=200.0)
    spectrum = np.full(ne, 3.0)
    spectrum += 80.0 * np.exp(-((energy_kev - fe_e) ** 2) / (2 * 0.03**2))
    cube = np.tile(spectrum, (ny, nx, 1))
    ds = DataStruct(
        data=cube, kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(1.0, 0, "nm"), AxisCal(1.0, 0, "nm"), AxisCal(scale, 0, "keV")),
        metadata={"source": name},
    )
    return store.add_parsed(ds, name), float(fe_e)


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


def test_batch_operation_schema_exposes_spectral_ops(client) -> None:
    response = client.get("/api/batch/operations")
    operations = {item["name"]: item for item in response.json()["operations"]}
    assert {
        "eels_map", "eels_quantify", "eds_element_map", "eds_quantify",
        "radial_profile",
    } <= operations.keys()
    # value-producing ops report produces="analysis" even in a non-"analysis"
    # category (eels/eds/diffraction) — the schema-time hint added alongside
    # this catalogue, since category alone used to decide it
    assert operations["eels_quantify"]["produces"] == "analysis"
    assert operations["eds_quantify"]["produces"] == "analysis"
    assert operations["radial_profile"]["produces"] == "analysis"
    assert operations["eels_map"]["produces"] == "image"
    assert operations["eds_element_map"]["produces"] == "image"
    assert operations["eels_map"]["category"] == "eels"
    assert operations["eds_quantify"]["category"] == "eds"
    assert operations["radial_profile"]["category"] == "diffraction"


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


def test_batch_recipe_mixes_eds_ops_with_filters_and_values(client) -> None:
    """A recipe mixing a new EDS quant/map op with the pre-existing filter
    and analysis ops (Scripting #6, remaining half): quantify the Fe peak
    (value, runs against the raw cube), extract its element map (image,
    still against the raw cube since quantify doesn't alter the chain),
    smooth it with an existing filter op, then collect image stats. A
    plain 2D image can't satisfy the EDS ops' spectrum-image requirement,
    so it exercises per-input failure isolation too."""
    good, fe_e = _eds_cube("good.bcf")
    bad = _image("not-a-cube.dm4")
    response = client.post("/api/batch/run", json={
        "image_ids": [good, bad],
        "steps": [
            {"op": "eds_quantify", "params": {"elements": "Fe"}},
            {"op": "eds_element_map", "params": {
                "e_lo": fe_e - 0.1, "e_hi": fe_e + 0.1,
            }},
            {"op": "gaussian", "params": {"sigma": 1.0}},
            {"op": "image_stats", "params": {}},
        ],
    })
    assert response.status_code == 200, response.text
    final = _poll(client, response.json()["job_id"])
    assert final["status"] == "done"
    result = final["result"]
    assert result["succeeded"] == 1
    assert result["failed"] == 1

    good_out = next(o for o in result["outputs"] if o["image_id"] == good)
    assert good_out["status"] == "done"
    assert [v["op"] for v in good_out["values"]] == ["eds_quantify", "image_stats"]
    quant = good_out["values"][0]["value"]
    assert quant["elements"] == ["Fe"]
    assert quant["mean_atomic_pct"][0] == pytest.approx(100.0, abs=1e-6)
    stats = good_out["values"][1]["value"]
    assert stats["shape"] == [6, 6]
    assert good_out["derived"] is not None
    render = client.get(f"/api/image/{good_out['derived']['id']}/render")
    assert render.status_code == 200

    bad_out = next(o for o in result["outputs"] if o["image_id"] == bad)
    assert bad_out["status"] == "error"
    assert "spectrum-image" in bad_out["error"]
    assert bad_out["derived"] is None
    assert bad_out["values"] == []


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
