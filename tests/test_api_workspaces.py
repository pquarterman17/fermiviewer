"""API tests for named workspaces (design WS4b) — the switcher's backend.

Workspaces reuse the project serializer (a `<slug>.fvp` since plan #32); these
cover the naming layer: slugging, the index, round-trip restore, deletion,
self-healing, and that a workspace written as a legacy v1 pair still opens.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer import workspaces
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4
from fixtures.v1_session import write_v1_session

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Redirect the OS config dir so workspaces land in a tmp dir."""
    monkeypatch.setenv("FV_CONFIG_DIR", str(tmp_path / "cfg"))
    store.clear()
    project.clear()
    yield
    store.clear()
    project.clear()


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


def test_slugify() -> None:
    assert workspaces.slugify("EELS Session 1") == "eels-session-1"
    assert workspaces.slugify("  Trailing/Slashes!!  ") == "trailing-slashes"
    assert workspaces.slugify("***") == "workspace"  # never empty


def test_save_list_load_roundtrip(client, tmp_path) -> None:
    img_id = _open_fixture(client, tmp_path)
    src = np.array(store.get(img_id).data, copy=True)
    state = {"views": {img_id: {"z": 2, "px": 0.5, "py": 0.5}}}

    r = client.post(
        "/api/workspaces/save",
        json={"name": "My Study", "client_state": state},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "my-study"
    assert body["name"] == "My Study"
    assert body["n_images"] == 1

    listed = client.get("/api/workspaces").json()["workspaces"]
    assert len(listed) == 1
    assert listed[0]["slug"] == "my-study"
    assert listed[0]["name"] == "My Study"
    assert listed[0]["n_images"] == 1
    assert listed[0]["saved_at"]  # timestamp recorded

    # open an extra image, then load the workspace → replaces the session
    extra = _open_fixture(client, tmp_path)
    assert len(store.ids()) == 2
    r2 = client.post("/api/workspaces/load", json={"slug": "my-study"})
    assert r2.status_code == 200
    assert r2.json()["name"] == "My Study"
    # the opaque half round-trips verbatim; the promoted sections come back
    # alongside it, empty here because this workspace has no samples/measures
    assert r2.json()["client_state"]["views"] == state["views"]
    assert r2.json()["client_state"]["imageGroups"] == []
    assert r2.json()["client_state"]["measures"] == {}
    assert r2.json()["unavailable"] == []
    assert workspaces.project_path("my-study").is_file()  # one .fvp, no sidecars
    assert not workspaces.session_path("my-study").exists()
    assert store.ids() == [img_id]  # extra image gone
    np.testing.assert_array_equal(store.get(img_id).data, src)
    del extra


def test_resave_same_name_updates_in_place(client, tmp_path) -> None:
    _open_fixture(client, tmp_path)
    client.post("/api/workspaces/save", json={"name": "Work"})
    _open_fixture(client, tmp_path)  # now two images
    r = client.post("/api/workspaces/save", json={"name": "Work"})
    assert r.json()["n_images"] == 2
    listed = client.get("/api/workspaces").json()["workspaces"]
    assert len(listed) == 1  # same slug → overwritten, not duplicated
    assert listed[0]["n_images"] == 2


def test_delete(client, tmp_path) -> None:
    _open_fixture(client, tmp_path)
    client.post("/api/workspaces/save", json={"name": "Temp"})
    r = client.delete("/api/workspaces/temp")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert client.get("/api/workspaces").json()["workspaces"] == []
    # deleting again is a no-op (already gone)
    assert client.delete("/api/workspaces/temp").json()["deleted"] is False


def test_list_self_heals_orphaned_index(client, tmp_path) -> None:
    _open_fixture(client, tmp_path)
    client.post("/api/workspaces/save", json={"name": "Ghost"})
    # remove the project out of band; the index still references it
    workspaces.project_path("ghost").unlink()
    assert client.get("/api/workspaces").json()["workspaces"] == []


def test_a_legacy_v1_workspace_still_opens_and_upgrades_on_save(
    client, tmp_path
) -> None:
    """Workspaces saved before plan #32 are a `.json`/`.npz` pair. They must
    keep opening — migrated in memory — and the next save writes the `.fvp`."""
    ds = DataStruct(
        data=np.arange(6, dtype=np.uint16).reshape(2, 3),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        metadata={},
    )
    write_v1_session(
        workspaces.session_path("old-study"),
        [("legacy-1", "frame.dm4", ds)],
        {"views": {"legacy-1": {"z": 4}}},
    )
    workspaces.register("old-study", "Old Study", 1, "2026-01-01T00:00:00+00:00")
    assert [w["slug"] for w in client.get("/api/workspaces").json()["workspaces"]] == [
        "old-study"
    ]

    r = client.post("/api/workspaces/load", json={"slug": "old-study"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Old Study"
    assert r.json()["client_state"]["views"] == {"legacy-1": {"z": 4}}
    assert store.ids() == ["legacy-1"]

    client.post("/api/workspaces/save", json={"name": "Old Study"})
    assert workspaces.project_path("old-study").is_file()
    # the .fvp now wins, and deleting the workspace clears every name
    assert workspaces.stored_path("old-study") == workspaces.project_path("old-study")
    client.delete("/api/workspaces/old-study")
    assert workspaces.stored_path("old-study") is None
    assert not workspaces.session_path("old-study").with_suffix(".npz").exists()


def test_error_paths(client, tmp_path) -> None:
    # nothing open → nothing to save
    _open_fixture(client, tmp_path)  # open so the empty-name check runs first
    store.clear()
    assert (
        client.post("/api/workspaces/save", json={"name": "X"}).status_code
        == 422
    )
    # blank name rejected
    _open_fixture(client, tmp_path)
    assert (
        client.post("/api/workspaces/save", json={"name": "   "}).status_code
        == 422
    )
    # unknown slug → 404
    assert (
        client.post("/api/workspaces/load", json={"slug": "nope"}).status_code
        == 404
    )
