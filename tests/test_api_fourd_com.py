"""API tests for `POST /api/fourd/{id}/com` (PLAN_4DSTEM #7).

Deliberately a separate file from test_api_fourd.py, mirroring
test_api_fourd_virtual.py's precedent — keeps the shifted-disk fixture and
the validation matrix self-contained.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.fourd.dataset import FourDDataset
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
# synthetic shifted-disk dataset — known per-probe COM offset
# ════════════════════════════════════════════════════════════════════

_DET_SHAPE = (21, 21)
_CENTER = (10.0, 10.0)
# scan_shape (3, 1): one shifted disk per scan row. (2,-1) and its negation
# (-2,1) are point-symmetric about _CENTER on this odd-sized, exactly-
# centered grid, and (0,0) is self-symmetric, so the scan-MEAN pattern's
# centroid is EXACTLY _CENTER — letting the auto-center path be checked
# against the same expected maps as the manual-center path (same
# construction as test_api_fourd_virtual.py's disk/ring pair).
_SHIFTS = [(0.0, 0.0), (2.0, -1.0), (-2.0, 1.0)]


def _shifted_disk(dy: float, dx: float) -> np.ndarray:
    ky = np.arange(_DET_SHAPE[0], dtype=np.float64)[:, None]
    kx = np.arange(_DET_SHAPE[1], dtype=np.float64)[None, :]
    dist = np.hypot(ky - (_CENTER[0] + dy), kx - (_CENTER[1] + dx))
    return (dist <= 2.0).astype(np.float64)


def _register_shifted_disk_dataset() -> str:
    cube = np.stack([_shifted_disk(dy, dx) for dy, dx in _SHIFTS])[:, None, :, :]
    assert cube.shape == (3, 1, 21, 21)
    ds = FourDDataset(
        handle=cube,
        scan_shape=(3, 1),
        det_shape=_DET_SHAPE,
        scan_axes=(
            AxisCal(scale=2.0, origin=0.0, units="nm"),
            AxisCal(scale=3.0, origin=0.0, units="nm"),
        ),
        det_axes=(AxisCal(), AxisCal()),
        dtype=cube.dtype,
        metadata={"source": "synthetic-com.h5"},
    )
    return fourd_store.add(ds, "synthetic-com.h5", source_path="/data/synthetic-com.h5")


def test_com_tracks_known_shift_with_manual_center(client: TestClient) -> None:
    fourd_id = _register_shifted_disk_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/com",
        json={"center_ky": 10.0, "center_kx": 10.0, "name": None},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    comy_arr = np.asarray(image_store.get(body["comy"]["id"]).data)
    comx_arr = np.asarray(image_store.get(body["comx"]["id"]).data)
    for i, (dy, dx) in enumerate(_SHIFTS):
        assert comy_arr[i, 0] == pytest.approx(dy, abs=0.05)
        assert comx_arr[i, 0] == pytest.approx(dx, abs=0.05)


def test_com_auto_center_matches_manual_center(client: TestClient) -> None:
    fourd_id = _register_shifted_disk_dataset()
    manual = client.post(
        f"/api/fourd/{fourd_id}/com",
        json={"center_ky": 10.0, "center_kx": 10.0, "name": None},
    ).json()
    auto = client.post(
        f"/api/fourd/{fourd_id}/com",
        json={"center_ky": None, "center_kx": None, "name": None},
    ).json()
    manual_y = np.asarray(image_store.get(manual["comy"]["id"]).data)
    manual_x = np.asarray(image_store.get(manual["comx"]["id"]).data)
    auto_y = np.asarray(image_store.get(auto["comy"]["id"]).data)
    auto_x = np.asarray(image_store.get(auto["comx"]["id"]).data)
    np.testing.assert_array_equal(auto_y, manual_y)
    np.testing.assert_array_equal(auto_x, manual_x)


def test_com_records_the_resolved_center_on_the_auto_path(
    client: TestClient,
) -> None:
    """The auto path must store the center it actually measured against,
    not the request's null. Without it a COM map cannot be reproduced, and
    #8's COM→mrad→field calibration has no reference to calibrate from —
    `/virtual-detector` records the resolved value for the same reason.
    """
    fourd_id = _register_shifted_disk_dataset()
    auto = client.post(
        f"/api/fourd/{fourd_id}/com",
        json={"center_ky": None, "center_kx": None, "name": None},
    ).json()
    for key in ("comy", "comx"):
        meta = image_store.get(auto[key]["id"]).metadata
        assert meta["center_ky"] is not None, f"{key} lost its descan center"
        assert meta["center_kx"] is not None, f"{key} lost its descan center"
        # and it is the SAME center the equivalent manual call uses
        assert meta["center_ky"] == pytest.approx(10.0)
        assert meta["center_kx"] == pytest.approx(10.0)


def test_com_registers_two_normal_derived_images(client: TestClient) -> None:
    fourd_id = _register_shifted_disk_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/com",
        json={"center_ky": 10.0, "center_kx": 10.0, "name": None},
    )
    assert r.status_code == 200
    body = r.json()
    comy, comx = body["comy"], body["comx"]
    assert comy["id"] != comx["id"]
    assert comy["kind"] == "image"
    assert comx["kind"] == "image"
    assert comy["shape"] == [3, 1]
    assert comx["shape"] == [3, 1]
    # scan axes carried through, same convention as /virtual-detector
    assert comy["pixel_size"] == pytest.approx(3.0)
    assert comy["pixel_unit"] == "nm"
    assert comy["meta"]["analysis"] == "com_y"
    assert comx["meta"]["analysis"] == "com_x"
    assert comy["meta"]["fourd_id"] == fourd_id
    assert comy["meta"]["center_ky"] == pytest.approx(10.0)
    assert comy["meta"]["center_kx"] == pytest.approx(10.0)

    # both flow through the ordinary image pipeline untouched
    for meta in (comy, comx):
        assert client.get(f"/api/image/{meta['id']}/meta").status_code == 200
        r3 = client.get(f"/api/image/{meta['id']}/render")
        assert r3.status_code == 200
        assert r3.headers["content-type"] == "image/png"
    assert len(client.get("/api/session/images").json()) == 2


def test_com_two_calls_register_four_images(client: TestClient) -> None:
    """Like /virtual-detector (not /nav): every call is a fresh analysis."""
    fourd_id = _register_shifted_disk_dataset()
    for _ in range(2):
        r = client.post(
            f"/api/fourd/{fourd_id}/com",
            json={"center_ky": 10.0, "center_kx": 10.0, "name": None},
        )
        assert r.status_code == 200
    assert len(client.get("/api/session/images").json()) == 4


def test_com_custom_name_used_for_both_maps(client: TestClient) -> None:
    fourd_id = _register_shifted_disk_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/com",
        json={"center_ky": 10.0, "center_kx": 10.0, "name": "my scan"},
    )
    body = r.json()
    assert body["comy"]["name"] == "my scan (COMy)"
    assert body["comx"]["name"] == "my scan (COMx)"


def test_com_default_name_format(client: TestClient) -> None:
    fourd_id = _register_shifted_disk_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/com",
        json={"center_ky": 10.0, "center_kx": 10.0, "name": None},
    )
    body = r.json()
    assert body["comy"]["name"] == "COMy(synthetic-com.h5)"
    assert body["comx"]["name"] == "COMx(synthetic-com.h5)"


def test_com_unknown_fourd_id_is_404(client: TestClient) -> None:
    r = client.post(
        "/api/fourd/4d-999/com",
        json={"center_ky": None, "center_kx": None, "name": None},
    )
    assert r.status_code == 404


# ════════════════════════════════════════════════════════════════════
# both-or-neither center 422 contract
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "overrides",
    [
        {"center_ky": 10.0, "center_kx": None},
        {"center_ky": None, "center_kx": 10.0},
        {"center_ky": -1.0, "center_kx": 10.0},  # out of bounds (< 0)
        {"center_ky": 10.0, "center_kx": 21.0},  # out of bounds (> det_shape-1)
    ],
)
def test_com_center_validation_errors_422(client: TestClient, overrides: dict) -> None:
    fourd_id = _register_shifted_disk_dataset()
    body = {"center_ky": 10.0, "center_kx": 10.0, "name": None}
    body.update(overrides)
    r = client.post(f"/api/fourd/{fourd_id}/com", json=body)
    assert r.status_code == 422, r.text


def test_com_center_at_exact_boundary_is_valid(client: TestClient) -> None:
    """0 and det_shape-1 are the inclusive bounds, not off-by-one errors."""
    fourd_id = _register_shifted_disk_dataset()
    for cy, cx in [(0.0, 0.0), (20.0, 20.0)]:
        r = client.post(
            f"/api/fourd/{fourd_id}/com",
            json={"center_ky": cy, "center_kx": cx, "name": None},
        )
        assert r.status_code == 200, r.text


def test_com_both_omitted_is_valid_auto_center(client: TestClient) -> None:
    fourd_id = _register_shifted_disk_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/com",
        json={"center_ky": None, "center_kx": None, "name": None},
    )
    assert r.status_code == 200, r.text
