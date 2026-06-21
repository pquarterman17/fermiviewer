"""Calibration DB: CRUD, manual apply, auto-apply on import."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.io.calibration_db import (
    extract_calibration_key,
    save_calibration,
)
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FV_CALIB_PATH", str(tmp_path / "calib.json"))
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open_uncal(client, tmp_path) -> str:
    flat = np.arange(24)
    f = write_mini_dm4(tmp_path / "u.dm4", dims=[6, 4], data=flat)
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def test_crud_and_manual_apply(client, tmp_path) -> None:
    img_id = _open_uncal(client, tmp_path)
    meta = client.get(f"/api/image/{img_id}/meta").json()
    assert meta["pixel_size"] is None  # starts uncalibrated

    r = client.post(
        "/api/calibration/apply",
        json={
            "image_id": img_id,
            "pixel_size": 0.31,
            "unit": "nm",
            "save_as_key": "TestScope|50000",
        },
    )
    assert r.status_code == 200
    assert r.json()["image"]["pixel_size"] == pytest.approx(0.31)
    # persisted offer-save
    entries = client.get("/api/calibration").json()["entries"]
    assert entries["TestScope|50000"]["pixel_size"] == pytest.approx(0.31)
    # measurement now calibrated end to end
    prof = client.post(
        "/api/measure/profile",
        json={"image_id": img_id, "a": [1, 1], "b": [1, 6]},
    ).json()
    assert prof["unit"] == "nm"
    # delete
    assert (
        client.delete("/api/calibration/TestScope|50000").status_code == 200
    )
    assert client.get("/api/calibration").json()["entries"] == {}
    assert client.delete("/api/calibration/zzz").status_code == 404


def test_clear_calibration(client, tmp_path) -> None:
    img_id = _open_uncal(client, tmp_path)
    applied = client.post(
        "/api/calibration/apply",
        json={"image_id": img_id, "pixel_size": 0.5, "unit": "nm"},
    )
    assert applied.json()["image"]["pixel_size"] == pytest.approx(0.5)

    cleared = client.post("/api/calibration/clear", json={"image_id": img_id})
    assert cleared.status_code == 200
    assert cleared.json()["image"]["pixel_size"] is None
    # the stored DataStruct is now uncalibrated end to end
    meta = client.get(f"/api/image/{img_id}/meta").json()
    assert meta["pixel_size"] is None
    prof = client.post(
        "/api/measure/profile",
        json={"image_id": img_id, "a": [1, 1], "b": [1, 6]},
    ).json()
    assert prof["unit"] == "px"
    # unknown id → 404
    assert (
        client.post("/api/calibration/clear", json={"image_id": "nope"}).status_code
        == 404
    )


def test_key_extraction_and_auto_apply_unit() -> None:
    meta = {
        "image_tags": {
            "Microscope Info": {"Microscope": "Titan"},
            "Indicated Magnification": 50000.0,
        }
    }
    key = extract_calibration_key(meta)
    assert key == "Titan|50000"
    assert extract_calibration_key({"x": 1}) is None

    # auto-apply path: store an entry then run the helper on a fake image
    from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
    from fermiviewer.routes.calibration import auto_apply_calibration

    save_calibration("Titan|50000", 0.42, "nm")
    ds = DataStruct(
        data=np.zeros((4, 6)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata=meta,
    )
    img_id = store.add_parsed(ds, "fake.dm4")
    assert auto_apply_calibration(img_id, ds) is True
    after = store.get(img_id)
    assert after.pixel_cal.scale == pytest.approx(0.42)
    assert after.metadata["calibration_source"] == "db:Titan|50000"
    # already-calibrated images are left alone
    assert auto_apply_calibration(img_id, after) is False
