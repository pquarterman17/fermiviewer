"""The 1C result API: capture on analysis routes, session-wide query,
member-data access, deletion — and the full capture → save → reopen loop.

Two adopters prove the contract from opposite ends: EDS quantification
(spectral, small inline table, σ-bearing scalars, derived element maps) and
particle analysis (non-spectral, member-backed morphometrics table, derived
label map). The persistence fundamentals stay in tests/test_project_results.py;
this file owns the route surface and the session lifecycle.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.io.project_file import load_project
from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.api


@pytest.fixture()
def client() -> TestClient:
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def _open(client: TestClient, path: Path) -> str:
    return client.post("/api/session/open", json={"paths": [str(path)]}).json()[0]["id"]


@pytest.fixture()
def eds_cube_id(client: TestClient, tmp_path: Path) -> str:
    """5×4 px × 512 ch EDS cube (keV axis) with an Fe Kα peak — the same
    synthetic construction test_api_analysis.py quantifies."""
    ny, nx, ne = 4, 5, 512
    e = np.arange(ne) * 0.02
    peak = 60 * np.exp(-((e - 6.404) ** 2) / (2 * 0.05**2))
    spec = (2.0 + peak).astype(np.float32)
    flat = np.repeat(spec, ny * nx)
    f = write_mini_dm4(
        tmp_path / "eds.dm4",
        dims=[nx, ny, ne],
        data=flat,
        data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 0.02, "origin": 0, "units": "keV"},
        ],
    )
    return _open(client, f)


@pytest.fixture()
def particle_image_id(client: TestClient, tmp_path: Path) -> str:
    """8×8 image with two bright square particles on a dark field."""
    img = np.zeros((8, 8), dtype=np.float32)
    img[1:3, 1:3] = 100.0
    img[5:8, 5:8] = 100.0
    f = write_mini_dm4(
        tmp_path / "particles.dm4",
        dims=[8, 8],
        data=img.ravel(),
        data_type=2,
        cal=[
            {"scale": 2.0, "origin": 0, "units": "nm"},
            {"scale": 2.0, "origin": 0, "units": "nm"},
        ],
    )
    return _open(client, f)


# ── capture on analysis routes ───────────────────────────────────────


def test_record_defaults_off_and_captures_nothing(client, eds_cube_id) -> None:
    """Recording is a user decision, not a side effect of every exploratory
    run — without record:true the session stays free of records."""
    r = client.post(
        "/api/eds/quantify",
        json={
            "image_id": eds_cube_id,
            "elements": ["Fe"],
        },
    )
    assert r.status_code == 200
    assert "result" not in r.json()
    assert client.get("/api/results").json()["results"] == []


def test_eds_quantify_captures_a_contract_conformant_record(
    client,
    eds_cube_id,
) -> None:
    r = client.post(
        "/api/eds/quantify",
        json={
            "image_id": eds_cube_id,
            "elements": ["Fe"],
            "record": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    result_id = body["result"]["id"]

    (entry,) = client.get("/api/results").json()["results"]
    assert entry["id"] == result_id
    assert entry["analysis"] == "eds.quantify"
    assert entry["status"] == "completed"
    assert entry["missing_members"] == []
    # resolved params, defaults filled — the reproduction key — and never
    # the capture toggle itself
    assert entry["params"]["method"] == "cliff-lorimer"
    assert entry["params"]["half_window_kev"] == pytest.approx(0.085)
    assert "record" not in entry["params"]
    # per-element σ-bearing scalar + the composition table (1B card contract)
    scalar = next(o for o in entry["outputs"] if o["kind"] == "scalar")
    assert scalar["name"] == "Fe"
    assert scalar["data"]["value"] == pytest.approx(100.0)
    assert scalar["data"]["unit"] == "at%"
    assert "sigma" in scalar["data"]
    table = next(o for o in entry["outputs"] if o["kind"] == "table")
    assert table["data"]["columns"][0] == "element"
    assert table["data"]["rows"][0][0] == "Fe"
    # calibration snapshotted from the source at compute time
    (snap,) = entry["calibration"]
    assert snap["image_id"] == eds_cube_id
    assert snap["axes"][0]["units"] == "nm"
    # the registered element map rides as a derived id
    assert entry["derived_ids"] == [body["maps"][0]["id"]]
    assert entry["source_ids"] == [eds_cube_id]


def test_particles_capture_uses_a_member_backed_table(
    client,
    particle_image_id,
) -> None:
    """Thousands of morphometric rows must never inline into manifest.json —
    the particle table is the member-array adopter (ADR 0004 §2)."""
    r = client.post(
        "/api/analyze/particles",
        json={
            "image_id": particle_image_id,
            "record": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    result_id = body["result"]["id"]

    entry = client.get(f"/api/results/{result_id}").json()
    assert entry["analysis"] == "structure.particles"
    table = next(o for o in entry["outputs"] if o["kind"] == "table")
    assert table["member"] == f"results/{result_id}/2.npy"
    assert table["data"]["columns"][0] == "id"
    assert len(table["data"]["shape_class"]) == body["n_particles"]
    # the auto-picked threshold is recorded as the RESOLVED param
    assert entry["params"]["threshold"] == pytest.approx(body["threshold"])
    assert entry["derived_ids"] == [body["labels"]["id"]]

    data = client.get(f"/api/results/{result_id}/outputs/2/data").json()
    assert data["shape"] == [body["n_particles"], len(table["data"]["columns"])]
    assert data["dtype"] == "float64"
    # row 0, column 0 is the first particle id; uncalibrated cells came
    # through as null, not NaN (strict JSON)
    assert data["values"][0][0] == pytest.approx(1.0)


# ── query surface ────────────────────────────────────────────────────


def test_unknown_ids_are_404s(client) -> None:
    assert client.get("/api/results/nope").status_code == 404
    assert client.delete("/api/results/nope").status_code == 404
    assert client.get("/api/results/nope/outputs/0/data").status_code == 404


def test_out_of_range_output_index_is_a_404(client, eds_cube_id) -> None:
    r = client.post(
        "/api/eds/quantify",
        json={
            "image_id": eds_cube_id,
            "elements": ["Fe"],
            "record": True,
        },
    )
    result_id = r.json()["result"]["id"]
    assert client.get(f"/api/results/{result_id}/outputs/99/data").status_code == 404


def test_delete_removes_the_record_from_session_and_next_save(
    client,
    particle_image_id,
    tmp_path,
) -> None:
    r = client.post(
        "/api/analyze/particles",
        json={
            "image_id": particle_image_id,
            "record": True,
        },
    )
    result_id = r.json()["result"]["id"]

    deleted = client.delete(f"/api/results/{result_id}")
    assert deleted.status_code == 200
    assert deleted.json()["n_results"] == 0
    assert client.get("/api/results").json()["results"] == []

    saved = client.post(
        "/api/project/save",
        json={
            "path": str(tmp_path / "after-delete.fvp"),
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["n_results"] == 0
    assert load_project(tmp_path / "after-delete.fvp").results == ()


# ── the full loop: capture → save → reopen ───────────────────────────


def test_captured_record_survives_save_and_reopen_with_arrays(
    client,
    particle_image_id,
    tmp_path,
) -> None:
    """The workflow item 1 exists for: run an analysis, save the project,
    reopen it, and the record is still there — metadata, member array,
    calibration snapshot and all — with no client cooperation required."""
    run = client.post(
        "/api/analyze/particles",
        json={
            "image_id": particle_image_id,
            "record": True,
        },
    )
    result_id = run.json()["result"]["id"]
    n = run.json()["n_particles"]

    path = tmp_path / "captured.fvp"
    assert client.post("/api/project/save", json={"path": str(path)}).status_code == 200

    loaded = client.post("/api/project/load", json={"path": str(path)})
    assert loaded.status_code == 200, loaded.text
    (entry,) = loaded.json()["results"]
    assert entry["id"] == result_id
    assert entry["missing_members"] == []

    data = client.get(f"/api/results/{result_id}/outputs/2/data").json()
    assert data["shape"][0] == n

    # and the on-disk container holds the member, not inline rows
    (record,) = load_project(path).results
    table = record.outputs[2]
    assert table.member == f"results/{result_id}/2.npy"
    assert table.array is not None and table.array.shape[0] == n
    assert "rows" not in table.data
