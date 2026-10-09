"""AFM/SPM levelling (calc/afm_level.py), its /filter kinds and ops, and
opening a NanoScope scan's other channels."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer import ops
from fermiviewer.calc import afm_level as al
from fermiviewer.calc.colormaps import COLORMAP_NAMES, build_lut
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.server import ALLOWED_HOSTS, create_app
from fermiviewer.session import store

ALLOWED_HOSTS.add("testserver")
REAL = Path("/home/user/test-data/bruker/afm/topostats_plasmids.spm")


def _scan(seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Tilted surface + per-line offsets + noise, with one particle.
    Returns (scan, particle mask)."""
    rng = np.random.default_rng(seed)
    h, w = 64, 128
    yy, xx = np.mgrid[0:h, 0:w]
    img = 0.02 * xx + 0.01 * yy + rng.normal(0, 2, h)[:, None]
    img = img + rng.normal(0, 0.05, (h, w))
    particle = np.zeros((h, w), dtype=bool)
    particle[20:30, 40:70] = True
    img[particle] += 10
    return img, particle


@pytest.mark.parametrize("method", ["median", "mdiff"])
def test_row_levelling_removes_line_offsets_despite_a_particle(method) -> None:
    img, particle = _scan()
    out = al.level_rows(al.level_plane(img, fit_percentile=70), method)
    base = np.where(particle, np.nan, out)
    assert np.nanstd(np.nanmedian(base, axis=1)) < 0.05      # rows now agree
    assert np.ptp(out[particle]) < 2 and out[particle].mean() > 8  # particle kept


def test_row_poly_removes_a_per_line_tilt() -> None:
    h, w = 16, 64
    x = np.arange(w)
    img = np.array([(r * 0.3) * (x / w) + r for r in range(h)], dtype=float)
    assert np.abs(al.level_rows(img, "poly", order=1)).max() < 1e-9


def test_base_only_plane_fit_is_not_tilted_by_a_tall_feature() -> None:
    rng = np.random.default_rng(2)
    yy, xx = np.mgrid[0:64, 0:128]
    particle = np.zeros((64, 128), dtype=bool)
    particle[10:40, 80:120] = True
    tilted = 0.05 * xx + 0.02 * yy + rng.normal(0, 0.05, (64, 128)) + 10 * particle
    full = al.level_plane(tilted)
    base = al.level_plane(tilted, fit_percentile=70)
    assert np.std(full[~particle]) > 0.3          # the particle tilted the plain fit
    assert np.std(base[~particle]) < 0.07         # the base fit is flat to the noise
    assert abs(base[particle].mean() - 10) < 0.1  # particle height preserved


def test_scars_are_found_and_repaired() -> None:
    rng = np.random.default_rng(1)
    img = rng.normal(0, 0.1, (40, 80))
    img[12, 5:70] += 3                                         # one-line scar
    img[25:27, 10:60] -= 4                                     # two-line scar
    res = al.remove_scars(img, threshold=3, max_width=2, min_length=8)
    assert res.scar_mask[12, 5:70].all() and res.scar_mask[25:27, 10:60].all()
    assert np.abs(res.corrected).max() < 1.0
    assert res.n_pixels == 65 + 100


def test_short_bumps_are_not_scars() -> None:
    img = np.zeros((20, 50))
    img[10, 20:24] = 5                                          # 4 px: a feature
    assert al.remove_scars(img, min_length=8).n_pixels == 0


def test_three_point_and_zero() -> None:
    yy, xx = np.mgrid[0:50, 0:60]
    plane = 3 + 0.2 * xx - 0.1 * yy
    out = al.level_three_point(plane, [(0, 0), (0, 59), (49, 30)])
    assert np.abs(out).max() < 1e-9
    with pytest.raises(ValueError, match="one line"):
        al.level_three_point(plane, [(0, 0), (10, 10), (20, 20)])
    assert al.zero_level(plane, "min").min() == 0
    assert abs(np.median(al.zero_level(plane, "median"))) < 1e-12


def test_nan_pixels_stay_nan_and_never_poison_the_fit() -> None:
    img, _ = _scan()
    img[5, 5] = np.nan
    for out in (al.level_plane(img, order=2), al.level_rows(img, "mdiff"),
                al.level_rows(img, "poly")):
        assert np.isnan(out[5, 5]) and np.isfinite(np.delete(out.ravel(), 5 * 128 + 5)).all()


def test_ops_keep_the_height_unit() -> None:
    img, _ = _scan()
    ds = DataStruct(data=img, kind=DataKind.IMAGE,
                    axes=(AxisCal(2.0, 0, "nm"), AxisCal(2.0, 0, "nm")),
                    metadata={"value_unit": "nm", "channel": "Height"})
    for name, params in [("plane_level", {"order": 3, "fit_percentile": 50}),
                         ("row_level", {"method": "mdiff"}), ("scar_removal", {}),
                         ("zero_level", {"mode": "mean"}), ("gaussian", {})]:
        assert ops.run(name, ds, params).derived.metadata["value_unit"] == "nm"
    assert "value_unit" not in ops.run("multiotsu", ds, {}).derived.metadata
    assert ops.run("roughness", ds, {}).value["unit"] == "nm"


def test_afmhot_is_a_known_colormap() -> None:
    assert "afmhot" in COLORMAP_NAMES
    lut = build_lut("afmhot")
    assert tuple(lut[0]) == (0, 0, 0) and tuple(lut[-1]) == (255, 255, 255)


# ── HTTP: /filter kinds and channel access ────────────────────────────

@pytest.fixture()
def client():
    store.clear()
    yield TestClient(create_app())
    store.clear()


def _height_image(client: TestClient) -> str:
    img, _ = _scan()
    ds = DataStruct(data=img, kind=DataKind.IMAGE,
                    axes=(AxisCal(2.0, 0, "nm"), AxisCal(2.0, 0, "nm")),
                    metadata={"value_unit": "nm"})
    return store.add_parsed(ds, "scan.spm")


@pytest.mark.parametrize("kind,params", [
    ("plane_level", {"order": "2", "fit_percentile": 80}),
    ("row_level", {"method": "poly", "order": 2}),
    ("scar_removal", {"threshold": 4}),
    ("zero_level", {"mode": "median"}),
    ("three_point_level", {"points": [[1, 1], [1, 100], [60, 50]]}),
])
def test_filter_kinds_keep_nm(client, kind, params) -> None:
    r = client.post("/api/filter", json={"image_id": _height_image(client),
                                         "kind": kind, "params": params})
    assert r.status_code == 200, r.text
    assert r.json()["value_unit"] == "nm"


def test_three_point_level_accepts_the_bottom_right_edge_pixels(client) -> None:
    """Points on the last row/column (what the menu sends for a click stored
    at normalized x or y = 1) are inside a 64×128 image."""
    r = client.post("/api/filter", json={
        "image_id": _height_image(client), "kind": "three_point_level",
        "params": {"points": [[63, 127], [63, 0], [0, 127]]}})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("kind,params,msg", [
    ("row_level", {"method": "sideways"}, "method"),
    ("plane_level", {"order": 4}, "order"),
    ("plane_level", {"fit_percentile": 0}, "percentile"),
    ("three_point_level", {"points": [[1, 1]]}, "3 points"),
])
def test_bad_levelling_params_are_422(client, kind, params, msg) -> None:
    r = client.post("/api/filter", json={"image_id": _height_image(client),
                                         "kind": kind, "params": params})
    assert r.status_code == 422 and msg in r.text


def test_plane_level_filter_no_longer_fails_on_nan(client) -> None:
    img, _ = _scan()
    img[0, 0] = np.nan
    img_id = store.add_parsed(DataStruct(data=img, kind=DataKind.IMAGE,
                                         axes=(AxisCal(), AxisCal()), metadata={}), "n")
    r = client.post("/api/filter", json={"image_id": img_id, "kind": "plane_level"})
    assert r.status_code == 200, r.text


def test_other_channels_need_a_nanoscope_scan(client) -> None:
    r = client.post(f"/api/afm/{_height_image(client)}/channels")
    assert r.status_code == 422


@pytest.mark.skipif(not REAL.exists(), reason="Bruker sample corpus not present")
def test_open_other_channels_from_disk_and_upload(client) -> None:
    meta = client.post("/api/session/open", json={"paths": [str(REAL)]}).json()[0]
    first = client.post(f"/api/afm/{meta['id']}/channels").json()
    names = [m["name"] for m in first]
    assert len(names) == 7 and any("DMTModulus (retrace)" in n for n in names)
    assert client.post(f"/api/afm/{meta['id']}/channels").json() == []
    with REAL.open("rb") as f:
        up = client.post("/api/session/upload",
                         files=[("files", ("u.spm", f, "application/octet-stream"))]).json()[0]
    assert len(client.post(f"/api/afm/{up['id']}/channels").json()) == 7
