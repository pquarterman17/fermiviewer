"""EDS SI explorer endpoint tests — synthetic cube oracles.

Tests /eds/line-energy/{symbol} (GET) and /eds/element-map (POST)
against known values from the MATLAB reference implementation
(openSpectrumImageWorkshop.m / imaging.eds.lineEnergy + elementMap).
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.eds, pytest.mark.api]


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open_eds_cube(client: TestClient, tmp_path) -> str:
    """4×5 px × 1024 ch EDS SI cube: flat bg + Fe Kα peak at 6.404 keV."""
    ny, nx, ne = 4, 5, 1024
    energy_kev = np.arange(ne) * 0.01          # 0–10.23 keV
    # flat background 2 cts/ch + Fe Kα Gaussian
    spec = np.full(ne, 2.0, dtype=np.float32)
    spec += 50.0 * np.exp(-((energy_kev - 6.404) ** 2) / (2 * 0.03 ** 2)).astype(
        np.float32
    )
    flat = np.tile(spec, ny * nx)
    de = float(energy_kev[1] - energy_kev[0])   # 0.01 keV/ch
    origin = 0.0                                 # channel 0 → 0 keV
    f = write_mini_dm4(
        tmp_path / "eds_si.dm4",
        dims=[nx, ny, ne],
        data=flat,
        data_type=2,   # float32
        cal=[
            {"scale": 1.0, "origin": 0, "units": "nm"},
            {"scale": 1.0, "origin": 0, "units": "nm"},
            {"scale": de, "origin": origin, "units": "keV"},
        ],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


# ── /eds/line-energy ─────────────────────────────────────────────────

def test_line_energy_fe_k(client: TestClient) -> None:
    """Fe Kα = 6.404 keV — verbatim from the _K_LINES table."""
    r = client.get("/api/eds/line-energy/Fe")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "Fe"
    assert body["line"] == "K"
    assert body["energy_kev"] == pytest.approx(6.404, abs=1e-6)


def test_line_energy_si_k(client: TestClient) -> None:
    """Si Kα = 1.740 keV — second reference value from the table."""
    r = client.get("/api/eds/line-energy/Si")
    assert r.status_code == 200
    body = r.json()
    assert body["line"] == "K"
    assert body["energy_kev"] == pytest.approx(1.740, abs=1e-6)


def test_line_energy_au_falls_back(client: TestClient) -> None:
    """Au has no K in the table; auto selects L or M."""
    r = client.get("/api/eds/line-energy/Au")
    assert r.status_code == 200
    body = r.json()
    assert body["line"] in ("L", "M")
    assert np.isfinite(body["energy_kev"])


def test_line_energy_unknown(client: TestClient) -> None:
    """Unknown element symbol → 404."""
    r = client.get("/api/eds/line-energy/Xx")
    assert r.status_code == 404


def test_line_energy_beam_kv_query(client: TestClient) -> None:
    """beam_kv query param is accepted; returns a finite energy."""
    r = client.get("/api/eds/line-energy/Fe?beam_kv=8")
    assert r.status_code == 200
    assert np.isfinite(r.json()["energy_kev"])


# ── /eds/element-map ─────────────────────────────────────────────────

def test_element_map_no_bg(client: TestClient, tmp_path) -> None:
    """Window sum without background matches H×W shape and is non-negative."""
    cube_id = _open_eds_cube(client, tmp_path)
    r = client.post("/api/eds/element-map", json={
        "image_id": cube_id,
        "e_lo": 6.3,
        "e_hi": 6.5,
        "bg": "none",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["shape"] == [4, 5]
    assert body["e_lo"] == pytest.approx(6.3, abs=1e-9)
    assert body["bg"] == "none"
    assert body["map_meta"] is None   # save_derived defaults to False
    m = np.array(body["map"])
    assert m.shape == (4, 5)
    assert m.min() >= 0
    assert body["total_counts"] > 0


def test_element_map_linear_bg(client: TestClient, tmp_path) -> None:
    """Linear bg subtraction yields counts ≤ raw sum (flat bg is positive)."""
    cube_id = _open_eds_cube(client, tmp_path)
    r_none = client.post("/api/eds/element-map", json={
        "image_id": cube_id, "e_lo": 6.3, "e_hi": 6.5, "bg": "none",
    })
    r_lin = client.post("/api/eds/element-map", json={
        "image_id": cube_id, "e_lo": 6.3, "e_hi": 6.5, "bg": "linear",
    })
    assert r_none.status_code == 200
    assert r_lin.status_code == 200
    total_none = r_none.json()["total_counts"]
    total_lin = r_lin.json()["total_counts"]
    # background-subtracted ≤ raw (linear bg subtracts positive baseline)
    assert total_lin <= total_none + 1e-6


def test_element_map_bounds_clamped(client: TestClient, tmp_path) -> None:
    """Swapped lo/hi are accepted (sorted internally, matching MATLAB)."""
    cube_id = _open_eds_cube(client, tmp_path)
    r = client.post("/api/eds/element-map", json={
        "image_id": cube_id, "e_lo": 6.5, "e_hi": 6.3,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["e_lo"] == pytest.approx(6.3, abs=1e-9)
    assert body["e_hi"] == pytest.approx(6.5, abs=1e-9)


def test_element_map_save_derived(client: TestClient, tmp_path) -> None:
    """save_derived=True returns a map_meta with id and kind=='image'."""
    cube_id = _open_eds_cube(client, tmp_path)
    r = client.post("/api/eds/element-map", json={
        "image_id": cube_id,
        "e_lo": 6.3,
        "e_hi": 6.5,
        "bg": "linear",
        "save_derived": True,
    })
    assert r.status_code == 200
    body = r.json()
    meta = body["map_meta"]
    assert meta is not None
    assert "id" in meta
    assert meta["kind"] == "image"
    assert meta["shape"] == [4, 5]


def test_element_map_window_outside_axis_422(client: TestClient, tmp_path) -> None:
    """Window entirely outside the energy axis → 422."""
    cube_id = _open_eds_cube(client, tmp_path)
    r = client.post("/api/eds/element-map", json={
        "image_id": cube_id, "e_lo": 20.0, "e_hi": 25.0,
    })
    assert r.status_code == 422


def test_element_map_unknown_image_id(client: TestClient) -> None:
    """Unknown image id → 404."""
    r = client.post("/api/eds/element-map", json={
        "image_id": "no-such-id", "e_lo": 6.3, "e_hi": 6.5,
    })
    assert r.status_code == 404


def test_element_map_2d_image_rejected(client: TestClient, tmp_path) -> None:
    """Sending a 2D image id → 400 (not a cube)."""
    # create a plain 2D dm4
    flat = np.arange(20, dtype=np.float32)
    f = write_mini_dm4(
        tmp_path / "img2d.dm4", dims=[5, 4], data=flat, data_type=2,
        cal=[
            {"scale": 1.0, "origin": 0, "units": "nm"},
            {"scale": 1.0, "origin": 0, "units": "nm"},
        ],
    )
    img_id = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]
    r = client.post("/api/eds/element-map", json={
        "image_id": img_id, "e_lo": 1.0, "e_hi": 2.0,
    })
    assert r.status_code == 400


# ── /api/image/{id}/spectrum for SI pixel / ROI ───────────────────────

def test_spectrum_sum_no_region(client: TestClient, tmp_path) -> None:
    """GET without rect returns the global sum spectrum (1024 channels)."""
    cube_id = _open_eds_cube(client, tmp_path)
    r = client.get(f"/api/image/{cube_id}/spectrum")
    assert r.status_code == 200
    body = r.json()
    assert body["region"] is None
    assert len(body["counts"]) == 1024
    assert body["units"] == "keV"


def test_spectrum_single_pixel(client: TestClient, tmp_path) -> None:
    """GET with a 1×1 rect returns a 1024-length spectrum."""
    cube_id = _open_eds_cube(client, tmp_path)
    r = client.get(
        f"/api/image/{cube_id}/spectrum?row0=2&col0=3&row1=2&col1=3"
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["counts"]) == 1024
    assert body["region"] == [2, 3, 2, 3]


def test_spectrum_roi_sums_correctly(client: TestClient, tmp_path) -> None:
    """ROI summed spectrum: a 2×3 ROI sums 6 identical pixel spectra."""
    cube_id = _open_eds_cube(client, tmp_path)
    r_roi = client.get(
        f"/api/image/{cube_id}/spectrum?row0=1&col0=1&row1=2&col1=3"
    )
    r_sum = client.get(f"/api/image/{cube_id}/spectrum")
    assert r_roi.status_code == 200
    roi_counts = np.array(r_roi.json()["counts"])
    sum_counts = np.array(r_sum.json()["counts"])
    assert roi_counts.shape == (1024,)
    # all pixels are identical: roi(2×3=6) / total(4×5=20) ≈ 6/20
    ratio = roi_counts.sum() / sum_counts.sum()
    assert ratio == pytest.approx(6 / 20, rel=1e-6)
