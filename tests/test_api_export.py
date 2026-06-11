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


def test_scale_bar_custom_geometry(client, img_id) -> None:
    """Custom norm_x/y and length_phys honour overrides without breaking
    existing golden/export tests (all defaults remain backward-compatible)."""
    # default bar — bottom-left
    default = np.asarray(
        Image.open(
            io.BytesIO(
                client.post(
                    "/api/export",
                    json={
                        "image_id": img_id,
                        "format": "png",
                        "scale": 4,
                        "include": ["scale_bar"],
                    },
                ).content
            )
        )
    )
    # custom bar — top-right corner (norm_x=0.7, norm_y=0.1)
    custom = np.asarray(
        Image.open(
            io.BytesIO(
                client.post(
                    "/api/export",
                    json={
                        "image_id": img_id,
                        "format": "png",
                        "scale": 4,
                        "include": ["scale_bar"],
                        "scale_bar_norm_x": 0.7,
                        "scale_bar_norm_y": 0.1,
                        "scale_bar_length_phys": 1.0,
                        "scale_bar_thickness": 4,
                    },
                ).content
            )
        )
    )
    # images must differ (bar is in different location)
    assert (default != custom).any()
    # custom thickness=4 means 4 white rows somewhere near the top half
    # (the bar is white in a gray image; verify some white pixels exist
    # in the upper portion of the image)
    top_half = custom[: custom.shape[0] // 2, :, :]
    assert (top_half == 255).any()


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


def test_annotation_labels_tilt_corrected() -> None:
    """#34: tilt correction scales the in-axis component of distance/
    profile/polyline LABELS (1/sin θ cross-section, 1/cos θ surface);
    drawn geometry stays untouched; off-axis lines are unchanged."""
    from fermiviewer.calc.export import measure_annotations

    # MEASURES[0]: horizontal 16 px distance (Δx=16, Δy=0)
    base = measure_annotations(MEASURES[:1], 12, 16, None, "px", 1)
    # in-axis (X) cross-section at 30°: 16 / sin(30°) = 32
    ax = measure_annotations(MEASURES[:1], 12, 16, None, "px", 1,
                             tilt_angle_deg=30.0, tilt_axis="X")
    assert ax[0].label == "32 px"
    assert ax[0].points == base[0].points          # geometry untouched
    # off-axis (Y) tilt leaves a horizontal line unchanged
    off = measure_annotations(MEASURES[:1], 12, 16, None, "px", 1,
                              tilt_angle_deg=30.0, tilt_axis="Y")
    assert off[0].label == "16 px"
    # surface geometry: 16 / cos(60°) = 32
    surf = measure_annotations(MEASURES[:1], 12, 16, None, "px", 1,
                               tilt_angle_deg=60.0, tilt_axis="X",
                               tilt_geometry="surface")
    assert surf[0].label == "32 px"
    # negative angle is equivalent (the component is squared)
    neg = measure_annotations(MEASURES[:1], 12, 16, None, "px", 1,
                              tilt_angle_deg=-30.0, tilt_axis="X")
    assert neg[0].label == "32 px"


def test_box_profile_outline_annotation() -> None:
    """Box profiles (width set) bake the averaging-box outline around
    the dashed centerline — mirrors MeasureOverlay."""
    from fermiviewer.calc.export import measure_annotations

    m = [{"kind": "profile", "width": 4,
          "pts": [{"x": 0.0, "y": 0.5}, {"x": 1.0, "y": 0.5}]}]
    annos = measure_annotations(m, 12, 16, None, "px", 2)
    kinds = [a.kind for a in annos]
    assert kinds == ["outline", "profile"]
    # horizontal centerline (0,6)→(16,6), width 4 → corners y = 6±2,
    # everything ×2 output scale
    assert annos[0].points == ((0.0, 16.0), (32.0, 16.0),
                               (32.0, 8.0), (0.0, 8.0))
    assert annos[0].label == ""
    # plain profiles (no width) bake no outline
    plain = measure_annotations(MEASURES[1:2], 12, 16, None, "px", 2)
    assert [a.kind for a in plain] == ["profile"]


def test_box_profile_outline_svg(client, img_id) -> None:
    """SVG export contains the box polygon for width-carrying profiles."""
    body = {
        "image_id": img_id, "format": "svg", "scale": 2,
        "include": ["measurements"],
        "measures": [{"kind": "profile", "width": 3,
                      "pts": [{"x": 0.2, "y": 0.5}, {"x": 0.8, "y": 0.5}],
                      "endSymbol": "none"}],
    }
    svg = client.post("/api/export", json=body).content.decode()
    assert svg.count("<polygon") == 1


def test_export_tilt_baking(client, img_id) -> None:
    """#34 API: tilt params change the baked label bytes; 0 is a no-op."""
    body = {
        "image_id": img_id,
        "format": "png",
        "scale": 4,
        "include": ["measurements"],
        "measures": MEASURES[:1],
    }
    plain = client.post("/api/export", json=body).content
    zero = client.post(
        "/api/export", json={**body, "tilt_angle_deg": 0.0},
    ).content
    assert zero == plain
    tilted = client.post(
        "/api/export",
        json={**body, "tilt_angle_deg": 30.0, "tilt_axis": "X"},
    ).content
    assert tilted != plain


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


def test_end_symbol_baking_png(client, img_id) -> None:
    """Endpoint glyphs differ from no-glyph for each symbol kind (PIL path)."""
    base_body = {
        "image_id": img_id, "format": "png", "scale": 4,
        "include": ["measurements"],
        "measures": [{"kind": "distance",
                      "pts": [{"x": 0.2, "y": 0.5}, {"x": 0.8, "y": 0.5}]}],
    }
    no_glyph = np.asarray(Image.open(io.BytesIO(
        client.post("/api/export", json={**base_body}).content
    )))
    for sym in ("bar", "circle", "square", "cross"):
        body = dict(base_body)
        body["measures"] = [{"kind": "distance",
                              "pts": [{"x": 0.2, "y": 0.5},
                                      {"x": 0.8, "y": 0.5}],
                              "endSymbol": sym}]
        arr = np.asarray(Image.open(io.BytesIO(
            client.post("/api/export", json=body).content
        )))
        # with a glyph the images must differ from none
        assert (arr != no_glyph).any(), f"glyph '{sym}' produced no difference"


def test_end_symbol_baking_svg(client, img_id) -> None:
    """Endpoint glyphs appear in SVG output for each symbol kind."""
    body = {
        "image_id": img_id, "format": "svg", "scale": 2,
        "include": ["measurements"],
        "measures": [{"kind": "distance",
                      "pts": [{"x": 0.2, "y": 0.5}, {"x": 0.8, "y": 0.5}],
                      "endSymbol": "circle"}],
    }
    svg = client.post("/api/export", json=body).content.decode()
    # endpoint circles added (there is already a distance <line>)
    assert svg.count("<circle") == 2  # one per endpoint

    body["measures"][0]["endSymbol"] = "square"  # type: ignore[index]
    svg = client.post("/api/export", json=body).content.decode()
    # two endpoint rects — in addition to the distance line
    assert svg.count("<rect") == 2

    body["measures"][0]["endSymbol"] = "cross"  # type: ignore[index]
    svg = client.post("/api/export", json=body).content.decode()
    # 2 endpoints × 2 lines per cross = 4 lines total (distance line + 4 cross lines)
    # (distance line also counts as <line>): 1 + 2*2 = 5
    assert svg.count("<line") == 5

    body["measures"][0]["endSymbol"] = "bar"  # type: ignore[index]
    svg = client.post("/api/export", json=body).content.decode()
    # bar = 1 perpendicular tick per endpoint: distance line + 2 = 3
    assert svg.count("<line") == 3
    # the measure is horizontal → bar ticks are vertical (x1 == x2)
    import re
    ticks = re.findall(
        r'<line x1="([\d.]+)" y1="[\d.]+" x2="([\d.]+)" y2="[\d.]+"', svg,
    )
    vertical = [t for t in ticks if t[0] == t[1]]
    assert len(vertical) == 2


def test_end_symbol_none_unchanged(client, img_id) -> None:
    """endSymbol=none produces the same bytes as omitting the field."""
    base_measures = [{"kind": "distance",
                      "pts": [{"x": 0.1, "y": 0.3}, {"x": 0.9, "y": 0.7}]}]
    none_measures = [{"kind": "distance",
                      "pts": [{"x": 0.1, "y": 0.3}, {"x": 0.9, "y": 0.7}],
                      "endSymbol": "none"}]
    common = {"image_id": img_id, "format": "png", "scale": 2,
              "include": ["measurements"]}
    r_base = client.post("/api/export", json={**common, "measures": base_measures})
    r_none = client.post("/api/export", json={**common, "measures": none_measures})
    assert r_base.content == r_none.content


def test_batch_export_zip(client, tmp_path) -> None:
    import zipfile

    ids = [_open_frame(client, tmp_path, f"z{i}.dm4", 0.3 * i)
           for i in range(3)]
    r = client.post("/api/export/batch", json={
        "image_ids": ids, "format": "png", "scale": 2,
    })
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert len(names) == 3
    assert all(n.endswith(".png") for n in names)
    png = Image.open(io.BytesIO(zf.read(names[0])))
    assert png.size == (32, 24)
    assert client.post("/api/export/batch", json={
        "image_ids": [], "format": "png",
    }).status_code == 422


def test_rename_and_open_raw(client, tmp_path) -> None:
    ids = [_open_frame(client, tmp_path, "r0.dm4", 0.0)]
    r = client.post(f"/api/image/{ids[0]}/rename", json={"name": "renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"
    assert client.post(f"/api/image/{ids[0]}/rename",
                       json={"name": "  "}).status_code == 422

    # headerless RAW round-trip
    arr = (np.arange(48, dtype="<u2") * 100).reshape(6, 8)
    raw = tmp_path / "img.raw"
    raw.write_bytes(arr.tobytes())
    r = client.post("/api/session/open-raw", json={
        "path": str(raw), "width": 8, "height": 6, "bit_depth": 16,
    })
    assert r.status_code == 200
    meta = r.json()
    assert meta["shape"] == [6, 8]
    np.testing.assert_array_equal(store.get(meta["id"]).data, arr)
    assert client.post("/api/session/open-raw", json={
        "path": str(raw), "width": 8, "height": 6, "bit_depth": 12,
    }).status_code == 422


def test_figure_panel(client, tmp_path) -> None:
    ids = [_open_frame(client, tmp_path, f"p{i}.dm4", 0.2 * i)
           for i in range(3)]
    r = client.post("/api/export/figure", json={
        "image_ids": ids, "cols": 2, "gap": 4, "scale": 1,
    })
    assert r.status_code == 200
    fig = Image.open(io.BytesIO(r.content))
    # 2 cols × 2 rows of 16×12 panels + one 4px gap each way
    assert fig.size == (16 * 2 + 4, 12 * 2 + 4)
    assert client.post("/api/export/figure", json={
        "image_ids": ids[:1],
    }).status_code == 422


def test_scale_bar_label_subunit() -> None:
    """Bar labels step down to Å below 1 nm (EM convention — mirrors
    fmtSub in Stage.tsx; keep both sides in sync)."""
    from fermiviewer.calc.export import _bar_label

    assert _bar_label(20, "nm") == "20 nm"
    assert _bar_label(0.5, "nm") == "5 Å"          # not "500 pm"
    assert _bar_label(0.005, "nm") == "5 pm"       # below 1 Å
    assert _bar_label(0.5, "µm") == "500 nm"
    assert _bar_label(0.0005, "µm") == "5 Å"       # µm → Å step-down
    assert _bar_label(3, "px") == "3 px"           # unknown unit unchanged


def test_scale_bar_detection() -> None:
    from fermiviewer.calc.scalebar_detect import detect_scale_bar

    # realistic banner strip: mid-gray background (so it normalizes
    # away from both thresholds), a small dark speck, a white bar
    img = np.full((100, 200), 120.0)
    img[20:60, 30:170] = 160.0                 # specimen texture
    img[94:96, 10:14] = 0.0                    # dark speck (< 20 px run)
    img[92:96, 60:121] = 255.0                 # white bar, 61 px wide
    r = detect_scale_bar(img)
    assert r.found
    assert r.bar_len == 61
    assert (r.bar_x1, r.bar_x2) == (60 + 1, 120 + 1)   # 1-based
    assert r.bar_y >= 90
    # uniform strip → graceful not-found
    flat = np.zeros((100, 200))
    assert not detect_scale_bar(flat).found
    # tiny image guard
    assert not detect_scale_bar(np.zeros((5, 5))).found


def test_scale_bar_detect_endpoint(client, img_id) -> None:
    r = client.post("/api/calibration/detect-bar",
                    json={"image_id": img_id})
    assert r.status_code == 200
    assert "found" in r.json()


# ── item #48: export scale-bar font size ─────────────────────────────

def test_scale_bar_font_size_changes_pixels(client, img_id) -> None:
    """Exports at different font sizes produce different pixel output."""
    common = {
        "image_id": img_id,
        "format": "png",
        "scale": 4,
        "include": ["scale_bar"],
    }
    small = np.asarray(Image.open(io.BytesIO(
        client.post("/api/export", json={**common, "scale_bar_font_size": 12}).content
    )))
    large = np.asarray(Image.open(io.BytesIO(
        client.post("/api/export", json={**common, "scale_bar_font_size": 32}).content
    )))
    # Different font sizes must produce visibly different images
    assert (small != large).any(), "font_size 12 vs 32 produced identical output"


def test_scale_bar_font_default_unchanged(client, img_id) -> None:
    """Omitting scale_bar_font_size and sending null both produce the
    same bytes as explicitly sending the default size 20 — backward
    compatibility is preserved."""
    common = {
        "image_id": img_id,
        "format": "png",
        "scale": 2,
        "include": ["scale_bar"],
    }
    omitted = client.post("/api/export", json=common).content
    null_sent = client.post("/api/export", json={**common,
                                                  "scale_bar_font_size": None}).content
    explicit_20 = client.post("/api/export", json={**common,
                                                    "scale_bar_font_size": 20}).content
    assert omitted == null_sent
    assert omitted == explicit_20


def test_scale_bar_font_size_bounds(client, img_id) -> None:
    """Non-positive or absurd font sizes are rejected at validation (422),
    never reaching the PIL/SVG label placement math."""
    common = {
        "image_id": img_id,
        "format": "png",
        "scale": 1,
        "include": ["scale_bar"],
    }
    for bad in (-5, 0, 201):
        r = client.post("/api/export", json={**common,
                                             "scale_bar_font_size": bad})
        assert r.status_code == 422, f"font_size={bad} accepted"


def test_scale_bar_font_size_svg(client, img_id) -> None:
    """SVG export carries the font-size attribute in the scale-bar label."""
    common = {
        "image_id": img_id,
        "format": "svg",
        "scale": 2,
        "include": ["scale_bar"],
    }
    svg_small = client.post("/api/export", json={**common,
                                                  "scale_bar_font_size": 12}).content.decode()
    svg_large = client.post("/api/export", json={**common,
                                                  "scale_bar_font_size": 32}).content.decode()
    assert 'font-size="24"' in svg_small   # 12 × scale 2
    assert 'font-size="64"' in svg_large   # 32 × scale 2


def test_scale_bar_font_load_helper() -> None:
    """_load_font returns a usable font at a given size (or None on error)."""
    from fermiviewer.routes._export_render import _load_font

    font = _load_font(20)
    # Either we got a real font or None (both are acceptable)
    if font is not None:
        from PIL.ImageFont import FreeTypeFont
        assert isinstance(font, FreeTypeFont)
        # Text bbox should be larger for bigger fonts
        bbox_small = _load_font(12)
        bbox_large = _load_font(32)
        if bbox_small is not None and bbox_large is not None:
            w_small = bbox_small.getbbox("20 nm")[2]
            w_large = bbox_large.getbbox("20 nm")[2]
            assert w_large > w_small, "larger font should produce wider text"


def test_vendored_font_path() -> None:
    """Vendored TTF exists at the expected path (catches packaging regressions)."""
    from fermiviewer.assets.fonts import jetbrains_mono_regular

    path = jetbrains_mono_regular()
    assert path.exists(), f"JetBrainsMono-Regular.ttf missing at {path}"
    assert path.suffix == ".ttf"
    ofl = path.parent / "OFL.txt"
    assert ofl.exists(), "OFL.txt must ship alongside the TTF"
