"""API tests for POST /regions/propose — edge auto-detect assist (plan
item 16). The blob-area assertion is the one that proves detection
actually works, not merely that the endpoint returns *something*."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.imaging]

_H, _W = 60, 60
_CX, _CY, _R = 30.0, 32.0, 14.0
_BG, _FG = 10.0, 200.0


def _blob_mask() -> np.ndarray:
    yy, xx = np.mgrid[0:_H, 0:_W]
    return ((xx - _CX) ** 2 + (yy - _CY) ** 2) <= _R**2


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def blob_id(client, tmp_path) -> str:
    """A calibrated image with one obvious bright circular blob on a flat
    dark background — a synthetic case with a KNOWN true area, so the
    endpoint's returned area can be checked against ground truth rather
    than merely checking the call succeeds."""
    img = np.where(_blob_mask(), _FG, _BG)
    f = write_mini_dm4(
        tmp_path / "blob.dm4",
        dims=[_W, _H],
        data=img.ravel(),
        cal=[{"scale": 2.0, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def test_propose_region_matches_true_blob_area(client, blob_id) -> None:
    true_area_px = int(_blob_mask().sum())

    r = client.post(
        "/api/regions/propose",
        json={
            "image_id": blob_id,
            "seed": [_CX / _W, _CY / _H],
            "n_classes": 2,
            "tolerance": 1.5,
        },
    )
    assert r.status_code == 200
    body = r.json()

    assert len(body["points"]) >= 4
    for x, y in body["points"]:
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0

    # the assertion that proves detection worked, not just "returned
    # something": within 8% of the true pixel-count area.
    assert body["area_px"] == pytest.approx(true_area_px, rel=0.08)
    # pixel_size=2.0 nm/px was set on the fixture → area scales by 2**2
    assert body["area_calibrated"] == pytest.approx(
        body["area_px"] * 4.0, rel=1e-9
    )
    assert body["unit"] == "nm"


def test_propose_region_with_rect_seed_crops_and_still_finds_the_blob(
    client, blob_id
) -> None:
    true_area_px = int(_blob_mask().sum())
    r0, r1 = (_CY - _R - 4) / _H, (_CY + _R + 4) / _H
    c0, c1 = (_CX - _R - 4) / _W, (_CX + _R + 4) / _W

    r = client.post(
        "/api/regions/propose",
        json={
            "image_id": blob_id,
            "rect": [c0, r0, c1, r1],
            "n_classes": 2,
            "tolerance": 1.5,
        },
    )
    assert r.status_code == 200
    assert r.json()["area_px"] == pytest.approx(true_area_px, rel=0.08)


def test_propose_region_vertex_count_is_manageable(client, blob_id) -> None:
    r = client.post(
        "/api/regions/propose",
        json={"image_id": blob_id, "seed": [_CX / _W, _CY / _H], "n_classes": 2},
    )
    assert r.status_code == 200
    # a 14-px-radius circle traced raw would have dozens of marching-
    # squares vertices; simplification must bring that down a lot.
    assert len(r.json()["points"]) < 30


def test_propose_region_unknown_image_is_404(client) -> None:
    assert client.post(
        "/api/regions/propose", json={"image_id": "nope", "seed": [0.5, 0.5]}
    ).status_code == 404


def test_propose_region_requires_seed_or_rect(client, blob_id) -> None:
    r = client.post("/api/regions/propose", json={"image_id": blob_id})
    assert r.status_code == 422


def test_propose_region_rejects_out_of_bounds_seed(client, blob_id) -> None:
    r = client.post(
        "/api/regions/propose",
        json={"image_id": blob_id, "seed": [1.5, 0.5]},
    )
    assert r.status_code == 422


def test_propose_region_rejects_bad_n_classes(client, blob_id) -> None:
    r = client.post(
        "/api/regions/propose",
        json={"image_id": blob_id, "seed": [0.5, 0.5], "n_classes": 9},
    )
    assert r.status_code == 422


def test_propose_region_never_500s_on_a_degenerate_rect(client, blob_id) -> None:
    # a rect with zero width/height should be a clean 422, not a crash
    r = client.post(
        "/api/regions/propose",
        json={"image_id": blob_id, "rect": [0.5, 0.5, 0.5, 0.5]},
    )
    assert r.status_code == 422


# ── realdata: a real HAADF image (../test-data/gatan/microscopy) ────────


@pytest.mark.realdata
def test_propose_region_on_real_haadf_image(client, gatan_microscopy) -> None:
    """No manufactured ground truth exists for a real image, so the seed
    is the image's OWN brightest pixel — a genuine localized bright
    feature almost any real HAADF frame has — rather than an arbitrary
    fixed point that might land on flat background and prove nothing."""
    f = gatan_microscopy / "zenodo8403583_apatite_HAADF.dm4"
    meta = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]
    img_id = meta["id"]
    h, w = meta["shape"]

    raster = np.asarray(store.get(img_id).data, dtype=np.float64)
    peak_row, peak_col = np.unravel_index(np.argmax(raster), raster.shape)

    r = client.post(
        "/api/regions/propose",
        json={
            "image_id": img_id,
            "seed": [float(peak_col) / w, float(peak_row) / h],
            "n_classes": 3,
            "tolerance": 2.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["points"]) >= 3
    assert 0.0 < body["area_px"] < h * w
    for x, y in body["points"]:
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
