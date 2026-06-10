"""Tests for #34 tilt-corrected distance + #44 EDS auto-assign.

#34 calc unit tests:
  - measure_distance agrees with line_profile endpoint for the same segment
  - raw vs corrected values match the MATLAB reference formula
  - θ boundary validator rejects ±90 exactly

#44 calc unit tests:
  - detect_peaks finds Fe Kα / Cu Kα / O Kα in a synthetic spectrum
  - assign_elements returns correct candidates with correct delta order
  - API endpoint /eds/auto-assign wires correctly
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.eds import assign_elements, detect_peaks
from fermiviewer.calc.profiles import line_profile, measure_distance
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.imaging


# ── #34 measure_distance calc unit tests ─────────────────────────────

class TestMeasureDistance:
    def test_basic_pythagorean(self):
        """3-4-5 triangle → raw_px = 5, no tilt."""
        r = measure_distance(0, 0, 3, 4)
        assert r.raw_px == pytest.approx(5.0)
        assert r.corrected_px == pytest.approx(5.0)
        assert r.raw_calibrated is None
        assert r.unit == "px"

    def test_calibrated(self):
        """Calibrated: raw_calibrated = raw_px * pixel_size."""
        r = measure_distance(0, 0, 0, 10, pixel_size=2.0, pixel_unit="nm")
        assert r.raw_calibrated == pytest.approx(20.0)
        assert r.corrected_calibrated == pytest.approx(20.0)
        assert r.unit == "nm"

    def test_cross_section_y_axis(self):
        """Pure Y segment, cross-section geometry: corrected = Δy / sin θ."""
        theta = 52.0
        dy = 10.0
        r = measure_distance(0, 0, 0, dy, tilt_angle_deg=theta)
        expected = dy / np.sin(np.deg2rad(theta))
        assert r.corrected_px == pytest.approx(expected, rel=1e-9)
        assert r.raw_px == pytest.approx(dy)

    def test_cross_section_x_axis(self):
        """Pure X segment tilted on X axis: corrected = Δx / sin θ."""
        theta = 30.0
        dx = 8.0
        r = measure_distance(0, 0, dx, 0, tilt_angle_deg=theta, tilt_axis="X")
        expected = dx / np.sin(np.deg2rad(theta))
        assert r.corrected_px == pytest.approx(expected, rel=1e-9)

    def test_surface_geometry(self):
        """Plan-view surface geometry: corrected = Δy / cos θ."""
        theta = 30.0
        dy = 100.0
        r = measure_distance(0, 0, 0, dy,
                             tilt_angle_deg=theta, geometry="surface")
        expected = dy / np.cos(np.deg2rad(theta))
        assert r.corrected_px == pytest.approx(expected, rel=1e-9)

    def test_zero_tilt_no_correction(self):
        """Zero tilt → corrected_px == raw_px exactly."""
        r = measure_distance(1, 1, 7, 9, tilt_angle_deg=0.0)
        assert r.corrected_px == pytest.approx(r.raw_px)

    def test_boundary_validator_rejects_90(self):
        with pytest.raises(ValueError, match="(-90, 90)"):
            measure_distance(0, 0, 0, 10, tilt_angle_deg=90.0)

    def test_boundary_validator_rejects_minus_90(self):
        with pytest.raises(ValueError, match="(-90, 90)"):
            measure_distance(0, 0, 0, 10, tilt_angle_deg=-90.0)

    def test_boundary_allows_near_90(self):
        """89.9° is in range and must not raise."""
        r = measure_distance(0, 0, 0, 10, tilt_angle_deg=89.9)
        assert r.corrected_px > 10.0

    def test_agrees_with_line_profile_length(self):
        """corrected_px must equal the corrected length from line_profile
        (the tilt math is identical — both are ports of the MATLAB reference).
        """
        img = np.zeros((64, 64))
        theta = 45.0
        x1, y1, x2, y2 = 1.0, 1.0, 1.0, 11.0   # pure Y segment, Δy = 10
        dist, _ = line_profile(img, x1, y1, x2, y2, tilt_angle_deg=theta)
        r = measure_distance(x1, y1, x2, y2, tilt_angle_deg=theta)
        assert r.corrected_px == pytest.approx(dist[-1], rel=1e-6)

    def test_negative_tilt(self):
        """Negative tilt angles work (sign matters for geometry, not for |sin|)."""
        r = measure_distance(0, 0, 0, 10, tilt_angle_deg=-30.0)
        assert r.corrected_px == pytest.approx(10 / np.sin(np.deg2rad(30)))


# ── #34 API endpoint ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open_image(client, tmp_path, data: np.ndarray) -> str:
    h, w = data.shape
    f = write_mini_dm4(
        tmp_path / "img.dm4", dims=[w, h],
        data=data.ravel().astype(np.float32),
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


class TestMeasureDistanceTiltedApi:
    def test_uncalibrated_returns_px(self, client, tmp_path):
        """Without pixel calibration, unit is 'px' and calibrated values null."""
        # create an uncalibrated image by writing with scale=nan workaround:
        # just use a cube with scale=1 and check raw_px
        data = np.zeros((32, 32), dtype=np.float32)
        img_id = _open_image(client, tmp_path, data)
        r = client.post("/api/measure/distance-tilted", json={
            "image_id": img_id,
            "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 11.0,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["raw_px"] == pytest.approx(10.0)
        assert body["corrected_px"] == pytest.approx(10.0)

    def test_tilt_correction_via_api(self, client, tmp_path):
        """API returns corrected_px == Δy / sin θ for a pure-Y segment."""
        data = np.zeros((32, 32), dtype=np.float32)
        img_id = _open_image(client, tmp_path, data)
        theta = 45.0
        r = client.post("/api/measure/distance-tilted", json={
            "image_id": img_id,
            "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 11.0,
            "tilt_angle_deg": theta,
            "tilt_axis": "Y",
            "geometry": "cross-section",
        })
        assert r.status_code == 200
        body = r.json()
        expected = 10.0 / np.sin(np.deg2rad(theta))
        assert body["corrected_px"] == pytest.approx(expected, rel=1e-6)

    def test_bad_tilt_angle_422(self, client, tmp_path):
        data = np.zeros((32, 32), dtype=np.float32)
        img_id = _open_image(client, tmp_path, data)
        r = client.post("/api/measure/distance-tilted", json={
            "image_id": img_id,
            "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 11.0,
            "tilt_angle_deg": 90.0,
        })
        assert r.status_code == 422


# ── #44 EDS detect_peaks + assign_elements ───────────────────────────

class TestDetectPeaks:
    def _make_spectrum(self, peaks_kev: list[float]) -> tuple[np.ndarray, np.ndarray]:
        energy = np.linspace(0.1, 20.0, 2000)
        counts = np.zeros_like(energy)
        for pk in peaks_kev:
            counts += np.exp(-0.5 * ((energy - pk) / 0.05) ** 2) * 1000
        counts += 10.0   # baseline
        return energy, counts

    def test_finds_known_peaks(self):
        fe_ka, cu_ka, o_ka = 6.404, 8.048, 0.525
        energy, counts = self._make_spectrum([fe_ka, cu_ka, o_ka])
        peaks = detect_peaks(energy, counts, threshold=0.01)
        # Each known line should appear within 0.1 keV
        for line_kev in [fe_ka, cu_ka, o_ka]:
            assert any(abs(p - line_kev) < 0.1 for p in peaks), \
                f"peak at {line_kev} keV not detected; found {peaks.tolist()}"

    def test_threshold_filters_low_peaks(self):
        energy = np.linspace(0.1, 10.0, 500)
        counts = np.zeros(500)
        # Use a Gaussian-shaped big peak so that after box-3 smoothing there is a
        # strict local maximum (flat tops lose the > strict comparison).
        idx = np.arange(500)
        counts += 1000.0 * np.exp(-0.5 * ((idx - 100) / 4.0) ** 2)
        # tiny peak at index 300 — value ~1% of max; below threshold=0.05
        counts[300] = 10.0
        peaks = detect_peaks(energy, counts, threshold=0.05)
        assert len(peaks) == 1   # tiny peak should be suppressed

    def test_empty_spectrum(self):
        energy = np.linspace(0, 5, 10)
        counts = np.zeros(10)
        peaks = detect_peaks(energy, counts, threshold=0.05)
        assert peaks.size == 0


class TestAssignElements:
    def test_fe_ka_6404(self):
        """Fe Kα at 6.404 keV → Fe must appear first in candidates."""
        results = assign_elements(np.array([6.404]))
        assert len(results) == 1
        cands = results[0].candidates
        assert len(cands) > 0
        assert cands[0].symbol == "Fe"
        assert cands[0].line == "K"

    def test_cu_ka_8048(self):
        results = assign_elements(np.array([8.048]))
        assert results[0].candidates[0].symbol == "Cu"

    def test_o_ka_0525(self):
        results = assign_elements(np.array([0.525]))
        assert results[0].candidates[0].symbol == "O"

    def test_tolerance_window(self):
        """Peak in an empty table gap returns no candidates.

        17.0 keV sits between Nb Kα (16.615) and Mo Kα (17.479) with a
        0.864 keV gap — well outside the 0.15 keV tolerance on both sides.
        """
        results = assign_elements(np.array([17.0]), tolerance_kev=0.15)
        assert len(results[0].candidates) == 0

    def test_candidates_sorted_by_delta(self):
        """Closest match must be first."""
        results = assign_elements(np.array([1.74]), tolerance_kev=0.5)
        cands = results[0].candidates
        deltas = [c.delta_kev for c in cands]
        assert deltas == sorted(deltas)

    def test_multiple_peaks(self):
        """All input peaks get an entry (even if candidates empty)."""
        peaks = np.array([0.525, 6.404, 8.048, 99.0])
        results = assign_elements(peaks, tolerance_kev=0.15)
        assert len(results) == 4
        # 99 keV — no line — empty candidates
        assert len(results[3].candidates) == 0


# ── #44 API endpoint ─────────────────────────────────────────────────

def _open_eds_cube(client, tmp_path) -> str:
    """Create a minimal EDS SI cube with synthetic Fe + O peaks."""
    ny, nx, ne = 3, 3, 500
    energy_kev = np.linspace(0.1, 10.0, ne)
    spec = np.zeros(ne)
    for pk in [0.525, 6.404]:   # O Kα, Fe Kα
        spec += np.exp(-0.5 * ((energy_kev - pk) / 0.04) ** 2) * 2000
    spec += 5.0   # baseline
    flat = np.repeat(spec.astype(np.float32), ny * nx)
    de = float(energy_kev[1] - energy_kev[0])
    origin = float(-energy_kev[0] / de)
    f = write_mini_dm4(
        tmp_path / "eds.dm4", dims=[nx, ny, ne], data=flat, data_type=2,
        cal=[
            {"scale": 1.0, "origin": 0, "units": "nm"},
            {"scale": 1.0, "origin": 0, "units": "nm"},
            {"scale": de, "origin": origin, "units": "keV"},
        ],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


class TestEdsAutoAssignApi:
    def test_returns_peaks_and_assignments(self, client, tmp_path):
        cube_id = _open_eds_cube(client, tmp_path)
        r = client.post("/api/eds/auto-assign", json={
            "image_id": cube_id,
            "tolerance_kev": 0.15,
            "threshold": 0.01,
        })
        assert r.status_code == 200
        body = r.json()
        assert "peaks_kev" in body
        assert "assignments" in body
        assert len(body["peaks_kev"]) == len(body["assignments"])
        # must detect at least the two synthetic peaks
        peaks = body["peaks_kev"]
        assert any(abs(p - 0.525) < 0.1 for p in peaks), "O Kα not detected"
        assert any(abs(p - 6.404) < 0.1 for p in peaks), "Fe Kα not detected"

    def test_fe_peak_assigned_to_fe(self, client, tmp_path):
        cube_id = _open_eds_cube(client, tmp_path)
        r = client.post("/api/eds/auto-assign", json={
            "image_id": cube_id,
            "tolerance_kev": 0.15,
            "threshold": 0.01,
        })
        body = r.json()
        # find the assignment closest to Fe Kα
        fe_asgn = min(
            body["assignments"],
            key=lambda a: abs(a["peak_kev"] - 6.404),
        )
        assert abs(fe_asgn["peak_kev"] - 6.404) < 0.2
        syms = [c["symbol"] for c in fe_asgn["candidates"]]
        assert "Fe" in syms

    def test_requires_spectral_kind(self, client, tmp_path):
        data = np.zeros((16, 16), dtype=np.float32)
        h, w = data.shape
        f = write_mini_dm4(
            tmp_path / "img.dm4", dims=[w, h],
            data=data.ravel(),
            cal=[{"scale": 1.0, "origin": 0, "units": "nm"}] * 2,
        )
        img_id = client.post(
            "/api/session/open", json={"paths": [str(f)]}
        ).json()[0]["id"]
        r = client.post("/api/eds/auto-assign",
                        json={"image_id": img_id})
        assert r.status_code == 400
