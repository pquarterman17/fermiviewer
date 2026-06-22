"""Cross-section layer endpoint tests: POST /api/analyze/layers."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.special import erf

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.imaging]

H, W = 120, 60
PX = 0.5                                   # nm/pixel
CENTERS = (30.0, 60.0, 90.0)
LEVELS = (0.2, 0.8, 0.4, 0.9)


def _layered_image() -> np.ndarray:
    y = np.arange(H, dtype=np.float64)
    prof = np.full(H, LEVELS[0])
    for c, (lo, hi) in zip(CENTERS, zip(LEVELS, LEVELS[1:], strict=False), strict=True):
        prof += (hi - lo) * 0.5 * (1 + erf((y - c) / (3 * np.sqrt(2))))
    return np.tile(prof[:, None], (1, W))   # (H, W), horizontal layers


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def image_id(client, tmp_path) -> str:
    img = _layered_image()
    f = write_mini_dm4(
        tmp_path / "stack.dm4", dims=[W, H],
        data=img.ravel().astype(np.float32), data_type=2,
        cal=[
            {"scale": PX, "origin": 0, "units": "nm"},
            {"scale": PX, "origin": 0, "units": "nm"},
        ],
    )
    r = client.post("/api/session/open", json={"paths": [str(f)]})
    assert r.status_code == 200
    return r.json()[0]["id"]


def test_layers_recovers_thickness_and_calibration(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={"image_id": image_id})
    assert r.status_code == 200
    body = r.json()
    assert body["axis"] == "y" and body["layers_horizontal"] is True
    assert body["unit"] == "nm" and body["pixel_size"] == pytest.approx(0.5)
    assert len(body["interfaces"]) == 3
    assert len(body["layers"]) == 2
    for lyr in body["layers"]:
        assert lyr["thickness"] == pytest.approx(15.0, abs=0.5)   # 30 px × 0.5 nm
    for it in body["interfaces"]:
        assert it["sigma_erf"] == pytest.approx(1.5, abs=0.3)     # 3 px × 0.5 nm
    assert abs(body["tilt_deg"]) < 1.5


def test_layers_n_layers_hint(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={
        "image_id": image_id, "sensitivity": 0.05, "n_layers": 3,
    })
    assert r.status_code == 200
    assert len(r.json()["interfaces"]) == 2     # keep 2 strongest


def test_layers_axis_override_finds_none(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={"image_id": image_id, "axis": "x"})
    assert r.status_code == 200
    assert r.json()["axis"] == "x"
    assert r.json()["interfaces"] == []


def test_layers_roi_restricts_depth(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={
        "image_id": image_id, "roi": [1, 1, 70, W],
    })
    assert r.status_code == 200
    assert len(r.json()["interfaces"]) == 2     # rows 1..70 → interfaces at 30, 60


def test_layers_rejects_cube(client, tmp_path) -> None:
    f = write_mini_dm4(
        tmp_path / "cube.dm4", dims=[4, 4, 8],
        data=np.ones(128, dtype=np.float32), data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"},
             {"scale": 1, "origin": 0, "units": "nm"},
             {"scale": 1, "origin": 0, "units": "eV"}],
    )
    cid = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]
    r = client.post("/api/analyze/layers", json={"image_id": cid})
    assert r.status_code == 400


def test_layers_unknown_image(client) -> None:
    r = client.post("/api/analyze/layers", json={"image_id": "nope"})
    assert r.status_code == 404
