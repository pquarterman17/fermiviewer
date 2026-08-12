"""API tests for the model-based EELS fit endpoints (PLAN_SPECTRAL_QUANT #2)."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.eels_model import edge_shape_fn
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.eels]


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open(client: TestClient, path) -> str:
    return client.post(
        "/api/session/open", json={"paths": [str(path)]}
    ).json()[0]["id"]


# O-K + Mn-L model spectrum with areal-density ratio 2:1 → at% 66.7/33.3
_EDGES = [
    {"element": "O", "shell": "K", "z": 8, "onset_ev": 532.0},
    {"element": "Mn", "shell": "L", "z": 25, "onset_ev": 640.0},
]


@pytest.fixture()
def fit_cube_id(client, tmp_path) -> str:
    ny, nx, ne = 3, 4, 512
    e = 400.0 + np.arange(ne) * 0.5862                 # ≈400–700 eV
    s_o = edge_shape_fn(8, "K", 200.0, 10.0, 532.0)(e)
    s_mn = edge_shape_fn(25, "L", 200.0, 10.0, 640.0)(e)
    unit = 50.0 / max(s_o.max(), 1e-30)
    spec = 5e8 * e**-2.5 + (2.0 * unit) * s_o + (1.0 * unit) * s_mn
    flat = np.repeat(spec.astype(np.float32), ny * nx)
    f = write_mini_dm4(
        tmp_path / "fit_si.dm4", dims=[nx, ny, ne], data=flat, data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 0.5862, "origin": -682.36, "units": "eV"},
        ],
    )
    return _open(client, f)


def test_eels_fit_endpoint(client, fit_cube_id) -> None:
    r = client.post("/api/eels/fit", json={
        "image_id": fit_cube_id, "edges": _EDGES,
        "e0_kv": 200, "beta_mrad": 10,
    })
    assert r.status_code == 200
    body = r.json()
    assert [e["element"] for e in body["edges"]] == ["O", "Mn"]
    # onset_ev is echoed back per edge (#7 / audit R8 fit-report export)
    assert body["edges"][0]["onset_ev"] == 532.0
    assert body["edges"][1]["onset_ev"] == 640.0
    assert body["edges"][0]["atomic_percent"] == pytest.approx(66.7, abs=3.0)
    assert body["edges"][1]["atomic_percent"] == pytest.approx(33.3, abs=3.0)
    assert body["edges"][0]["amplitude_error"] >= 0
    # at% 1σ from the fit covariance — a genuine 2-element fit has real error
    assert body["edges"][0]["atomic_percent_error"] > 0
    assert body["edges"][1]["atomic_percent_error"] > 0
    # curves are returned for the overlay, full-length
    assert len(body["energy"]) == 512
    assert len(body["model"]) == 512
    assert len(body["background"]) == 512
    assert len(body["edges"][0]["curve"]) == 512
    assert body["success"] is True
    # fit-quality readout (#2 / audit R4): R² is never above 1 (up to fp
    # slop) and this is a noiseless synthetic spectrum generated from the
    # model's own edge shapes, so the fit should explain nearly all of it
    assert "r_squared" in body
    assert body["r_squared"] <= 1.0 + 1e-9
    assert body["r_squared"] == pytest.approx(1.0, abs=0.02)
    # fit_range (#7 / audit R8): resolved default window actually optimised
    # against — non-degenerate, upper bound is the axis end (no bg_window
    # was supplied on these edges, so the lower bound resolves to 0.0 —
    # see fit_edges' default: min(el.bg_window[0]), which is (0.0, 0.0)
    # unless a request sets it).
    assert len(body["fit_range"]) == 2
    assert body["fit_range"][0] < body["fit_range"][1]
    assert body["fit_range"][1] == pytest.approx(body["energy"][-1])


@pytest.fixture()
def noise_cube_id(client, tmp_path) -> str:
    """Same shape/axis as fit_cube_id but pure noise — no edge or
    background structure at all, so a model fit should explain little of
    its variance. Used to show r_squared is DISTINCTLY lower than the
    clean fit's, not just to demonstrate the value moves at all."""
    ny, nx, ne = 3, 4, 512
    rng = np.random.default_rng(42)
    spec = rng.uniform(1.0, 100.0, ne)
    flat = np.repeat(spec.astype(np.float32), ny * nx)
    f = write_mini_dm4(
        tmp_path / "noise_si.dm4", dims=[nx, ny, ne], data=flat, data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 0.5862, "origin": -682.36, "units": "eV"},
        ],
    )
    return _open(client, f)


def test_eels_fit_r_squared_lower_for_noise(
    client, fit_cube_id, noise_cube_id
) -> None:
    clean = client.post("/api/eels/fit", json={
        "image_id": fit_cube_id, "edges": _EDGES, "e0_kv": 200, "beta_mrad": 10,
    }).json()
    noisy = client.post("/api/eels/fit", json={
        "image_id": noise_cube_id, "edges": _EDGES, "e0_kv": 200, "beta_mrad": 10,
    }).json()
    assert noisy["r_squared"] <= 1.0 + 1e-9
    assert noisy["r_squared"] < 0.5
    assert noisy["r_squared"] < clean["r_squared"] - 0.3


def test_eels_fit_map_registers_maps(client, fit_cube_id) -> None:
    r = client.post("/api/eels/fit-map", json={
        "image_id": fit_cube_id, "edges": _EDGES,
        "e0_kv": 200, "beta_mrad": 10,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["elements"] == ["O", "Mn"]
    assert body["mean_atomic_percent"][0] == pytest.approx(66.7, abs=3.0)
    assert body["mean_atomic_percent"][1] == pytest.approx(33.3, abs=3.0)
    assert body["background_exponent"] == pytest.approx(2.5, abs=0.3)
    # each at% map is a render-able derived image
    assert len(body["maps"]) == 2
    for m in body["maps"]:
        assert m["kind"] == "image"
        assert m["shape"] == [3, 4]
        assert m["meta"]["derived_from"] == fit_cube_id
        assert client.get(f"/api/image/{m['id']}/render").status_code == 200


def test_eels_fit_requires_spectral(client, tmp_path) -> None:
    # a plain 2-D image has no spectral axis → 400
    flat = np.arange(16 * 12, dtype=np.float32)
    f = write_mini_dm4(tmp_path / "img.dm4", dims=[16, 12], data=flat)
    img_id = _open(client, f)
    assert client.post("/api/eels/fit", json={
        "image_id": img_id, "edges": _EDGES,
    }).status_code == 400
    # fit-map needs a cube specifically
    assert client.post("/api/eels/fit-map", json={
        "image_id": img_id, "edges": _EDGES,
    }).status_code == 400


def test_eels_fit_unknown_image(client) -> None:
    assert client.post("/api/eels/fit", json={
        "image_id": "nope", "edges": _EDGES,
    }).status_code == 404
