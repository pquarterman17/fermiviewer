"""Advanced EELS deconvolution endpoint tests: /eels/subpixel-align +
/eels/richardson-lucy. Low-loss SI cube fixture (ZLP + plasmon)."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.eels]

NY, NX, NE = 3, 4, 256
SCALE, ORIGIN = 0.25, 40.0                 # e = (i - 40)*0.25 → -10..53.75 eV
ENERGY = (np.arange(NE) - ORIGIN) * SCALE
ZLP = 1000.0 * np.exp(-(ENERGY**2) / (2 * 0.5**2))
PLASMON = 150.0 * np.exp(-((ENERGY - 20.0) ** 2) / (2 * 3.0**2))
SPEC = ZLP + PLASMON


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
    arr = np.empty((NE, NY, NX))               # file order: E slowest
    for y in range(NY):
        for x in range(NX):
            s = SPEC.copy()
            if (y, x) == (0, 1):               # one pixel shifted +3 channels
                s = np.roll(s, 3)
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


# ── /eels/subpixel-align ─────────────────────────────────────────────

def test_subpixel_align_registers_derived_cube(client, cube_id) -> None:
    r = client.post("/api/eels/subpixel-align", json={"image_id": cube_id})
    assert r.status_code == 200
    body = r.json()
    assert body["aligned"]["kind"] == "spectrum_image"
    assert body["aligned"]["id"] != cube_id
    # the +3-channel pixel means a non-trivial max shift and some moved pixels
    assert body["max_shift"] > 0.0
    assert 0.0 < body["shifted_fraction"] <= 1.0


def test_subpixel_align_requires_cube(client, tmp_path) -> None:
    # a 1-D spectrum is not a cube
    f = write_mini_dm4(
        tmp_path / "spec.dm4", dims=[NE],
        data=SPEC.astype(np.float32), data_type=2,
        cal=[{"scale": SCALE, "origin": ORIGIN, "units": "eV"}],
    )
    sid = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]
    r = client.post("/api/eels/subpixel-align", json={"image_id": sid})
    assert r.status_code == 400


def test_subpixel_align_unknown_image(client) -> None:
    r = client.post("/api/eels/subpixel-align", json={"image_id": "nope"})
    assert r.status_code == 404


# ── /eels/richardson-lucy ────────────────────────────────────────────

def test_richardson_lucy_sharpens_summed_spectrum(client, cube_id) -> None:
    r = client.post("/api/eels/richardson-lucy", json={
        "image_id": cube_id, "zlp_window": [-5, 5], "iterations": 20,
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["deconvolved"]) == NE
    spec = np.array(body["spectrum"])
    deconv = np.array(body["deconvolved"])
    # deconvolution concentrates intensity → taller, non-negative
    assert deconv.max() >= spec.max()
    assert np.all(deconv >= -1e-9)


def test_richardson_lucy_empty_zlp_window_is_422(client, cube_id) -> None:
    r = client.post("/api/eels/richardson-lucy", json={
        "image_id": cube_id, "zlp_window": [500, 600],   # off the axis
    })
    assert r.status_code == 422


def test_richardson_lucy_rejects_plain_image(client, tmp_path) -> None:
    f = write_mini_dm4(
        tmp_path / "img.dm4", dims=[4, 4],
        data=np.ones(16, dtype=np.float32), data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"},
             {"scale": 1, "origin": 0, "units": "nm"}],
    )
    iid = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]
    r = client.post("/api/eels/richardson-lucy", json={"image_id": iid})
    assert r.status_code == 400
