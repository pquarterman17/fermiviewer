"""EELS advanced endpoint tests: thickness, KK, Fourier-log, SVD,
ZLP alignment — fully fixture-driven (no external data).

The fixture is a low-loss SI cube: gaussian ZLP at 0 eV + plasmon at
20 eV, per-pixel amplitude ramp (rank-1 for SVD), and pixel (0,1)
shifted +3 channels (alignment ground truth). t/λ = ln(I_t/I_0) is
closed-form from the construction.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.eels]

NY, NX, NE = 3, 4, 256
SCALE, ORIGIN = 0.25, 40.0          # e_i = (i - 40) * 0.25 → -10..53.75 eV
ENERGY = (np.arange(NE) - ORIGIN) * SCALE
SPEC = 1000.0 * np.exp(-(ENERGY**2) / (2 * 0.5**2)) \
    + 150.0 * np.exp(-((ENERGY - 20.0) ** 2) / (2 * 3.0**2))
SHIFT_CH = 3                         # pixel (0,1) rolled by +3 channels


def _expected_t_over_lambda() -> float:
    zlp = SPEC[(ENERGY >= -5) & (ENERGY <= 5)].sum()
    return float(np.log(SPEC.sum() / zlp))


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def cube_id(client, tmp_path) -> str:
    arr = np.empty((NE, NY, NX))     # file order: E slowest, x fastest
    for y in range(NY):
        for x in range(NX):
            amp = 1.0 + 0.05 * (y * NX + x)
            s = SPEC * amp
            if (y, x) == (0, 1):
                s = np.roll(s, SHIFT_CH)
            arr[:, y, x] = s
    f = write_mini_dm4(
        tmp_path / "lowloss.dm4", dims=[NX, NY, NE],
        data=arr.ravel().astype(np.float32), data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": SCALE, "origin": ORIGIN, "units": "eV"},
        ],
    )
    r = client.post("/api/session/open", json={"paths": [str(f)]})
    assert r.status_code == 200
    return r.json()[0]["id"]


def test_thickness_map(client, cube_id) -> None:
    r = client.post("/api/eels/thickness", json={"image_id": cube_id})
    assert r.status_code == 200
    body = r.json()
    assert body["valid_fraction"] == 1.0
    assert body["mean_t_over_lambda"] == pytest.approx(
        _expected_t_over_lambda(), rel=1e-3)
    meta = body["map"]
    assert meta["kind"] == "image"
    assert meta["shape"] == [NY, NX]
    assert client.get(f"/api/image/{meta['id']}/render").status_code == 200
    # empty ZLP window → clean 422
    assert client.post("/api/eels/thickness", json={
        "image_id": cube_id, "zlp_window": [900, 901],
    }).status_code == 422


def test_kramers_kronig(client, cube_id) -> None:
    r = client.post("/api/eels/kk", json={
        "image_id": cube_id, "refractive_index": 2.0,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["t_over_lambda"] == pytest.approx(
        _expected_t_over_lambda(), rel=1e-3)
    assert body["thickness_nm"] > 0
    n = len(body["energy"])
    assert n == int((ENERGY > 0).sum())
    for key in ("eps1", "eps2", "elf", "optical_conductivity",
                "refractive_index"):
        vals = body[key]
        assert len(vals) == n
        assert np.isfinite(vals).all()


def test_fourier_log(client, cube_id) -> None:
    r = client.post("/api/eels/fourier-log", json={"image_id": cube_id})
    assert r.status_code == 200
    body = r.json()
    assert body["t_over_lambda"] == pytest.approx(
        _expected_t_over_lambda(), rel=1e-3)
    assert len(body["ssd"]) == NE
    assert min(body["ssd"]) >= 0.0


def test_svd(client, cube_id) -> None:
    r = client.post("/api/eels/svd", json={
        "image_id": cube_id, "n_components": 3,
        "denoise": True, "n_score_maps": 2,
    })
    assert r.status_code == 200
    body = r.json()
    # amplitude ramp + one rolled pixel → rank 2: two components
    # must capture essentially all variance
    assert body["explained"][0] > 80.0
    assert body["cumulative"][1] > 99.9
    assert len(body["score_maps"]) == 2
    assert len(body["eigenspectra"]) == 2
    assert len(body["eigenspectra"][0]) == NE
    for m in body["score_maps"]:
        assert m["shape"] == [NY, NX]
        assert client.get(f"/api/image/{m['id']}/render").status_code == 200
    den = body["denoised"]
    assert den["kind"] == "spectrum_image"
    # derived cube flows through the normal spectral API
    assert client.get(f"/api/image/{den['id']}/spectrum").status_code == 200


def test_align_zlp(client, cube_id) -> None:
    r = client.post("/api/eels/align-zlp", json={
        "image_id": cube_id, "window": [-8, 8],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["max_shift"] == SHIFT_CH
    assert body["shifted_fraction"] == pytest.approx(1 / (NY * NX))
    meta = body["aligned"]
    assert meta["kind"] == "spectrum_image"
    assert meta["meta"]["derived_from"] == cube_id
    # aligned cube: a fresh thickness call sees the same t/λ
    r2 = client.post("/api/eels/thickness", json={"image_id": meta["id"]})
    assert r2.json()["mean_t_over_lambda"] == pytest.approx(
        _expected_t_over_lambda(), rel=1e-3)
