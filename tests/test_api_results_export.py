"""The HTTP surface for the self-contained export: `/api/results/export`.

The archive's content is covered by `test_results_export.py`. What is
tested HERE is only what the route adds: session lookup, id errors, the
download headers, and that the bytes on the wire really do open as an
archive whose citations resolve — the claim the endpoint makes.
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.project_session import project
from fermiviewer.routes import results_api
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api]

#: The pristine class, captured before any test patches it — two patches
#: in one test would otherwise stack, the second wrapping the first and
#: silently ignoring its own max_size.
_REAL_SPOOL = tempfile.SpooledTemporaryFile


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


def _spy_spools(monkeypatch, max_size: int) -> list:
    """Replace the route's spool factory so the test can see whether the
    archive actually rolled to disk, instead of trusting a threshold.

    Worth the indirection: `SpooledTemporaryFile(max_size=0)` never rolls
    (`_check` tests `if self._max_size and ...`), so a test that merely set
    the threshold to zero would assert nothing about the disk path while
    appearing to cover it.
    """
    made = []

    def factory(*args, **kwargs):
        spool = _REAL_SPOOL(max_size=max_size)
        made.append(spool)
        return spool

    monkeypatch.setattr(results_api.tempfile, "SpooledTemporaryFile", factory)
    return made


def test_the_archive_rolls_to_disk_rather_than_holding_the_whole_zip(
    client, tmp_path, monkeypatch
) -> None:
    """The endpoint must not accumulate the whole ZIP in RAM — the payloads
    it exists to make portable are elemental-map stacks and spectrum cubes.

    A 1-byte threshold forces the rolled path for any real archive, and the
    spy asserts the roll HAPPENED rather than inferring it from the config.
    """
    made = _spy_spools(monkeypatch, max_size=1)
    result_id = _profile(client, _image(client, tmp_path))
    response = client.post("/api/results/export", json={"result_ids": [result_id]})

    assert response.status_code == 200
    (spool,) = made
    assert spool._rolled is True                      # actually went to disk
    zf = _archive(response)
    assert zf.testzip() is None                       # and came back intact
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["results"][0]["id"] == result_id


def test_a_rolled_export_matches_an_in_memory_one_array_for_array(
    client, tmp_path, monkeypatch
) -> None:
    """Rolling to disk is a memory decision, not a format one: the download
    a user gets must not depend on which side of the threshold it fell."""
    result_id = _profile(client, _image(client, tmp_path))
    body = {"result_ids": [result_id]}

    kept = _spy_spools(monkeypatch, max_size=1 << 30)          # stays in RAM
    in_memory = client.post("/api/results/export", json=body).content
    assert kept[0]._rolled is False

    rolled = _spy_spools(monkeypatch, max_size=1)              # rolls to disk
    spooled = client.post("/api/results/export", json=body).content
    assert rolled[-1]._rolled is True

    # `generated_at` differs between the two calls, so compare the entry
    # names and every array — the parts a spill could plausibly corrupt.
    a = zipfile.ZipFile(io.BytesIO(in_memory))
    b = zipfile.ZipFile(io.BytesIO(spooled))
    assert a.namelist() == b.namelist()
    assert any(n.endswith(".npy") for n in a.namelist())
    for name in a.namelist():
        if name.endswith(".npy"):
            assert a.read(name) == b.read(name)
