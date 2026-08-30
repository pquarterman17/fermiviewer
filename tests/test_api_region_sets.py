"""Live CRUD bridge for ADR 0006 region workspaces (roadmap 4B-1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store


@pytest.fixture()
def client():
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


REGIONS = {
    "schema": 1,
    "classes": [
        {"id": "grain", "label": "Grain", "color": "#8b5cf6", "note": None}
    ],
    "sets": [
        {
            "id": "set-1",
            "name": "Primary grains",
            "image_id": "image-1",
            "meta": {},
            "regions": [
                {
                    "id": "region-1",
                    "name": "Grain 1",
                    "region_class": "grain",
                    "meta": {},
                    "parts": [
                        {
                            "mode": "include",
                            "shape": {
                                "kind": "polygon",
                                "outline": [[1, 1], [1, 8], [8, 8], [8, 1]],
                                "holes": [[[3, 3], [3, 5], [5, 5], [5, 3]]],
                            },
                        },
                        {
                            "mode": "exclude",
                            "shape": {"kind": "rect", "bounds": [6, 6, 7, 7]},
                        },
                    ],
                }
            ],
        }
    ],
}


@pytest.mark.api
def test_region_workspace_replaces_and_reads_exact_geometry(client: TestClient) -> None:
    assert client.get("/api/region-sets").json() == {
        "schema": 1,
        "classes": [],
        "sets": [],
    }

    response = client.post("/api/region-sets/replace", json=REGIONS)
    assert response.status_code == 200, response.text
    assert response.json() == REGIONS
    assert client.get("/api/region-sets").json() == REGIONS
    assert project.current().region_sets[0].regions[0].parts[1].mode == "exclude"


@pytest.mark.api
def test_invalid_replacement_is_atomic(client: TestClient) -> None:
    assert client.post("/api/region-sets/replace", json=REGIONS).status_code == 200
    invalid = {**REGIONS, "sets": [REGIONS["sets"][0], REGIONS["sets"][0]]}

    response = client.post("/api/region-sets/replace", json=invalid)
    assert response.status_code == 422
    assert "duplicate region set id" in response.text
    assert client.get("/api/region-sets").json() == REGIONS


@pytest.mark.api
def test_shape_invariant_errors_are_422s(client: TestClient) -> None:
    malformed = {
        **REGIONS,
        "sets": [{
            **REGIONS["sets"][0],
            "regions": [{
                **REGIONS["sets"][0]["regions"][0],
                "parts": [{
                    "mode": "include",
                    "shape": {"kind": "polygon", "bounds": [1, 1, 3, 3]},
                }],
            }],
        }],
    }
    response = client.post("/api/region-sets/replace", json=malformed)
    assert response.status_code == 422
    assert project.current().region_sets == ()


@pytest.mark.api
def test_replacement_must_declare_its_regions_schema(client: TestClient) -> None:
    missing = {key: value for key, value in REGIONS.items() if key != "schema"}
    response = client.post("/api/region-sets/replace", json=missing)
    assert response.status_code == 422
    assert "schema" in response.text
    assert project.current().region_sets == ()
