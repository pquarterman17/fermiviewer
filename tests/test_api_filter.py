"""API tests for POST /filter — derived-image filter pipeline."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.filters import apply_gaussian, bin_image
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.imaging]


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def img_id(client, tmp_path) -> str:
    w, h = 16, 12
    flat = np.array([x + 10 * y for y in range(h) for x in range(w)])
    f = write_mini_dm4(
        tmp_path / "img.dm4", dims=[w, h], data=flat,
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def test_gaussian_filter_matches_calc(client, img_id) -> None:
    r = client.post(
        "/api/filter",
        json={"image_id": img_id, "kind": "gaussian", "params": {"sigma": 1.5}},
    )
    assert r.status_code == 200
    meta = r.json()
    assert meta["name"].startswith("gaussian(")
    assert meta["shape"] == [12, 16]
    assert meta["pixel_size"] == pytest.approx(0.5)  # cal carried through

    # derived pixels equal a direct calc call on the source raster
    src = store.get(img_id).data
    expect = apply_gaussian(np.asarray(src, dtype=np.float64), sigma=1.5)
    got = store.get(meta["id"]).data
    np.testing.assert_allclose(got, expect, rtol=1e-12)


def test_bin_scales_calibration(client, img_id) -> None:
    r = client.post(
        "/api/filter",
        json={"image_id": img_id, "kind": "bin", "params": {"bin_size": 2}},
    )
    meta = r.json()
    assert meta["shape"] == [6, 8]
    assert meta["pixel_size"] == pytest.approx(1.0)  # 0.5 nm × 2

    src = store.get(img_id).data
    expect = bin_image(np.asarray(src, dtype=np.float64), 2)
    np.testing.assert_allclose(store.get(meta["id"]).data, expect, rtol=1e-12)


def test_all_kinds_run(client, img_id) -> None:
    for kind in ("median", "unsharp", "butterworth", "clahe", "plane_level"):
        r = client.post("/api/filter", json={"image_id": img_id, "kind": kind})
        assert r.status_code == 200, f"{kind}: {r.text}"
        assert r.json()["shape"] == [12, 16]


def test_filter_chain(client, img_id) -> None:
    # derived images are themselves filterable
    first = client.post(
        "/api/filter", json={"image_id": img_id, "kind": "gaussian"}
    ).json()
    second = client.post(
        "/api/filter", json={"image_id": first["id"], "kind": "bin"}
    )
    assert second.status_code == 200
    assert second.json()["shape"] == [6, 8]


def test_error_paths(client, img_id) -> None:
    assert (
        client.post(
            "/api/filter", json={"image_id": "nope", "kind": "gaussian"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/filter", json={"image_id": img_id, "kind": "sharpen9000"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/filter",
            json={
                "image_id": img_id,
                "kind": "median",
                "params": {"window_size": 4},
            },
        ).status_code
        == 422
    )


# ── geometric ops (stage toolbar) ────────────────────────────────────

def test_rotate_and_flip(client, img_id) -> None:
    src = np.asarray(store.get(img_id).data, dtype=np.float64)

    r = client.post("/api/filter",
                    json={"image_id": img_id, "kind": "rotate90"})
    assert r.status_code == 200
    meta = r.json()
    assert meta["shape"] == [16, 12]                 # H/W swapped
    np.testing.assert_array_equal(
        store.get(meta["id"]).data, np.rot90(src, k=-1))

    r = client.post("/api/filter",
                    json={"image_id": img_id, "kind": "rotate270"})
    np.testing.assert_array_equal(
        store.get(r.json()["id"]).data, np.rot90(src, k=1))

    r = client.post("/api/filter",
                    json={"image_id": img_id, "kind": "rotate180"})
    m180 = r.json()
    assert m180["shape"] == [12, 16]                 # dims unchanged
    np.testing.assert_array_equal(
        store.get(m180["id"]).data, src[::-1, ::-1])

    r = client.post("/api/filter",
                    json={"image_id": img_id, "kind": "fliph"})
    np.testing.assert_array_equal(
        store.get(r.json()["id"]).data, src[:, ::-1])

    r = client.post("/api/filter",
                    json={"image_id": img_id, "kind": "flipv"})
    np.testing.assert_array_equal(
        store.get(r.json()["id"]).data, src[::-1, :])


def test_rotate_round_trip_identity(client, img_id) -> None:
    """rotate90 then rotate270 of the derived image == original."""
    src = np.asarray(store.get(img_id).data, dtype=np.float64)
    cw = client.post("/api/filter",
                     json={"image_id": img_id, "kind": "rotate90"}).json()
    back = client.post("/api/filter",
                       json={"image_id": cw["id"], "kind": "rotate270"}).json()
    np.testing.assert_array_equal(store.get(back["id"]).data, src)
    assert back["pixel_size"] == pytest.approx(0.5)  # cal survives


def test_crop(client, img_id) -> None:
    src = np.asarray(store.get(img_id).data, dtype=np.float64)
    r = client.post("/api/filter", json={
        "image_id": img_id, "kind": "crop",
        "params": {"row0": 3, "col0": 5, "row1": 8, "col1": 12},
    })
    assert r.status_code == 200
    meta = r.json()
    assert meta["shape"] == [6, 8]                   # inclusive 1-based
    np.testing.assert_array_equal(
        store.get(meta["id"]).data, src[2:8, 4:12])
    assert meta["pixel_size"] == pytest.approx(0.5)

    # fully out-of-range rect → clean 422
    assert client.post("/api/filter", json={
        "image_id": img_id, "kind": "crop",
        "params": {"row0": 50, "col0": 5, "row1": 60, "col1": 12},
    }).status_code == 422
    # missing params → clean 422 (not a 500)
    assert client.post("/api/filter", json={
        "image_id": img_id, "kind": "crop", "params": {"row0": 1},
    }).status_code == 422


def test_morph_and_multiotsu_kinds(client, img_id) -> None:
    r = client.post("/api/filter", json={
        "image_id": img_id, "kind": "morph",
        "params": {"operation": "dilate", "radius": 1, "shape": "disk"},
    })
    assert r.status_code == 200
    out = np.asarray(store.get(r.json()["id"]).data)
    assert set(np.unique(out)) <= {0.0, 1.0}          # binary result

    r = client.post("/api/filter", json={
        "image_id": img_id, "kind": "multiotsu", "params": {"n_classes": 3},
    })
    assert r.status_code == 200
    labels = np.asarray(store.get(r.json()["id"]).data)
    assert set(np.unique(labels)) <= {1.0, 2.0, 3.0}  # MATLAB 1-based
    assert client.post("/api/filter", json={
        "image_id": img_id, "kind": "multiotsu", "params": {"n_classes": 9},
    }).status_code == 422
