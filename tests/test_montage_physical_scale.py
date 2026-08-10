"""calc/montage.py physical-scale mode + /analyze/montage-compare endpoint.

Verifies (plan item #25 — comparison montage with a shared scale bar):
  - known-answer resampling: a feature of equal PHYSICAL size occupies the
    same number of output pixels in both tiles after resampling to one
    common scale (this is the assertion that proves the panel honest)
  - the ONE baked scale bar's length in output px matches its stated
    physical length
  - tile labels carry the caller-supplied text (sample name + parameter
    value) through to the derived image's metadata
  - an uncalibrated input image is refused with a 422 naming that image,
    never a silent pixel-space fallback
  - two REAL Helios corpus frames at very different scales (realdata,
    auto-skips when the sibling corpus is absent)
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import ndimage as ndi

from fermiviewer.calc.montage import PhysicalMontageResult, montage_physical_scale
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = [pytest.mark.api, pytest.mark.imaging]


# ── calc-level: known-answer resampling ─────────────────────────────────


def _square(canvas_n: int, sq_size: int, off: int) -> np.ndarray:
    a = np.zeros((canvas_n, canvas_n))
    a[off:off + sq_size, off:off + sq_size] = 1.0
    return a


def _feature_extent(tile: np.ndarray, seed: tuple[int, int]) -> tuple[int, int, int]:
    """(height, width, area) in px of the connected foreground component
    touching `seed` — isolates the placed square from the baked scale bar/
    label, which also thresholds as foreground elsewhere in the tile."""
    labeled, _ = ndi.label(tile > 0.5)
    lbl = labeled[seed]
    assert lbl != 0, "seed did not land on a foreground pixel"
    ys, xs = np.nonzero(labeled == lbl)
    return int(ys.max() - ys.min() + 1), int(xs.max() - xs.min() + 1), int(len(ys))


def test_equal_physical_size_occupies_equal_output_pixels() -> None:
    """4x pixel-size mismatch, same 160-unit physical square in both tiles:
    after montage_physical_scale resamples to the coarser (4.0 unit/px)
    scale, both tiles must show the SAME feature footprint in output px."""
    fine = _square(400, 160, 20)     # 1.0 unit/px -> 160-unit square
    coarse = _square(100, 40, 5)     # 4.0 unit/px -> 160-unit square (same)

    result = montage_physical_scale(
        [fine, coarse], [1.0, 4.0], ["um", "um"], cols=2, gap=0, labels=None,
    )
    assert isinstance(result, PhysicalMontageResult)
    # coarsest wins: nothing is upsampled beyond the coarse tile's own res.
    assert result.pixel_size == 4.0
    assert result.pixel_unit == "um"

    tile0 = result.canvas[:100, :100]     # fine, resampled 400->100
    tile1 = result.canvas[:100, 100:200]  # coarse, unchanged

    h0, w0, area0 = _feature_extent(tile0, (25, 25))
    h1, w1, area1 = _feature_extent(tile1, (25, 25))
    assert (h0, w0) == (40, 40), "fine tile's feature should shrink to 40x40 px"
    assert (h1, w1) == (40, 40), "coarse tile's feature is already 40x40 px"
    assert area0 == area1 == 1600


def test_finer_tile_is_downsampled_not_upsampled() -> None:
    """The coarse tile (already at the common scale) keeps its native
    pixel count; only the finer tile shrinks."""
    fine = np.random.default_rng(0).random((200, 200))
    coarse = np.random.default_rng(1).random((50, 50))
    result = montage_physical_scale(
        [fine, coarse], [1.0, 4.0], ["um", "um"], cols=2, gap=0, labels=None,
    )
    # 200*0.25=50 for the fine tile; both tiles end up 50x50 -> canvas 50x100
    assert result.canvas.shape == (50, 100)


def test_mismatched_units_are_converted_to_a_common_basis() -> None:
    """1000 nm/px and 1 um/px are the SAME physical scale (UNIT_TO_NM) —
    neither tile should be resampled."""
    a = np.ones((30, 30))
    b = np.ones((30, 30))
    result = montage_physical_scale(
        [a, b], [1000.0, 1.0], ["nm", "um"], cols=2, gap=0, labels=None,
    )
    assert result.canvas.shape == (30, 60)


# ── calc-level: the ONE scale bar's physical length ─────────────────────


def test_scale_bar_length_matches_its_stated_physical_length() -> None:
    """bar.width (output px) must equal round(stated_length / common_px)."""
    fine = _square(400, 160, 20)
    coarse = _square(100, 40, 5)
    result = montage_physical_scale(
        [fine, coarse], [1.0, 4.0], ["um", "um"], cols=2, gap=0, labels=None,
    )
    bar = result.scale_bar
    stated_value = float(bar.label.split()[0])  # e.g. "200 um" -> 200.0
    assert bar.label.endswith(result.pixel_unit)
    assert bar.width == round(stated_value / result.pixel_size)


def test_only_one_scale_bar_is_baked_for_the_whole_panel() -> None:
    """A per-tile bar would defeat the point once every tile shares a
    scale — assert the geometry callers get back describes exactly one
    bar (a single ScaleBar, not one per tile)."""
    frames = [np.zeros((60, 60)) for _ in range(3)]
    result = montage_physical_scale(
        frames, [1.0, 2.0, 1.0], ["um", "um", "um"], cols=3, gap=0, labels=None,
    )
    assert result.scale_bar is not None
    # exactly one bar's worth of geometry — a scalar dataclass, not a list
    assert not isinstance(result.scale_bar, list)


# ── calc-level: validation ───────────────────────────────────────────────


def test_uncalibrated_pixel_size_raises() -> None:
    with pytest.raises(ValueError, match="no valid pixel size"):
        montage_physical_scale(
            [np.zeros((4, 4)), np.zeros((4, 4))],
            [float("nan"), 1.0], ["um", "um"],
        )


def test_unknown_unit_raises() -> None:
    with pytest.raises(ValueError, match="unknown pixel unit"):
        montage_physical_scale(
            [np.zeros((4, 4)), np.zeros((4, 4))],
            [1.0, 1.0], ["parsecs", "um"],
        )


# ── API endpoint contract ────────────────────────────────────────────────

from fixtures.minidm4 import write_mini_dm4  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open_calibrated(
    client: TestClient, tmp_path, data: np.ndarray, scale: float, units: str,
    name: str,
) -> str:
    h, w = data.shape
    f = write_mini_dm4(
        tmp_path / name, dims=[w, h], data=data.ravel(),
        cal=[{"scale": scale, "origin": 0, "units": units}] * 2,
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def _open_uncalibrated(client: TestClient, tmp_path, data: np.ndarray, name: str) -> str:
    h, w = data.shape
    f = write_mini_dm4(tmp_path / name, dims=[w, h], data=data.ravel())
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def test_endpoint_registers_derived_image_at_common_scale(client, tmp_path) -> None:
    id_fine = _open_calibrated(
        client, tmp_path, _square(64, 24, 8), 1.0, "um", "fine.dm4",
    )
    id_coarse = _open_calibrated(
        client, tmp_path, _square(16, 6, 2), 4.0, "um", "coarse.dm4",
    )
    r = client.post(
        "/api/analyze/montage-compare",
        json={"tiles": [{"image_id": id_fine}, {"image_id": id_coarse}], "gap": 0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    img = body["image"]
    assert img["pixel_size"] == 4.0
    assert img["pixel_unit"] == "um"
    assert "scale_bar" in body and body["scale_bar"]["label"]


def test_endpoint_labels_carry_the_parameter_value(client, tmp_path) -> None:
    """Caller-composed labels (sample name + parameter value) survive into
    the registered derived image's metadata."""
    id_a = _open_calibrated(client, tmp_path, np.zeros((32, 32)), 1.0, "um", "a.dm4")
    id_b = _open_calibrated(client, tmp_path, np.zeros((32, 32)), 1.0, "um", "b.dm4")
    r = client.post(
        "/api/analyze/montage-compare",
        json={
            "tiles": [
                {"image_id": id_a, "label": "FilmA — 400 degC"},
                {"image_id": id_b, "label": "FilmB — 500 degC"},
            ],
            "gap": 0,
        },
    )
    assert r.status_code == 200, r.text
    tile_labels = r.json()["image"]["meta"]["tile_labels"]
    assert tile_labels == ["FilmA — 400 degC", "FilmB — 500 degC"]


def test_endpoint_default_label_falls_back_to_image_name(client, tmp_path) -> None:
    img_id = _open_calibrated(
        client, tmp_path, np.zeros((16, 16)), 1.0, "um", "unlabelled.dm4",
    )
    r = client.post(
        "/api/analyze/montage-compare",
        json={"tiles": [{"image_id": img_id}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["image"]["meta"]["tile_labels"] == ["unlabelled.dm4"]


def test_endpoint_uncalibrated_image_returns_422_naming_it(client, tmp_path) -> None:
    id_ok = _open_calibrated(
        client, tmp_path, np.zeros((16, 16)), 1.0, "um", "calibrated.dm4",
    )
    id_bad = _open_uncalibrated(client, tmp_path, np.zeros((16, 16)), "flat.dm4")
    r = client.post(
        "/api/analyze/montage-compare",
        json={"tiles": [{"image_id": id_ok}, {"image_id": id_bad}]},
    )
    assert r.status_code == 422, r.text
    assert id_bad in r.text
    assert "flat.dm4" in r.text


def test_endpoint_unknown_image_id_returns_404(client) -> None:
    r = client.post(
        "/api/analyze/montage-compare",
        json={"tiles": [{"image_id": "bad-id"}]},
    )
    assert r.status_code == 404


def test_endpoint_empty_tiles_returns_422(client) -> None:
    r = client.post("/api/analyze/montage-compare", json={"tiles": []})
    assert r.status_code == 422


# ── realdata: two real Helios frames at very different scales ───────────


@pytest.mark.realdata
def test_real_helios_frames_at_mismatched_scales(client, rsciio_examples) -> None:
    """Two real Thermo Fisher Helios TIFFs, calibrated tens of times apart
    (an e-beam SEM frame at ~3.37 um/px vs a navcam overview at ~264 um/px
    — the corpus's two calibrated Helios frames; see test_tiff_metadata.py's
    real-vendor-calibration table). The panel must not error and must
    register at the COARSER (navcam) scale, never a silent per-tile
    fallback."""
    _dir = rsciio_examples / "fei" / "microscopy"
    ebeam = client.post(
        "/api/session/open",
        json={"paths": [str(_dir / "rosettasciio_Helios-Ebeam-16bits.tif")]},
    ).json()[0]
    navcam = client.post(
        "/api/session/open",
        json={"paths": [str(_dir / "rosettasciio_Helios-navcam.tif")]},
    ).json()[0]

    px_ebeam, px_navcam = ebeam["pixel_size"], navcam["pixel_size"]
    assert px_ebeam is not None and px_navcam is not None
    ratio = px_navcam / px_ebeam
    assert ratio > 50, f"expected a large real scale mismatch, got {ratio:.1f}x"

    r = client.post(
        "/api/analyze/montage-compare",
        json={
            "tiles": [
                {"image_id": ebeam["id"], "label": f"Ebeam ({px_ebeam:.3g} um/px)"},
                {"image_id": navcam["id"], "label": f"Navcam ({px_navcam:.3g} um/px)"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    img = r.json()["image"]
    # the coarser (navcam) scale wins — nothing upsampled past its own res.
    assert img["pixel_size"] == pytest.approx(px_navcam)
    assert img["pixel_unit"] == navcam["pixel_unit"]
