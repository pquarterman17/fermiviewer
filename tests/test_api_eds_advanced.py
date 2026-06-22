"""Model-based EDS endpoint tests: /eds/continuum + /eds/peakfit.

Fixture is a small EDS SI cube on a keV axis: every pixel carries a
Kramers continuum + Fe-Kα and Cu-Kα Gaussian peaks, so the summed
spectrum is a clean (N·pixel) version with known relative areas.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.eds import line_energy
from fermiviewer.calc.eds_calib import fano_sigma_kev
from fermiviewer.calc.eds_continuum import kramers_continuum
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.eds]

NY, NX, NE = 2, 3, 1000
SCALE = 0.02                       # 20 eV/channel → 0..20 keV
ENERGY = np.arange(NE) * SCALE
E0_KEV = 18.0
FE = line_energy("Fe", beam_kv=200.0)[0]
CU = line_energy("Cu", beam_kv=200.0)[0]
SQRT_2PI = np.sqrt(2.0 * np.pi)


def _peak(area: float, center: float) -> np.ndarray:
    sigma = fano_sigma_kev(center)
    amp = area / (sigma * SQRT_2PI)
    return amp * np.exp(-0.5 * ((ENERGY - center) / sigma) ** 2)


# per-pixel spectrum: continuum + Fe (area 4000) + Cu (area 6000)
PIXEL = kramers_continuum(ENERGY, E0_KEV, amp=300.0) + _peak(4000.0, FE) + _peak(6000.0, CU)


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
    arr = np.empty((NE, NY, NX))
    for y in range(NY):
        for x in range(NX):
            arr[:, y, x] = PIXEL
    f = write_mini_dm4(
        tmp_path / "eds.dm4", dims=[NX, NY, NE],
        data=arr.ravel().astype(np.float32), data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": SCALE, "origin": 0, "units": "keV"},
        ],
    )
    r = client.post("/api/session/open", json={"paths": [str(f)]})
    assert r.status_code == 200
    return r.json()[0]["id"]


# ── /eds/continuum ───────────────────────────────────────────────────

def test_continuum_recovers_scaled_amplitude(client, cube_id) -> None:
    r = client.post("/api/eds/continuum", json={
        "image_id": cube_id, "e0_kev": E0_KEV,
        "exclude_lines": ["Fe", "Cu"], "fit_absorption": False, "weights": None,
    })
    assert r.status_code == 200
    body = r.json()
    # summed over NY*NX pixels → amp scales by the pixel count
    assert body["amp"] == pytest.approx(300.0 * NY * NX, rel=0.05)
    assert len(body["continuum"]) == NE


def test_continuum_rejects_non_spectral(client, tmp_path) -> None:
    f = write_mini_dm4(
        tmp_path / "img.dm4", dims=[4, 4],
        data=np.ones(16, dtype=np.float32), data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"},
             {"scale": 1, "origin": 0, "units": "nm"}],
    )
    img_id = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]
    r = client.post("/api/eds/continuum", json={"image_id": img_id, "e0_kev": E0_KEV})
    assert r.status_code == 400


def test_continuum_unknown_image(client) -> None:
    r = client.post("/api/eds/continuum", json={"image_id": "nope", "e0_kev": E0_KEV})
    assert r.status_code == 404


# ── /eds/peakfit ─────────────────────────────────────────────────────

def test_peakfit_recovers_area_ratio(client, cube_id) -> None:
    r = client.post("/api/eds/peakfit", json={
        "image_id": cube_id, "elements": ["Fe", "Cu"],
        "background": "bremsstrahlung", "e0_kev": E0_KEV, "weights": None,
    })
    assert r.status_code == 200
    body = r.json()
    areas = {e["symbol"]: e["net_area"] for e in body["elements"]}
    # Cu:Fe area ratio is 6000:4000 = 1.5 regardless of the pixel-count scale
    assert areas["Cu"] / areas["Fe"] == pytest.approx(1.5, rel=0.05)
    assert all(e["curve"] is not None for e in body["elements"])


def test_peakfit_quantify_returns_composition(client, cube_id) -> None:
    r = client.post("/api/eds/peakfit", json={
        "image_id": cube_id, "elements": ["Fe", "Cu"],
        "background": "bremsstrahlung", "e0_kev": E0_KEV,
        "quantify": True, "k_factors": [1.0, 1.0], "weights": None,
    })
    assert r.status_code == 200
    quant = r.json()["quant"]
    assert quant["elements"] == ["Fe", "Cu"]
    # weight% ∝ k·I → 4000:6000 = 40:60 with equal k-factors
    np.testing.assert_allclose(quant["weight_percent"], [40.0, 60.0], rtol=0.05)


def test_peakfit_bremsstrahlung_without_e0_is_422(client, cube_id) -> None:
    r = client.post("/api/eds/peakfit", json={
        "image_id": cube_id, "elements": ["Fe"], "background": "bremsstrahlung",
    })
    assert r.status_code == 422


def test_peakfit_unknown_background_is_422(client, cube_id) -> None:
    r = client.post("/api/eds/peakfit", json={
        "image_id": cube_id, "elements": ["Fe"], "background": "spline",
    })
    assert r.status_code == 422
