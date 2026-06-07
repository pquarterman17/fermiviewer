"""calc/stack.py + stack-op endpoints (image math, align, MIP) and
elliptical ROI stats."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.profiles import roi_stats
from fermiviewer.calc.stack import align_stack, image_math, mip
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.imaging]


# ── calc oracles (verbatim executeImageMath / executeAlignStack) ─────

def test_image_math_ops() -> None:
    a = np.arange(12, dtype=np.float64).reshape(3, 4) + 10
    b = np.ones((3, 4)) * 2
    np.testing.assert_array_equal(image_math(a, b, "subtract"), a - b)
    np.testing.assert_array_equal(image_math(a, b, "add"), a + b)
    np.testing.assert_array_equal(image_math(a, b, "divide"), a / 2)
    np.testing.assert_array_equal(image_math(a, b, "ratio"), a / (a + 2))
    # denominator clamp at 1 (count-data convention)
    z = np.zeros((3, 4))
    np.testing.assert_array_equal(image_math(a, z, "divide"), a)
    # mismatched sizes crop to common top-left region
    big = np.ones((5, 6))
    assert image_math(a, big, "add").shape == (3, 4)
    with pytest.raises(ValueError, match="op must be"):
        image_math(a, b, "xor")


def test_align_stack_recovers_known_shift() -> None:
    rng = np.random.default_rng(7)
    ref = rng.random((32, 40))
    mover = np.roll(ref, (-3, 5), axis=(0, 1))   # drifted frame
    aligned, shifts = align_stack([ref, mover])
    assert tuple(shifts[0]) == (0, 0)
    assert tuple(shifts[1]) == (3, -5)           # inverse of the drift
    np.testing.assert_allclose(aligned[1], ref, rtol=1e-12)


def test_mip() -> None:
    a = np.zeros((4, 4))
    a[1, 1] = 5
    b = np.zeros((4, 4))
    b[2, 2] = 7
    out = mip([a, b])
    assert out[1, 1] == 5 and out[2, 2] == 7
    # frames pad into the FIRST frame's canvas
    small = np.full((2, 2), 9.0)
    out2 = mip([a, small])
    assert out2.shape == (4, 4)
    assert out2[0, 0] == 9 and out2[3, 3] == 0


def test_ellipse_roi_stats() -> None:
    img = np.ones((11, 11))
    rect = roi_stats(img, 1, 1, 11, 11)
    ell = roi_stats(img, 1, 1, 11, 11, shape="ellipse")
    # inscribed ellipse keeps ~π/4 of the bounding box
    assert ell["n_pixels"] < rect["n_pixels"]
    assert ell["n_pixels"] / rect["n_pixels"] == pytest.approx(
        np.pi / 4, abs=0.08)
    with pytest.raises(ValueError, match="shape"):
        roi_stats(img, 1, 1, 5, 5, shape="hex")


# ── endpoints ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open(client, tmp_path, name, arr) -> str:
    h, w = arr.shape
    f = write_mini_dm4(tmp_path / name, dims=[w, h],
                       data=arr.ravel().astype(np.float32), data_type=2,
                       cal=[{"scale": 1, "origin": 0, "units": "nm"}] * 2)
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def test_stack_endpoints(client, tmp_path) -> None:
    rng = np.random.default_rng(3)
    ref = rng.random((16, 20)) * 100
    mov = np.roll(ref, (2, -3), axis=(0, 1))
    a = _open(client, tmp_path, "a.dm4", ref)
    b = _open(client, tmp_path, "b.dm4", mov)

    r = client.post("/api/analyze/image-math",
                    json={"a_id": a, "b_id": b, "op": "subtract"})
    assert r.status_code == 200
    assert r.json()["image"]["name"].startswith("subtract(")

    r = client.post("/api/analyze/align-stack",
                    json={"image_ids": [a, b]})
    assert r.status_code == 200
    body = r.json()
    assert body["shifts"][1] == [-2, 3]
    aligned = np.asarray(store.get(body["images"][0]["id"]).data)
    src = np.asarray(store.get(a).data)
    np.testing.assert_allclose(aligned, src, rtol=1e-5)

    r = client.post("/api/analyze/mip", json={"image_ids": [a, b]})
    assert r.status_code == 200
    assert r.json()["image"]["name"] == "MIP(2)"
    assert client.post("/api/analyze/mip",
                       json={"image_ids": [a]}).status_code == 422

    # elliptical ROI through the endpoint
    r = client.post("/api/measure/roi", json={
        "image_id": a, "rect": [2, 2, 14, 18], "shape": "ellipse",
    })
    assert r.status_code == 200
    assert r.json()["n_pixels"] > 0
