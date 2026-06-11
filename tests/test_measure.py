"""Profile/ROI/FFT tests — calc oracles + API flow."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.fourier import compute_fft
from fermiviewer.calc.profiles import line_profile, roi_stats
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.imaging


# ── calc oracles ─────────────────────────────────────────────────────

def test_line_profile_linear_ramp() -> None:
    # img(y, x) = x → a horizontal profile reproduces x exactly,
    # including sub-pixel endpoints (bilinear on a plane is exact)
    img = np.tile(np.arange(1, 33, dtype=np.float64), (8, 1))
    dist, inten = line_profile(img, x1=2.5, y1=4, x2=30.5, y2=4)
    assert dist[0] == 0 and dist[-1] == pytest.approx(28.0)
    np.testing.assert_allclose(inten, np.linspace(2.5, 30.5, inten.size), rtol=1e-12)
    # calibrated distance
    d2, _ = line_profile(img, 1, 1, 11, 1, pixel_size=0.5)
    assert d2[-1] == pytest.approx(5.0)


def test_line_profile_tilt_correction() -> None:
    img = np.zeros((64, 64))
    base, _ = line_profile(img, 1, 1, 1, 11)           # Δy = 10
    cross, _ = line_profile(img, 1, 1, 1, 11, tilt_angle_deg=30)
    surf, _ = line_profile(img, 1, 1, 1, 11, tilt_angle_deg=30, geometry="surface")
    assert cross[-1] == pytest.approx(base[-1] / np.sin(np.deg2rad(30)))
    assert surf[-1] == pytest.approx(base[-1] / np.cos(np.deg2rad(30)))
    # tilt about X leaves a pure-Y segment unchanged
    other, _ = line_profile(img, 1, 1, 1, 11, tilt_angle_deg=30, tilt_axis="X")
    assert other[-1] == pytest.approx(base[-1])


def test_roi_stats_against_numpy() -> None:
    rng_free = np.arange(48, dtype=np.float64).reshape(6, 8)
    s = roi_stats(rng_free, 2, 3, 5, 7)
    sel = rng_free[1:5, 2:7]
    assert s["mean"] == sel.mean() and s["std"] == sel.std()
    assert s["min"] == sel.min() and s["max"] == sel.max()
    assert s["n_pixels"] == sel.size
    s2 = roi_stats(rng_free, 5, 7, 2, 3, pixel_size=2.0)   # swapped + calibrated
    assert s2["area"] == sel.size * 4.0
    with pytest.raises(ValueError, match="empty"):
        roi_stats(rng_free, 99, 99, 120, 120)


def test_fft_sinusoid_peaks() -> None:
    n = 64
    yy, xx = np.mgrid[0:n, 0:n]
    img = np.sin(2 * np.pi * 8 * xx / n)               # 8 cycles along x
    mag, phase = compute_fft(img)
    assert mag.shape == (n, n) and phase.shape == (n, n)
    center = n // 2
    mag_nodc = mag.copy()
    mag_nodc[center, center] = 0
    peaks = np.argwhere(mag_nodc > 0.9 * mag_nodc.max())
    assert {tuple(p) for p in peaks} == {(center, center - 8), (center, center + 8)}


# ── API flow ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def ramp_id(client, tmp_path) -> str:
    w, h = 32, 8
    flat = np.array([x for _y in range(h) for x in range(w)], dtype=np.float32)
    f = write_mini_dm4(
        tmp_path / "ramp.dm4", dims=[w, h], data=flat, data_type=2,
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def test_profile_endpoint(client, ramp_id) -> None:
    r = client.post("/api/measure/profile", json={
        "image_id": ramp_id, "a": [4, 1], "b": [4, 21],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["unit"] == "nm"
    assert body["length"] == pytest.approx(10.0)       # 20 px × 0.5 nm
    assert body["intensity"][0] == pytest.approx(0.0)
    assert body["intensity"][-1] == pytest.approx(20.0)


def test_roi_endpoint(client, ramp_id) -> None:
    r = client.post("/api/measure/roi", json={
        "image_id": ramp_id, "rect": [2, 5, 6, 10],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["mean"] == pytest.approx(np.arange(4, 10).mean())
    assert body["area"] == pytest.approx(5 * 6 * 0.25)  # px² × (0.5 nm)²
    assert body["unit"] == "nm"


def test_fft_endpoint_creates_derived(client, ramp_id) -> None:
    r = client.post(f"/api/image/{ramp_id}/fft")
    assert r.status_code == 200
    meta = r.json()
    assert meta["kind"] == "image"
    assert meta["shape"] == [8, 32]
    assert meta["meta"]["derived_from"] == ramp_id
    assert client.get(f"/api/image/{meta['id']}/render").status_code == 200
    assert client.post("/api/image/nope/fft").status_code == 404


# ── width-averaged + polyline profiles (new, no MATLAB counterpart) ──

def test_width_averaged_profile() -> None:
    # img(y, x) = y → averaging ±1 row about y=4 still reads 4 exactly
    # (the offsets are symmetric), while a single line at y=3.5 reads 3.5
    img = np.tile(np.arange(1, 9, dtype=np.float64)[:, None], (1, 32))
    _, single = line_profile(img, 2, 4, 30, 4)
    _, wide = line_profile(img, 2, 4, 30, 4, width=3)
    np.testing.assert_allclose(single, np.full(single.size, 4.0), rtol=1e-12)
    np.testing.assert_allclose(wide, np.full(wide.size, 4.0), rtol=1e-12)
    # width=1 is bit-identical to the original path
    _, w1 = line_profile(img, 2, 4, 30, 4, width=1)
    np.testing.assert_array_equal(w1, single)
    # edge clipping: a 3-wide line hugging row 1 ignores the outside row
    _, edge = line_profile(img, 2, 1, 30, 1, width=3)
    np.testing.assert_allclose(edge, np.full(edge.size, 1.5), rtol=1e-12)


def test_polyline_profile_l_shape() -> None:
    from fermiviewer.calc.profiles import polyline_profile

    img = np.tile(np.arange(1, 33, dtype=np.float64), (16, 1))  # img = x
    # L-shape: horizontal run (x 1→11, y 2) then vertical (y 2→10)
    d, v = polyline_profile(img, xs=[1, 11, 11], ys=[2, 2, 10])
    assert d[0] == 0 and d[-1] == pytest.approx(18.0)   # 10 + 8
    assert np.all(np.diff(d) > 0)                       # strictly increasing
    # first leg reads x ramp; second leg constant x=11
    np.testing.assert_allclose(v[:11], np.linspace(1, 11, 11), rtol=1e-12)
    np.testing.assert_allclose(v[11:], 11.0, rtol=1e-12)
    # calibrated distances accumulate across segments
    d2, _ = polyline_profile(img, xs=[1, 11, 11], ys=[2, 2, 10], pixel_size=0.5)
    assert d2[-1] == pytest.approx(9.0)
    with pytest.raises(ValueError, match="at least 2"):
        polyline_profile(img, xs=[1], ys=[2])


def test_profile_endpoint_polyline_and_width(client, ramp_id) -> None:
    # polyline through 3 vertices
    r = client.post("/api/measure/profile", json={
        "image_id": ramp_id,
        "points": [[2, 1], [2, 11], [8, 11]],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["length"] == pytest.approx(16.0 * 0.5)  # ramp fixture cal
    # width-averaged two-point profile still works
    r2 = client.post("/api/measure/profile", json={
        "image_id": ramp_id, "a": [4, 2], "b": [4, 14], "width": 3,
    })
    assert r2.status_code == 200
    # neither a/b nor points → 422
    assert client.post("/api/measure/profile", json={
        "image_id": ramp_id,
    }).status_code == 422


# ── reduce='sum' vs 'mean' (item #49) ────────────────────────────────

def test_reduce_sum_equals_mean_times_width() -> None:
    """sum profile = mean profile × n_lines (no edge clipping, mid-image)."""
    img = np.ones((32, 64), dtype=np.float64) * 5.0
    width = 7
    _, mean_p = line_profile(img, 10, 16, 50, 16, width=width, reduce="mean")
    _, sum_p = line_profile(img, 10, 16, 50, 16, width=width, reduce="sum")
    # constant image: sum must equal mean × width
    np.testing.assert_allclose(sum_p, mean_p * width, rtol=1e-12)


def test_reduce_default_is_mean() -> None:
    """Default reduce='mean' is backward compatible — bit-identical."""
    img = np.random.default_rng(42).random((16, 32))
    _, default = line_profile(img, 2, 8, 28, 8, width=5)
    _, explicit = line_profile(img, 2, 8, 28, 8, width=5, reduce="mean")
    np.testing.assert_array_equal(default, explicit)


def test_reduce_width1_mean_sum_identical() -> None:
    """width=1 → single sample, mean and sum are the same."""
    img = np.random.default_rng(7).random((16, 32))
    _, mean_p = line_profile(img, 2, 8, 28, 8, width=1, reduce="mean")
    _, sum_p = line_profile(img, 2, 8, 28, 8, width=1, reduce="sum")
    np.testing.assert_array_equal(mean_p, sum_p)


def test_reduce_invalid_raises() -> None:
    img = np.ones((8, 8))
    with pytest.raises(ValueError, match="reduce"):
        line_profile(img, 1, 1, 5, 5, reduce="max")


def test_profile_endpoint_reduce_sum(client, ramp_id) -> None:
    """API accepts reduce='sum'; response includes reduce field."""
    r = client.post("/api/measure/profile", json={
        "image_id": ramp_id, "a": [4, 2], "b": [4, 14], "width": 3, "reduce": "sum",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["reduce"] == "sum"
    # default omitted → mean
    r2 = client.post("/api/measure/profile", json={
        "image_id": ramp_id, "a": [4, 2], "b": [4, 14], "width": 3,
    })
    assert r2.json()["reduce"] == "mean"
