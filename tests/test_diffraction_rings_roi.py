"""Matched-ring, typed-d, and analysis-ROI tests for the diffraction subsystem.

Tests cover:
  - calc.diffraction.d_spacing_to_radius (FFT + TEM camera modes)
  - calc.diffraction.apply_roi (rect + circle)
  - /diffraction/index response now includes matched_d, ref_d, center, measured_r
  - /diffraction/detect with a rect ROI shifts spots back into full-image coords
  - /diffraction/index with a rect ROI re-centres correctly
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.diffraction import (
    apply_roi,
    d_spacing_to_radius,
    find_spots,
    index_spots,
)
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = [pytest.mark.diffraction, pytest.mark.api]


# ════════════════════════════════════════════════════════════════════
# d_spacing_to_radius — pure calc
# ════════════════════════════════════════════════════════════════════


class TestDSpacingToRadius:
    """Port of drawRingOverlay.m / drawMatchedRings.m physics."""

    def test_fft_mode_basic(self) -> None:
        # d = W * px / R  →  R = W * px / d
        # W=512, px=0.0195 Å/px, d=2.338 Å  → R = 512*0.0195/2.338 ≈ 4.273 px
        r_px = d_spacing_to_radius(2.338, (512, 512), pixel_size=0.0195)
        assert r_px == pytest.approx(512 * 0.0195 / 2.338, rel=1e-9)

    def test_fft_mode_round_trip(self) -> None:
        # Given R → d = W*px/R, inverse gives same R back.
        img_w, px = 256, 0.05
        for d in (1.0, 2.338, 3.14, 5.0):
            r_px = d_spacing_to_radius(d, (256, 256), pixel_size=px)
            assert d == pytest.approx(img_w * px / r_px, rel=1e-9)

    def test_invalid_d_returns_nan(self) -> None:
        assert math.isnan(d_spacing_to_radius(0.0, (512, 512), pixel_size=0.05))
        assert math.isnan(d_spacing_to_radius(-1.0, (512, 512), pixel_size=0.05))

    def test_camera_mode_verbatim_draw_ring_overlay(self) -> None:
        """Verbatim port of drawRingOverlay.m formula:
            sin theta = lambda / (2 d);  R = L * tan(2 arcsin(sin theta)) / px
        Using 200 kV, d=2.338 A, L=200 mm, px=0.05 mm/px.
        """
        from fermiviewer.calc.crystal import electron_wavelength
        lam = electron_wavelength(200.0)  # Angstrom
        d = 2.338
        sin_t = lam / (2 * d)
        expected_mm = 200.0 * math.tan(2 * math.asin(sin_t))
        expected_px = expected_mm / 0.05

        r_px = d_spacing_to_radius(
            d, (512, 512), pixel_size=0.05,
            camera_length=200.0, acc_voltage=200.0,
        )
        assert r_px == pytest.approx(expected_px, rel=1e-9)

    def test_camera_mode_sin_theta_gt1_returns_nan(self) -> None:
        # d very small relative to lambda → sin theta > 1 → NaN
        r_px = d_spacing_to_radius(0.001, (512, 512), pixel_size=0.05,
                                   camera_length=200.0, acc_voltage=200.0)
        assert math.isnan(r_px)


# ════════════════════════════════════════════════════════════════════
# apply_roi — pure calc
# ════════════════════════════════════════════════════════════════════


class TestApplyRoi:
    def test_none_returns_full_image_zero_offset(self) -> None:
        img = np.ones((100, 100))
        out, (r0, c0) = apply_roi(img, None)
        assert out is img
        assert (r0, c0) == (0, 0)

    def test_rect_crops_and_returns_offset(self) -> None:
        img = np.arange(400, dtype=float).reshape(20, 20)
        roi = {"kind": "rect", "r0": 5, "c0": 3, "r1": 10, "c1": 8}
        out, (r0, c0) = apply_roi(img, roi)
        assert (r0, c0) == (5, 3)
        assert out.shape == (5, 5)
        np.testing.assert_array_equal(out, img[5:10, 3:8])

    def test_rect_clamps_to_image_bounds(self) -> None:
        img = np.ones((10, 10))
        roi = {"kind": "rect", "r0": -5, "c0": -5, "r1": 50, "c1": 50}
        out, _ = apply_roi(img, roi)
        assert out.shape == (10, 10)

    def test_rect_degenerate_returns_full(self) -> None:
        img = np.ones((10, 10))
        roi = {"kind": "rect", "r0": 5, "c0": 5, "r1": 5, "c1": 5}
        out, (r0, c0) = apply_roi(img, roi)
        assert out is img
        assert (r0, c0) == (0, 0)

    def test_circle_shape_and_mask(self) -> None:
        img = np.ones((50, 50))
        roi = {"kind": "circle", "cr": 25, "cc": 25, "radius": 10}
        out, (r0, c0) = apply_roi(img, roi)
        assert (r0, c0) == (15, 15)
        assert out.shape == (21, 21)
        # centre pixel should be 1.0
        assert out[10, 10] == 1.0
        # corner pixel is outside the circle → masked to 0
        assert out[0, 0] == 0.0

    def test_unknown_kind_returns_full(self) -> None:
        img = np.ones((10, 10))
        out, (r0, c0) = apply_roi(img, {"kind": "triangle"})
        assert out is img
        assert (r0, c0) == (0, 0)


# ════════════════════════════════════════════════════════════════════
# ROI shifts spots into full-image coords after detect
# ════════════════════════════════════════════════════════════════════


def test_roi_spot_shift() -> None:
    """Spots detected in a cropped sub-image must be shifted back to the
    full-image 1-based coordinate frame after apply_roi."""
    # Synthetic 64×64 image with a bright blob at row=40, col=40 (1-based)
    img = np.zeros((64, 64))
    img[39, 39] = 1.0  # 0-based
    roi = {"kind": "rect", "r0": 30, "c0": 30, "r1": 50, "c1": 50}
    crop, (r_off, c_off) = apply_roi(img, roi)
    spots_crop = find_spots(crop, min_radius=0, threshold=0.5)
    assert spots_crop.shape[0] == 1
    # shift back to full-image frame
    spots_full = spots_crop + np.array([[r_off, c_off]])
    # blob is at 0-based (39, 39) → 1-based (40, 40)
    assert spots_full[0, 0] == pytest.approx(40, abs=1)
    assert spots_full[0, 1] == pytest.approx(40, abs=1)


# ════════════════════════════════════════════════════════════════════
# index_spots — matched_d / ref_d already existed; confirm pipeline
# ════════════════════════════════════════════════════════════════════


def test_index_returns_matched_d_and_ref_d() -> None:
    """index_spots must return non-empty matched_d / ref_d arrays for a
    matched phase (Silicon, FFT mode, 200 kV)."""
    from fermiviewer.calc.diffraction import simulate
    sim = simulate("Silicon", zone_axis=(0, 0, 1))
    pos = np.array([[s.pixel_row, s.pixel_col] for s in sim.spots[1:]])
    cands = index_spots(pos, (512, 512), pixel_size=0.05,
                        camera_length=200, acc_voltage=200, top_n=5)
    si = next((c for c in cands if c.phase_name == "Silicon"), None)
    assert si is not None
    assert si.matched_d.shape == si.matched_hkl.shape[:1]
    assert si.ref_d.shape == si.matched_d.shape
    assert np.all(si.matched_d > 0)
    assert np.all(si.ref_d > 0)


# ════════════════════════════════════════════════════════════════════
# API endpoint tests
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def diff_image_id(client: TestClient, tmp_path) -> str:
    """Upload a 128×128 synthetic diffraction pattern (4 spots)."""
    from fixtures.minidm4 import write_mini_dm4

    img = np.zeros((128, 128), dtype=np.float32)
    # place spots at the 4 cardinals, 30 px from the 1-based centre (65, 65)
    for r, c in [(65, 95), (65, 35), (95, 65), (35, 65)]:
        img[r - 1, c - 1] = 1.0
    # suppress direct beam position
    img[64, 64] = 0.0

    flat = img.reshape(-1, order="F")
    f = write_mini_dm4(
        tmp_path / "diff.dm4",
        dims=[128, 128],
        data=flat.astype(np.float32),
        data_type=2,
        cal=[
            {"scale": 0.05, "origin": 0, "units": "nm"},
            {"scale": 0.05, "origin": 0, "units": "nm"},
        ],
    )
    resp = client.post("/api/session/open", json={"paths": [str(f)]})
    return resp.json()[0]["id"]


def test_index_response_has_matched_d_ref_d_center_measured_r(
    client: TestClient, diff_image_id: str,
) -> None:
    """The /diffraction/index response must include center, measured_r,
    matched_d, ref_d for each candidate — the fields needed by the
    frontend matched-ring overlay (port of indexDiffraction.m .measuredR
    / .center / candidates.matchedD / candidates.refD)."""
    spots = [[65, 95], [65, 35], [95, 65], [35, 65]]
    r = client.post("/api/diffraction/index", json={
        "image_id": diff_image_id,
        "spots": spots,
        "pixel_size_mm": 0.05,
        "camera_length_mm": 200.0,
        "acc_voltage_kv": 200,
        "top_n": 3,
    })
    assert r.status_code == 200
    body = r.json()
    # top-level fields
    assert "center" in body
    assert "measured_r" in body
    assert len(body["center"]) == 2
    assert len(body["measured_r"]) == 4  # one per input spot
    # all measured_r should be positive (spots not at centre)
    assert all(v > 0 for v in body["measured_r"])
    # center should be floor(128/2)+1 = 65
    assert body["center"] == [65, 65]
    # each candidate must expose matched_d and ref_d
    for cand in body["candidates"]:
        assert "matched_d" in cand
        assert "ref_d" in cand
        assert len(cand["matched_d"]) == cand["n_matched"]
        assert len(cand["ref_d"]) == cand["n_matched"]


def test_detect_with_rect_roi(
    client: TestClient, diff_image_id: str,
) -> None:
    """Spots detected inside a rect ROI must be returned in full-image
    coordinates (not cropped-image coordinates)."""
    # ROI covers rows 55–80, cols 85–110 — the (65, 95) spot is inside.
    r = client.post("/api/diffraction/detect", json={
        "image_id": diff_image_id,
        "min_radius": 0,
        "threshold": 0.5,
        "roi": {"kind": "rect", "r0": 55, "c0": 85, "r1": 80, "c1": 110},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["n"] >= 1
    # The detected spot should be near (65, 95) in full-image coords
    spot = body["spots"][0]
    assert abs(spot[0] - 65) <= 2
    assert abs(spot[1] - 95) <= 2


def test_detect_with_circle_roi(
    client: TestClient, diff_image_id: str,
) -> None:
    """A circular ROI that contains the (35, 65) spot should find it."""
    r = client.post("/api/diffraction/detect", json={
        "image_id": diff_image_id,
        "min_radius": 0,
        "threshold": 0.5,
        "roi": {"kind": "circle", "cr": 35, "cc": 65, "radius": 15},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["n"] >= 1


def test_index_without_roi_is_backward_compatible(
    client: TestClient, diff_image_id: str,
) -> None:
    """Omitting 'roi' must still work (backward compat for existing callers)."""
    spots = [[65, 95], [65, 35], [95, 65], [35, 65]]
    r = client.post("/api/diffraction/index", json={
        "image_id": diff_image_id,
        "spots": spots,
    })
    assert r.status_code == 200
    assert "candidates" in r.json()


def test_index_with_rect_roi(
    client: TestClient, diff_image_id: str,
) -> None:
    """Index with an ROI should still return valid candidates and center."""
    spots = [[65, 95], [65, 35], [95, 65], [35, 65]]
    r = client.post("/api/diffraction/index", json={
        "image_id": diff_image_id,
        "spots": spots,
        "roi": {"kind": "rect", "r0": 20, "c0": 20, "r1": 110, "c1": 110},
    })
    assert r.status_code == 200
    body = r.json()
    assert "center" in body
    assert "candidates" in body
    assert len(body["candidates"]) > 0


# ── roi_frame / index_spots_roi (ADR 0005 §1 lift) ────────────────────


def test_roi_frame_offset_and_size_describe_the_same_region() -> None:
    """The bug this lift fixes: the crop origin was clamped to the image
    while the effective size came from the RAW roi, so an overhanging ROI
    left spots unshifted but shrank the width — and width scales d directly
    in the uncalibrated branch, so d-spacings came back quietly wrong."""
    import numpy as np

    from fermiviewer.calc.diffraction import apply_roi, roi_frame

    img = np.zeros((40, 50))
    for roi in (
        {"kind": "rect", "r0": 5, "c0": 6, "r1": 20, "c1": 30},
        {"kind": "rect", "r0": -5, "c0": -5, "r1": 100, "c1": 100},  # overhangs
        {"kind": "circle", "cr": 8, "cc": 9, "radius": 20},          # overhangs
        {"kind": "circle", "cr": 20, "cc": 25, "radius": 5},
    ):
        cropped, (row_off, col_off) = apply_roi(img, roi)
        frame = roi_frame(img.shape, roi)
        assert (frame.row_off, frame.col_off) == (row_off, col_off), roi
        assert (frame.height, frame.width) == cropped.shape[:2], roi


def test_roi_frame_falls_back_to_the_whole_image_like_apply_roi() -> None:
    from fermiviewer.calc.diffraction import roi_frame

    frame = roi_frame((40, 50), None)
    assert (frame.row_off, frame.col_off, frame.height, frame.width) == (0, 0, 40, 50)


def test_index_spots_roi_refuses_a_roi_that_selects_nothing() -> None:
    """Strict-ROI discipline (wave C): the route's zero-defaults would
    otherwise index the full pattern while the caller believed a region
    was in force."""
    import numpy as np
    import pytest

    from fermiviewer.calc.diffraction_index import index_spots_roi

    spots = np.array([[10.0, 12.0], [20.0, 22.0]])
    with pytest.raises(ValueError, match="selects no pixels"):
        index_spots_roi(
            (40, 50), spots, {"kind": "rect", "r0": 10, "c0": 10, "r1": 10, "c1": 10}
        )
    with pytest.raises(ValueError, match="selects no pixels"):
        index_spots_roi((40, 50), spots, {"kind": "circle", "cr": 5, "cc": 5, "radius": 0})


def test_index_spots_roi_keeps_overlay_geometry_in_the_full_image_frame() -> None:
    """center/measured_r drive the matched-ring overlay, drawn on the whole
    image — only the indexing itself moves into the ROI frame."""
    import numpy as np

    from fermiviewer.calc.diffraction_index import index_spots_roi

    spots = np.array([[10.0, 12.0], [30.0, 40.0]])
    roi = {"kind": "rect", "r0": 5, "c0": 6, "r1": 35, "c1": 45}
    scoped = index_spots_roi((40, 50), spots, roi)
    whole = index_spots_roi((40, 50), spots, None)

    assert scoped.center == whole.center == (21, 26)
    assert scoped.measured_r == whole.measured_r


def test_index_spots_roi_rejects_a_ragged_spot_list() -> None:
    """It used to escape np.asarray as an unhandled 500."""
    import numpy as np
    import pytest

    from fermiviewer.calc.diffraction_index import index_spots_roi

    with pytest.raises(ValueError, match=r"\(N, 2\)"):
        index_spots_roi((40, 50), np.array([[1.0, 2.0, 3.0]]))
