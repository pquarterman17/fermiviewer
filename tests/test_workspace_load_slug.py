"""POST /workspaces/load must validate the slug the same way DELETE
/workspaces/{slug} already does — accepting an arbitrary string let a
crafted slug (e.g. containing "../") reach workspaces.session_path()
unchecked, unlike the delete route's anti-traversal regex.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("FV_CONFIG_DIR", str(tmp_path / "cfg"))
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open_fixture(client, tmp_path) -> str:
    w, h = 8, 6
    flat = np.array([x + 10 * y for y in range(h) for x in range(w)])
    f = write_mini_dm4(
        tmp_path / "img.dm4", dims=[w, h], data=flat,
        cal=[{"scale": 0.25, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


@pytest.mark.parametrize(
    "slug",
    ["../../etc/passwd", "Bad_Slug!", "has spaces", "UPPER", ""],
)
def test_workspace_load_rejects_bad_slug(client: TestClient, slug: str) -> None:
    r = client.post("/api/workspaces/load", json={"slug": slug})
    assert r.status_code == 422


def test_workspace_load_accepts_clean_slug(client: TestClient, tmp_path) -> None:
    _open_fixture(client, tmp_path)
    client.post("/api/workspaces/save", json={"name": "My Study"})
    # a clean slug passes validation and loads successfully
    r = client.post("/api/workspaces/load", json={"slug": "my-study"})
    assert r.status_code == 200
    assert r.json()["name"] == "My Study"
    # a clean but nonexistent slug passes validation, 404s on lookup
    r2 = client.post("/api/workspaces/load", json={"slug": "no-such-workspace"})
    assert r2.status_code == 404
