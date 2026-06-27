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
    # at%/wt% 1σ propagated from the peak-amplitude fit covariance — present,
    # finite, non-negative (≈0 here: noiseless synthetic fit; the >0 / coverage
    # behaviour is validated with real noise in test_uncertainty.py)
    for key in ("atomic_percent_error", "weight_percent_error"):
        assert len(quant[key]) == 2
        assert all(np.isfinite(s) and s >= 0 for s in quant[key])


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


# ── /eds/recalibrate ─────────────────────────────────────────────────

def _shifted_cube_id(client, tmp_path, gain_d: float, off_d: float) -> str:
    """SI cube whose Fe/Cu peaks sit at observed = gain_d·true + off_d
    (a simulated detector miscalibration on a correct keV axis)."""
    pix = (
        kramers_continuum(ENERGY, E0_KEV, amp=200.0)
        + _peak(4000.0, gain_d * FE + off_d)
        + _peak(6000.0, gain_d * CU + off_d)
    )
    arr = np.empty((NE, NY, NX))
    for y in range(NY):
        for x in range(NX):
            arr[:, y, x] = pix
    f = write_mini_dm4(
        tmp_path / "eds_shift.dm4", dims=[NX, NY, NE],
        data=arr.ravel().astype(np.float32), data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": SCALE, "origin": 0, "units": "keV"},
        ],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def test_recalibrate_well_calibrated_is_near_identity(client, cube_id) -> None:
    r = client.post("/api/eds/recalibrate", json={
        "image_id": cube_id, "elements": ["Fe", "Cu"],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["gain"] == pytest.approx(1.0, abs=1e-2)
    assert body["offset"] == pytest.approx(0.0, abs=2e-2)
    assert body["applied"] is True
    assert body["image"]["id"] == cube_id


def test_recalibrate_corrects_a_shift(client, tmp_path) -> None:
    gain_d, off_d = 0.99, 0.05
    cid = _shifted_cube_id(client, tmp_path, gain_d, off_d)
    r = client.post("/api/eds/recalibrate", json={
        "image_id": cid, "elements": ["Fe", "Cu"],
    })
    assert r.status_code == 200
    body = r.json()
    # recovered correction is the inverse of the injected distortion
    assert body["gain"] == pytest.approx(1.0 / gain_d, rel=2e-2)
    assert body["offset"] == pytest.approx(-off_d / gain_d, abs=1e-2)
    # the energy AxisCal scale was rewritten to gain·old_scale
    assert body["scale"] == pytest.approx(body["gain"] * SCALE, rel=1e-9)


def test_recalibrate_explicit_pairs(client, cube_id) -> None:
    r = client.post("/api/eds/recalibrate", json={
        "image_id": cube_id, "pairs": [[6.39, 6.404], [8.02, 8.048]],
    })
    assert r.status_code == 200
    assert r.json()["gain"] == pytest.approx((8.048 - 6.404) / (8.02 - 6.39), rel=1e-9)


def test_recalibrate_skips_unknown_elements(client, cube_id) -> None:
    r = client.post("/api/eds/recalibrate", json={
        "image_id": cube_id, "elements": ["Fe", "Cu", "Xx"],
    })
    assert r.status_code == 200
    assert r.json()["skipped"] == ["Xx"]


def test_recalibrate_no_anchors_is_422(client, cube_id) -> None:
    r = client.post("/api/eds/recalibrate", json={"image_id": cube_id})
    assert r.status_code == 422


def test_recalibrate_preview_does_not_apply(client, cube_id) -> None:
    r = client.post("/api/eds/recalibrate", json={
        "image_id": cube_id, "pairs": [[6.39, 6.404], [8.02, 8.048]], "apply": False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is False
    assert "image" not in body
