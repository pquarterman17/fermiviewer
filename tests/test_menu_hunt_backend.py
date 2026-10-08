"""Regressions from the menu-bar QA sweep (backend side)."""

from __future__ import annotations

import io
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from fixtures.minidm4 import write_mini_dm4

from fermiviewer.calc.render import histogram
from fermiviewer.routes.export_batch import _archive_stem
from fermiviewer.server import create_app
from fermiviewer.session import store


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open(client, tmp_path, data, name="img.dm4") -> str:
    h, w = data.shape
    f = write_mini_dm4(tmp_path / name, dims=[w, h], data=data.ravel(),
                       cal=[{"scale": 1.0, "origin": 0, "units": "nm"}] * 2)
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def test_histogram_near_constant_data() -> None:
    # radius-0 VDF output: span below float resolution for 128 edges
    d = np.full((10, 10), 1.3101028018784382)
    d[0, 0] = 1.3101028018784395
    centers, counts = histogram(d, 128)
    assert counts.sum() == 100 and np.all(np.isfinite(centers))


@pytest.mark.parametrize(("name", "stem"), [
    ("x.dm3", "x"),
    ("FFT(x.dm3)", "FFT(x.dm3)"),
    ("../../evil", "evil"),
    ("a/b\\c.tif", "c"),
    ("..", ""),
])
def test_archive_stem(name: str, stem: str) -> None:
    assert _archive_stem(name) == stem


def test_batch_export_entries_have_no_path_parts(client, tmp_path) -> None:
    ids = [_open(client, tmp_path, np.random.default_rng(i).random((16, 16)),
                 f"t{i}.dm4") for i in range(2)]
    for i in ids:
        store.rename(i, "../../evil")
    r = client.post("/api/export/batch", json={"image_ids": ids, "format": "png"})
    assert r.status_code == 200, r.text
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert all("/" not in n and not n.startswith(".") for n in names), names


def test_vdf_rejects_bad_params(client, tmp_path) -> None:
    iid = _open(client, tmp_path, np.random.default_rng(0).random((32, 32)))
    for body in ({"center": [16, 16], "radius": 0},
                 {"center": [-5, 99999], "radius": 5},
                 {"center": [16, 16], "radius": 5, "inner_radius": 6}):
        r = client.post("/api/analyze/vdf", json={"image_id": iid, **body})
        assert r.status_code == 422, (body, r.text)


def test_project_save_requires_full_existing_path(client, tmp_path) -> None:
    _open(client, tmp_path, np.ones((8, 8)))
    for p in ("relative.fvp", str(tmp_path / "missing" / "x.fvp")):
        r = client.post("/api/project/save", json={"path": p})
        assert r.status_code == 422, (p, r.text)
    assert not (tmp_path / "missing").exists()
    r = client.post("/api/project/save", json={"path": str(tmp_path / "ok.fvp")})
    assert r.status_code == 200, r.text
