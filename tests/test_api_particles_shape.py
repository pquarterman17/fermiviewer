"""API tests for the particle-shape wire contract (SHAPE_ANALYSIS_PLAN
Wave 1 #1/#2): the eight fields `/api/analyze/particles` gains
(circularity, aspect_ratio, eccentricity, orientation_rad, solidity,
feret_max, feret_max_calibrated, shape_class) plus the optional
`class_thresholds` override. Calc-level numerics are covered by
test_shape_metrics.py; these verify the route wiring, JSON shapes, and
the missing-value serialization for the calibrated twin.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.imaging]

_SHAPE_FIELDS = (
    "circularity", "aspect_ratio", "eccentricity", "orientation_rad",
    "solidity", "feret_max", "feret_max_calibrated", "shape_class",
)


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open(
    client: TestClient, tmp_path, data: np.ndarray, name: str = "img.dm4",
    calibrated: bool = True,
) -> str:
    h, w = data.shape
    cal = [{"scale": 0.5, "origin": 0, "units": "nm"}] * 2 if calibrated else None
    f = write_mini_dm4(tmp_path / name, dims=[w, h], data=data.ravel(), cal=cal)
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def _blobs_image() -> np.ndarray:
    img = np.zeros((40, 50))
    img[5:12, 6:13] = 10       # roughly square blob -> sphere-like
    img[20:30, 25:38] = 12     # elongated blob
    return img + 1


# ── wire shape ──────────────────────────────────────────────────────────


def test_particles_response_gains_all_eight_shape_fields(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _blobs_image())
    r = client.post(
        "/api/analyze/particles",
        json={"image_id": img_id, "threshold": 5, "min_area": 10},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["n_particles"] == 2
    for p in body["particles"]:
        for field in _SHAPE_FIELDS:
            assert field in p, f"missing {field} in {p}"
        # dimensionless/typed fields are always present (never null)
        assert isinstance(p["circularity"], float)
        assert isinstance(p["eccentricity"], float)
        assert isinstance(p["orientation_rad"], float)
        assert isinstance(p["solidity"], float)
        assert isinstance(p["feret_max"], float)
        assert p["shape_class"] in (
            "sphere-like", "rod-like", "intermediate", "aggregate",
        )
    # existing fields untouched (additive-only contract)
    assert {"id", "area", "centroid", "equiv_diameter", "mean_intensity",
            "area_calibrated", "diameter_calibrated"} <= body["particles"][0].keys()


def test_orientation_range_is_skimage_convention(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _blobs_image())
    body = client.post(
        "/api/analyze/particles",
        json={"image_id": img_id, "threshold": 5, "min_area": 10},
    ).json()
    for p in body["particles"]:
        assert -np.pi / 2 < p["orientation_rad"] <= np.pi / 2 + 1e-9


# ── calibrated twin: missing-value pattern must match diameter_calibrated ──


def test_feret_max_calibrated_is_null_when_uncalibrated(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _blobs_image(), calibrated=False)
    body = client.post(
        "/api/analyze/particles",
        json={"image_id": img_id, "threshold": 5, "min_area": 10},
    ).json()
    assert body["unit"] == "px"
    for p in body["particles"]:
        # exact same missing-value serialization diameter_calibrated uses
        assert p["diameter_calibrated"] is None
        assert p["feret_max_calibrated"] is None
        # px-space fields stay real numbers regardless of calibration
        assert p["feret_max"] > 0


def test_feret_max_calibrated_matches_pixel_size_when_calibrated(
    client, tmp_path,
) -> None:
    img_id = _open(client, tmp_path, _blobs_image(), calibrated=True)
    body = client.post(
        "/api/analyze/particles",
        json={"image_id": img_id, "threshold": 5, "min_area": 10},
    ).json()
    assert body["unit"] == "nm"
    for p in body["particles"]:
        assert p["feret_max_calibrated"] == pytest.approx(p["feret_max"] * 0.5)
        # same calibration factor the diameter twin already uses
        assert p["diameter_calibrated"] == pytest.approx(p["equiv_diameter"] * 0.5)


# ── degenerate region: aspect_ratio null on the wire ────────────────────


def test_single_pixel_particle_has_null_aspect_ratio(client, tmp_path) -> None:
    img = np.zeros((20, 30))
    img[10, 5] = 10          # isolated single-pixel particle
    img[5:12, 15:22] = 10    # a normal blob elsewhere
    img_id = _open(client, tmp_path, img + 1)
    body = client.post(
        "/api/analyze/particles",
        json={"image_id": img_id, "threshold": 5, "min_area": 1},
    ).json()
    assert body["n_particles"] == 2
    by_area = {p["area"]: p for p in body["particles"]}
    assert by_area[1]["aspect_ratio"] is None
    # never Infinity/NaN leaking onto the wire as a bare float either
    assert by_area[1]["aspect_ratio"] != float("inf")


# ── class_thresholds: tunable end-to-end ────────────────────────────────


def test_class_thresholds_default_matches_frozen_contract(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _blobs_image())
    body = client.post(
        "/api/analyze/particles",
        json={"image_id": img_id, "threshold": 5, "min_area": 10},
    ).json()
    square_blob = next(p for p in body["particles"] if p["area"] == 49)
    assert square_blob["aspect_ratio"] == pytest.approx(1.0)
    assert square_blob["shape_class"] == "sphere-like"


def test_class_thresholds_override_flips_classification(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _blobs_image())
    # tighten sphere_max_aspect below the square blob's ~1.0 aspect ratio
    # so it no longer qualifies as sphere-like, without touching anything
    # else about the request/response shape
    body = client.post(
        "/api/analyze/particles",
        json={
            "image_id": img_id, "threshold": 5, "min_area": 10,
            "class_thresholds": {"sphere_max_aspect": 0.5},
        },
    ).json()
    square_blob = next(p for p in body["particles"] if p["area"] == 49)
    assert square_blob["shape_class"] == "intermediate"


def test_class_thresholds_aggregate_override(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _blobs_image())
    # raise aggregate_max_solidity above 1.0 -> every region with any
    # finite solidity becomes aggregate, overriding rod/sphere entirely
    body = client.post(
        "/api/analyze/particles",
        json={
            "image_id": img_id, "threshold": 5, "min_area": 10,
            "class_thresholds": {"aggregate_max_solidity": 1.01},
        },
    ).json()
    assert all(p["shape_class"] == "aggregate" for p in body["particles"])


def test_class_thresholds_partial_override_keeps_other_defaults(
    client, tmp_path,
) -> None:
    """A request that overrides only one threshold field still applies the
    CALC-LAYER defaults for the rest — resolved via dataclasses.replace,
    not pydantic default-fill. The distinction bit once: the route model
    briefly carried its own copies of the default literals, so a partial
    override silently reverted the corrected sphere cutoff (0.92) to the
    stale 0.85. The probe is a square whose Crofton circularity sits
    INSIDE the 0.85–0.92 trap zone: under the calc default it must stay
    intermediate even when an unrelated threshold is overridden; under
    stale pydantic literals it flips sphere-like and this test goes red."""
    img = np.zeros((60, 60))
    img[10:41, 10:41] = 10     # 31x31 square — Crofton circ ≈ 0.88-0.89
    img_id = _open(client, tmp_path, img + 1)

    # sanity: with no overrides the square is in the trap zone → intermediate
    base = client.post(
        "/api/analyze/particles",
        json={"image_id": img_id, "threshold": 5, "min_area": 10},
    ).json()
    (square,) = base["particles"]
    assert 0.85 < square["circularity"] < 0.92
    assert square["shape_class"] == "intermediate"

    # partial override of an UNRELATED threshold must not change that
    body = client.post(
        "/api/analyze/particles",
        json={
            "image_id": img_id, "threshold": 5, "min_area": 10,
            "class_thresholds": {"rod_min_aspect": 1000.0},
        },
    ).json()
    (square,) = body["particles"]
    assert square["shape_class"] == "intermediate"

    # and an EXPLICIT sphere override is still honoured
    body = client.post(
        "/api/analyze/particles",
        json={
            "image_id": img_id, "threshold": 5, "min_area": 10,
            "class_thresholds": {"sphere_min_circularity": 0.5},
        },
    ).json()
    (square,) = body["particles"]
    assert square["shape_class"] == "sphere-like"
