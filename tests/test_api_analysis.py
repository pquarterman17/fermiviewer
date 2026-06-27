"""Analysis endpoint tests — fully fixture-driven (no external data)."""

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


def _open(client: TestClient, path) -> str:
    return client.post("/api/session/open", json={"paths": [str(path)]}).json()[0]["id"]


@pytest.fixture()
def eels_cube_id(client, tmp_path) -> str:
    """4×3 px × 512 ch SI: power-law bg + O-K-like edge at 532 eV."""
    ny, nx, ne = 3, 4, 512
    e = 400 + np.arange(ne) * 0.5862            # ≈400–700 eV
    spec = 5e6 * e**-2.5 + np.where(e > 532, 80.0, 0.0)
    # file order is d0 (x) fastest, E slowest → repeat each channel value
    # across all pixels (np.tile would scramble the spectral axis)
    flat = np.repeat(spec.astype(np.float32), ny * nx)
    f = write_mini_dm4(
        tmp_path / "si.dm4", dims=[nx, ny, ne], data=flat, data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 0.5862, "origin": -682.36, "units": "eV"},
        ],
    )
    return _open(client, f)


def test_eels_background_endpoint(client, eels_cube_id) -> None:
    r = client.post("/api/eels/background", json={
        "image_id": eels_cube_id, "fit_window": [420, 520],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["params"]["r"] == pytest.approx(2.5, rel=1e-3)
    assert len(body["signal"]) == 512
    # bad window → clean 422
    assert client.post("/api/eels/background", json={
        "image_id": eels_cube_id, "fit_window": [100, 101],
    }).status_code == 422


def test_eels_map_creates_derived_image(client, eels_cube_id) -> None:
    r = client.post("/api/eels/map", json={
        "image_id": eels_cube_id,
        "signal_window": [540, 600],
        "background_window": [420, 520],
    })
    assert r.status_code == 200
    meta = r.json()
    assert meta["kind"] == "image"
    assert meta["shape"] == [3, 4]
    # derived image is render-able through the normal image API
    png = client.get(f"/api/image/{meta['id']}/render")
    assert png.status_code == 200
    assert meta["meta"]["derived_from"] == eels_cube_id


def test_eels_quantify_endpoint(client, eels_cube_id) -> None:
    r = client.post("/api/eels/quantify", json={
        "image_id": eels_cube_id,
        "edges": [{
            "element": "O", "shell": "K", "z": 8, "onset_ev": 532,
            "signal_window": [540, 600], "bg_window": [420, 520],
        }],
        "e0_kv": 200, "beta_mrad": 10,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["elements"] == ["O"]
    assert body["atomic_percent"] == [pytest.approx(100.0)]
    assert body["sigma"][0] > 0
    # a single edge is 100 % by construction → zero compositional error;
    # the >0 / coverage behaviour is validated in test_uncertainty.py
    assert body["atomic_percent_error"] == [pytest.approx(0.0)]


@pytest.fixture()
def eds_cube_id(client, tmp_path) -> str:
    """5×4 px × 512 ch EDS cube (keV axis) with an Fe Kα peak."""
    ny, nx, ne = 4, 5, 512
    e = np.arange(ne) * 0.02                     # 0–10.22 keV
    peak = 60 * np.exp(-((e - 6.404) ** 2) / (2 * 0.05**2))
    spec = (2.0 + peak).astype(np.float32)
    flat = np.repeat(spec, ny * nx)              # E slowest in file order
    f = write_mini_dm4(
        tmp_path / "eds.dm4", dims=[nx, ny, ne], data=flat, data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 0.02, "origin": 0, "units": "keV"},
        ],
    )
    return _open(client, f)


def test_eds_quantify_endpoint(client, eds_cube_id) -> None:
    r = client.post("/api/eds/quantify", json={
        "image_id": eds_cube_id, "elements": ["Fe", "Xx"],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["elements"] == ["Fe"]            # unknown symbol skipped
    assert body["lines"] == ["K"]
    assert body["mean_atomic_pct"] == [pytest.approx(100.0)]
    assert body["maps"][0]["shape"] == [4, 5]
    # single element → zero compositional error (additive uncertainty fields)
    assert body["mean_atomic_pct_error"] == [pytest.approx(0.0)]
    assert body["mean_weight_pct_error"] == [pytest.approx(0.0)]

    zaf = client.post("/api/eds/quantify", json={
        "image_id": eds_cube_id, "elements": ["Fe"], "method": "zaf",
    })
    assert zaf.status_code == 200

    assert client.post("/api/eds/quantify", json={
        "image_id": eds_cube_id, "elements": ["Xx"],
    }).status_code == 422


@pytest.fixture()
def pattern_id(client, tmp_path) -> str:
    """128×128 image with 4 bright spots around the centre."""
    yy, xx = np.mgrid[1:129, 1:129]
    img = np.zeros((128, 128))
    for r, c in [(65, 95), (65, 35), (95, 65), (35, 65), (65, 65)]:
        img += 1000 * np.exp(-((yy - r) ** 2 + (xx - c) ** 2) / 4)
    flat = img.T.astype(np.float32).ravel()      # file order d0=x fastest
    f = write_mini_dm4(
        tmp_path / "dp.dm4", dims=[128, 128], data=flat, data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"}] * 2,
    )
    return _open(client, f)


def test_diffraction_detect_and_index(client, pattern_id) -> None:
    r = client.post("/api/diffraction/detect", json={
        "image_id": pattern_id, "min_radius": 10, "threshold": 0.1,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["n"] == 4
    found = {tuple(map(int, s)) for s in body["spots"]}
    assert found == {(65, 95), (65, 35), (95, 65), (35, 65)}

    idx = client.post("/api/diffraction/index", json={
        "image_id": pattern_id,
        "spots": body["spots"],
        "pixel_size_mm": 0.05,
        "camera_length_mm": 200,
        "acc_voltage_kv": 200,
    })
    assert idx.status_code == 200
    cands = idx.json()["candidates"]
    assert len(cands) == 5
    assert all(set(c) >= {"phase", "score", "n_matched"} for c in cands)


def test_analysis_errors(client, pattern_id) -> None:
    assert client.post("/api/eels/background", json={
        "image_id": "nope", "fit_window": [1, 2],
    }).status_code == 404
    # 2D image has no spectral axis / cube
    assert client.post("/api/eels/background", json={
        "image_id": pattern_id, "fit_window": [1, 2],
    }).status_code == 400
    assert client.post("/api/eels/map", json={
        "image_id": pattern_id, "signal_window": [1, 2],
    }).status_code == 400
