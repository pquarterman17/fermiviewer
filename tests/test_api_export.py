"""API tests for POST /export — server-side rendering pipeline."""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

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


def test_png_export_scaled(client, img_id) -> None:
    r = client.post(
        "/api/export",
        json={"image_id": img_id, "format": "png", "scale": 3},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert 'filename="img.png"' in r.headers["content-disposition"]
    png = Image.open(io.BytesIO(r.content))
    assert png.size == (48, 36)  # 3× nearest-neighbour
    arr = np.asarray(png)
    assert arr.shape == (36, 48, 3)
    # gray cmap, full window: min pixel 0, max 255
    assert arr.min() == 0 and arr.max() == 255


def test_window_and_colormap(client, img_id) -> None:
    # narrow window clips: everything above hi → top LUT entry
    r = client.post(
        "/api/export",
        json={
            "image_id": img_id,
            "format": "png",
            "lo": 0.0,
            "hi": 0.01,
            "cmap": "viridis",
        },
    )
    arr = np.asarray(Image.open(io.BytesIO(r.content)))
    # viridis top stop is (253, 231, 37); most pixels clip to it
    top = (arr == [253, 231, 37]).all(axis=2)
    assert top.sum() > arr.shape[0] * arr.shape[1] * 0.9


def test_tiff16_roundtrip(client, img_id) -> None:
    import tifffile

    r = client.post(
        "/api/export", json={"image_id": img_id, "format": "tiff16"}
    )
    assert r.status_code == 200
    u16 = tifffile.imread(io.BytesIO(r.content))
    assert u16.dtype == np.uint16
    assert u16.shape == (12, 16)
    assert u16.min() == 0 and u16.max() == 65535


def test_scale_bar_baking(client, img_id) -> None:
    base = client.post(
        "/api/export", json={"image_id": img_id, "format": "png", "scale": 4}
    ).content
    with_bar = client.post(
        "/api/export",
        json={
            "image_id": img_id,
            "format": "png",
            "scale": 4,
            "include": ["scale_bar"],
        },
    ).content
    assert base != with_bar  # bar visibly baked
    a = np.asarray(Image.open(io.BytesIO(with_bar)))
    b = np.asarray(Image.open(io.BytesIO(base)))
    assert (a != b).any(axis=2).sum() > 20  # bar + label pixels differ


def test_jpeg_and_errors(client, img_id) -> None:
    r = client.post(
        "/api/export", json={"image_id": img_id, "format": "jpeg"}
    )
    assert r.status_code == 200
    assert r.content[:2] == b"\xff\xd8"  # JPEG SOI

    assert (
        client.post(
            "/api/export", json={"image_id": "nope", "format": "png"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/export", json={"image_id": img_id, "format": "svg"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/export", json={"image_id": img_id, "format": "bmp"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/export",
            json={"image_id": img_id, "format": "png", "scale": 9},
        ).status_code
        == 422  # pydantic le=4
    )
