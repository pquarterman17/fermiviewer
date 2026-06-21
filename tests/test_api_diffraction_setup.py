"""Diffraction setup routes (Diffraction #1/#2 wiring): /diffraction/calibrate,
CIF phase import/delete, custom phases reaching simulate + the phase list."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.phase_registry import registry
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.diffraction

_SI_CIF = """data_Si
_chemical_name_mineral 'My Silicon'
_chemical_formula_sum 'Si'
_cell_length_a 5.4309
_cell_length_b 5.4309
_cell_length_c 5.4309
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'F d -3 m'
loop_
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si 0.0 0.0 0.0
Si 0.25 0.25 0.25
"""


@pytest.fixture(autouse=True)
def _clean():
    store.clear()
    # drop any custom phases a prior test added (registry is process-wide)
    for p in list(registry.custom):
        registry.remove(p.name)
    yield
    store.clear()
    for p in list(registry.custom):
        registry.remove(p.name)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _ring_image(n=129, radius=40.0) -> np.ndarray:
    yy, xx = np.ogrid[:n, :n]
    c = n // 2
    r = np.hypot(yy - c, xx - c)
    return np.exp(-((r - radius) ** 2) / (2 * 3.0**2)) * 1000.0


def _open(client, tmp_path, data) -> str:
    h, w = data.shape
    f = write_mini_dm4(
        tmp_path / "dp.dm4", dims=[w, h], data=data.ravel().astype(np.float64),
        cal=[{"scale": 1.0, "origin": 0, "units": "1/nm"}] * 2,
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def test_calibrate_fits_a_synthetic_ring(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _ring_image(radius=40.0))
    r = client.post(
        "/api/diffraction/calibrate",
        json={"image_id": img_id, "d_known_ang": 2.0, "r_min": 10, "r_max": 60},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ellipse"]["mean_radius"] == pytest.approx(40.0, abs=1.5)
    assert body["ellipse"]["eccentricity"] < 0.1
    assert body["rms_residual_px"] < 2.0
    # camera constant C = R·d = 40·2.0 ≈ 80
    assert body["camera_constant_px_ang"] == pytest.approx(80.0, abs=4.0)


def test_calibrate_derives_d_from_standard_phase(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _ring_image(radius=35.0))
    r = client.post(
        "/api/diffraction/calibrate",
        json={
            "image_id": img_id,
            "standard_phase": "Gold",
            "hkl": [1, 1, 1],
            "r_min": 10,
            "r_max": 55,
        },
    )
    assert r.status_code == 200, r.text
    # Au(111): d = a/sqrt(3) = 4.0782/1.732 ≈ 2.355 Å
    assert r.json()["d_known_ang"] == pytest.approx(2.355, abs=0.01)


def test_cif_import_lists_and_simulates_then_deletes(client) -> None:
    # import a custom phase
    r = client.post("/api/diffraction/phases/import", json={"cif_text": _SI_CIF})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "My Silicon"
    assert r.json()["custom"] is True

    # it appears in the phase list, flagged custom
    phases = client.get("/api/diffraction/phases").json()["phases"]
    mine = next(p for p in phases if p["name"] == "My Silicon")
    assert mine["custom"] is True
    assert any(not p["custom"] for p in phases)  # built-ins still present

    # it simulates (reaches diff.simulate via the registry)
    sim = client.post(
        "/api/analyze/simulate",
        json={"phase_name": "My Silicon", "zone_axis": [0, 0, 1], "image_size": [128, 128]},
    )
    assert sim.status_code == 200, sim.text
    assert sim.json()["phase"] == "My Silicon"
    assert len(sim.json()["spots"]) >= 1

    # delete it
    d = client.delete("/api/diffraction/phases/My Silicon")
    assert d.status_code == 200
    after = client.get("/api/diffraction/phases").json()["phases"]
    assert all(p["name"] != "My Silicon" for p in after)


def test_cannot_delete_a_builtin_phase(client) -> None:
    assert client.delete("/api/diffraction/phases/Gold").status_code == 422


def test_simulate_scattering_model_selector(client) -> None:
    # both models run; "z" is the golden-pinned proxy, "fe" the default
    for model in ("fe", "z"):
        r = client.post(
            "/api/analyze/simulate",
            json={"phase_name": "Silicon", "image_size": [128, 128],
                  "scattering_model": model},
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["spots"]) >= 1


def test_bad_cif_is_422(client) -> None:
    r = client.post("/api/diffraction/phases/import", json={"cif_text": "not a cif"})
    assert r.status_code == 422
