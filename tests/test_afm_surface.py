"""AFM surface analysis: ISO 25178 parameters, 2-D PSD/ACF, histograms
(calc/afm_surface.py), step height and region heights
(calc/afm_features.py), their ops and routes."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import ndimage

from fermiviewer import ops
from fermiviewer.calc import afm_features as feat
from fermiviewer.calc import afm_surface as surf
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops.catalogue_afm import z_to_lateral
from fermiviewer.server import ALLOWED_HOSTS, create_app
from fermiviewer.session import store

ALLOWED_HOSTS.add("testserver")
YY, XX = np.mgrid[0:128, 0:256].astype(float)


def _grooves(angle_deg: float, period: float) -> np.ndarray:
    """Sinusoidal grooves whose LAY runs at `angle_deg` (screen CCW from +x)."""
    t = np.radians(angle_deg)
    # distance across the lay: along the normal (−sin t, −cos t) in (x, row)
    return np.sin(2 * np.pi * (-XX * np.sin(t) - YY * np.cos(t)) / period)


def _ds(z, unit="nm", px=2.0, lat="nm") -> DataStruct:
    return DataStruct(data=z, kind=DataKind.IMAGE,
                      axes=(AxisCal(px, 0, lat), AxisCal(px, 0, lat)),
                      metadata={"value_unit": unit} if unit else {})


# ── spectra, correlation, texture ─────────────────────────────────────

def test_psd_integrates_to_the_variance_and_peaks_at_the_period() -> None:
    z = _grooves(0, 16)
    psd, fy, fx = surf.psd_2d(z, 0.5, 0.5)
    assert psd.sum() * (fy[1] - fy[0]) * (fx[1] - fx[0]) == pytest.approx(z.var(), rel=1e-3)
    f, p = surf.radial_psd(psd, fy, fx)
    assert f[np.argmax(p)] == pytest.approx(1 / (16 * 0.5), rel=0.1)


@pytest.mark.parametrize("angle", [0, 30, 90, 135])
def test_texture_direction_follows_the_lay(angle) -> None:
    std = surf.areal_parameters(_grooves(angle, 12)).std
    assert min(abs(std - angle), 180 - abs(std - angle)) < 1.0


def test_grooves_are_strongly_textured_and_noise_is_isotropic() -> None:
    p = surf.areal_parameters(_grooves(0, 16))
    assert p.str_ == 0.0                                    # never decays along the lay
    assert p.sal == pytest.approx(np.arccos(0.2) / (2 * np.pi) * 16, rel=0.02)
    iso = ndimage.gaussian_filter(np.random.default_rng(0).normal(size=(256, 256)), 4)
    assert surf.areal_parameters(iso).str_ > 0.8


def test_acf_ignores_missing_pixels() -> None:
    z = _grooves(0, 16)
    z[40:50, 100:140] = np.nan
    acf = surf.acf_2d(z)
    n, w = z.shape
    assert acf[n - 1, w - 1] == pytest.approx(1.0)
    assert acf[n - 1 + 8, w - 1] == pytest.approx(-1.0, abs=0.02)    # half a period


# ── height and hybrid parameters ──────────────────────────────────────

def test_height_parameters_of_a_sine() -> None:
    p = surf.areal_parameters(_grooves(0, 16))
    assert p.sq == pytest.approx(1 / np.sqrt(2), rel=1e-3)
    assert p.sa == pytest.approx(2 / np.pi, rel=2e-2)
    assert p.sku == pytest.approx(1.5, rel=1e-3) and abs(p.ssk) < 1e-6
    assert p.sz == pytest.approx(2.0, rel=1e-6)


def test_slopes_need_heights_and_lateral_distances_in_one_unit() -> None:
    tilt = 0.1 * XX * 2.0                       # 0.1 nm per nm on a 2 nm grid
    p = surf.areal_parameters(tilt, 2.0, 2.0, z_to_lateral=1.0)
    assert p.sdq == pytest.approx(0.1, rel=1e-6)
    assert p.sdr == pytest.approx(100 * (np.sqrt(1.01) - 1), rel=1e-6)
    assert np.isnan(surf.areal_parameters(tilt, 2.0, 2.0).sdq)       # unknown units
    # heights in µm over an nm grid convert by 1000
    assert z_to_lateral(_ds(tilt, unit="µm")) == pytest.approx(1000)
    assert np.isnan(z_to_lateral(_ds(tilt, unit="V")))
    assert np.isnan(z_to_lateral(_ds(tilt, lat="")))


def test_histograms() -> None:
    z = 0.1 * XX * 2.0
    hx, hy = surf.height_histogram(z, bins=10)
    assert hy.sum() == pytest.approx(100) and hx.size == 10
    sx, sy = surf.slope_histogram(z, 2.0, 2.0, 1.0)
    assert sx[np.argmax(sy)] == pytest.approx(np.degrees(np.arctan(0.1)), abs=1.0)
    assert surf.slope_histogram(z, 2.0, 2.0, float("nan"))[0].size == 0


# ── step height and region heights ────────────────────────────────────

@pytest.mark.parametrize("z,expect", [
    (0.01 * XX + 0.02 * YY + 5 * (XX > 100), 5.0),          # step dominates the tilt
    (0.05 * XX + 3 * (YY > 60), 3.0),                       # tilt dominates the step
    (-(0.05 * XX + 3 * (YY > 60)), 3.0),                    # a step down
])
def test_step_height_is_independent_of_tilt(z, expect) -> None:
    rng = np.random.default_rng(0)
    s = feat.step_height(z + rng.normal(0, 0.1, z.shape))
    assert s.height == pytest.approx(expect, abs=0.02)
    assert s.lower_std == pytest.approx(0.1, rel=0.1) and s.upper_std == pytest.approx(0.1, rel=0.1)


def test_step_height_refuses_a_flat_region() -> None:
    with pytest.raises(ValueError, match="flat"):
        feat.step_height(np.zeros((20, 20)))


def test_region_heights_measure_from_the_local_substrate() -> None:
    z = np.full((40, 60), 2.0)                     # substrate at 2
    z[10:20, 10:20] += 5                           # a 5-high box
    z[25:35, 40:50] += 1                           # a 1-high box
    labels = np.zeros(z.shape, dtype=int)
    labels[10:20, 10:20] = 1
    labels[25:35, 40:50] = 2
    rh = feat.region_heights(labels, z, pixel_area=4.0)
    np.testing.assert_allclose(rh.max_height, [7, 3])
    np.testing.assert_allclose(rh.height_above_base, [5, 1])
    np.testing.assert_allclose(rh.volume_above_base, [5 * 100 * 4, 1 * 100 * 4])


# ── ops and routes ────────────────────────────────────────────────────

def test_ops() -> None:
    ds = _ds(_grooves(0, 16))
    v = ops.run("surface_texture", ds, {"level": "none"}).value
    assert v["Sq"] == pytest.approx(1 / np.sqrt(2), rel=1e-3) and v["unit"] == "nm"
    step = ops.run("step_height", _ds(3.0 * (YY > 60)), {}).value
    assert step["height"] == pytest.approx(3.0)


@pytest.fixture()
def client():
    store.clear()
    yield TestClient(create_app())
    store.clear()


def test_surface_route(client) -> None:
    img = store.add_parsed(_ds(_grooves(30, 12)), "g.spm")
    r = client.post(f"/api/afm/{img}/surface", json={"level": "plane"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["units"]["Sa"] == "nm" and body["units"]["Sal"] == "nm"
    assert abs(body["params"]["Std"] - 30) < 1.0 and body["slopes_calibrated"]
    assert len(body["psd"]["frequency"]) == len(body["psd"]["power"]) > 10
    assert sum(body["height_hist"]["percent"]) == pytest.approx(100)
    roi = client.post(f"/api/afm/{img}/surface", json={"roi": [1, 1, 64, 64]}).json()
    assert roi["n_pixels"] == 64 * 64


@pytest.mark.parametrize("kind", ["psd", "acf"])
def test_map_route_registers_an_image(client, kind) -> None:
    img = store.add_parsed(_ds(_grooves(0, 16)), "g.spm")
    r = client.post(f"/api/afm/{img}/map", json={"kind": kind})
    assert r.status_code == 200, r.text
    assert r.json()["name"].startswith(kind.upper())


def test_step_route(client) -> None:
    img = store.add_parsed(_ds(0.05 * XX + 3 * (YY > 60)), "s.spm")
    r = client.post(f"/api/afm/{img}/step-height", json={"roi": [40, 1, 80, 256]})
    assert r.status_code == 200, r.text
    assert r.json()["height"] == pytest.approx(3.0, abs=0.01) and r.json()["unit"] == "nm"
    flat = store.add_parsed(_ds(np.zeros((20, 20))), "f.spm")
    assert client.post(f"/api/afm/{flat}/step-height", json={}).status_code == 422


def _bumps(unit: str | None) -> str:
    z = np.zeros((64, 64))
    z[10:20, 10:20] = 4.0
    z[40:50, 30:45] = 2.0
    return store.add_parsed(_ds(z, unit=unit), "bumps")


def test_particles_carry_heights_only_for_height_maps(client) -> None:
    afm = client.post("/api/analyze/particles",
                      json={"image_id": _bumps("nm"), "threshold": 1.0}).json()
    rows = sorted(afm["particles"], key=lambda p: p["area"])
    assert [p["height_above_base"] for p in rows] == [4.0, 2.0]
    assert rows[0]["volume"] == pytest.approx(4.0 * 100 * 4.0)      # 2 nm pixels
    assert afm["volume_unit"] == "nm³" and afm["height_unit"] == "nm"
    em = client.post("/api/analyze/particles",
                     json={"image_id": _bumps(None), "threshold": 1.0}).json()
    assert "volume_unit" not in em and "volume" not in em["particles"][0]


def test_grains_carry_heights_for_height_maps(client) -> None:
    r = client.post("/api/analyze/grains", json={"image_id": _bumps("nm"), "min_area": 4})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["max_height"]) == body["n_grains"] and body["volume_unit"] == "nm³"
