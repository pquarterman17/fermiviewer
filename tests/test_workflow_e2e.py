"""Cross-feature workflow integration tests — chains the kind of
multi-step pipelines a user actually runs, which the per-endpoint
tests never combine. Fixture-driven (no external data)."""

from __future__ import annotations

import io
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open_image(client, tmp_path, name, arr) -> str:
    h, w = arr.shape
    f = write_mini_dm4(tmp_path / name, dims=[w, h],
                       data=arr.ravel().astype(np.float32), data_type=2,
                       cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2)
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def test_geometry_chain_round_trips(client, tmp_path) -> None:
    """open → rotate90 → rotate90 → fliph → flipv == rotate180 twice
    == identity; calibration survives every hop."""
    rng = np.random.default_rng(11)
    src = rng.random((24, 30)) * 1000
    iid = _open_image(client, tmp_path, "g.dm4", src)

    cur = iid
    for kind in ("rotate90", "rotate90", "fliph", "flipv"):
        r = client.post("/api/filter", json={"image_id": cur, "kind": kind})
        assert r.status_code == 200
        cur = r.json()["id"]
    # two 90° rotations + both flips = identity
    np.testing.assert_allclose(
        np.asarray(store.get(cur).data), src, rtol=1e-6)
    assert client.get(f"/api/image/{cur}/meta").json()["pixel_size"] == 0.5


def test_drift_pipeline_align_then_mip_then_gif(client, tmp_path) -> None:
    """The drift-series workflow: open 3 shifted frames → align-stack →
    MIP of the ALIGNED set is sharp (≈ reference), then GIF the set."""
    rng = np.random.default_rng(5)
    ref = rng.random((20, 26)) * 100
    ids = [_open_image(client, tmp_path, "f0.dm4", ref)]
    for k, shift in enumerate([(2, -1), (-3, 4)], start=1):
        ids.append(_open_image(
            client, tmp_path, f"f{k}.dm4",
            np.roll(ref, shift, axis=(0, 1)),
        ))

    aligned = client.post("/api/analyze/align-stack",
                          json={"image_ids": ids}).json()
    aligned_ids = [ids[0]] + [m["id"] for m in aligned["images"]]

    mip = client.post("/api/analyze/mip",
                      json={"image_ids": aligned_ids}).json()
    # MIP of perfectly aligned identical frames == the reference
    np.testing.assert_allclose(
        np.asarray(store.get(mip["image"]["id"]).data), ref, rtol=1e-5)

    gif = client.post("/api/export/gif", json={
        "image_ids": aligned_ids, "fps": 8,
    })
    assert gif.status_code == 200
    # perfectly aligned frames are IDENTICAL — PIL legitimately merges
    # duplicate consecutive GIF frames, accumulating their durations,
    # so assert on total animation time rather than frame count
    g = Image.open(io.BytesIO(gif.content))
    total_ms = 0
    for k in range(g.n_frames):
        g.seek(k)
        total_ms += g.info.get("duration", 0)
    # GIF stores durations in CENTIseconds — allow per-frame rounding
    assert abs(total_ms - 3 * round(1000 / 8)) <= 30


def test_cube_explode_then_figure_then_batch(client, tmp_path) -> None:
    """SI cube → explode → figure panel of the frames → batch ZIP."""
    ny, nx, nf = 10, 12, 4
    arr = np.empty((nf, ny, nx), dtype=np.float32)
    for k in range(nf):
        arr[k] = np.linspace(0, 100 * (k + 1), ny * nx).reshape(ny, nx)
    f = write_mini_dm4(
        tmp_path / "cube.dm4", dims=[nx, ny, nf], data=arr.ravel(),
        data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"}] * 2
        + [{"scale": 1, "origin": 0, "units": "frame"}],
    )
    cid = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]

    frames = client.post(f"/api/image/{cid}/explode").json()
    frame_ids = [m["id"] for m in frames]
    assert len(frame_ids) == nf

    fig = client.post("/api/export/figure", json={
        "image_ids": frame_ids, "cols": 2, "gap": 2, "scale": 1,
    })
    assert fig.status_code == 200
    img = Image.open(io.BytesIO(fig.content))
    assert img.size == (12 * 2 + 2, 10 * 2 + 2)

    z = client.post("/api/export/batch", json={
        "image_ids": frame_ids, "format": "png",
    })
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert len(names) == nf
    assert len(set(names)) == nf                # de-duped names


def test_fourier_filter_chain(client, tmp_path) -> None:
    """Lattice image → local FFT of an ROI → full fft-mask pass-filter →
    the filtered image keeps the lattice frequency."""
    y, x = np.mgrid[0:64, 0:64]
    lattice = np.sin(2 * np.pi * x / 8) + 0.3 * np.random.default_rng(2).random((64, 64))
    iid = _open_image(client, tmp_path, "lat.dm4", lattice * 100)

    # local FFT of a region works and is smaller than the full FFT
    loc = client.post(f"/api/image/{iid}/fft",
                      json={"rect": [10, 10, 40, 40]}).json()
    assert loc["shape"] == [31, 31]

    # pass-mask ONLY the lattice bin (radius < 1 excludes the noise
    # bins next door, which would legitimately break exact periodicity)
    cr, cc = 64 // 2 + 1, 64 // 2 + 1
    res = client.post("/api/analyze/fft-mask", json={
        "image_id": iid, "masks": [[cr, cc + 8, 0.9]], "mode": "pass",
    })
    assert res.status_code == 200
    filt = np.asarray(store.get(res.json()["image"]["id"]).data)
    # a single-frequency pass is exactly periodic with period 8
    tol = float(np.abs(filt).max()) * 1e-9 + 1e-12
    np.testing.assert_allclose(filt[:, :-8], filt[:, 8:], atol=tol)


def test_quantify_map_consumes_region_spectrum(client, tmp_path) -> None:
    """EELS cube: region spectrum of the C-rich half shows more C signal
    than the O-rich half; quantify-map maps agree spatially."""
    energy = np.linspace(200, 700, 500)
    bg = 4e5 * energy**-2.2

    def spec(c_amp, o_amp):
        return (bg + np.where(energy >= 284, c_amp, 0.0)
                + np.where(energy >= 532, o_amp, 0.0))

    ny, nx = 4, 6
    cube = np.empty((energy.size, ny, nx), dtype=np.float32)
    for yy in range(ny):
        for xx in range(nx):
            cube[:, yy, xx] = spec(50, 5) if xx < 3 else spec(5, 50)
    f = write_mini_dm4(
        tmp_path / "si.dm4", dims=[nx, ny, energy.size],
        data=cube.ravel(), data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"}] * 2
        + [{"scale": float(energy[1] - energy[0]),
            "origin": -float(energy[0] / (energy[1] - energy[0])),
            "units": "eV"}],
    )
    cid = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]

    left = client.get(
        f"/api/image/{cid}/spectrum?row0=1&col0=1&row1=4&col1=3"
    ).json()
    right = client.get(
        f"/api/image/{cid}/spectrum?row0=1&col0=4&row1=4&col1=6"
    ).json()
    e = np.asarray(left["energy"])
    c_band = (e >= 300) & (e <= 500)
    assert (np.asarray(left["counts"])[c_band].sum()
            > np.asarray(right["counts"])[c_band].sum())

    edges = [
        {"element": "C", "shell": "K", "z": 6, "onset_ev": 284,
         "signal_window": [284, 384], "bg_window": [230, 280]},
        {"element": "O", "shell": "K", "z": 8, "onset_ev": 532,
         "signal_window": [532, 632], "bg_window": [470, 525]},
    ]
    maps = client.post("/api/eels/quantify-map", json={
        "image_id": cid, "edges": edges,
    }).json()
    c_map = np.asarray(store.get(maps["maps"][0]["id"]).data)
    assert c_map[:, :3].mean() > c_map[:, 3:].mean()
