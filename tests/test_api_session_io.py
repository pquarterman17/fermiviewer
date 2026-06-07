"""API tests for /session/save + /session/load — workspace round-trip."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _clean_store():
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


def test_save_load_roundtrip(client, tmp_path) -> None:
    img_id = _open_fixture(client, tmp_path)
    # add a derived image so the session has lineage content
    fft_id = client.post(f"/api/image/{img_id}/fft").json()["id"]
    src_data = np.array(store.get(img_id).data, copy=True)
    fft_data = np.array(store.get(fft_id).data, copy=True)

    state = {"views": {img_id: {"z": 2, "px": 0.5, "py": 0.5}}, "theme": "dark"}
    r = client.post(
        "/api/session/save",
        json={"path": str(tmp_path / "work.json"), "client_state": state},
    )
    assert r.status_code == 200
    assert r.json()["n_images"] == 2
    assert (tmp_path / "work.json").is_file()
    assert (tmp_path / "work.npz").is_file()

    # wipe and reload
    store.clear()
    r2 = client.post(
        "/api/session/load", json={"path": str(tmp_path / "work.json")}
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["client_state"] == state
    metas = {m["id"]: m for m in body["images"]}
    assert set(metas) == {img_id, fft_id}  # ids preserved

    # pixels and calibration survive exactly (original dtype too)
    restored = store.get(img_id)
    np.testing.assert_array_equal(restored.data, src_data)
    assert restored.data.dtype == src_data.dtype
    assert metas[img_id]["pixel_size"] == pytest.approx(0.25)
    assert metas[img_id]["pixel_unit"] == "nm"
    np.testing.assert_allclose(store.get(fft_id).data, fft_data)
    assert store.get(fft_id).metadata.get("derived_from") == img_id

    # the restored session is fully usable (render works)
    assert client.get(f"/api/image/{img_id}/render").status_code == 200


def test_load_replace_semantics(client, tmp_path) -> None:
    img_id = _open_fixture(client, tmp_path)
    client.post(
        "/api/session/save", json={"path": str(tmp_path / "s.json")}
    )
    # open another image after saving
    extra_id = _open_fixture(client, tmp_path)
    assert len(store.ids()) == 2

    # replace=True (default) wipes the extra image
    client.post("/api/session/load", json={"path": str(tmp_path / "s.json")})
    assert store.ids() == [img_id]

    # replace=False appends; saved id collides → fresh id assigned
    r = client.post(
        "/api/session/load",
        json={"path": str(tmp_path / "s.json"), "replace": False},
    )
    new_id = r.json()["images"][0]["id"]
    assert new_id != img_id
    assert len(store.ids()) == 2
    del extra_id


def test_error_paths(client, tmp_path) -> None:
    # nothing open → nothing to save
    assert (
        client.post(
            "/api/session/save", json={"path": str(tmp_path / "x.json")}
        ).status_code
        == 422
    )
    # missing manifest
    assert (
        client.post(
            "/api/session/load", json={"path": str(tmp_path / "nope.json")}
        ).status_code
        == 404
    )
    # manifest without sidecar
    (tmp_path / "lonely.json").write_text('{"version": 1, "images": []}')
    assert (
        client.post(
            "/api/session/load", json={"path": str(tmp_path / "lonely.json")}
        ).status_code
        == 404
    )
    # corrupt version
    img_id = _open_fixture(client, tmp_path)
    client.post("/api/session/save", json={"path": str(tmp_path / "v.json")})
    bad = (tmp_path / "v.json").read_text().replace('"version": 1', '"version": 99')
    (tmp_path / "v.json").write_text(bad)
    assert (
        client.post(
            "/api/session/load", json={"path": str(tmp_path / "v.json")}
        ).status_code
        == 422
    )
    del img_id
