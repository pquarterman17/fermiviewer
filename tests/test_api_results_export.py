"""The HTTP surface for the self-contained export: `/api/results/export`.

The archive's content is covered by `test_results_export.py`. What is
tested HERE is only what the route adds: session lookup, id errors, the
download headers, and that the bytes on the wire really do open as an
archive whose citations resolve — the claim the endpoint makes.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api]


@pytest.fixture()
def client() -> TestClient:
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def _image(client: TestClient, tmp_path: Path) -> str:
    img = np.zeros((16, 16), dtype=np.float32)
    img[4:12, 4:12] = 100.0
    f = write_mini_dm4(
        tmp_path / "a.dm4",
        dims=[16, 16],
        data=img.ravel(),
        data_type=2,
        cal=[
            {"scale": 0.5, "origin": 0, "units": "nm"},
            {"scale": 0.5, "origin": 0, "units": "nm"},
        ],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def _profile(client: TestClient, image_id: str) -> str:
    response = client.post(
        "/api/measure/profile",
        json={
            "image_id": image_id,
            "a": [2, 2],
            "b": [14, 14],
            "width": 3.0,
            "reduce": "mean",
            "record": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["id"]


def _archive(response) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(response.content))


def test_the_download_is_an_archive_whose_citations_resolve(client, tmp_path) -> None:
    """End to end: a captured profile comes back as a file that needs
    nothing else to reconstruct the curve it describes."""
    result_id = _profile(client, _image(client, tmp_path))
    response = client.post("/api/results/export", json={"result_ids": [result_id]})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]

    zf = _archive(response)
    manifest = json.loads(zf.read("manifest.json"))
    (entry,) = manifest["results"]
    assert entry["id"] == result_id
    assert entry["analysis"] == "measure.profile"
    assert entry["params"]["width"] == 3.0

    names = set(zf.namelist())
    for output in entry["outputs"]:
        if output["member"] is not None:
            assert output["member"] in names
            with zf.open(output["member"]) as fh:
                assert np.load(fh, allow_pickle=False).size > 0


def test_the_export_preserves_the_callers_selection_order(client, tmp_path) -> None:
    image = _image(client, tmp_path)
    first, second = _profile(client, image), _profile(client, image)
    response = client.post(
        "/api/results/export", json={"result_ids": [second, first]}
    )
    manifest = json.loads(_archive(response).read("manifest.json"))
    assert [r["id"] for r in manifest["results"]] == [second, first]


def test_unknown_ids_are_named_all_at_once(client, tmp_path) -> None:
    good = _profile(client, _image(client, tmp_path))
    response = client.post(
        "/api/results/export", json={"result_ids": [good, "nope", "also-nope"]}
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "nope" in detail and "also-nope" in detail


def test_an_empty_selection_is_rejected(client) -> None:
    assert client.post(
        "/api/results/export", json={"result_ids": []}
    ).status_code == 422


def test_a_caller_supplied_filename_is_sanitised_to_a_zip(client, tmp_path) -> None:
    """The name reaches a latin-1 header; a path or a quote in it must not
    escape into Content-Disposition."""
    result_id = _profile(client, _image(client, tmp_path))
    response = client.post(
        "/api/results/export",
        json={"result_ids": [result_id], "filename": '../../etc/pa"sswd.txt'},
    )
    disposition = response.headers["content-disposition"]
    assert disposition == 'attachment; filename="passwd.zip"'


def test_the_default_filename_is_used_when_none_is_given(client, tmp_path) -> None:
    result_id = _profile(client, _image(client, tmp_path))
    response = client.post("/api/results/export", json={"result_ids": [result_id]})
    assert 'filename="results.zip"' in response.headers["content-disposition"]
