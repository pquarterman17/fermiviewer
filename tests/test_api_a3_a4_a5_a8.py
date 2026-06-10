"""Integration tests for A3/A4/A5/A8 wire-ups.

A3 — POST /analyze/back-project (FBP)
A4 — POST /analyze/composition-profile (EDS SI element-fraction line)
A5 — POST /analyze/elnes (EELS fine-structure fingerprint)
A8 — GET  /diffraction/phases + POST /analyze/simulate

Follows the fixture-driven pattern of test_api_analysis.py.
"""

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


def _open_image(client: TestClient, tmp_path, data: np.ndarray) -> str:
    h, w = data.shape
    f = write_mini_dm4(
        tmp_path / "img.dm4", dims=[w, h], data=data.ravel().astype(np.float32),
        cal=[{"scale": 1.0, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def _open_cube(client: TestClient, tmp_path, ny: int, nx: int,
               energy: np.ndarray, spec: np.ndarray) -> str:
    """Create an SI cube where every pixel shares the same spectrum."""
    ne = energy.size
    flat = np.repeat(spec.astype(np.float32), ny * nx)
    f = write_mini_dm4(
        tmp_path / "cube.dm4", dims=[nx, ny, ne], data=flat, data_type=2,
        cal=[
            {"scale": 1.0, "origin": 0, "units": "nm"},
            {"scale": 1.0, "origin": 0, "units": "nm"},
            {"scale": float(energy[1] - energy[0]),
             "origin": float(-energy[0] / (energy[1] - energy[0])),
             "units": "eV"},
        ],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


# ── A3 Back Project ───────────────────────────────────────────────────

class TestBackProject:
    def test_ramp_filter_returns_square_image(self, client, tmp_path):
        """Sinogram (20 angles × 64 width) → 64×64 reconstruction."""
        n_ang, width = 20, 64
        rng = np.random.default_rng(0)
        sino = rng.random((n_ang, width)).astype(np.float32)
        img_id = _open_image(client, tmp_path, sino)

        r = client.post("/api/analyze/back-project",
                        json={"image_id": img_id, "filter": "ramp"})
        assert r.status_code == 200
        meta = r.json()
        assert meta["kind"] == "image"
        assert meta["shape"] == [width, width]   # [H, W]
        # Derived image is render-able
        assert client.get(f"/api/image/{meta['id']}/render").status_code == 200

    def test_hamming_filter(self, client, tmp_path):
        sino = np.ones((10, 32), dtype=np.float32)
        img_id = _open_image(client, tmp_path, sino)
        r = client.post("/api/analyze/back-project",
                        json={"image_id": img_id, "filter": "hamming",
                              "output_size": 64})
        assert r.status_code == 200
        assert r.json()["shape"] == [64, 64]

    def test_bad_filter_422(self, client, tmp_path):
        sino = np.ones((5, 16), dtype=np.float32)
        img_id = _open_image(client, tmp_path, sino)
        r = client.post("/api/analyze/back-project",
                        json={"image_id": img_id, "filter": "bogus"})
        assert r.status_code == 422

    def test_requires_image_kind(self, client, tmp_path):
        """A cube should be rejected."""
        e = np.linspace(400, 700, 64)
        spec = np.ones(64, dtype=np.float32)
        cube_id = _open_cube(client, tmp_path, 4, 4, e, spec)
        r = client.post("/api/analyze/back-project",
                        json={"image_id": cube_id})
        assert r.status_code == 400


# ── A4 Composition Profile ────────────────────────────────────────────

class TestCompositionProfile:
    def _make_at_pct_maps(self, client: TestClient, tmp_path,
                           n: int = 2) -> tuple[list[str], list[str]]:
        """Create n synthetic at% map images and register them."""
        rng = np.random.default_rng(42)
        map_ids = []
        elements = [f"El{i}" for i in range(n)]
        for _ in range(n):
            data = (rng.random((16, 24)) * 100).astype(np.float32)
            img_id = _open_image(client, tmp_path, data)
            map_ids.append(img_id)
        return map_ids, elements

    def test_profile_shape(self, client, tmp_path):
        map_ids, elements = self._make_at_pct_maps(client, tmp_path, 2)
        r = client.post("/api/analyze/composition-profile", json={
            "image_id": map_ids[0],
            "map_ids": map_ids,
            "elements": elements,
            "x1": 2.0, "y1": 8.0, "x2": 20.0, "y2": 8.0,
            "n_points": 100,
        })
        assert r.status_code == 200
        body = r.json()
        assert len(body["distance"]) == 100
        assert len(body["atomic_pct"]) == 2          # n_elements series
        assert len(body["atomic_pct"][0]) == 100
        assert body["unit"] in ("px", "nm")

    def test_mismatched_ids_elements_422(self, client, tmp_path):
        map_ids, _ = self._make_at_pct_maps(client, tmp_path, 2)
        r = client.post("/api/analyze/composition-profile", json={
            "image_id": map_ids[0],
            "map_ids": map_ids,
            "elements": ["A"],          # 1 element, 2 maps → 422
            "x1": 1.0, "y1": 1.0, "x2": 10.0, "y2": 1.0,
        })
        assert r.status_code == 422


# ── A5 ELNES ──────────────────────────────────────────────────────────

class TestElnes:
    def _make_eels_cube(self, client, tmp_path):
        e = np.linspace(500, 600, 256)
        spec = (5e4 * e ** -2.0
                + np.where(e > 532, 50.0 * np.exp(-(e - 532) / 5.0), 0.0))
        return _open_cube(client, tmp_path, 3, 3, e, spec)

    def test_returns_elnes_arrays(self, client, tmp_path):
        cube_id = self._make_eels_cube(client, tmp_path)
        r = client.post("/api/analyze/elnes", json={
            "image_id": cube_id,
            "edge_onset": 532.0,
            "fit_window": [505.0, 528.0],
            "elnes_window": [0.0, 25.0],
            "normalize": True,
        })
        assert r.status_code == 200
        body = r.json()
        assert "relative_energy" in body
        assert "intensity" in body
        assert len(body["relative_energy"]) == len(body["intensity"])
        # first relative-energy should be near 0
        assert abs(body["relative_energy"][0]) < 2.0

    def test_overlay_with_reference(self, client, tmp_path):
        cube_id = self._make_eels_cube(client, tmp_path)
        r = client.post("/api/analyze/elnes", json={
            "image_id": cube_id,
            "edge_onset": 532.0,
            "fit_window": [505.0, 528.0],
            "reference_id": cube_id,   # same spectrum as ref → perfect overlay
        })
        assert r.status_code == 200
        body = r.json()
        assert "reference_energy" in body
        assert "reference_intensity" in body

    def test_bad_fit_window_422(self, client, tmp_path):
        cube_id = self._make_eels_cube(client, tmp_path)
        # fit_window[1] >= edge_onset → ValueError in elnes → 422
        r = client.post("/api/analyze/elnes", json={
            "image_id": cube_id,
            "edge_onset": 532.0,
            "fit_window": [533.0, 540.0],  # fit_window[1]=540 >= onset=532
        })
        assert r.status_code == 422

    def test_requires_spectral_422(self, client, tmp_path):
        img = np.ones((8, 8), dtype=np.float32)
        img_id = _open_image(client, tmp_path, img)
        r = client.post("/api/analyze/elnes", json={
            "image_id": img_id,
            "edge_onset": 532.0,
            "fit_window": [505.0, 528.0],
        })
        assert r.status_code == 400


# ── A8 Simulate + phase list ──────────────────────────────────────────

class TestSimulate:
    def test_phase_list(self, client):
        r = client.get("/api/diffraction/phases")
        assert r.status_code == 200
        phases = r.json()["phases"]
        assert len(phases) >= 10
        names = [p["name"] for p in phases]
        assert any("Silicon" in n for n in names)
        # each entry has name, formula, category
        for p in phases:
            assert "name" in p and "formula" in p and "category" in p

    def test_simulate_silicon_001(self, client):
        """Silicon [001] zone axis must produce spots and a valid image."""
        r = client.post("/api/analyze/simulate", json={
            "phase_name": "Silicon",
            "zone_axis": [0, 0, 1],
            "acc_voltage": 200.0,
            "camera_length": 200.0,
            "pixel_size": 0.05,
            "image_size": [256, 256],
        })
        assert r.status_code == 200
        body = r.json()
        assert body["phase"] == "Silicon"
        assert body["zone_axis"] == [0, 0, 1]
        assert len(body["spots"]) > 0
        assert body["image"] is None   # no parent_image_id

    def test_simulate_registers_derived(self, client, tmp_path):
        """With parent_image_id the result registers as a derived image."""
        dp = np.zeros((64, 64), dtype=np.float32)
        dp_id = _open_image(client, tmp_path, dp)

        r = client.post("/api/analyze/simulate", json={
            "phase_name": "Silicon",
            "zone_axis": [0, 0, 1],
            "image_size": [64, 64],
            "parent_image_id": dp_id,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["image"] is not None
        assert body["image"]["kind"] == "image"
        sim_id = body["image"]["id"]
        assert client.get(f"/api/image/{sim_id}/render").status_code == 200

    def test_unknown_phase_422(self, client):
        r = client.post("/api/analyze/simulate", json={
            "phase_name": "NoSuchPhaseXYZ",
            "zone_axis": [0, 0, 1],
        })
        assert r.status_code == 422

    def test_spot_direct_beam_present(self, client):
        """Spot[0] is always the direct beam (NaN d-spacing, intensity=1)."""
        r = client.post("/api/analyze/simulate", json={
            "phase_name": "Gold",
            "zone_axis": [1, 1, 0],
        })
        assert r.status_code == 200
        spots = r.json()["spots"]
        direct = spots[0]
        assert direct["hkl"] == [0, 0, 0]
        assert direct["d_spacing"] is None
        assert direct["intensity"] == pytest.approx(1.0)
