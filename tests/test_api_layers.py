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


def _open_map(client, tmp_path, name: str, sig: float) -> str:
    """A layered image with interfaces at CENTERS but a given erf width."""
    y = np.arange(H, dtype=np.float64)
    prof = np.full(H, LEVELS[0])
    for c, (lo, hi) in zip(CENTERS, zip(LEVELS, LEVELS[1:], strict=False), strict=True):
        prof += (hi - lo) * 0.5 * (1 + erf((y - c) / (sig * np.sqrt(2))))
    img = np.tile(prof[:, None], (1, W))
    f = write_mini_dm4(
        tmp_path / f"{name}.dm4", dims=[W, H],
        data=img.ravel().astype(np.float32), data_type=2,
        cal=[{"scale": PX, "origin": 0, "units": "nm"},
             {"scale": PX, "origin": 0, "units": "nm"}],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def test_layers_multi_per_element_sigma(client, tmp_path) -> None:
    sharp = _open_map(client, tmp_path, "sharp", 2.0)
    diffuse = _open_map(client, tmp_path, "diffuse", 5.0)
    r = client.post("/api/analyze/layers/multi", json={
        "image_ids": [sharp, diffuse], "reference": 0,
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["maps"]) == 2
    assert len(body["reference_positions"]) == 3
    # the diffuse map has wider σ_erf at the shared interfaces than the sharp one
    sharp_sig = np.mean([i["sigma_erf"] for i in body["maps"][0]["interfaces"]])
    diffuse_sig = np.mean([i["sigma_erf"] for i in body["maps"][1]["interfaces"]])
    assert diffuse_sig > sharp_sig * 1.5


def test_layers_multi_shape_mismatch_422(client, tmp_path, image_id) -> None:
    other = _open_map(client, tmp_path, "other", 3.0)
    # `image_id` is 120×60; build a different-shaped one
    small = write_mini_dm4(
        tmp_path / "small.dm4", dims=[10, 10],
        data=np.ones(100, dtype=np.float32), data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"},
             {"scale": 1, "origin": 0, "units": "nm"}],
    )
    small_id = client.post("/api/session/open", json={"paths": [str(small)]}).json()[0]["id"]
    r = client.post("/api/analyze/layers/multi", json={"image_ids": [other, small_id]})
    assert r.status_code == 422


def test_layers_multi_empty_422(client) -> None:
    r = client.post("/api/analyze/layers/multi", json={"image_ids": []})
    assert r.status_code == 422


def test_layers_waviness_returns_sigma_w_and_trace(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={
        "image_id": image_id, "waviness": True,
    })
    assert r.status_code == 200
    body = r.json()
    # flat synthetic layers → ~zero waviness, but the fields are populated
    for it in body["interfaces"]:
        assert it["sigma_w"] is not None
        assert isinstance(it["trace"], list) and len(it["trace"]) == W
    for lyr in body["layers"]:
        assert lyr["thickness_std"] is not None


def test_layers_no_waviness_leaves_fields_null(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={"image_id": image_id})
    body = r.json()
    assert all(it["sigma_w"] is None and it["trace"] is None for it in body["interfaces"])


def test_layers_edit_recomputes_from_positions(client, image_id) -> None:
    r = client.post("/api/analyze/layers/edit", json={
        "image_id": image_id, "positions": [30.0, 90.0], "axis": "y",
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["interfaces"]) == 2
    assert len(body["layers"]) == 1
    # 30→90 px × 0.5 nm = 30 nm
    assert body["layers"][0]["thickness"] == pytest.approx(30.0, abs=0.5)


def test_layers_edit_drops_out_of_range(client, image_id) -> None:
    r = client.post("/api/analyze/layers/edit", json={
        "image_id": image_id, "positions": [30.0, 9999.0], "axis": "y",
    })
    assert r.status_code == 200
    assert len(r.json()["interfaces"]) == 1


def test_layers_edit_bad_axis_422(client, image_id) -> None:
    r = client.post("/api/analyze/layers/edit", json={
        "image_id": image_id, "positions": [30.0], "axis": "auto",
    })
    assert r.status_code == 422


def test_layers_bf_modality_runs(client, image_id) -> None:
    # the clean synthetic stack still resolves under BF scale-space detection
    r = client.post("/api/analyze/layers", json={
        "image_id": image_id, "modality": "bf",
    })
    assert r.status_code == 200
    assert len(r.json()["interfaces"]) == 3
