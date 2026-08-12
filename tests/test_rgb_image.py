"""DataKind.RGB_IMAGE — the data-model half of ADR 0003.

Covers the contract (shape/dtype/axes validation), the raster boundary's
luma collapse, ImageMeta classification, the spectral gates, and the `.fvp`
round-trip with a colour thumbnail. The registration endpoint and serving
paths have their own tests.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fermiviewer.calc.raster import raster_of
from fermiviewer.datastruct import SPECTRAL_KINDS, AxisCal, DataKind, DataStruct
from fermiviewer.io.project_file import load_project, save_project
from fermiviewer.models import ImageMeta
from fermiviewer.server import create_app
from fermiviewer.session import store


def _rgb(h: int = 3, w: int = 4) -> np.ndarray:
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[..., 0] = 200  # red-dominant so channel mixups are visible
    rgb[..., 1] = 50
    rgb[..., 2] = 10
    return rgb


def _rgb_struct() -> DataStruct:
    return DataStruct(
        data=_rgb(),
        kind=DataKind.RGB_IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        metadata={"parser": "derived", "source": "composite"},
    )


# ── contract ─────────────────────────────────────────────────────────


def test_rgb_image_constructs_with_two_spatial_axes() -> None:
    ds = _rgb_struct()
    assert ds.data.shape == (3, 4, 3)
    assert ds.pixel_cal.calibrated
    assert ds.pixel_size == pytest.approx(0.5)


def test_rgb_image_rejects_wrong_shapes_and_dtypes() -> None:
    axes2 = (AxisCal(), AxisCal())
    with pytest.raises(ValueError, match=r"\[H, W, 3\]"):
        DataStruct(np.zeros((3, 4, 4), dtype=np.uint8), DataKind.RGB_IMAGE, axes2)
    with pytest.raises(ValueError, match="uint8"):
        DataStruct(np.zeros((3, 4, 3), dtype=np.float64), DataKind.RGB_IMAGE, axes2)
    with pytest.raises(ValueError, match="3D"):
        DataStruct(np.zeros((3, 4), dtype=np.uint8), DataKind.RGB_IMAGE, axes2)
    with pytest.raises(ValueError, match="axes count"):
        DataStruct(
            np.zeros((3, 4, 3), dtype=np.uint8),
            DataKind.RGB_IMAGE,
            (AxisCal(), AxisCal(), AxisCal()),
        )


def test_rgb_image_has_no_energy_axis() -> None:
    ds = _rgb_struct()
    assert ds.kind not in SPECTRAL_KINDS
    with pytest.raises(ValueError, match="no energy axis"):
        _ = ds.energy_cal
    with pytest.raises(ValueError, match="no energy axis"):
        _ = ds.n_channels
    with pytest.raises(ValueError, match="no spectrum"):
        ds.sum_spectrum()


# ── raster boundary ──────────────────────────────────────────────────


def test_raster_of_collapses_rgb_to_bt601_luma() -> None:
    """Pure-channel pixels pin the exact weights: a mutation to channel-mean
    (the io/images.py load rule) or swapped coefficients fails here."""
    rgb = np.zeros((1, 3, 3), dtype=np.uint8)
    rgb[0, 0, 0] = 255  # pure R
    rgb[0, 1, 1] = 255  # pure G
    rgb[0, 2, 2] = 255  # pure B
    ds = DataStruct(rgb, DataKind.RGB_IMAGE, (AxisCal(), AxisCal()))
    luma = raster_of(ds)
    assert luma.shape == (1, 3)
    assert luma[0, 0] == pytest.approx(0.299 * 255)
    assert luma[0, 1] == pytest.approx(0.587 * 255)
    assert luma[0, 2] == pytest.approx(0.114 * 255)


# ── wire model ───────────────────────────────────────────────────────


def test_image_meta_classifies_rgb_as_non_spectral() -> None:
    meta = ImageMeta.from_datastruct("abc123", "composite.png", _rgb_struct())
    assert meta.kind is DataKind.RGB_IMAGE
    assert meta.shape == [3, 4, 3]
    assert meta.n_channels is None  # channels are colour, not energy
    assert meta.energy_first is None and meta.energy_last is None
    assert meta.pixel_size == pytest.approx(0.5)
    assert meta.content_rows is None  # composites carry no vendor databar


def test_spectral_endpoints_reject_rgb_with_400() -> None:
    client = TestClient(create_app())
    img_id = store.add_derived(_rgb_struct(), "composite", "parent000000")
    try:
        r = client.get(f"/api/image/{img_id}/spectrum")
        assert r.status_code == 400
        r = client.post(
            "/api/eels/auto-assign", json={"image_id": img_id}
        )
        assert r.status_code == 400
    finally:
        store.close(img_id)


# ── registration + serving ───────────────────────────────────────────


def _parent_cube() -> DataStruct:
    cube = np.random.default_rng(7).integers(
        0, 1000, size=(3, 4, 16)
    ).astype(np.uint16)
    return DataStruct(
        data=cube,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(0.5, units="nm"),
            AxisCal(0.5, units="nm"),
            AxisCal(10.0, units="eV"),
        ),
    )


def _register_composite(client: TestClient, parent_id: str, rgb: np.ndarray):
    import base64

    return client.post(
        "/api/composite/register",
        json={
            "parent_id": parent_id,
            "name": "Composite — Fe, Cu",
            "width": rgb.shape[1],
            "height": rgb.shape[0],
            "pixels_b64": base64.b64encode(rgb.tobytes()).decode(),
            "recipe": {"channels": [{"symbol": "Fe"}, {"symbol": "Cu"}]},
        },
    )


def test_composite_registers_and_serves_colour() -> None:
    client = TestClient(create_app())
    parent_id = store.add_parsed(_parent_cube(), "cube.hspy")
    ids = [parent_id]
    try:
        rgb = _rgb()
        r = _register_composite(client, parent_id, rgb)
        assert r.status_code == 200
        meta = r.json()
        assert meta["kind"] == "rgb_image"
        ids.append(meta["id"])
        # inherited spatial calibration → the scale bar works
        assert meta["pixel_size"] == pytest.approx(0.5)

        # /render is a colour PNG of exactly the posted pixels
        png = client.get(f"/api/image/{meta['id']}/render")
        assert png.status_code == 200
        im = Image.open(io.BytesIO(png.content))
        assert im.mode == "RGB"
        np.testing.assert_array_equal(np.asarray(im), rgb)

        # /rgb8 round-trips the raw bytes
        raw = client.get(f"/api/image/{meta['id']}/rgb8")
        assert raw.status_code == 200
        assert raw.headers["X-Shape"] == f"{rgb.shape[0]},{rgb.shape[1]},3"
        assert raw.content == rgb.tobytes()

        # the scalar/tile paths refuse rather than silently de-colour
        assert client.get(f"/api/image/{meta['id']}/data16").status_code == 400
        assert client.get(f"/api/image/{meta['id']}/tile-info").status_code == 400
        assert client.get(f"/api/image/{meta['id']}/tile").status_code == 400

        # histogram is DELIBERATELY the luma histogram (raster boundary):
        # harmless, and better than a 500 from an overlooked caller
        assert client.get(f"/api/image/{meta['id']}/histogram").status_code == 200
    finally:
        for img_id in ids:
            store.close(img_id)


def test_composite_register_rejects_bad_payloads() -> None:
    import base64

    client = TestClient(create_app())
    parent_id = store.add_parsed(_parent_cube(), "cube.hspy")
    spectrum_id = store.add_parsed(
        DataStruct(
            np.arange(8, dtype=np.float64),
            DataKind.SPECTRUM,
            (AxisCal(0.01, units="keV"),),
        ),
        "spec.msa",
    )
    try:
        good = base64.b64encode(_rgb().tobytes()).decode()
        base = {
            "parent_id": parent_id,
            "name": "c",
            "width": 4,
            "height": 3,
            "pixels_b64": good,
        }
        r = client.post(
            "/api/composite/register", json={**base, "parent_id": "nope"}
        )
        assert r.status_code == 404
        r = client.post(
            "/api/composite/register", json={**base, "parent_id": spectrum_id}
        )
        assert r.status_code == 400
        # dims that disagree with the parent's scan are a client bug
        r = client.post(
            "/api/composite/register", json={**base, "width": 5, "height": 3}
        )
        assert r.status_code == 422
        r = client.post(
            "/api/composite/register", json={**base, "pixels_b64": "not-base64!!"}
        )
        assert r.status_code == 422
        short = base64.b64encode(b"\x00" * 5).decode()
        r = client.post(
            "/api/composite/register", json={**base, "pixels_b64": short}
        )
        assert r.status_code == 422
    finally:
        store.close(parent_id)
        store.close(spectrum_id)


# ── persistence ──────────────────────────────────────────────────────


def test_rgb_image_round_trips_through_fvp(tmp_path: Path) -> None:
    ds = _rgb_struct()
    path = save_project(tmp_path / "study.fvp", [("rgb1", "composite.png", ds)])
    loaded = load_project(path)
    (img,) = loaded.images
    out = img.datastruct
    assert out.kind is DataKind.RGB_IMAGE
    assert out.data.dtype == np.uint8
    np.testing.assert_array_equal(out.data, ds.data)
    assert len(out.axes) == 2
    assert out.axes[0].units == "nm"


def test_rgb_thumbnail_is_colour(tmp_path: Path) -> None:
    path = save_project(tmp_path / "study.fvp", [("rgb1", "composite.png", _rgb_struct())])
    with zipfile.ZipFile(path) as zf:
        png = zf.read("thumbs/rgb1.png")
    im = Image.open(io.BytesIO(png))
    assert im.mode == "RGB"
    # red-dominant input must stay red-dominant — a luma-collapsed thumbnail
    # would come back gray (r == g == b)
    r, g, b = im.getpixel((0, 0))
    assert r > g > b
