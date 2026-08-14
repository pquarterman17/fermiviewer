"""API tests for `POST /api/fourd/{id}/dpc` (PLAN_4DSTEM #8).

Mirrors test_api_fourd_com.py's fixture idiom: synthetic shifted-disk
cubes give a KNOWN COM field, so the registered DPC magnitude/direction/
charge-density maps can be checked against an analytic expectation, not
just their shape/metadata. Two cubes: a UNIFORM shift (constant COM ->
zero divergence, the null case) and a linear/"radial" shift (KNOWN
non-zero divergence, so the charge-density path is actually exercised).
"""

from __future__ import annotations

import math

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


_DET_SHAPE = (21, 21)
_CENTER = (10.0, 10.0)
_MRAD_PER_PX = 2.0


def _shifted_disk(dy: float, dx: float) -> np.ndarray:
    ky = np.arange(_DET_SHAPE[0], dtype=np.float64)[:, None]
    kx = np.arange(_DET_SHAPE[1], dtype=np.float64)[None, :]
    dist = np.hypot(ky - (_CENTER[0] + dy), kx - (_CENTER[1] + dx))
    return (dist <= 2.0).astype(np.float64)


def _register(cube: np.ndarray, scan_shape: tuple[int, int], name: str) -> str:
    ds = FourDDataset(
        handle=cube,
        scan_shape=scan_shape,
        det_shape=_DET_SHAPE,
        scan_axes=(
            AxisCal(scale=2.0, origin=0.0, units="nm"),
            AxisCal(scale=3.0, origin=0.0, units="nm"),
        ),
        det_axes=(AxisCal(), AxisCal()),
        dtype=cube.dtype,
        metadata={"source": name},
    )
    return fourd_store.add(ds, name, source_path=f"/data/{name}")


# ── uniform shift: constant COM everywhere -> zero divergence ──────────

_UNIFORM_SHAPE = (2, 3)
_UNIFORM_DY, _UNIFORM_DX = 3.0, -2.0


def _register_uniform_shift_dataset() -> str:
    disk = _shifted_disk(_UNIFORM_DY, _UNIFORM_DX)
    cube = np.broadcast_to(
        disk, (_UNIFORM_SHAPE[0], _UNIFORM_SHAPE[1], *_DET_SHAPE)
    ).copy()
    return _register(cube, _UNIFORM_SHAPE, "uniform-dpc.h5")


# ── radial shift: COM(i,j) ~ (i-1, j-1) -> known nonzero divergence ────
# Symmetric about scan position (1,1) (offsets range over {-1,0,1} on each
# axis) so the scan-MEAN pattern's centroid is EXACTLY _CENTER, the same
# trick test_api_fourd_com.py's fixture uses to check auto-center against
# the manual-center path.

_RADIAL_SHAPE = (3, 3)


def _register_radial_shift_dataset() -> str:
    cube = np.stack(
        [np.stack([_shifted_disk(i - 1, j - 1) for j in range(3)]) for i in range(3)]
    )
    assert cube.shape == (3, 3, 21, 21)
    return _register(cube, _RADIAL_SHAPE, "radial-dpc.h5")


# ── too-narrow-for-divergence: scan_shape (3, 1), 1 column ─────────────

_SMALL_SHAPE = (3, 1)
_SMALL_SHIFTS = [(0.0, 0.0), (2.0, -1.0), (-2.0, 1.0)]


def _register_small_dataset() -> str:
    cube = np.stack([_shifted_disk(dy, dx) for dy, dx in _SMALL_SHIFTS])[:, None, :, :]
    return _register(cube, _SMALL_SHAPE, "small-dpc.h5")


def _body(**overrides: object) -> dict:
    base: dict = {
        "center_ky": _CENTER[0],
        "center_kx": _CENTER[1],
        "mrad_per_px": _MRAD_PER_PX,
        "name": None,
    }
    base.update(overrides)
    return base


def _arr(image_id: str) -> np.ndarray:
    return np.asarray(image_store.get(image_id).data)


# ════════════════════════════════════════════════════════════════════
# structure / registration
# ════════════════════════════════════════════════════════════════════


def test_dpc_registers_three_normal_derived_images(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/dpc", json=_body())
    assert r.status_code == 200, r.text
    body = r.json()
    mag, direction, rho = body["magnitude"], body["direction"], body["divergence"]
    ids = {mag["id"], direction["id"], rho["id"]}
    assert len(ids) == 3
    for meta in (mag, direction, rho):
        assert meta["kind"] == "image"
        assert meta["shape"] == [2, 3]
        assert meta["pixel_size"] == pytest.approx(3.0)
        assert meta["pixel_unit"] == "nm"
        assert meta["meta"]["fourd_id"] == fourd_id
        assert meta["meta"]["center_ky"] == pytest.approx(10.0)
        assert meta["meta"]["center_kx"] == pytest.approx(10.0)
        assert meta["meta"]["mrad_per_px"] == pytest.approx(2.0)
    assert mag["meta"]["analysis"] == "dpc_magnitude"
    assert mag["meta"]["units"] == "mrad"
    assert direction["meta"]["analysis"] == "dpc_direction"
    assert direction["meta"]["units"] == "rad"
    assert rho["meta"]["analysis"] == "dpc_divergence"
    assert rho["meta"]["units"] == "mrad_per_scan_px"
    # the physics interpretation rides in metadata, WITH its caveat, rather
    # than in a display name that would overstate what the number is
    assert "charge density" in rho["meta"]["interpretation"]
    assert "thickness" in rho["meta"]["interpretation"]

    # all three flow through the ordinary image pipeline untouched
    for meta in (mag, direction, rho):
        assert client.get(f"/api/image/{meta['id']}/meta").status_code == 200
        r3 = client.get(f"/api/image/{meta['id']}/render")
        assert r3.status_code == 200
        assert r3.headers["content-type"] == "image/png"
    assert len(client.get("/api/session/images").json()) == 3


def test_dpc_two_calls_register_six_images(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    for _ in range(2):
        r = client.post(f"/api/fourd/{fourd_id}/dpc", json=_body())
        assert r.status_code == 200
    assert len(client.get("/api/session/images").json()) == 6


def test_dpc_custom_name_used_for_all_three_maps(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/dpc", json=_body(name="my scan"))
    body = r.json()
    assert body["magnitude"]["name"] == "my scan (DPCmagnitude)"
    assert body["direction"]["name"] == "my scan (DPCdirection)"
    assert body["divergence"]["name"] == "my scan (DPCdivergence)"


def test_dpc_default_name_format(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/dpc", json=_body())
    body = r.json()
    assert body["magnitude"]["name"] == "DPCmagnitude(uniform-dpc.h5)"
    assert body["direction"]["name"] == "DPCdirection(uniform-dpc.h5)"
    assert body["divergence"]["name"] == "DPCdivergence(uniform-dpc.h5)"


def test_dpc_unknown_fourd_id_is_404(client: TestClient) -> None:
    r = client.post("/api/fourd/4d-999/dpc", json=_body())
    assert r.status_code == 404


# ════════════════════════════════════════════════════════════════════
# numeric correctness — uniform field (zero divergence, constant
# magnitude/direction)
# ════════════════════════════════════════════════════════════════════


def test_dpc_magnitude_direction_match_known_uniform_shift(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/dpc", json=_body())
    body = r.json()
    expected_mag = math.hypot(_UNIFORM_DY, _UNIFORM_DX) * _MRAD_PER_PX
    expected_dir = math.atan2(_UNIFORM_DY, _UNIFORM_DX)
    mag_arr = _arr(body["magnitude"]["id"])
    dir_arr = _arr(body["direction"]["id"])
    assert mag_arr == pytest.approx(expected_mag, abs=0.2)
    assert dir_arr == pytest.approx(expected_dir, abs=0.05)


def test_dpc_divergence_is_zero_for_uniform_shift(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/dpc", json=_body())
    body = r.json()
    rho_arr = _arr(body["divergence"]["id"])
    assert rho_arr == pytest.approx(0.0, abs=1e-9)


# ════════════════════════════════════════════════════════════════════
# numeric correctness — radial field (known non-zero divergence): the
# charge-density path is actually exercised, not just its null case
# ════════════════════════════════════════════════════════════════════


def test_dpc_divergence_is_nonzero_for_radial_shift(client: TestClient) -> None:
    fourd_id = _register_radial_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/dpc", json=_body())
    assert r.status_code == 200, r.text
    body = r.json()
    rho_arr = _arr(body["divergence"]["id"])
    # analytic: div(com) = d(i-1)/di + d(j-1)/dj = 1 + 1 = 2, scaled by
    # mrad_per_px -> 4.0
    assert rho_arr == pytest.approx(4.0, abs=1.0)
    assert np.all(rho_arr > 1.0)  # clearly non-zero, not a near-null pass


def test_dpc_records_center_and_calibration_in_metadata(client: TestClient) -> None:
    fourd_id = _register_radial_shift_dataset()
    r = client.post(
        f"/api/fourd/{fourd_id}/dpc",
        json={"center_ky": None, "center_kx": None, "mrad_per_px": 2.0, "name": None},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("magnitude", "direction", "divergence"):
        meta = body[key]["meta"]
        assert meta["center_ky"] == pytest.approx(10.0)
        assert meta["center_kx"] == pytest.approx(10.0)
        assert meta["mrad_per_px"] == pytest.approx(2.0)


def test_dpc_auto_center_matches_manual_center(client: TestClient) -> None:
    fourd_id = _register_radial_shift_dataset()
    manual = client.post(f"/api/fourd/{fourd_id}/dpc", json=_body()).json()
    auto = client.post(
        f"/api/fourd/{fourd_id}/dpc",
        json={"center_ky": None, "center_kx": None, "mrad_per_px": 2.0, "name": None},
    ).json()
    # The auto path resolves its center via pattern_center's own
    # floating-point centroid arithmetic rather than the literal 10.0/10.0
    # the manual path passes — both resolve to the SAME mathematical
    # center (see the fixture's symmetry note) but not always the
    # identical float, so a tight tolerance stands in for exact equality
    # (unlike test_api_fourd_com.py's analogous check, whose synthetic
    # center is bit-identical either way).
    for key in ("magnitude", "divergence"):
        np.testing.assert_allclose(
            _arr(manual[key]["id"]), _arr(auto[key]["id"]), atol=1e-9
        )
    # direction is ill-conditioned at the one scan position whose field is
    # ~(0, 0) (the radial fixture's own center, scan position (1, 1)) —
    # atan2 of two near-zero, floating-point-noisy components can land on
    # either side of the +-pi branch cut, so that single degenerate
    # position is excluded. Elsewhere the two paths' centers differ by a
    # few ULP (see above), which can push an angle sitting exactly ON the
    # +-pi branch cut (a position on the -kx axis) to the opposite sign —
    # a real (and physically meaningless) 2*pi wraparound, not a genuine
    # mismatch — so angles are compared WRAPPED into (-pi, pi] rather than
    # as raw floats.
    manual_dir = _arr(manual["direction"]["id"])
    auto_dir = _arr(auto["direction"]["id"])
    manual_mag = _arr(manual["magnitude"]["id"])
    well_defined = manual_mag > 1e-6
    assert well_defined.sum() == manual_mag.size - 1  # exactly one degenerate position
    wrapped_diff = (manual_dir - auto_dir + math.pi) % (2 * math.pi) - math.pi
    np.testing.assert_allclose(wrapped_diff[well_defined], 0.0, atol=1e-9)


# ════════════════════════════════════════════════════════════════════
# validation
# ════════════════════════════════════════════════════════════════════


def test_dpc_requires_mrad_per_px(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    body = _body()
    del body["mrad_per_px"]
    r = client.post(f"/api/fourd/{fourd_id}/dpc", json=body)
    assert r.status_code == 422


@pytest.mark.parametrize("bad", [0.0, -1.0, -0.5])
def test_dpc_rejects_non_positive_mrad_per_px(client: TestClient, bad: float) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/dpc", json=_body(mrad_per_px=bad))
    assert r.status_code == 422, r.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"center_ky": 10.0, "center_kx": None},
        {"center_ky": None, "center_kx": 10.0},
        {"center_ky": -1.0, "center_kx": 10.0},
        {"center_ky": 10.0, "center_kx": 21.0},
    ],
)
def test_dpc_center_validation_errors_422(client: TestClient, overrides: dict) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/dpc", json=_body(**overrides))
    assert r.status_code == 422, r.text


def test_dpc_center_at_exact_boundary_is_valid(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    for cy, cx in [(0.0, 0.0), (20.0, 20.0)]:
        r = client.post(
            f"/api/fourd/{fourd_id}/dpc", json=_body(center_ky=cy, center_kx=cx)
        )
        assert r.status_code == 200, r.text


def test_dpc_scan_shape_too_small_for_divergence_is_422(client: TestClient) -> None:
    """`divergence_map` requires >= 2 scan positions along each axis — a
    (3, 1) scan (1 column) cannot produce a charge-density map, and that
    ValueError must surface as a 422, not a 500."""
    fourd_id = _register_small_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/dpc", json=_body())
    assert r.status_code == 422, r.text
    assert "at least 2 scan positions" in r.text
