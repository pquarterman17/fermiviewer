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


# ── vector formats + measurement baking ──────────────────────────────

MEASURES = [
    {"kind": "distance", "pts": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}]},
    {"kind": "profile", "pts": [{"x": 0.0, "y": 0.5}, {"x": 1.0, "y": 0.5}]},
    {"kind": "angle", "pts": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.5},
                              {"x": 1.0, "y": 0.5}]},
    {"kind": "roi", "pts": [{"x": 0.25, "y": 0.25}, {"x": 0.75, "y": 0.75}]},
]


def test_svg_vector_export(client, img_id) -> None:
    r = client.post("/api/export", json={
        "image_id": img_id, "format": "svg", "scale": 2,
        "include": ["scale_bar", "measurements"], "measures": MEASURES,
    })
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert 'filename="img.svg"' in r.headers["content-disposition"]
    svg = r.content.decode()
    assert svg.startswith("<svg")
    assert "data:image/png;base64," in svg     # embedded raster
    assert svg.count("<line") == 2             # distance + profile
    assert 'stroke-dasharray="6 4"' in svg     # profile dashed
    assert "<polyline" in svg                  # angle
    assert svg.count("<rect") == 2             # roi + scale bar
    assert "°" in svg                          # angle label
    # distance: 16 px × 0.5 nm = 8 nm, mirrored fmt
    assert ">8 nm</text>" in svg
    # embedded PNG decodes at output size
    b64 = svg.split("base64,")[1].split('"')[0]
    import base64

    png = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert png.size == (32, 24)


def test_pdf_export(client, img_id) -> None:
    r = client.post("/api/export", json={
        "image_id": img_id, "format": "pdf",
        "include": ["measurements"], "measures": MEASURES,
    })
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert 'filename="img.pdf"' in r.headers["content-disposition"]


def test_measurement_baking_png(client, img_id) -> None:
    base = client.post("/api/export", json={
        "image_id": img_id, "format": "png", "scale": 4,
    }).content
    baked = client.post("/api/export", json={
        "image_id": img_id, "format": "png", "scale": 4,
        "include": ["measurements"], "measures": MEASURES,
        "overlay_color": "#ff0000",
    }).content
    assert base != baked
    a = np.asarray(Image.open(io.BytesIO(baked)))
    b = np.asarray(Image.open(io.BytesIO(base)))
    changed = (a != b).any(axis=2)
    assert changed.sum() > 100                 # lines + labels baked
    # pure red overlay pixels exist (line interiors, away from AA text)
    assert ((a[..., 0] == 255) & (a[..., 1] == 0) & (a[..., 2] == 0)).any()
    # measures without the include flag → ignored (no accidental baking)
    plain = client.post("/api/export", json={
        "image_id": img_id, "format": "png", "scale": 4,
        "measures": MEASURES,
    }).content
    assert plain == base


def test_annotation_labels() -> None:
    """calc-level: labels mirror MeasureOverlay (fmt, vertex, μ/σ)."""
    from fermiviewer.calc.export import measure_annotations

    raster = np.full((12, 16), 7.0)
    annos = measure_annotations(
        MEASURES, 12, 16, pixel_size=0.5, pixel_unit="nm",
        scale=1, raster=raster,
    )
    by_kind = {a.kind: a for a in annos}
    assert by_kind["distance"].label == "8 nm"          # 16 px × 0.5
    assert by_kind["profile"].dashed
    # vertex (8,6) px; rays to (0,0) and (16,6): |atan2 Δ| = 143.13°
    assert by_kind["angle"].label == "143.1°"
    assert by_kind["roi"].label == "μ 7 · σ 0"          # uniform raster
    # uncalibrated → px labels
    annos_px = measure_annotations(MEASURES[:1], 12, 16, None, "px", 2)
    assert annos_px[0].label == "16 px"
    assert annos_px[0].points[1] == (32.0, 0.0)         # 2× output coords


ANNOTATIONS = [
    {"kind": "text", "pts": [{"x": 0.5, "y": 0.5}], "text": "grain A"},
    {"kind": "arrow", "pts": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.9}],
     "text": "defect"},
    {"kind": "box", "pts": [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.6}],
     "text": "ROI 1"},
]


def test_annotation_export(client, img_id) -> None:
    # SVG: vector elements + captions present
    r = client.post("/api/export", json={
        "image_id": img_id, "format": "svg", "scale": 2,
        "include": ["measurements"], "measures": ANNOTATIONS,
    })
    assert r.status_code == 200
    svg = r.content.decode()
    assert ">grain A</text>" in svg
    assert ">defect</text>" in svg
    assert ">ROI 1</text>" in svg
    assert "<polyline" in svg          # arrowhead
    assert "<rect" in svg              # box
    # PNG baking renders without error and differs from base
    base = client.post("/api/export", json={
        "image_id": img_id, "format": "png", "scale": 4,
    }).content
    baked = client.post("/api/export", json={
        "image_id": img_id, "format": "png", "scale": 4,
        "include": ["measurements"], "measures": ANNOTATIONS,
    }).content
    assert baked != base


def _open_frame(client, tmp_path, name: str, offset: float) -> str:
    w, h = 16, 12
    # vary the PATTERN per frame (a constant offset would window
    # away to identical frames, which PIL collapses to one)
    flat = np.array(
        [x * (1 + offset) + 10 * y * (2 - offset) for y in range(h)
         for x in range(w)],
        dtype=np.float32,
    )
    f = write_mini_dm4(tmp_path / name, dims=[w, h], data=flat, data_type=2,
                       cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2)
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def test_gif_export(client, tmp_path) -> None:
    ids = [_open_frame(client, tmp_path, f"f{i}.dm4", 0.5 * i)
           for i in range(3)]
    r = client.post("/api/export/gif", json={
        "image_ids": ids, "fps": 5, "scale": 2,
    })
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/gif"
    assert r.content[:6] in (b"GIF87a", b"GIF89a")
    gif = Image.open(io.BytesIO(r.content))
    assert gif.n_frames == 3
    assert gif.size == (32, 24)                      # 2× scaled
    # one frame → 422; /export with gif → redirect hint 422
    assert client.post("/api/export/gif", json={
        "image_ids": ids[:1],
    }).status_code == 422
    assert client.post("/api/export", json={
        "image_id": ids[0], "format": "gif",
    }).status_code == 422
    # mismatched dims → 422
    big = np.arange(20 * 20, dtype=np.float32)
    f = write_mini_dm4(tmp_path / "big.dm4", dims=[20, 20], data=big,
                       data_type=2,
                       cal=[{"scale": 1, "origin": 0, "units": "nm"}] * 2)
    big_id = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]
    assert client.post("/api/export/gif", json={
        "image_ids": [ids[0], big_id],
    }).status_code == 422


def test_colorbar_baking(client, img_id) -> None:
    base = client.post("/api/export", json={
        "image_id": img_id, "format": "png", "scale": 2,
    })
    with_bar = client.post("/api/export", json={
        "image_id": img_id, "format": "png", "scale": 2,
        "include": ["colorbar"], "cmap": "viridis",
    })
    assert with_bar.status_code == 200
    a = Image.open(io.BytesIO(base.content))
    b = Image.open(io.BytesIO(with_bar.content))
    assert b.width == a.width + 81          # pad 5 + strip 20 + labels 56
    assert b.height == a.height
    # SVG variant widens the canvas and embeds the strip
    svg = client.post("/api/export", json={
        "image_id": img_id, "format": "svg",
        "include": ["colorbar"], "cmap": "viridis",
    }).content.decode()
    assert svg.count("base64,") == 2        # image + strip
