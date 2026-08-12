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
