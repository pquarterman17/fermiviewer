"""API tests for the 4D-STEM routes + /session/open's 4D wiring."""

from __future__ import annotations

from pathlib import Path

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


def _register_dataset(rows=2, cols=3, det_h=4, det_w=5) -> tuple[str, np.ndarray]:
    rng = np.random.default_rng(0)
    cube = rng.integers(0, 100, size=(rows, cols, det_h, det_w)).astype(np.float64)
    ds = FourDDataset(
        handle=cube,
        scan_shape=(rows, cols),
        det_shape=(det_h, det_w),
        scan_axes=(
            AxisCal(scale=1.0, origin=0.0, units="nm"),
            AxisCal(scale=1.0, origin=0.0, units="nm"),
        ),
        det_axes=(AxisCal(), AxisCal()),
        dtype=cube.dtype,
        metadata={"source": "synthetic.mib"},
    )
    fourd_id = fourd_store.add(ds, "synthetic.mib", source_path="/data/synthetic.mib")
    return fourd_id, cube


def _decode_u16_response(r) -> tuple[np.ndarray, float, float]:
    shape = tuple(int(v) for v in r.headers["X-Shape"].split(","))
    vmin = float(r.headers["X-Min"])
    vmax = float(r.headers["X-Max"])
    arr = np.frombuffer(r.content, dtype="<u2").reshape(shape)
    return arr, vmin, vmax


def test_list_fourd(client: TestClient) -> None:
    fourd_id, _cube = _register_dataset()
    r = client.get("/api/fourd")
    assert r.status_code == 200
    metas = r.json()
    assert len(metas) == 1
    assert metas[0]["id"] == fourd_id
    assert metas[0]["is_fourd"] is True
    assert metas[0]["scan_shape"] == [2, 3]
    assert metas[0]["det_shape"] == [4, 5]


def test_fourd_meta(client: TestClient) -> None:
    fourd_id, _cube = _register_dataset()
    r = client.get(f"/api/fourd/{fourd_id}/meta")
    assert r.status_code == 200
    assert r.json()["id"] == fourd_id


def test_unknown_fourd_id_404s(client: TestClient) -> None:
    paths = (
        "/api/fourd/4d-999/meta",
        "/api/fourd/4d-999/nav",
        "/api/fourd/4d-999/mean-pattern",
    )
    for path in paths:
        assert client.get(path).status_code == 404
    assert (
        client.get("/api/fourd/4d-999/pattern", params={"y": 0, "x": 0}).status_code
        == 404
    )


def test_pattern_matches_dataset(client: TestClient) -> None:
    fourd_id, cube = _register_dataset()
    r = client.get(f"/api/fourd/{fourd_id}/pattern", params={"y": 1, "x": 2})
    assert r.status_code == 200
    arr, vmin, vmax = _decode_u16_response(r)
    expected = cube[1, 2]
    assert arr.shape == expected.shape
    assert vmin == pytest.approx(float(expected.min()))
    assert vmax == pytest.approx(float(expected.max()))
    # reconstruct real values and compare
    recon = arr.astype(np.float64) / 65535.0 * (vmax - vmin) + vmin
    np.testing.assert_allclose(recon, expected, atol=(vmax - vmin) / 65535.0 + 1e-6)


def test_pattern_out_of_range_is_422(client: TestClient) -> None:
    fourd_id, _cube = _register_dataset()
    r = client.get(f"/api/fourd/{fourd_id}/pattern", params={"y": 99, "x": 0})
    assert r.status_code == 422


def test_pattern_missing_query_params_is_422(client: TestClient) -> None:
    fourd_id, _cube = _register_dataset()
    r = client.get(f"/api/fourd/{fourd_id}/pattern")
    assert r.status_code == 422


def test_mean_pattern(client: TestClient) -> None:
    fourd_id, cube = _register_dataset()
    r = client.get(f"/api/fourd/{fourd_id}/mean-pattern")
    assert r.status_code == 200
    arr, vmin, vmax = _decode_u16_response(r)
    expected = cube.mean(axis=(0, 1))
    assert arr.shape == expected.shape
    assert vmin == pytest.approx(float(expected.min()), abs=1e-6)
    assert vmax == pytest.approx(float(expected.max()), abs=1e-6)


def test_nav_registers_a_normal_derived_image(client: TestClient) -> None:
    fourd_id, cube = _register_dataset()
    r = client.get(f"/api/fourd/{fourd_id}/nav")
    assert r.status_code == 200
    meta = r.json()
    assert meta["kind"] == "image"
    assert meta["shape"] == [2, 3]

    # it flows through the ordinary image pipeline untouched
    r2 = client.get(f"/api/image/{meta['id']}/meta")
    assert r2.status_code == 200
    r3 = client.get(f"/api/image/{meta['id']}/render")
    assert r3.status_code == 200
    assert r3.headers["content-type"] == "image/png"


def test_nav_is_idempotent(client: TestClient) -> None:
    fourd_id, _cube = _register_dataset()
    r1 = client.get(f"/api/fourd/{fourd_id}/nav")
    r2 = client.get(f"/api/fourd/{fourd_id}/nav")
    assert r1.json()["id"] == r2.json()["id"]
    # only ONE derived image was registered, not two
    assert len(client.get("/api/session/images").json()) == 1


def test_nav_reregisters_after_the_image_is_closed(client: TestClient) -> None:
    fourd_id, _cube = _register_dataset()
    first = client.get(f"/api/fourd/{fourd_id}/nav").json()
    client.delete(f"/api/image/{first['id']}")
    second = client.get(f"/api/fourd/{fourd_id}/nav").json()
    assert second["id"] != first["id"]
    assert client.get(f"/api/image/{second['id']}/meta").status_code == 200


# ── /session/open wiring: a 4D file registers into the FourD store and
# comes back discriminated, not as a normal image ──────────────────────


def _write_minimal_mib(path: Path) -> Path:
    """A 1-chip, 2x8 R64 .mib with a single frame — the smallest file the
    real reader accepts (width must be a multiple of 8)."""
    height, width = 2, 8
    fields = [
        "MQ1", "000001", "00128", "01", f"{width:04d}", f"{height:04d}",
        "R64", "   1x1", "0F",
    ]
    header = (",".join(fields) + ",").encode("ascii")
    header = header + b" " * (128 - len(header))
    payload = np.zeros((height, width), dtype=np.uint8).tobytes()
    path.write_bytes(header + payload)
    return path


def test_session_open_routes_mib_to_fourd_store(client: TestClient, tmp_path: Path) -> None:
    mib_path = _write_minimal_mib(tmp_path / "tiny.mib")
    r = client.post("/api/session/open", json={"paths": [str(mib_path)]})
    assert r.status_code == 200
    metas = r.json()
    assert len(metas) == 1
    assert metas[0]["is_fourd"] is True
    assert metas[0]["name"] == "tiny.mib"
    # NOT registered as a normal image
    assert client.get("/api/session/images").json() == []
    # IS registered in the fourd store
    assert len(client.get("/api/fourd").json()) == 1


def test_session_open_mixed_normal_and_fourd(client: TestClient, tmp_path: Path) -> None:
    from fixtures.minidm4 import write_mini_dm4

    mib_path = _write_minimal_mib(tmp_path / "tiny2.mib")
    dm4_path = write_mini_dm4(
        tmp_path / "img.dm4", dims=[4, 3], data=list(range(12)),
        cal=[{"scale": 1.0, "origin": 0, "units": "nm"}] * 2,
    )
    r = client.post(
        "/api/session/open", json={"paths": [str(dm4_path), str(mib_path)]}
    )
    assert r.status_code == 200
    metas = r.json()
    assert len(metas) == 2
    is_fourd_flags = sorted(bool(m.get("is_fourd")) for m in metas)
    assert is_fourd_flags == [False, True]
    assert len(client.get("/api/session/images").json()) == 1
    assert len(client.get("/api/fourd").json()) == 1
