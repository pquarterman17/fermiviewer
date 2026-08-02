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


@pytest.mark.parametrize("bad_y", ["abc", "1.5", ""])
def test_pattern_non_integer_y_is_422(client: TestClient, bad_y: str) -> None:
    fourd_id, _cube = _register_dataset()
    r = client.get(f"/api/fourd/{fourd_id}/pattern", params={"y": bad_y, "x": 0})
    assert r.status_code == 422


def test_requests_against_a_closed_dataset_are_404_not_500(client: TestClient) -> None:
    """DELETE /api/fourd/{id} (below) is the HTTP-facing way to close a
    dataset; this test exercises the underlying store-level close() path
    directly (as internal callers like session cleanup do) to confirm every
    OTHER route 404s cleanly afterward — never a 500 from a stale
    reference somewhere."""
    fourd_id, _cube = _register_dataset()
    fourd_store.close(fourd_id)
    assert client.get(f"/api/fourd/{fourd_id}/meta").status_code == 404
    assert client.get(f"/api/fourd/{fourd_id}/nav").status_code == 404
    assert client.get(f"/api/fourd/{fourd_id}/mean-pattern").status_code == 404
    assert (
        client.get(f"/api/fourd/{fourd_id}/pattern", params={"y": 0, "x": 0}).status_code
        == 404
    )
    r = client.post(
        f"/api/fourd/{fourd_id}/virtual-detector",
        json={
            "center_ky": 1.0, "center_kx": 1.0,
            "inner_r": 0.0, "outer_r": 2.0,
            "shape": "circle", "name": None,
        },
    )
    assert r.status_code == 404


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


# ── DELETE /api/fourd/{fourd_id} ────────────────────────────────────────


def test_delete_fourd_closes_the_dataset(client: TestClient) -> None:
    fourd_id, _cube = _register_dataset()
    r = client.delete(f"/api/fourd/{fourd_id}")
    assert r.status_code == 200
    assert r.json() == {"status": "closed"}
    assert client.get(f"/api/fourd/{fourd_id}/meta").status_code == 404
    assert fourd_id not in [m["id"] for m in client.get("/api/fourd").json()]


def test_delete_fourd_unknown_id_is_404(client: TestClient) -> None:
    assert client.delete("/api/fourd/4d-999").status_code == 404


def test_delete_fourd_twice_404s_the_second_time(client: TestClient) -> None:
    """Mirrors routes.images.close_image: the same id can't be closed twice
    — the second DELETE 404s rather than silently no-opping, exactly like
    an unknown id would."""
    fourd_id, _cube = _register_dataset()
    assert client.delete(f"/api/fourd/{fourd_id}").status_code == 200
    assert client.delete(f"/api/fourd/{fourd_id}").status_code == 404


def test_delete_fourd_does_not_touch_a_derived_nav_image(client: TestClient) -> None:
    """The nav image (and any virtual-detector map) is an ORDINARY image in
    the separate image_store — closing the 4D dataset it was derived from
    must not evict or invalidate it."""
    fourd_id, _cube = _register_dataset()
    nav = client.get(f"/api/fourd/{fourd_id}/nav").json()

    r = client.delete(f"/api/fourd/{fourd_id}")
    assert r.status_code == 200

    assert client.get(f"/api/fourd/{fourd_id}/meta").status_code == 404
    r2 = client.get(f"/api/image/{nav['id']}/meta")
    assert r2.status_code == 200
    r3 = client.get(f"/api/image/{nav['id']}/render")
    assert r3.status_code == 200


def test_delete_fourd_releases_the_file_handle_for_deletion(
    client: TestClient, tmp_path: Path
) -> None:
    """CRITICAL on Windows: a 4D dataset held open for the server's
    lifetime (the bug this route fixes) keeps its backing file locked, so
    it could never be deleted or replaced even after the user was done
    with it. Uses a real file-backed dataset (via /session/open, not the
    synthetic in-memory one from _register_dataset) so this actually
    exercises the memmap close path."""
    mib_path = _write_minimal_mib(tmp_path / "close_me.mib")
    opened = client.post("/api/session/open", json={"paths": [str(mib_path)]}).json()
    fourd_id = opened[0]["id"]
    assert client.get(f"/api/fourd/{fourd_id}/pattern", params={"y": 0, "x": 0}).status_code == 200

    r = client.delete(f"/api/fourd/{fourd_id}")
    assert r.status_code == 200

    import gc

    gc.collect()
    mib_path.unlink()  # must not raise PermissionError ([WinError 32])


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


def test_session_open_same_path_twice_registers_two_independent_datasets(
    client: TestClient, tmp_path: Path
) -> None:
    """Matches the normal (2D) image store's existing no-dedup policy
    (SessionStore.open_paths never checks for an already-open path either)
    — opening the same 4D path twice is allowed and gives two independently
    usable, independently closeable entries, not a shared/reused one."""
    mib_path = _write_minimal_mib(tmp_path / "dup.mib")
    r1 = client.post("/api/session/open", json={"paths": [str(mib_path)]})
    r2 = client.post("/api/session/open", json={"paths": [str(mib_path)]})
    id1 = r1.json()[0]["id"]
    id2 = r2.json()[0]["id"]
    assert id1 != id2
    assert len(client.get("/api/fourd").json()) == 2
    assert client.get(f"/api/fourd/{id1}/pattern", params={"y": 0, "x": 0}).status_code == 200
    assert client.get(f"/api/fourd/{id2}/pattern", params={"y": 0, "x": 0}).status_code == 200
    fourd_store.close(id1)
    # closing the first must not break the second
    assert client.get(f"/api/fourd/{id2}/pattern", params={"y": 0, "x": 0}).status_code == 200
    assert client.get(f"/api/fourd/{id1}/pattern", params={"y": 0, "x": 0}).status_code == 404


# ── concurrency smoke ───────────────────────────────────────────────────


def test_concurrent_pattern_and_virtual_detector_requests_do_not_crash(
    client: TestClient,
) -> None:
    """FastAPI runs sync routes in a thread pool, so concurrent requests
    against the same dataset are a real scenario, not a theoretical one."""
    import threading

    fourd_id, _cube = _register_dataset(rows=4, cols=4, det_h=6, det_w=6)
    errors: list[tuple[str, int]] = []

    def worker(i: int) -> None:
        y, x = i % 4, (i * 3) % 4
        r = client.get(f"/api/fourd/{fourd_id}/pattern", params={"y": y, "x": x})
        if r.status_code != 200:
            errors.append(("pattern", r.status_code))
        r2 = client.get(f"/api/fourd/{fourd_id}/nav")
        if r2.status_code != 200:
            errors.append(("nav", r2.status_code))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
