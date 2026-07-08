"""API tests closing coverage gaps in routes/imaging_ops.py.

/api/analyze/fft-mask, /api/analyze/ctf, /api/analyze/noise and
/api/analyze/defects had zero HTTP-level coverage before this file (only
test_ragged_array_422.py monkeypatched analyze_ctf's error path; the
success path was untested). Calc-level numerics for all four are already
golden-tested in test_imaging.py / test_w4_scraps.py — these verify the
route wiring: request validation, derived-image registration, and the
404/400/422 error contract shared with the rest of imaging_ops.py.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

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


def _synth_pattern() -> np.ndarray:
    """64x96 periodic texture (same closed form as test_imaging.py's synth
    fixture) — enough spectral structure for FFT-mask/CTF/noise/defect-line
    analysis without RNG flakiness."""
    r = np.arange(1, 65, dtype=np.float64)[:, None]
    c = np.arange(1, 97, dtype=np.float64)[None, :]
    return np.sin(r / 7) * np.cos(c / 11) + 0.001 * (r * c) / (64 * 96)


def _open(client, tmp_path, data: np.ndarray, name: str = "img.dm4") -> str:
    h, w = data.shape
    f = write_mini_dm4(
        tmp_path / name, dims=[w, h], data=data.ravel(),
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


# ── fft-mask ────────────────────────────────────────────────────────────


def test_fft_mask_pass_and_reject(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _synth_pattern())
    r = client.post("/api/analyze/fft-mask", json={
        "image_id": img_id, "masks": [[33, 61, 4]], "mode": "pass",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["image"]["name"].startswith("FFTpass(")
    assert body["image"]["shape"] == [64, 96]
    assert client.get(
        f"/api/image/{body['image']['id']}/render"
    ).status_code == 200

    r2 = client.post("/api/analyze/fft-mask", json={
        "image_id": img_id, "masks": [[33, 61, 4]], "mode": "reject",
    })
    assert r2.status_code == 200
    assert r2.json()["image"]["name"].startswith("FFTreject(")


def test_fft_mask_errors(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _synth_pattern())
    # no masks at all
    assert client.post("/api/analyze/fft-mask", json={
        "image_id": img_id, "masks": [],
    }).status_code == 422
    # non-positive radius
    assert client.post("/api/analyze/fft-mask", json={
        "image_id": img_id, "masks": [[33, 61, 0]],
    }).status_code == 422
    # invalid mode string
    assert client.post("/api/analyze/fft-mask", json={
        "image_id": img_id, "masks": [[33, 61, 4]], "mode": "blend",
    }).status_code == 422
    # unknown image id
    assert client.post("/api/analyze/fft-mask", json={
        "image_id": "nope", "masks": [[1, 1, 1]],
    }).status_code == 404


# ── ctf ───────────────────────────────────────────────────────────────


def test_ctf_endpoint_success(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _synth_pattern())
    r = client.post("/api/analyze/ctf", json={
        "image_id": img_id, "voltage_kv": 200.0, "cs_mm": 1.2,
        "pixel_size_a": 2.0,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "defocus_a", "defocus_nm", "r_squared", "lambda_a",
        "radial_freq", "radial_power", "ctf_fit",
    ):
        assert key in body
    n = len(body["radial_freq"])
    assert n > 0
    assert len(body["radial_power"]) == n
    assert len(body["ctf_fit"]) == n
    assert body["defocus_nm"] == pytest.approx(body["defocus_a"] / 10)


def test_ctf_endpoint_unknown_id(client) -> None:
    assert client.post(
        "/api/analyze/ctf", json={"image_id": "nope"}
    ).status_code == 404


def test_ctf_endpoint_pixel_size_must_be_positive(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _synth_pattern())
    # pixel_size_a: Field(gt=0) — pydantic 422, not a calc-layer ValueError
    assert client.post("/api/analyze/ctf", json={
        "image_id": img_id, "pixel_size_a": 0,
    }).status_code == 422


# ── noise ─────────────────────────────────────────────────────────────


def test_noise_endpoint_all_methods(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _synth_pattern())
    for method in ("mad", "localvar", "both"):
        r = client.post("/api/analyze/noise", json={
            "image_id": img_id, "method": method,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["method"] == method
        assert body["sigma"] >= 0
        assert body["noise_type"] in (
            "poisson", "gaussian", "mixed", "unknown",
        )
        assert isinstance(body["recommendation"], str)
        assert body["recommendation"]


def test_noise_endpoint_bad_method(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _synth_pattern())
    assert client.post("/api/analyze/noise", json={
        "image_id": img_id, "method": "bogus",
    }).status_code == 422


def test_noise_endpoint_unknown_id(client) -> None:
    assert client.post(
        "/api/analyze/noise", json={"image_id": "nope"}
    ).status_code == 404


# ── defects ───────────────────────────────────────────────────────────


def test_defects_endpoint_default_sweep(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _synth_pattern())
    r = client.post("/api/analyze/defects", json={"image_id": img_id})
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "intersections", "test_lines", "density", "density_unit", "enhanced",
    ):
        assert key in body
    assert body["test_lines"] > 0
    assert body["density_unit"] == "lines/nm^2"
    assert client.get(
        f"/api/image/{body['enhanced']['id']}/render"
    ).status_code == 200


def test_defects_endpoint_fixed_direction(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _synth_pattern())
    r = client.post("/api/analyze/defects", json={
        "image_id": img_id, "direction": 45.0, "kernel_length": 9,
        "grid_spacing": 20,
    })
    assert r.status_code == 200, r.text


def test_defects_endpoint_unknown_id(client) -> None:
    assert client.post(
        "/api/analyze/defects", json={"image_id": "nope"}
    ).status_code == 404


def test_defects_zero_grid_spacing_is_422(tmp_path) -> None:
    """grid_spacing=0 used to reach np.arange with step 0 in
    calc/defects.py (ZeroDivisionError → unhandled 500, escaping the
    ValueError→422 guard); the ge=1 bound on DefectsRequest.grid_spacing
    now rejects it at validation like every sibling analyze/* endpoint."""
    raw_client = TestClient(create_app(), raise_server_exceptions=False)
    img_id = _open(raw_client, tmp_path, _synth_pattern())
    r = raw_client.post("/api/analyze/defects", json={
        "image_id": img_id, "grid_spacing": 0,
    })
    assert r.status_code == 422


# ── shared _raster() helper: wrong-kind + SPECTRUM_IMAGE branches ──────


def test_raster_helper_rejects_1d_spectrum(client) -> None:
    """A bare 1D SPECTRUM has no raster — every imaging_ops endpoint
    shares this 400 via the `_raster` helper; noise stands in for all."""
    ds = DataStruct(
        data=np.arange(50, dtype=np.float64),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(),),
    )
    spec_id = store.add_parsed(ds, "spec.msa")
    r = client.post("/api/analyze/noise", json={"image_id": spec_id})
    assert r.status_code == 400


def test_raster_helper_sums_spectrum_image(client) -> None:
    """A SPECTRUM_IMAGE is summed over the energy axis into a 2D raster
    (`_raster`'s SPECTRUM_IMAGE branch) rather than rejected."""
    rng = np.random.default_rng(0)
    cube = rng.normal(100.0, 5.0, size=(10, 10, 6))
    ds = DataStruct(
        data=cube, kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(), AxisCal(), AxisCal()),
    )
    si_id = store.add_parsed(ds, "si.dm4")
    r = client.post("/api/analyze/noise", json={"image_id": si_id})
    assert r.status_code == 200
    assert r.json()["sigma"] >= 0
