"""API tests for `POST /api/fourd/{id}/idpc` (PLAN_4DSTEM #9).

Mirrors test_api_fourd_dpc.py's fixture idiom (synthetic shifted-disk
cubes → a known COM field) for the structural/registration/validation
checks. Physical correctness of the Fourier-space integration itself (the
"reconstructs a known potential up to an additive constant" property) is
proven at the pure calc layer in test_fourd_idpc.py — this file instead
checks the ROUTE'S WIRING: that it resolves the same center `/com`/`/dpc`
would, streams the same COM field, and calls `calc.fourd.idpc.idpc_image`
with the request's `mrad_per_px`/`high_pass_cutoff` unchanged, by comparing
the registered array against calling `com_maps` + `idpc_image` directly
with the SAME known inputs — an end-to-end pass-through check, not a
re-derivation of the physics.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.fourd.com import com_maps
from fermiviewer.calc.fourd.dataset import FourDDataset
from fermiviewer.calc.fourd.idpc import DEFAULT_HIGH_PASS_CUTOFF, idpc_image
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


# ── radial shift: COM(i,j) ~ (i-1, j-1) — same fixture test_api_fourd_dpc.py
# uses, symmetric about scan position (1,1) so the scan-mean pattern's
# centroid lands exactly on _CENTER (auto-center matches manual-center).

_RADIAL_SHAPE = (3, 3)


def _register_radial_shift_dataset() -> str:
    cube = np.stack(
        [np.stack([_shifted_disk(i - 1, j - 1) for j in range(3)]) for i in range(3)]
    )
    return _register(cube, _RADIAL_SHAPE, "radial-idpc.h5")


def _register_uniform_shift_dataset() -> str:
    disk = _shifted_disk(1.0, -1.0)
    cube = np.broadcast_to(disk, (2, 3, *_DET_SHAPE)).copy()
    return _register(cube, (2, 3), "uniform-idpc.h5")


_SMALL_SHAPE = (3, 1)
_SMALL_SHIFTS = [(0.0, 0.0), (2.0, -1.0), (-2.0, 1.0)]


def _register_small_dataset() -> str:
    cube = np.stack([_shifted_disk(dy, dx) for dy, dx in _SMALL_SHIFTS])[:, None, :, :]
    return _register(cube, _SMALL_SHAPE, "small-idpc.h5")


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


def test_idpc_registers_one_normal_derived_image(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "image"
    assert body["shape"] == [2, 3]
    assert body["pixel_size"] == pytest.approx(3.0)
    assert body["pixel_unit"] == "nm"
    assert body["meta"]["fourd_id"] == fourd_id
    assert body["meta"]["analysis"] == "idpc"
    assert body["meta"]["center_ky"] == pytest.approx(10.0)
    assert body["meta"]["center_kx"] == pytest.approx(10.0)
    assert body["meta"]["mrad_per_px"] == pytest.approx(2.0)
    assert body["meta"]["high_pass_cutoff"] == pytest.approx(DEFAULT_HIGH_PASS_CUTOFF)
    assert body["meta"]["units"] == "mrad_scan_px"
    assert "additive constant" in body["meta"]["interpretation"]
    assert "accelerating voltage" in body["meta"]["interpretation"]

    assert client.get(f"/api/image/{body['id']}/meta").status_code == 200
    r2 = client.get(f"/api/image/{body['id']}/render")
    assert r2.status_code == 200
    assert r2.headers["content-type"] == "image/png"
    assert len(client.get("/api/session/images").json()) == 1


def test_idpc_two_calls_register_two_images(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    for _ in range(2):
        r = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body())
        assert r.status_code == 200
    assert len(client.get("/api/session/images").json()) == 2


def test_idpc_custom_name_used(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body(name="my scan"))
    assert r.json()["name"] == "my scan (iDPC)"


def test_idpc_default_name_format(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body())
    assert r.json()["name"] == "iDPC(uniform-idpc.h5)"


def test_idpc_unknown_fourd_id_is_404(client: TestClient) -> None:
    r = client.post("/api/fourd/4d-999/idpc", json=_body())
    assert r.status_code == 404


def test_idpc_omitted_high_pass_cutoff_uses_calc_module_default(
    client: TestClient,
) -> None:
    # `_body()` never sets high_pass_cutoff — the request field is optional
    # (pydantic.Field(default=...)), so omitting it must fall through to
    # `calc.fourd.idpc.DEFAULT_HIGH_PASS_CUTOFF`, never a re-invented value.
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body())
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["high_pass_cutoff"] == pytest.approx(
        DEFAULT_HIGH_PASS_CUTOFF
    )


# ════════════════════════════════════════════════════════════════════
# numeric correctness — route wiring vs the calc layer directly
# ════════════════════════════════════════════════════════════════════


def test_idpc_registered_array_matches_calc_layer_on_the_same_com_field(
    client: TestClient,
) -> None:
    """End-to-end wiring check: stream the SAME cube's COM field directly
    through `com_maps` + `idpc_image` (bypassing the route) and confirm the
    registered image matches — proves the route resolves the same center,
    passes `mrad_per_px`/`high_pass_cutoff` through unchanged, and doesn't
    silently transform the array before registering it."""
    fourd_id = _register_radial_shift_dataset()
    ds4 = fourd_store.get(fourd_id)
    com_y, com_x = com_maps(ds4.iter_scan_rows(), center=_CENTER)
    expected = idpc_image(
        com_y, com_x, mrad_per_px=_MRAD_PER_PX, high_pass_cutoff=DEFAULT_HIGH_PASS_CUTOFF
    )

    r = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body())
    assert r.status_code == 200, r.text
    np.testing.assert_allclose(_arr(r.json()["id"]), expected, atol=1e-12)


def test_idpc_custom_high_pass_cutoff_changes_the_registered_result(
    client: TestClient,
) -> None:
    # This fixture's scan is only 3x3 — its lowest nonzero spatial frequency
    # (1/3 cycles/px) is already far above DEFAULT_HIGH_PASS_CUTOFF (0.02),
    # so the default barely perturbs it (by design, see idpc.py's module
    # docstring) and isn't a reliable way to prove the route threads a
    # CUSTOM cutoff through. cutoff=1.0 (well past Nyquist) unambiguously
    # is, and that's all this wiring test needs to show.
    fourd_id = _register_radial_shift_dataset()
    mild = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body(high_pass_cutoff=0.0)).json()
    aggressive = client.post(
        f"/api/fourd/{fourd_id}/idpc", json=_body(high_pass_cutoff=1.0)
    ).json()
    assert aggressive["meta"]["high_pass_cutoff"] == pytest.approx(1.0)
    assert not np.allclose(_arr(mild["id"]), _arr(aggressive["id"]))


def test_idpc_auto_center_matches_manual_center(client: TestClient) -> None:
    fourd_id = _register_radial_shift_dataset()
    manual = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body()).json()
    auto = client.post(
        f"/api/fourd/{fourd_id}/idpc",
        json={"center_ky": None, "center_kx": None, "mrad_per_px": 2.0, "name": None},
    ).json()
    # Same floating-point-centroid-vs-literal-constant caveat as
    # test_api_fourd_dpc.py's analogous check — a tight tolerance stands in
    # for exact equality.
    np.testing.assert_allclose(_arr(manual["id"]), _arr(auto["id"]), atol=1e-9)


# ════════════════════════════════════════════════════════════════════
# validation
# ════════════════════════════════════════════════════════════════════


def test_idpc_requires_mrad_per_px(client: TestClient) -> None:
    fourd_id = _register_uniform_shift_dataset()
    body = _body()
    del body["mrad_per_px"]
    r = client.post(f"/api/fourd/{fourd_id}/idpc", json=body)
    assert r.status_code == 422


@pytest.mark.parametrize("bad", [0.0, -1.0, -0.5])
def test_idpc_rejects_non_positive_mrad_per_px(client: TestClient, bad: float) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body(mrad_per_px=bad))
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("bad", [-1.0, -0.001])
def test_idpc_rejects_negative_high_pass_cutoff(client: TestClient, bad: float) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body(high_pass_cutoff=bad))
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
def test_idpc_center_validation_errors_422(client: TestClient, overrides: dict) -> None:
    fourd_id = _register_uniform_shift_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body(**overrides))
    assert r.status_code == 422, r.text


def test_idpc_scan_shape_too_small_is_422(client: TestClient) -> None:
    """`idpc_image` requires >= 2 scan positions along each axis, same as
    `divergence_map` — a (3, 1) scan (1 column) must 422, not 500."""
    fourd_id = _register_small_dataset()
    r = client.post(f"/api/fourd/{fourd_id}/idpc", json=_body())
    assert r.status_code == 422, r.text
    assert "at least 2 scan positions" in r.text
