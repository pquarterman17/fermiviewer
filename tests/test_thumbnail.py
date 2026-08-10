"""calc/thumbnail.py — pure PNG rendering for `.fvp` `thumbs/` entries
(ADR 0002 §2, plan item 37).
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from fermiviewer.calc.render import to_display
from fermiviewer.calc.thumbnail import (
    THUMBNAIL_MAX_EDGE,
    raster_for_thumbnail,
    render_thumbnail_png,
)
from fermiviewer.datastruct import DataKind


def _decode(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png))


def test_downsamples_to_the_max_edge_preserving_aspect_ratio() -> None:
    data = np.random.default_rng(0).integers(0, 4096, size=(400, 800)).astype(np.uint16)
    png = render_thumbnail_png(data, DataKind.IMAGE)
    assert png is not None

    img = _decode(png)
    assert img.mode == "L"
    assert max(img.width, img.height) == THUMBNAIL_MAX_EDGE
    assert img.width == THUMBNAIL_MAX_EDGE  # the longer edge (800 -> 256)
    assert img.height == pytest.approx(128, abs=1)  # 400 * (256/800)


def test_never_upsamples_a_small_image() -> None:
    data = np.full((10, 20), 5, dtype=np.uint8)
    png = render_thumbnail_png(data, DataKind.IMAGE)
    assert png is not None

    img = _decode(png)
    assert (img.width, img.height) == (20, 10)


def test_uses_the_same_windowing_as_the_render_route() -> None:
    """No second contrast rule: this is `calc.render.to_display`'s own auto
    full-range window, just resized and PNG-encoded."""
    data = np.array([[0, 1000], [2000, 3000]], dtype=np.float32)
    png = render_thumbnail_png(data, DataKind.IMAGE)
    assert png is not None

    img = _decode(png)
    expected = to_display(data)
    np.testing.assert_array_equal(np.asarray(img), expected)


def test_spectrum_image_sums_over_the_energy_axis() -> None:
    cube = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
    raster = raster_for_thumbnail(cube, DataKind.SPECTRUM_IMAGE)
    assert raster is not None
    np.testing.assert_array_equal(raster, cube.sum(axis=2))

    png = render_thumbnail_png(cube, DataKind.SPECTRUM_IMAGE)
    assert png is not None
    img = _decode(png)
    assert (img.width, img.height) == (3, 2)


def test_a_1d_spectrum_has_no_raster_and_gets_no_thumbnail() -> None:
    spectrum = np.arange(10, dtype=np.float32)
    assert raster_for_thumbnail(spectrum, DataKind.SPECTRUM) is None
    assert render_thumbnail_png(spectrum, DataKind.SPECTRUM) is None


def test_an_empty_array_gets_no_thumbnail() -> None:
    assert render_thumbnail_png(np.zeros((0, 0), dtype=np.uint8), DataKind.IMAGE) is None
