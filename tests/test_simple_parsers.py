"""SER / MRC / TIFF / image / RAW parser tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.images import load_image, load_raw
from fermiviewer.io.registry import load_auto

pytestmark = pytest.mark.parser

REL = 1e-9


# ── golden corpus ────────────────────────────────────────────────────

@pytest.mark.golden
@pytest.mark.parametrize("ext", [".mrc", ".ser", ".tif"])
def test_committed_corpus_matches_matlab(golden, ml_datasets: Path, ext: str) -> None:
    entries = [
        e for e in golden("parsers_committed")["images"]
        if e["file"].lower().endswith(ext)
    ]
    assert entries, f"no {ext} entries in golden"
    for e in entries:
        ds = load_auto(ml_datasets / "Microscopy" / e["file"])
        assert ds.kind is DataKind.IMAGE, e["file"]
        assert ds.data.shape == (e["height"], e["width"]), e["file"]
        assert ds.metadata["bit_depth"] == e["bitDepth"], e["file"]
        px = np.asarray(ds.data, dtype=np.float64)
        assert px.sum() == pytest.approx(e["pixSum"], rel=REL), e["file"]
        assert px.min() == e["pixMin"] and px.max() == e["pixMax"], e["file"]
        if isinstance(e.get("pixelSize"), (int, float)):
            assert ds.pixel_size == pytest.approx(e["pixelSize"], rel=1e-6), e["file"]
            assert ds.pixel_unit == e["pixelUnit"], e["file"]


# ── synthetic round-trips ────────────────────────────────────────────

def test_raw_roundtrip(tmp_path) -> None:
    w, h = 7, 5
    px = (np.arange(w * h, dtype=np.uint16) * 3).reshape(h, w)
    f = tmp_path / "img.raw"
    f.write_bytes(px.astype("<u2").tobytes())

    ds = load_raw(f, width=w, height=h, bit_depth=16)
    np.testing.assert_array_equal(ds.data, px)

    # big-endian variant
    f2 = tmp_path / "be.raw"
    f2.write_bytes(px.astype(">u2").tobytes())
    np.testing.assert_array_equal(
        load_raw(f2, width=w, height=h, bit_depth=16, byte_order="big").data, px
    )

    # header skip
    f3 = tmp_path / "hdr.raw"
    f3.write_bytes(b"\xee" * 32 + px.astype("<u2").tobytes())
    np.testing.assert_array_equal(
        load_raw(f3, width=w, height=h, bit_depth=16, header_bytes=32).data, px
    )


def test_raw_geometry_errors(tmp_path) -> None:
    f = tmp_path / "small.raw"
    f.write_bytes(b"\x00" * 10)
    with pytest.raises(ValueError, match="check geometry"):
        load_raw(f, width=100, height=100)
    with pytest.raises(ValueError, match="bit_depth"):
        load_raw(f, width=1, height=1, bit_depth=24)


def test_png_rgb_collapses_to_gray(tmp_path) -> None:
    from PIL import Image

    rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    rgb[..., 0] = 30   # R
    rgb[..., 1] = 60   # G
    rgb[..., 2] = 90   # B
    f = tmp_path / "c.png"
    Image.fromarray(rgb).save(f)

    ds = load_image(f)
    assert ds.kind is DataKind.IMAGE
    assert ds.metadata["was_rgb"] is True
    np.testing.assert_allclose(ds.data, 60.0)   # channel mean


def test_empty_file_guards(tmp_path) -> None:
    for ext in (".ser", ".mrc", ".dm4", ".bcf"):
        f = tmp_path / f"empty{ext}"
        f.write_bytes(b"")
        with pytest.raises(ValueError):
            load_auto(f)


def test_palette_image_uses_colors_not_indices(tmp_path) -> None:
    # A palette ("P"-mode) PNG/GIF stores LUT indices; np.asarray yields
    # those indices, not colours, so the parser must convert to RGB first.
    from PIL import Image

    im = Image.new("P", (4, 6))
    pal = [0] * 768
    pal[3:6] = [255, 0, 0]  # palette index 1 -> pure red
    im.putpalette(pal)
    im.putdata([1] * 24)  # every pixel = index 1
    f = tmp_path / "p.png"
    im.save(f)

    ds = load_image(f)
    assert ds.metadata["was_rgb"] is True
    # channel mean of (255, 0, 0) = 85 — NOT the raw palette index 1
    np.testing.assert_allclose(ds.data, 85.0)
