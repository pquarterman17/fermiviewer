"""API tests for routes/shape_id.py (SHAPE_ANALYSIS_PLAN Tier-2 items #4
and #5): POST /analyze/efd-similarity and POST /analyze/fit-shape.

Calc-level numerics (invariances, fit accuracy) are covered by
test_efd.py / test_shape_fit.py; these tests verify the WIRE contract:
request validation, the recompute-and-rank flow, and the 404/422 cases.
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


def _open(client: TestClient, tmp_path, data: np.ndarray, name: str = "img.dm4") -> str:
    h, w = data.shape
    f = write_mini_dm4(
        tmp_path / name, dims=[w, h], data=data.ravel(),
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def _three_particle_image() -> np.ndarray:
    """Two disks (one big, one smaller, at opposite ends of the image --
    similar SHAPE to each other) plus one elongated ellipse ("rod-like").
    Curved boundaries throughout so `trace_outer_contour` at the route's
    finer tolerance yields plenty of vertices for every region -- see
    routes/shape_id.py's module docstring on why the tolerance is tuned
    tighter than trace_outer_contour's own default."""
    h, w = 200, 300
    img = np.zeros((h, w))
    yy, xx = np.mgrid[0:h, 0:w]
    disk_ref = (yy - 40) ** 2 + (xx - 40) ** 2 <= 20**2
    disk_similar = (yy - 40) ** 2 + (xx - 250) ** 2 <= 15**2
    rod = ((yy - 150) / 8.0) ** 2 + ((xx - 150) / 60.0) ** 2 <= 1.0
    img[disk_ref] = 10
    img[disk_similar] = 10
    img[rod] = 10
    return img + 1  # background above 0 so threshold=5 cleanly separates


# ── /analyze/efd-similarity ─────────────────────────────────────────


def _particle_req(image_id: str, **overrides) -> dict:
    req = {"image_id": image_id, "threshold": 5, "min_area": 1}
    req.update(overrides)
    return req


def test_ranks_self_first_and_similar_shape_above_dissimilar(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _three_particle_image())
    # locate the small disk's particle id first, by asking for particles
    r = client.post("/api/analyze/particles", json=_particle_req(img_id))
    particles = r.json()["particles"]
    assert len(particles) == 3
    # the two disks are both smaller-area than the rod; identify the ref
    # disk as the largest-area of the two smallest regions (area ~1257 px)
    ref = max(particles, key=lambda p: p["area"] if p["area"] < 1400 else -1)
    ref_id = ref["id"]

    r = client.post(
        "/api/analyze/efd-similarity",
        json=_particle_req(img_id, ref_id=ref_id),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["n_harmonics"] == 10
    ranked = body["ranked"]
    assert len(ranked) == 3
    assert ranked[0]["id"] == ref_id
    assert ranked[0]["distance"] == pytest.approx(0.0, abs=1e-9)
    # strictly increasing distance thereafter (no ties in this fixture)
    dists = [row["distance"] for row in ranked]
    assert dists == sorted(dists)
    # the OTHER disk should rank closer than the rod
    assert ranked[1]["distance"] < ranked[2]["distance"]


def test_default_n_harmonics_is_ten(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _three_particle_image())
    particles = client.post(
        "/api/analyze/particles", json=_particle_req(img_id)
    ).json()["particles"]
    ref_id = particles[0]["id"]
    r = client.post(
        "/api/analyze/efd-similarity", json=_particle_req(img_id, ref_id=ref_id)
    )
    assert r.json()["n_harmonics"] == 10


def test_caller_can_override_n_harmonics(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _three_particle_image())
    particles = client.post(
        "/api/analyze/particles", json=_particle_req(img_id)
    ).json()["particles"]
    ref_id = particles[0]["id"]
    r = client.post(
        "/api/analyze/efd-similarity",
        json=_particle_req(img_id, ref_id=ref_id, n_harmonics=4),
    )
    assert r.status_code == 200
    assert r.json()["n_harmonics"] == 4


def test_unknown_ref_id_is_404(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _three_particle_image())
    r = client.post(
        "/api/analyze/efd-similarity",
        json=_particle_req(img_id, ref_id=999),
    )
    assert r.status_code == 404


def test_unknown_image_id_is_404(client) -> None:
    r = client.post(
        "/api/analyze/efd-similarity",
        json=_particle_req("no-such-image", ref_id=1),
    )
    assert r.status_code == 404


def test_too_few_contour_points_for_harmonic_count_is_422_naming_region(
    client, tmp_path
) -> None:
    """Every region in the fixture has well under 50 traced vertices
    (checked directly against calc/contours.py's tracer), so requesting
    50 harmonics deterministically forces the too-few-points guard,
    regardless of the exact vertex count DP-simplification happens to
    produce for any one region."""
    img_id = _open(client, tmp_path, _three_particle_image())
    particles = client.post(
        "/api/analyze/particles", json=_particle_req(img_id)
    ).json()["particles"]
    ref_id = particles[0]["id"]
    r = client.post(
        "/api/analyze/efd-similarity",
        json=_particle_req(img_id, ref_id=ref_id, n_harmonics=50),
    )
    assert r.status_code == 422
    assert "region" in r.json()["detail"]


# ── /analyze/fit-shape ──────────────────────────────────────────────


def _circle_points(cy, cx, r, n=50) -> list[list[float]]:
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    pts = np.column_stack([cy + r * np.sin(t), cx + r * np.cos(t)])
    return pts.tolist()


def test_fit_shape_returns_circle_and_ellipse(client) -> None:
    pts = _circle_points(50.0, 30.0, 12.0)
    r = client.post("/api/analyze/fit-shape", json={"points": pts})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"circle", "ellipse"}
    assert body["circle"]["cy"] == pytest.approx(50.0, abs=0.5)
    assert body["circle"]["cx"] == pytest.approx(30.0, abs=0.5)
    assert body["circle"]["r"] == pytest.approx(12.0, abs=0.5)
    assert set(body["circle"].keys()) == {"cy", "cx", "r", "rms"}
    assert set(body["ellipse"].keys()) == {"cy", "cx", "a", "b", "theta_rad", "rms"}
    assert body["ellipse"]["a"] == pytest.approx(12.0, abs=0.5)
    assert body["ellipse"]["b"] == pytest.approx(12.0, abs=0.5)


def test_fit_shape_ellipse_field_mapping_on_elongated_shape(client) -> None:
    """A circle can't distinguish an a/b (or cy/cx) field swap since both
    axes are equal -- use a genuinely elongated ellipse so `a != b`."""

    def _ellipse_points(cy, cx, a, b, theta, n=80):
        t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
        ex, ey = a * np.cos(t), b * np.sin(t)
        ct, st = np.cos(theta), np.sin(theta)
        row = cy + st * ex + ct * ey
        col = cx + ct * ex - st * ey
        return np.column_stack([row, col]).tolist()

    pts = _ellipse_points(20.0, 40.0, 15.0, 6.0, 0.3)
    r = client.post("/api/analyze/fit-shape", json={"points": pts})
    assert r.status_code == 200
    ellipse = r.json()["ellipse"]
    assert ellipse["cy"] == pytest.approx(20.0, abs=0.5)
    assert ellipse["cx"] == pytest.approx(40.0, abs=0.5)
    assert ellipse["a"] == pytest.approx(15.0, abs=0.5)
    assert ellipse["b"] == pytest.approx(6.0, abs=0.5)
    assert ellipse["a"] > ellipse["b"]  # a is always the SEMI-MAJOR axis


def test_fit_shape_too_few_points_for_circle_is_422(client) -> None:
    r = client.post("/api/analyze/fit-shape", json={"points": [[0.0, 0.0], [1.0, 1.0]]})
    assert r.status_code == 422
    assert "circle" in r.json()["detail"]


def test_fit_shape_enough_for_circle_not_ellipse_is_422(client) -> None:
    pts = [[0.0, 0.0], [0.0, 4.0], [4.0, 4.0], [4.0, 0.0]]  # 4 points
    r = client.post("/api/analyze/fit-shape", json={"points": pts})
    assert r.status_code == 422
    assert "ellipse" in r.json()["detail"]


def test_fit_shape_malformed_points_is_422(client) -> None:
    r = client.post("/api/analyze/fit-shape", json={"points": [[1.0, 2.0, 3.0]] * 6})
    assert r.status_code == 422
