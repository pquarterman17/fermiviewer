"""API tests for session/open + image endpoints — fixture-driven."""

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
def dm4_image(tmp_path):
    """A 6×4 gradient image fixture: v(x, y) = x + 10·y."""
    w, h = 6, 4
    flat = np.array([x + 10 * y for y in range(h) for x in range(w)])
    return write_mini_dm4(
        tmp_path / "img.dm4", dims=[w, h], data=flat,
        cal=[{"scale": 0.2, "origin": 0, "units": "nm"}] * 2,
    )


def test_open_and_meta(client: TestClient, dm4_image) -> None:
    r = client.post("/api/session/open", json={"paths": [str(dm4_image)]})
    assert r.status_code == 200
    metas = r.json()
    assert len(metas) == 1
    m = metas[0]
    assert m["kind"] == "image"
    assert m["shape"] == [4, 6]
    assert m["pixel_size"] == pytest.approx(0.2)
    assert m["pixel_unit"] == "nm"

    r2 = client.get(f"/api/image/{m['id']}/meta")
    assert r2.status_code == 200
    assert r2.json() == m

    r3 = client.get("/api/session/images")
    assert [x["id"] for x in r3.json()] == [m["id"]]


def test_render_png_window_level(client: TestClient, dm4_image) -> None:
    img_id = client.post(
        "/api/session/open", json={"paths": [str(dm4_image)]}
    ).json()[0]["id"]

    r = client.get(f"/api/image/{img_id}/render")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    png = Image.open(io.BytesIO(r.content))
    assert png.size == (6, 4)            # PIL size is (W, H)
    arr = np.asarray(png)
    # full-range auto window: min → 0, max → 255
    assert arr.min() == 0 and arr.max() == 255
    assert arr[0, 0] == 0                # v(0,0)=0 is the global min
    assert arr[3, 5] == 255              # v(5,3)=35 is the global max

    # explicit narrow window clips
    r2 = client.get(f"/api/image/{img_id}/render", params={"lo": 0, "hi": 1})
    arr2 = np.asarray(Image.open(io.BytesIO(r2.content)))
    assert arr2[3, 5] == 255 and arr2[0, 1] == 255   # everything ≥ hi clips white


def test_histogram(client: TestClient, dm4_image) -> None:
    img_id = client.post(
        "/api/session/open", json={"paths": [str(dm4_image)]}
    ).json()[0]["id"]
    r = client.get(f"/api/image/{img_id}/histogram", params={"bins": 16})
    body = r.json()
    assert len(body["bins"]) == 16 and len(body["counts"]) == 16
    assert sum(body["counts"]) == 24     # every pixel counted
    assert client.get(f"/api/image/{img_id}/histogram", params={"bins": 1}).status_code == 422


def test_upload_via_picker(client: TestClient, dm4_image) -> None:
    # multipart upload = what the browser's native file picker sends
    with open(dm4_image, "rb") as f:
        r = client.post(
            "/api/session/upload",
            files=[("files", ("picked.dm4", f, "application/octet-stream"))],
        )
    assert r.status_code == 200
    m = r.json()[0]
    assert m["name"] == "picked.dm4"
    assert m["shape"] == [4, 6]
    assert m["pixel_size"] == pytest.approx(0.2)
    # fully usable afterwards (temp staging file is gone, data in memory)
    assert client.get(f"/api/image/{m['id']}/render").status_code == 200
    # source metadata points at the picked name, not a temp path
    meta = client.get(f"/api/image/{m['id']}/meta").json()
    assert meta["meta"]["source"] == "picked.dm4"

    # unsupported extension → 415; corrupt content → 422
    r2 = client.post(
        "/api/session/upload",
        files=[("files", ("x.xyz", b"junk", "application/octet-stream"))],
    )
    assert r2.status_code == 415
    r3 = client.post(
        "/api/session/upload",
        files=[("files", ("bad.dm4", b"notdm4", "application/octet-stream"))],
    )
    assert r3.status_code == 422

    exts = client.get("/api/session/supported-extensions").json()["extensions"]
    assert ".dm4" in exts and ".tif" in exts


def test_data16_normalized_raster(client: TestClient, dm4_image) -> None:
    img_id = client.post(
        "/api/session/open", json={"paths": [str(dm4_image)]}
    ).json()[0]["id"]

    r = client.get(f"/api/image/{img_id}/data16")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["x-shape"] == "4,6"
    vmin, vmax = float(r.headers["x-min"]), float(r.headers["x-max"])
    assert (vmin, vmax) == (0.0, 35.0)   # v(x,y) = x + 10·y on 6×4

    u16 = np.frombuffer(r.content, dtype="<u2").reshape(4, 6)
    assert u16[0, 0] == 0 and u16[3, 5] == 65535
    # reconstruction round-trips the original values exactly (integers)
    rec = u16.astype(np.float64) / 65535.0 * (vmax - vmin) + vmin
    expect = np.array([[x + 10 * y for x in range(6)] for y in range(4)])
    np.testing.assert_allclose(rec, expect, atol=(vmax - vmin) / 65535.0)

    assert client.get("/api/image/nope/data16").status_code == 404


def test_spectrum_image_renders_summed_map(client: TestClient, tmp_path) -> None:
    nx, ny, ne = 4, 3, 5
    flat = np.arange(nx * ny * ne)
    f = write_mini_dm4(
        tmp_path / "si.dm4", dims=[nx, ny, ne], data=flat,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 0.1, "origin": 0, "units": "eV"},
        ],
    )
    m = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]
    assert m["kind"] == "spectrum_image"
    assert m["n_channels"] == ne
    r = client.get(f"/api/image/{m['id']}/render")
    assert Image.open(io.BytesIO(r.content)).size == (nx, ny)


def test_spectrum_endpoint(client: TestClient, tmp_path, dm4_image) -> None:
    nx, ny, ne = 4, 3, 5
    flat = np.arange(nx * ny * ne)
    f = write_mini_dm4(
        tmp_path / "si.dm4", dims=[nx, ny, ne], data=flat,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 0.1, "origin": 0, "units": "eV"},
        ],
    )
    m = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]
    r = client.get(f"/api/image/{m['id']}/spectrum")
    assert r.status_code == 200
    body = r.json()
    assert len(body["energy"]) == ne
    assert len(body["counts"]) == ne
    assert body["units"] == "eV"
    # sum over all pixels equals the cube total
    assert sum(body["counts"]) == pytest.approx(float(flat.sum()))

    # plain 2D image has no spectral axis
    img_id = client.post(
        "/api/session/open", json={"paths": [str(dm4_image)]}
    ).json()[0]["id"]
    assert client.get(f"/api/image/{img_id}/spectrum").status_code == 400


def test_error_paths(client: TestClient, tmp_path) -> None:
    assert client.get("/api/image/nope/render").status_code == 404
    r = client.post("/api/session/open", json={"paths": [str(tmp_path / "x.xyz")]})
    assert r.status_code == 415          # unsupported extension
    bad = tmp_path / "bad.dm4"
    bad.write_bytes(b"notdm4")
    assert client.post(
        "/api/session/open", json={"paths": [str(bad)]}
    ).status_code == 422                  # parser rejects cleanly

    # close removes the image
    f = write_mini_dm4(
        tmp_path / "tiny.dm4", dims=[2, 2], data=np.arange(4),
        cal=[{"scale": 1, "origin": 0, "units": "nm"}] * 2,
    )
    img_id = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]
    assert client.delete(f"/api/image/{img_id}").status_code == 200
    assert client.get(f"/api/image/{img_id}/meta").status_code == 404


@pytest.mark.realdata
def test_open_real_dm4(client: TestClient, eels_corpus) -> None:
    f = eels_corpus / "FigS6_apatite_ZLP.dm4"
    m = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]
    assert m["kind"] == "spectrum_image"
    assert m["shape"] == [50, 52, 2024]
    r = client.get(f"/api/image/{m['id']}/render")
    assert Image.open(io.BytesIO(r.content)).size == (52, 50)
