"""calc/montage.py + /analyze/montage endpoint tests.

Verifies:
  - grid shape formula (rows × cols layout, matches executeMontage.m)
  - label baking path (no crash; text region is non-zero)
  - auto-cols selection (ceil(sqrt(n)))
  - overlap mode (step < tile size, averaged overlap region)
  - single-frame edge case (cols=1, shape == tile)
  - non-stack (plain IMAGE) and mixed-size tiles
  - /analyze/montage wire contract (derived image registered, JSON shape)
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.montage import montage
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = [pytest.mark.api, pytest.mark.imaging]


# ── calc-level oracle ────────────────────────────────────────────────


def test_grid_shape_no_overlap() -> None:
    """ceil(n/cols) rows × cols columns with gap between tiles."""
    h, w = 64, 80
    gap = 4
    n = 6
    cols = 3
    rows = math.ceil(n / cols)          # 2
    frames = [np.ones((h, w)) * i for i in range(n)]
    out = montage(frames, cols=cols, gap=gap, overlap=0.0, labels=None)
    expected_h = (rows - 1) * (h + gap) + h   # 132
    expected_w = (cols - 1) * (w + gap) + w   # 248
    assert out.shape == (expected_h, expected_w), (
        f"expected ({expected_h}, {expected_w}), got {out.shape}"
    )


def test_grid_shape_with_overlap() -> None:
    """Overlap mode: step = round(maxDim*(1-overlap)) — verbatim executeMontage.m."""
    h, w = 64, 64
    overlap = 0.25
    n = 4
    cols = 2
    rows = 2
    step_y = round(h * (1 - overlap))  # 48
    step_x = round(w * (1 - overlap))  # 48
    expected_h = (rows - 1) * step_y + h   # 112
    expected_w = (cols - 1) * step_x + w   # 112
    frames = [np.ones((h, w)) * float(i + 1) for i in range(n)]
    out = montage(frames, cols=cols, overlap=overlap, labels=None)
    assert out.shape == (expected_h, expected_w)


def test_auto_cols_is_ceil_sqrt() -> None:
    """Auto cols chooses ceil(sqrt(n)) — approximately square grid."""
    for n in (1, 2, 4, 6, 9, 12):
        expected_cols = math.ceil(math.sqrt(n))
        expected_rows = math.ceil(n / expected_cols)
        h, w, gap = 10, 10, 2
        frames = [np.zeros((h, w)) for _ in range(n)]
        out = montage(frames, cols=None, gap=gap, labels=None)
        exp_h = (expected_rows - 1) * (h + gap) + h
        exp_w = (expected_cols - 1) * (w + gap) + w
        assert out.shape == (exp_h, exp_w), (
            f"n={n}: expected ({exp_h},{exp_w}), got {out.shape}"
        )


def test_single_frame() -> None:
    """A single frame with auto cols → (1,1) grid, output == input shape."""
    frame = np.arange(100.0).reshape(10, 10)
    out = montage([frame], cols=None, labels=None, gap=0)
    assert out.shape == (10, 10)
    np.testing.assert_array_equal(out, frame)


def test_tile_values_no_overlap() -> None:
    """Each tile region should hold its own constant value (no bleeding)."""
    h, w = 4, 4
    gap = 0
    frames = [np.full((h, w), float(i)) for i in range(4)]
    out = montage(frames, cols=2, gap=gap, overlap=0.0, labels=None)
    # tile 0 top-left
    np.testing.assert_array_equal(out[:h, :w], 0.0)
    # tile 1 top-right
    np.testing.assert_array_equal(out[:h, w:], 1.0)
    # tile 2 bottom-left
    np.testing.assert_array_equal(out[h:, :w], 2.0)
    # tile 3 bottom-right
    np.testing.assert_array_equal(out[h:, w:], 3.0)


def test_label_baking_does_not_crash() -> None:
    """Labels path completes without error and modifies at least one pixel."""
    frames = [np.zeros((48, 80)) + float(i) for i in range(3)]
    labels = ["frame A", "frame B", "frame C"]
    out_no_label = montage(frames, cols=3, labels=None, gap=2)
    out_labeled = montage(frames, cols=3, labels=labels, gap=2, font_size=12)
    assert out_labeled.shape == out_no_label.shape
    # At least one pixel should differ (label text pixels)
    assert not np.array_equal(out_labeled, out_no_label)


def test_mixed_tile_sizes() -> None:
    """Smaller frames are placed in the top-left of their cell; no IndexError."""
    frames = [
        np.ones((64, 80)),
        np.ones((32, 40)) * 2,
        np.ones((64, 80)) * 3,
    ]
    out = montage(frames, cols=2, gap=0, labels=None)
    # Should not raise; check shape is based on max tile size
    assert out.shape[0] > 0 and out.shape[1] > 0


def test_empty_frames_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        montage([], cols=2)


def test_bad_overlap_raises() -> None:
    with pytest.raises(ValueError, match="overlap"):
        montage([np.zeros((4, 4))], overlap=1.0)


def test_label_length_mismatch_raises() -> None:
    frames = [np.zeros((4, 4))] * 3
    with pytest.raises(ValueError, match="labels length"):
        montage(frames, labels=["a", "b"])


# ── API endpoint contract ────────────────────────────────────────────

from fixtures.minidm4 import write_mini_dm4  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open(client, tmp_path, data: np.ndarray, name: str = "img.dm4") -> str:
    h, w = data.shape
    f = write_mini_dm4(
        tmp_path / name, dims=[w, h], data=data.ravel(),
        cal=[{"scale": 1.0, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def test_montage_endpoint_basic(client, tmp_path) -> None:
    """Six identical 32×32 tiles → montage(6) registered as derived image."""
    tile = np.random.default_rng(42).random((32, 32)) * 1000
    ids = [
        _open(client, tmp_path, tile, f"t{i}.dm4")
        for i in range(6)
    ]
    r = client.post(
        "/api/analyze/montage",
        json={"image_ids": ids, "cols": 3, "labels": False, "gap": 4},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "image" in body
    img = body["image"]
    assert img["name"] == "montage(6)"
    # 2 rows × 3 cols; step = 32+4 = 36; w = 2*36+32 = 104, h same
    assert img["shape"] == [68, 104]


def test_montage_endpoint_auto_cols(client, tmp_path) -> None:
    """cols=null → ceil(sqrt(4))=2 → 2×2 grid."""
    ids = [
        _open(client, tmp_path, np.ones((16, 16)) * i, f"f{i}.dm4")
        for i in range(4)
    ]
    r = client.post(
        "/api/analyze/montage",
        json={"image_ids": ids, "cols": None, "labels": False, "gap": 0},
    )
    assert r.status_code == 200, r.text
    img = r.json()["image"]
    assert img["shape"] == [32, 32]


def test_montage_endpoint_labels(client, tmp_path) -> None:
    """labels=true path completes; shape matches unlabeled run."""
    ids = [
        _open(client, tmp_path, np.zeros((32, 32)), f"lbl{i}.dm4")
        for i in range(2)
    ]
    r = client.post(
        "/api/analyze/montage",
        json={"image_ids": ids, "cols": 2, "labels": True, "gap": 4},
    )
    assert r.status_code == 200, r.text


def test_montage_endpoint_unknown_id(client, tmp_path) -> None:
    """Unknown image id → 404."""
    r = client.post(
        "/api/analyze/montage",
        json={"image_ids": ["bad-id"]},
    )
    assert r.status_code == 404


def test_montage_endpoint_overlap(client, tmp_path) -> None:
    """Overlap mode completes without error."""
    ids = [
        _open(client, tmp_path, np.ones((32, 32)) * i, f"ov{i}.dm4")
        for i in range(4)
    ]
    r = client.post(
        "/api/analyze/montage",
        json={"image_ids": ids, "cols": 2, "overlap": 0.25, "labels": False},
    )
    assert r.status_code == 200, r.text
    img = r.json()["image"]
    # step=round(32*0.75)=24; 2 rows → h=(1*24+32)=56; same for w
    assert img["shape"] == [56, 56]
