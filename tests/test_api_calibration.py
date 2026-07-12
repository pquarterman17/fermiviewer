"""Calibration DB: CRUD, manual apply, auto-apply on import."""

from __future__ import annotations

import glob
import warnings

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io import calibration_db
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


def test_recalibrate_spectrum_image_and_reject_spectrum() -> None:
    from fastapi import HTTPException

    from fermiviewer.routes.calibration import recalibrate

    cube = DataStruct(
        data=np.zeros((2, 3, 4)),
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(), AxisCal(), AxisCal(2.0, 1.0, "eV")),
    )
    calibrated = recalibrate(cube, 0.25, "nm")
    assert calibrated.axes[0] == AxisCal(0.25, 0.0, "nm")
    assert calibrated.axes[1] == AxisCal(0.25, 0.0, "nm")
    assert calibrated.axes[2] == cube.axes[2]

    spectrum = DataStruct(
        data=np.arange(4), kind=DataKind.SPECTRUM, axes=(AxisCal(1, 0, "eV"),)
    )
    with pytest.raises(HTTPException, match="no spatial calibration"):
        recalibrate(spectrum, 1.0, "nm")


def test_auto_apply_noop_paths() -> None:
    from fermiviewer.routes.calibration import auto_apply_calibration

    spectrum = DataStruct(
        data=np.arange(4), kind=DataKind.SPECTRUM, axes=(AxisCal(1, 0, "eV"),)
    )
    assert auto_apply_calibration("unused", spectrum) is False

    no_key = DataStruct(
        data=np.zeros((2, 2)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata={},
    )
    assert auto_apply_calibration("unused", no_key) is False

    unknown_key = DataStruct(
        data=np.zeros((2, 2)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata={"Microscope": "Unknown", "Magnification": 123},
    )
    assert auto_apply_calibration("unused", unknown_key) is False


def test_save_derives_key_and_reports_missing_key(client) -> None:
    ds = DataStruct(
        data=np.zeros((2, 2)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata={"Microscope": "Titan", "Magnification": 50000},
    )
    img_id = store.add_parsed(ds, "derived-key.dm4")
    saved = client.post(
        "/api/calibration",
        json={"image_id": img_id, "pixel_size": 0.2, "unit": "nm"},
    )
    assert saved.status_code == 200
    assert saved.json() == {"key": "Titan|50000"}

    missing = client.post(
        "/api/calibration", json={"pixel_size": 0.2, "unit": "nm"}
    )
    assert missing.status_code == 422
    assert "none derivable" in missing.json()["detail"]


def test_calibration_error_paths_and_stored_apply(client, tmp_path) -> None:
    img_id = _open_uncal(client, tmp_path)
    save_calibration("Stored|1", 0.75, "um")
    applied = client.post(
        "/api/calibration/apply",
        json={"image_id": img_id, "key": "Stored|1"},
    )
    assert applied.status_code == 200
    assert applied.json()["image"]["pixel_size"] == pytest.approx(0.75)
    assert applied.json()["image"]["pixel_unit"] == "um"

    unknown = client.post(
        "/api/calibration/apply",
        json={"image_id": img_id, "key": "missing"},
    )
    assert unknown.status_code == 404
    no_method = client.post(
        "/api/calibration/apply", json={"image_id": img_id}
    )
    assert no_method.status_code == 422

    spectrum = DataStruct(
        data=np.arange(8), kind=DataKind.SPECTRUM, axes=(AxisCal(1, 0, "eV"),)
    )
    spectrum_id = store.add_parsed(spectrum, "spectrum.msa")
    assert (
        client.post(
            "/api/calibration/detect-bar", json={"image_id": spectrum_id}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/calibration/clear", json={"image_id": spectrum_id}
        ).status_code
        == 400
    )


# ── durability: atomic _save, corrupt-file recovery ──────────────────


def test_save_load_roundtrip_unchanged() -> None:
    """The atomic write (_save via temp-file + os.replace) still round-trips
    a normal calibration DB exactly like the direct-write version did."""
    save_calibration("Roundtrip|1", 0.31, "nm", "note")
    p = calibration_db.db_path()
    assert p.is_file()
    assert calibration_db.list_calibrations()["Roundtrip|1"]["pixel_size"] == (
        pytest.approx(0.31)
    )
    # no leftover temp file from the atomic write
    assert list(p.parent.glob(f"{p.name}.tmp-*")) == []


def test_corrupt_db_backed_up_and_warns() -> None:
    """A corrupt calibrations.json is preserved as a `.corrupt-<ts>` backup
    (not silently overwritten on the next save) and _load warns + returns
    {} instead of crashing."""
    p = calibration_db.db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not valid json", encoding="utf-8")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = calibration_db.list_calibrations()
    assert result == {}
    assert any("corrupt" in str(w.message) for w in caught)
    assert not p.is_file()  # original renamed away, not left in place
    backups = glob.glob(str(p) + ".corrupt-*")
    assert len(backups) == 1

    # subsequent saves work normally against a fresh DB
    save_calibration("Fresh|1", 1.0, "um")
    fresh = calibration_db.list_calibrations()
    assert set(fresh) == {"Fresh|1"}
    assert fresh["Fresh|1"]["pixel_size"] == pytest.approx(1.0)
    assert p.is_file()
