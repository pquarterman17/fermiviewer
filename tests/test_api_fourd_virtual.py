"""API tests for `POST /api/fourd/{id}/virtual-detector` (PLAN_4DSTEM #5).

Deliberately a SEPARATE file from test_api_fourd.py rather than appended to
it — keeps the disk/ring physics fixture and the validation matrix
self-contained. See routes/fourd.py's module docstring for why this
endpoint is never abbreviated "vdf" (routes/imaging_ops.py already has an
unrelated `/analyze/vdf`).
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.fourd.dataset import FourDDataset
from fermiviewer.calc.fourd.geometry import aperture_mask, pattern_center
from fermiviewer.calc.fourd.virtual import virtual_detector
from fermiviewer.datastruct import AxisCal
from fermiviewer.server import create_app
from fermiviewer.session import store as image_store
from fermiviewer.session_fourd import fourd_store

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _clean_stores():
    image_store.clear()
    fourd_store.clear()
    yield
    image_store.clear()
    fourd_store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


# ════════════════════════════════════════════════════════════════════
# synthetic disk/ring dataset — hand-checkable BF vs ADF physics
# ════════════════════════════════════════════════════════════════════

_DET_SHAPE = (11, 11)
_CENTER = (5.0, 5.0)


def _disk_ring_patterns() -> tuple[np.ndarray, np.ndarray]:
    """A centered disk (dist<=2.0) and an outer ring (4.0<=dist<=5.0) on an
    11x11 grid centered at (5,5) — same construction as
    test_fourd_geometry.py's `test_bf_bright_adf_dark_for_disk_vs_ring_patterns`,
    scaled to intensity 100 per pixel so sums are easy to hand-check."""
    ky = np.arange(11, dtype=np.float64)[:, None]
    kx = np.arange(11, dtype=np.float64)[None, :]
    dist = np.hypot(ky - _CENTER[0], kx - _CENTER[1])
    disk = (dist <= 2.0).astype(np.float64) * 100.0
    ring = ((dist >= 4.0) & (dist <= 5.0)).astype(np.float64) * 100.0
    return disk, ring


def _register_disk_ring_dataset() -> tuple[str, np.ndarray, np.ndarray]:
    disk, ring = _disk_ring_patterns()
    # scan_shape (2, 2): column 0 sees the disk at both rows, column 1 sees
    # the ring at both rows — symmetric about (5,5) so the scan-mean
    # pattern's centroid is EXACTLY (5.0, 5.0), letting the auto-center
    # path be checked against the same expected maps as the manual-center
    # path.
    cube = np.stack([np.stack([disk, ring]), np.stack([disk, ring])])
    assert cube.shape == (2, 2, 11, 11)
    ds = FourDDataset(
        handle=cube,
        scan_shape=(2, 2),
        det_shape=_DET_SHAPE,
        scan_axes=(
            AxisCal(scale=2.0, origin=0.0, units="nm"),
            AxisCal(scale=3.0, origin=0.0, units="nm"),
        ),
        det_axes=(AxisCal(), AxisCal()),
        dtype=cube.dtype,
        metadata={"source": "synthetic-vd.h5"},
    )
    fourd_id = fourd_store.add(ds, "synthetic-vd.h5", source_path="/data/synthetic-vd.h5")
    return fourd_id, disk, ring


# BF fully contains the disk (dist<=2.0) and none of the ring; ADF fully
# contains the ring (dist in [4,5]) and none of the disk — same radii the
# geometry test file uses for its own disk/ring cube.
_BF_OUTER_R = 2.5
_ADF_INNER_R, _ADF_OUTER_R = 3.5, 5.5


def test_virtual_detector_bf_bright_where_disk_is(client: TestClient) -> None:
    fourd_id, disk, _ring = _register_disk_ring_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/virtual-detector",
        json={
            "center_ky": 5.0, "center_kx": 5.0,
            "inner_r": 0.0, "outer_r": _BF_OUTER_R,
            "shape": "circle", "name": None,
        },
    )
    assert r.status_code == 200
    meta = r.json()
    assert meta["shape"] == [2, 2]
    arr = np.asarray(image_store.get(meta["id"]).data)
    expected = np.array([[disk.sum(), 0.0], [disk.sum(), 0.0]])
    np.testing.assert_array_equal(arr, expected)


def test_virtual_detector_adf_bright_where_ring_is(client: TestClient) -> None:
    fourd_id, _disk, ring = _register_disk_ring_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/virtual-detector",
        json={
            "center_ky": 5.0, "center_kx": 5.0,
            "inner_r": _ADF_INNER_R, "outer_r": _ADF_OUTER_R,
            "shape": "annulus", "name": None,
        },
    )
    assert r.status_code == 200
    meta = r.json()
    arr = np.asarray(image_store.get(meta["id"]).data)
    expected = np.array([[0.0, ring.sum()], [0.0, ring.sum()]])
    np.testing.assert_array_equal(arr, expected)


def test_virtual_detector_auto_center_matches_manual_center(client: TestClient) -> None:
    fourd_id, disk, _ring = _register_disk_ring_dataset()
    manual = client.post(
        f"/api/fourd/{fourd_id}/virtual-detector",
        json={
            "center_ky": 5.0, "center_kx": 5.0,
            "inner_r": 0.0, "outer_r": _BF_OUTER_R,
            "shape": "circle", "name": None,
        },
    ).json()
    auto = client.post(
        f"/api/fourd/{fourd_id}/virtual-detector",
        json={
            "center_ky": None, "center_kx": None,
            "inner_r": 0.0, "outer_r": _BF_OUTER_R,
            "shape": "circle", "name": None,
        },
    ).json()
    assert auto["meta"]["center_ky"] == pytest.approx(5.0)
    assert auto["meta"]["center_kx"] == pytest.approx(5.0)
    manual_arr = np.asarray(image_store.get(manual["id"]).data)
    auto_arr = np.asarray(image_store.get(auto["id"]).data)
    np.testing.assert_array_equal(auto_arr, manual_arr)
    expected = np.array([[disk.sum(), 0.0], [disk.sum(), 0.0]])
    np.testing.assert_array_equal(auto_arr, expected)


def test_virtual_detector_circle_ignores_out_of_range_inner_r(client: TestClient) -> None:
    """inner_r is documented as unused for shape="circle" — a garbage value
    (that would 422 an annulus) must not affect the circle result or error."""
    fourd_id, disk, _ring = _register_disk_ring_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/virtual-detector",
        json={
            "center_ky": 5.0, "center_kx": 5.0,
            "inner_r": -999.0, "outer_r": _BF_OUTER_R,
            "shape": "circle", "name": None,
        },
    )
    assert r.status_code == 200
    arr = np.asarray(image_store.get(r.json()["id"]).data)
    expected = np.array([[disk.sum(), 0.0], [disk.sum(), 0.0]])
    np.testing.assert_array_equal(arr, expected)


def test_virtual_detector_custom_name(client: TestClient) -> None:
    fourd_id, _disk, _ring = _register_disk_ring_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/virtual-detector",
        json={
            "center_ky": 5.0, "center_kx": 5.0,
            "inner_r": 0.0, "outer_r": _BF_OUTER_R,
            "shape": "circle", "name": "my BF map",
        },
    )
    assert r.json()["name"] == "my BF map"


def test_virtual_detector_default_name_format(client: TestClient) -> None:
    fourd_id, _disk, _ring = _register_disk_ring_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/virtual-detector",
        json={
            "center_ky": 5.0, "center_kx": 5.0,
            "inner_r": 0.0, "outer_r": _BF_OUTER_R,
            "shape": "circle", "name": None,
        },
    )
    assert r.json()["name"] == "vd(synthetic-vd.h5, r=0-2.5)"


def test_virtual_detector_registers_normal_derived_image(client: TestClient) -> None:
    fourd_id, _disk, _ring = _register_disk_ring_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/virtual-detector",
        json={
            "center_ky": 5.0, "center_kx": 5.0,
            "inner_r": 0.0, "outer_r": _BF_OUTER_R,
            "shape": "circle", "name": None,
        },
    )
    assert r.status_code == 200
    meta = r.json()
    assert meta["kind"] == "image"
    assert meta["shape"] == [2, 2]
    # scan axes carried through: axes=(scan_axes[0], scan_axes[1]) and
    # DataStruct.pixel_cal always reports axes[1] (kx-axis, scale=3.0/nm).
    assert meta["pixel_size"] == pytest.approx(3.0)
    assert meta["pixel_unit"] == "nm"
    assert meta["meta"]["analysis"] == "virtual_detector"
    assert meta["meta"]["fourd_id"] == fourd_id
    assert meta["meta"]["center_ky"] == pytest.approx(5.0)
    assert meta["meta"]["center_kx"] == pytest.approx(5.0)
    assert meta["meta"]["inner_r"] == pytest.approx(0.0)
    assert meta["meta"]["outer_r"] == pytest.approx(_BF_OUTER_R)
    assert meta["meta"]["shape"] == "circle"

    # it flows through the ordinary image pipeline untouched
    r2 = client.get(f"/api/image/{meta['id']}/meta")
    assert r2.status_code == 200
    r3 = client.get(f"/api/image/{meta['id']}/render")
    assert r3.status_code == 200
    assert r3.headers["content-type"] == "image/png"
    assert len(client.get("/api/session/images").json()) == 1


def test_virtual_detector_two_calls_register_two_images(client: TestClient) -> None:
    """Unlike /nav (one canonical result, idempotent), each virtual-detector
    call is a distinct analysis and always registers a fresh derived image."""
    fourd_id, _disk, _ring = _register_disk_ring_dataset()
    for _ in range(2):
        r = client.post(
            f"/api/fourd/{fourd_id}/virtual-detector",
            json={
                "center_ky": 5.0, "center_kx": 5.0,
                "inner_r": 0.0, "outer_r": _BF_OUTER_R,
                "shape": "circle", "name": None,
            },
        )
        assert r.status_code == 200
    assert len(client.get("/api/session/images").json()) == 2


# ════════════════════════════════════════════════════════════════════
# validation
# ════════════════════════════════════════════════════════════════════


def test_virtual_detector_unknown_fourd_id_is_404(client: TestClient) -> None:
    r = client.post(
        "/api/fourd/4d-999/virtual-detector",
        json={
            "center_ky": None, "center_kx": None,
            "inner_r": 0.0, "outer_r": 2.5,
            "shape": "circle", "name": None,
        },
    )
    assert r.status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"outer_r": 0.0},
        {"outer_r": -1.0},
        {"shape": "annulus", "inner_r": 3.0, "outer_r": 2.0},  # inner >= outer
        {"shape": "annulus", "inner_r": 2.0, "outer_r": 2.0},  # inner == outer
        {"shape": "annulus", "inner_r": -1.0, "outer_r": 5.0},  # negative inner
        {"shape": "square"},  # unknown shape literal
        {"center_ky": 5.0, "center_kx": None},  # mismatched center pair
        {"center_ky": None, "center_kx": 5.0},  # mismatched center pair
        {"center_ky": -1.0, "center_kx": 5.0},  # out of bounds (< 0)
        {"center_ky": 5.0, "center_kx": 11.0},  # out of bounds (> det_shape-1)
    ],
)
def test_virtual_detector_validation_errors_422(
    client: TestClient, overrides: dict
) -> None:
    fourd_id, _disk, _ring = _register_disk_ring_dataset()
    body = {
        "center_ky": 5.0, "center_kx": 5.0,
        "inner_r": 0.0, "outer_r": 2.5,
        "shape": "circle", "name": None,
    }
    body.update(overrides)
    r = client.post(f"/api/fourd/{fourd_id}/virtual-detector", json=body)
    assert r.status_code == 422, r.text


def test_virtual_detector_center_at_exact_boundary_is_valid(client: TestClient) -> None:
    """0 and det_shape-1 are the inclusive bounds, not off-by-one errors."""
    fourd_id, _disk, _ring = _register_disk_ring_dataset()
    for cy, cx in [(0.0, 0.0), (10.0, 10.0)]:
        r = client.post(
            f"/api/fourd/{fourd_id}/virtual-detector",
            json={
                "center_ky": cy, "center_kx": cx,
                "inner_r": 0.0, "outer_r": 2.5,
                "shape": "circle", "name": None,
            },
        )
        assert r.status_code == 200, r.text


# ════════════════════════════════════════════════════════════════════
# realdata — real HyperSpy-4D file through the real /session/open path
# ════════════════════════════════════════════════════════════════════


@pytest.mark.realdata
def test_virtual_detector_realdata_matches_h5py_streamed_reference(
    client: TestClient, fourd_corpus: Path
) -> None:
    path = fourd_corpus / "twinned_nanowire.hdf5"
    r = client.post("/api/session/open", json={"paths": [str(path)]})
    assert r.status_code == 200
    metas = r.json()
    assert len(metas) == 1
    assert metas[0]["is_fourd"] is True
    fourd_id = metas[0]["id"]
    # the real file's array is (100, 30, 144, 144) — scan_shape passes
    # through data.shape[0:2] with NO transpose (io/fourd/hspy4d.py).
    assert metas[0]["scan_shape"] == [100, 30]
    assert metas[0]["det_shape"] == [144, 144]

    bf_body = {
        "center_ky": None, "center_kx": None,
        "inner_r": 0.0, "outer_r": 15.0,
        "shape": "circle", "name": None,
    }
    adf_body = {
        "center_ky": None, "center_kx": None,
        "inner_r": 25.0, "outer_r": 60.0,
        "shape": "annulus", "name": None,
    }
    r_bf = client.post(f"/api/fourd/{fourd_id}/virtual-detector", json=bf_body)
    r_adf = client.post(f"/api/fourd/{fourd_id}/virtual-detector", json=adf_body)
    assert r_bf.status_code == 200, r_bf.text
    assert r_adf.status_code == 200, r_adf.text
    bf_meta, adf_meta = r_bf.json(), r_adf.json()
    assert bf_meta["shape"] == [100, 30]
    assert adf_meta["shape"] == [100, 30]

    bf_arr = np.asarray(image_store.get(bf_meta["id"]).data, dtype=np.float64)
    adf_arr = np.asarray(image_store.get(adf_meta["id"]).data, dtype=np.float64)

    assert np.all(np.isfinite(bf_arr))
    assert np.all(np.isfinite(adf_arr))
    assert not np.allclose(bf_arr, bf_arr.flat[0])  # non-constant
    assert not np.allclose(adf_arr, adf_arr.flat[0])  # non-constant
    assert not np.allclose(bf_arr, adf_arr)  # BF and ADF differ

    # Independent reference: open the HDF5 file directly with h5py (NOT
    # through io.fourd.hspy4d/FourDDataset) and stream it in row-blocks
    # through the SAME production aperture_mask/virtual_detector math the
    # route uses, to isolate a route/plumbing bug from a calc-layer one.
    with h5py.File(path, "r") as f:
        data = f["Experiments"]["__unnamed__"]["data"]
        assert data.shape == (100, 30, 144, 144)
        det_shape = (int(data.shape[2]), int(data.shape[3]))

        def _stream(block_rows: int):
            rows = data.shape[0]
            for row0 in range(0, rows, block_rows):
                row1 = min(row0 + block_rows, rows)
                yield row0, np.asarray(data[row0:row1], dtype=np.float64)

        acc = np.zeros(det_shape, dtype=np.float64)
        n_positions = 0
        for _row0, block in _stream(10):
            acc += block.sum(axis=(0, 1), dtype=np.float64)
            n_positions += block.shape[0] * block.shape[1]
        mean_pattern = acc / n_positions
        center = pattern_center(mean_pattern)

        bf_mask_ref = aperture_mask(det_shape, center, 0.0, 15.0, shape="circle")
        adf_mask_ref = aperture_mask(det_shape, center, 25.0, 60.0, shape="annulus")
        bf_ref = virtual_detector(_stream(10), bf_mask_ref)
        adf_ref = virtual_detector(_stream(10), adf_mask_ref)

    np.testing.assert_array_equal(bf_arr, bf_ref)
    np.testing.assert_array_equal(adf_arr, adf_ref)
