"""Scan distortion correction endpoints and ops: /api/analyze/line-jitter,
/api/analyze/frame-drift, and the ``line_jitter`` / ``frame_drift`` ops.

The numerics live in calc/jitter (tests/test_jitter.py); here the checks are
the wiring: the route and the op call the same calc functions, register
derived images with the right calibration, and refuse bad input cleanly.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import ndimage

import fermiviewer.ops as ops
from fermiviewer.calc.jitter import estimate_frame_drift, estimate_line_jitter
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.imaging]


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _lattice(h: int = 128, w: int = 128, period: float = 16.0) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    return np.exp(-(((xx % period) - 8) ** 2 + ((yy % period) - 8) ** 2) / (2 * 2.6**2))


def _jittered(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = _lattice(128, 192)
    x = np.arange(192, dtype=float)
    d = rng.normal(0, 0.8, 128)
    rows = [np.interp(x - d[r], x, base[r]) for r in range(128)]
    return np.array(rows)[:, 32:160] + rng.normal(0, 0.02, (128, 128))


def _frames() -> list[np.ndarray]:
    rng = np.random.default_rng(1)
    tex = ndimage.gaussian_filter(rng.normal(size=(160, 160)), 3)
    tex /= tex.std()
    shifts = [(0.0, 0.0), (1.5, -2.0), (-1.0, 3.0)]
    return [
        ndimage.shift(tex, s, order=3, mode="nearest")[16:144, 16:144]
        + rng.normal(0, 0.2, (128, 128))
        for s in shifts
    ]


def _open(client: TestClient, tmp_path, name: str, arr: np.ndarray) -> str:
    h, w = arr.shape
    f = write_mini_dm4(
        tmp_path / name,
        dims=[w, h],
        data=arr.ravel().astype(np.float32),
        data_type=2,
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


# ── line jitter ─────────────────────────────────────────────────────────


def test_line_jitter_route_registers_corrected_image(client, tmp_path) -> None:
    img = _jittered()
    image_id = _open(client, tmp_path, "scan.dm4", img)
    r = client.post("/api/analyze/line-jitter", json={"image_id": image_id})
    assert r.status_code == 200
    body = r.json()
    assert body["image"]["name"].startswith("dejitter(")
    assert len(body["offsets"]) == 128
    # the route reports exactly what calc measures on the stored data
    expected = estimate_line_jitter(np.asarray(store.get(image_id).data, dtype=np.float64))
    np.testing.assert_allclose(body["offsets"], expected.offsets, atol=1e-9)
    assert body["rms"] == pytest.approx(expected.rms)
    derived = store.get(body["image"]["id"])
    assert derived.axes[0].scale == pytest.approx(0.5)
    assert derived.metadata["filter_kind"] == "line_jitter"


def test_line_jitter_route_rejects_bad_input(client, tmp_path) -> None:
    image_id = _open(client, tmp_path, "scan.dm4", _jittered())
    assert client.post("/api/analyze/line-jitter", json={"image_id": "nope"}).status_code == 404
    bad = client.post("/api/analyze/line-jitter", json={"image_id": image_id, "max_shift": 0})
    assert bad.status_code == 422


def test_line_jitter_op_matches_calc() -> None:
    img = _jittered(seed=4)
    ds = DataStruct(data=img, kind=DataKind.IMAGE, axes=(AxisCal(), AxisCal()))
    res = ops.run("line_jitter", ds, {"max_shift": 4.0})
    expected = estimate_line_jitter(img, max_shift=4.0)
    np.testing.assert_allclose(res.derived.metadata["jitter_offsets_px"], expected.offsets)
    assert res.derived.data.shape == img.shape


def test_line_jitter_op_refuses_non_images() -> None:
    spec = DataStruct(data=np.zeros(64), kind=DataKind.SPECTRUM, axes=(AxisCal(),))
    with pytest.raises(ValueError, match="2-D greyscale"):
        ops.run("line_jitter", spec, {})


# ── frame drift ─────────────────────────────────────────────────────────


def test_frame_drift_route_registers_average_and_frames(client, tmp_path) -> None:
    ids = [_open(client, tmp_path, f"f{i}.dm4", f) for i, f in enumerate(_frames())]
    r = client.post("/api/analyze/frame-drift", json={"image_ids": ids, "keep_frames": True})
    assert r.status_code == 200
    body = r.json()
    np.testing.assert_allclose(body["shifts"], [[0, 0], [1.5, -2.0], [-1.0, 3.0]], atol=0.25)
    top, bottom, left, right = body["crop"]
    assert body["average"]["name"] == "drift-corrected average(3)"
    assert len(body["frames"]) == 3
    avg = store.get(body["average"]["id"])
    assert avg.data.shape == (bottom - top, right - left)
    # cropping keeps every pixel's physical position
    assert avg.axes[0].origin == pytest.approx(-top)
    assert avg.axes[1].origin == pytest.approx(-left)


def test_frame_drift_route_needs_two_matching_images(client, tmp_path) -> None:
    a = _open(client, tmp_path, "a.dm4", _frames()[0])
    b = _open(client, tmp_path, "b.dm4", np.zeros((64, 64)))
    assert client.post("/api/analyze/frame-drift", json={"image_ids": [a]}).status_code == 422
    r = client.post("/api/analyze/frame-drift", json={"image_ids": [a, b]})
    assert r.status_code == 422
    assert "same size" in r.json()["detail"]
    bad = client.post("/api/analyze/frame-drift", json={"image_ids": [a, a], "reference": "x"})
    assert bad.status_code == 422


def test_frame_drift_op_matches_calc() -> None:
    frames = _frames()
    structs = [DataStruct(data=f, kind=DataKind.IMAGE, axes=(AxisCal(), AxisCal())) for f in frames]
    res = ops.run(
        "frame_drift", structs[0], {"reference": "first"}, inputs={"others": structs[1:]}
    )
    expected = estimate_frame_drift(frames, reference="first")
    np.testing.assert_allclose(res.derived.metadata["frame_drift_shifts_px"], expected.shifts)
    assert res.derived.metadata["frame_drift_frames"] == 3
