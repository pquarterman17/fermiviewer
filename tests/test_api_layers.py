"""Cross-section layer endpoint tests: POST /api/analyze/layers."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.special import erf

from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.imaging]

H, W = 120, 60
PX = 0.5                                   # nm/pixel
CENTERS = (30.0, 60.0, 90.0)
LEVELS = (0.2, 0.8, 0.4, 0.9)


def _layered_image() -> np.ndarray:
    y = np.arange(H, dtype=np.float64)
    prof = np.full(H, LEVELS[0])
    for c, (lo, hi) in zip(CENTERS, zip(LEVELS, LEVELS[1:], strict=False), strict=True):
        prof += (hi - lo) * 0.5 * (1 + erf((y - c) / (3 * np.sqrt(2))))
    return np.tile(prof[:, None], (1, W))   # (H, W), horizontal layers


@pytest.fixture(autouse=True)
def _clean_store():
    # `project` too: result records live in the server-carried session, so
    # without this a capture leaks into the next test's /api/results count.
    store.clear()
    project.clear()
    yield
    store.clear()
    project.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def image_id(client, tmp_path) -> str:
    img = _layered_image()
    f = write_mini_dm4(
        tmp_path / "stack.dm4", dims=[W, H],
        data=img.ravel().astype(np.float32), data_type=2,
        cal=[
            {"scale": PX, "origin": 0, "units": "nm"},
            {"scale": PX, "origin": 0, "units": "nm"},
        ],
    )
    r = client.post("/api/session/open", json={"paths": [str(f)]})
    assert r.status_code == 200
    return r.json()[0]["id"]


def test_layers_recovers_thickness_and_calibration(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={"image_id": image_id})
    assert r.status_code == 200
    body = r.json()
    assert body["axis"] == "y" and body["layers_horizontal"] is True
    assert body["unit"] == "nm" and body["pixel_size"] == pytest.approx(0.5)
    assert len(body["interfaces"]) == 3
    assert len(body["layers"]) == 2
    for lyr in body["layers"]:
        assert lyr["thickness"] == pytest.approx(15.0, abs=0.5)   # 30 px × 0.5 nm
    for it in body["interfaces"]:
        assert it["sigma_erf"] == pytest.approx(1.5, abs=0.3)     # 3 px × 0.5 nm
    assert abs(body["tilt_deg"]) < 1.5


def test_layers_n_layers_hint(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={
        "image_id": image_id, "sensitivity": 0.05, "n_layers": 3,
    })
    assert r.status_code == 200
    assert len(r.json()["interfaces"]) == 2     # keep 2 strongest


def test_layers_axis_override_finds_none(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={"image_id": image_id, "axis": "x"})
    assert r.status_code == 200
    assert r.json()["axis"] == "x"
    assert r.json()["interfaces"] == []


def test_layers_roi_restricts_depth(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={
        "image_id": image_id, "roi": [1, 1, 70, W],
    })
    assert r.status_code == 200
    assert len(r.json()["interfaces"]) == 2     # rows 1..70 → interfaces at 30, 60


def test_layers_rejects_cube(client, tmp_path) -> None:
    f = write_mini_dm4(
        tmp_path / "cube.dm4", dims=[4, 4, 8],
        data=np.ones(128, dtype=np.float32), data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"},
             {"scale": 1, "origin": 0, "units": "nm"},
             {"scale": 1, "origin": 0, "units": "eV"}],
    )
    cid = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]
    r = client.post("/api/analyze/layers", json={"image_id": cid})
    assert r.status_code == 400


def test_layers_unknown_image(client) -> None:
    r = client.post("/api/analyze/layers", json={"image_id": "nope"})
    assert r.status_code == 404


def test_layers_without_waviness_has_no_roughness_block(client, image_id) -> None:
    body = client.post("/api/analyze/layers", json={"image_id": image_id}).json()
    assert all(i["roughness"] is None for i in body["interfaces"])
    assert all(lyr["conformality"] is None for lyr in body["layers"])


def test_layers_roughness_block_and_conformality(client, tmp_path) -> None:
    """Items #9-12 over the wire: CI + quality + spectrum per interface,
    conformality per layer (both interfaces share the same waviness → r~1)."""
    from scipy.ndimage import gaussian_filter1d

    rng = np.random.default_rng(0)
    n_c, n_r = 256, 140
    jitter = gaussian_filter1d(rng.normal(0.0, 1.0, n_c), 6.0)
    jitter *= 1.5 / jitter.std()
    y = np.arange(n_r, dtype=np.float64)[:, None]
    d1, d2 = 40.0 + jitter, 95.0 + jitter
    img = (
        0.2
        + 0.6 * 0.5 * (1 + erf((y - d1[None, :]) / (2 * np.sqrt(2))))
        - 0.4 * 0.5 * (1 + erf((y - d2[None, :]) / (2 * np.sqrt(2))))
    )
    f = write_mini_dm4(
        tmp_path / "wavy.dm4", dims=[n_c, n_r],
        data=img.ravel().astype(np.float32), data_type=2,
        cal=[{"scale": PX, "origin": 0, "units": "nm"},
             {"scale": PX, "origin": 0, "units": "nm"}],
    )
    wid = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]
    r = client.post(
        "/api/analyze/layers",
        json={"image_id": wid, "waviness": True, "n_layers": 3},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["interfaces"]) == 2
    for it in body["interfaces"]:
        rb = it["roughness"]
        assert rb is not None
        assert 0.9 <= rb["quality"] <= 1.0
        assert rb["sigma_ci"] is not None
        lo, hi = rb["sigma_ci"]
        assert 0 < lo <= it["sigma_w"] <= hi
        assert len(rb["psd_wavelength"]) == len(rb["psd_power"]) > 0
        # true waviness 1.5 px x 0.5 nm/px = 0.75 nm, well inside the CI
        assert it["sigma_w"] == pytest.approx(0.75, rel=0.35)
    assert body["layers"][0]["conformality"] > 0.9


def _open_map(client, tmp_path, name: str, sig: float, px: float = PX) -> str:
    """A layered image with interfaces at CENTERS but a given erf width."""
    y = np.arange(H, dtype=np.float64)
    prof = np.full(H, LEVELS[0])
    for c, (lo, hi) in zip(CENTERS, zip(LEVELS, LEVELS[1:], strict=False), strict=True):
        prof += (hi - lo) * 0.5 * (1 + erf((y - c) / (sig * np.sqrt(2))))
    img = np.tile(prof[:, None], (1, W))
    f = write_mini_dm4(
        tmp_path / f"{name}.dm4", dims=[W, H],
        data=img.ravel().astype(np.float32), data_type=2,
        cal=[{"scale": px, "origin": 0, "units": "nm"},
             {"scale": px, "origin": 0, "units": "nm"}],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def test_layers_multi_per_element_sigma(client, tmp_path) -> None:
    sharp = _open_map(client, tmp_path, "sharp", 2.0)
    diffuse = _open_map(client, tmp_path, "diffuse", 5.0)
    r = client.post("/api/analyze/layers/multi", json={
        "image_ids": [sharp, diffuse], "reference": 0,
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["maps"]) == 2
    assert len(body["reference_positions"]) == 3
    # the diffuse map has wider σ_erf at the shared interfaces than the sharp one
    sharp_sig = np.mean([i["sigma_erf"] for i in body["maps"][0]["interfaces"]])
    diffuse_sig = np.mean([i["sigma_erf"] for i in body["maps"][1]["interfaces"]])
    assert diffuse_sig > sharp_sig * 1.5


def test_layers_multi_honors_roi_and_reports_reference(client, tmp_path) -> None:
    sharp = _open_map(client, tmp_path, "sharp-roi", 2.0)
    diffuse = _open_map(client, tmp_path, "diffuse-roi", 5.0)
    roi = [10, 1, 110, W]
    r = client.post("/api/analyze/layers/multi", json={
        "image_ids": [diffuse, sharp],
        "reference": 1,
        "roi": roi,
        "axis": "y",
        "sensitivity": 0.25,
        "n_layers": 4,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reference_id"] == sharp
    assert body["roi"] == roi
    assert len(body["reference_positions"]) == 3


def test_layers_multi_calibration_mismatch_422(client, tmp_path) -> None:
    reference = _open_map(client, tmp_path, "cal-ref", 2.0)
    mismatched = _open_map(client, tmp_path, "cal-other", 2.0, px=PX * 2)
    r = client.post("/api/analyze/layers/multi", json={
        "image_ids": [reference, mismatched],
    })
    assert r.status_code == 422
    assert "incompatible spatial calibration" in r.json()["detail"]


def test_layers_multi_shape_mismatch_422(client, tmp_path, image_id) -> None:
    other = _open_map(client, tmp_path, "other", 3.0)
    # `image_id` is 120×60; build a different-shaped one
    small = write_mini_dm4(
        tmp_path / "small.dm4", dims=[10, 10],
        data=np.ones(100, dtype=np.float32), data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"},
             {"scale": 1, "origin": 0, "units": "nm"}],
    )
    small_id = client.post("/api/session/open", json={"paths": [str(small)]}).json()[0]["id"]
    r = client.post("/api/analyze/layers/multi", json={"image_ids": [other, small_id]})
    assert r.status_code == 422


def test_layers_multi_empty_422(client) -> None:
    r = client.post("/api/analyze/layers/multi", json={"image_ids": []})
    assert r.status_code == 422


def test_layers_multi_nan_comparison_map_is_422_not_500(client, tmp_path) -> None:
    """A non-reference map's own recompute_layers() call was unwrapped: a
    few NaN pixels make calc.layers.cross_section_profile raise ValueError
    (non-finite values in the ROI), which escaped as an unhandled 500
    instead of the 422 every other calc call in this route already gets."""
    sharp = _open_map(client, tmp_path, "sharp-nan", 2.0)
    y = np.arange(H, dtype=np.float64)
    prof = np.full(H, LEVELS[0])
    for c, (lo, hi) in zip(CENTERS, zip(LEVELS, LEVELS[1:], strict=False), strict=True):
        prof += (hi - lo) * 0.5 * (1 + erf((y - c) / (2.0 * np.sqrt(2))))
    img = np.tile(prof[:, None], (1, W))
    rng = np.random.default_rng(0)
    img[rng.random(img.shape) < 0.01] = np.nan
    f = write_mini_dm4(
        tmp_path / "nanmap.dm4", dims=[W, H],
        data=img.ravel().astype(np.float32), data_type=2,
        cal=[{"scale": PX, "origin": 0, "units": "nm"},
             {"scale": PX, "origin": 0, "units": "nm"}],
    )
    nanmap = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]

    r = client.post("/api/analyze/layers/multi", json={
        "image_ids": [sharp, nanmap], "reference": 0,
    })
    assert r.status_code == 422, r.text


def _tilted_image_id(client, tmp_path, tilt_deg: float) -> str:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    a = np.radians(tilt_deg)
    d = (yy - H / 2) * np.cos(a) + (xx - W / 2) * np.sin(a) + H / 2
    out = np.full_like(d, LEVELS[0])
    for c, (lo, hi) in zip(CENTERS, zip(LEVELS, LEVELS[1:], strict=False), strict=True):
        out += (hi - lo) * 0.5 * (1 + erf((d - c) / (3 * np.sqrt(2))))
    f = write_mini_dm4(
        tmp_path / "tilted.dm4", dims=[W, H],
        data=out.ravel().astype(np.float32), data_type=2,
        cal=[{"scale": PX, "origin": 0, "units": "nm"},
             {"scale": PX, "origin": 0, "units": "nm"}],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def test_layers_level_via_rotate(client, tmp_path) -> None:
    tid = _tilted_image_id(client, tmp_path, 6.0)
    before = client.post("/api/analyze/layers", json={"image_id": tid}).json()
    assert abs(before["tilt_deg"]) > 3.0
    # rotate by +tilt to level (arbitrary-angle rotate op, same dims)
    leveled = client.post("/api/filter", json={
        "image_id": tid, "kind": "rotate", "params": {"angle": before["tilt_deg"]},
    })
    assert leveled.status_code == 200
    lid = leveled.json()["id"]
    after = client.post("/api/analyze/layers", json={"image_id": lid}).json()
    assert abs(after["tilt_deg"]) < abs(before["tilt_deg"]) / 2   # noticeably more level


def test_layers_waviness_returns_sigma_w_and_trace(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={
        "image_id": image_id, "waviness": True,
    })
    assert r.status_code == 200
    body = r.json()
    # flat synthetic layers → ~zero waviness, but the fields are populated
    for it in body["interfaces"]:
        assert it["sigma_w"] is not None
        assert isinstance(it["trace"], list) and len(it["trace"]) == W
    for lyr in body["layers"]:
        assert lyr["thickness_std"] is not None


def test_layers_no_waviness_leaves_fields_null(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={"image_id": image_id})
    body = r.json()
    assert all(it["sigma_w"] is None and it["trace"] is None for it in body["interfaces"])


def test_layers_edit_recomputes_from_positions(client, image_id) -> None:
    r = client.post("/api/analyze/layers/edit", json={
        "image_id": image_id, "positions": [30.0, 90.0], "axis": "y",
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["interfaces"]) == 2
    assert len(body["layers"]) == 1
    # 30→90 px × 0.5 nm = 30 nm
    assert body["layers"][0]["thickness"] == pytest.approx(30.0, abs=0.5)


def test_layers_edit_drops_out_of_range(client, image_id) -> None:
    r = client.post("/api/analyze/layers/edit", json={
        "image_id": image_id, "positions": [30.0, 9999.0], "axis": "y",
    })
    assert r.status_code == 200
    assert len(r.json()["interfaces"]) == 1


def test_layers_edit_bad_axis_422(client, image_id) -> None:
    r = client.post("/api/analyze/layers/edit", json={
        "image_id": image_id, "positions": [30.0], "axis": "auto",
    })
    assert r.status_code == 422


def test_layers_bf_modality_runs(client, image_id) -> None:
    # the clean synthetic stack still resolves under BF scale-space detection
    r = client.post("/api/analyze/layers", json={
        "image_id": image_id, "modality": "bf",
    })
    assert r.status_code == 200
    assert len(r.json()["interfaces"]) == 3


def _curtained_image_id(client, tmp_path) -> str:
    """A layered stack with localised bright FIB curtains in ~1/8 of columns."""
    img = _layered_image()
    rng = np.random.default_rng(7)
    bad = rng.choice(W, size=W // 8, replace=False)
    yy = np.arange(H, dtype=np.float64)[:, None]
    img[:, bad] += 4.0 * np.exp(-0.5 * ((yy - 45.0) / 3.0) ** 2)   # streak @ depth 45
    f = write_mini_dm4(
        tmp_path / "curtained.dm4", dims=[W, H],
        data=img.ravel().astype(np.float32), data_type=2,
        cal=[{"scale": PX, "origin": 0, "units": "nm"},
             {"scale": PX, "origin": 0, "units": "nm"}],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def test_layers_median_destripe_recovers_through_curtains(client, tmp_path) -> None:
    cid = _curtained_image_id(client, tmp_path)
    naive = client.post("/api/analyze/layers", json={"image_id": cid}).json()
    robust = client.post("/api/analyze/layers", json={
        "image_id": cid, "reduce": "median", "destripe": True,
    }).json()
    assert len(robust["interfaces"]) == 3                       # real layers recovered
    assert len(naive["interfaces"]) > len(robust["interfaces"])  # mean is fooled
    for lyr in robust["layers"]:
        assert lyr["thickness"] == pytest.approx(15.0, abs=1.0)


def test_layers_edit_accepts_destripe(client, tmp_path) -> None:
    cid = _curtained_image_id(client, tmp_path)
    r = client.post("/api/analyze/layers/edit", json={
        "image_id": cid, "positions": [30.0, 60.0, 90.0], "axis": "y",
        "reduce": "median", "destripe": True,
    })
    assert r.status_code == 200
    assert len(r.json()["interfaces"]) == 3


def test_layers_invalid_reduce_422(client, image_id) -> None:
    r = client.post("/api/analyze/layers", json={
        "image_id": image_id, "reduce": "bogus",
    })
    assert r.status_code == 422


def _open_map_with_units(
    client, tmp_path, name: str, sig: float, *, scale: float, units: str
) -> str:
    """`_open_map`, but with the calibration UNIT under test — the collision
    below needs a reference calibrated in "px" at exactly 1.0, which is what
    an uncalibrated map is indistinguishable from once a default is applied."""
    y = np.arange(H, dtype=np.float64)
    prof = np.full(H, LEVELS[0])
    for c, (lo, hi) in zip(CENTERS, zip(LEVELS, LEVELS[1:], strict=False), strict=True):
        prof += (hi - lo) * 0.5 * (1 + erf((y - c) / (sig * np.sqrt(2))))
    img = np.tile(prof[:, None], (1, W))
    f = write_mini_dm4(
        tmp_path / f"{name}.dm4", dims=[W, H],
        data=img.ravel().astype(np.float32), data_type=2,
        cal=[{"scale": scale, "origin": 0, "units": units},
             {"scale": scale, "origin": 0, "units": units}],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def test_layers_multi_route_and_op_both_reject_an_uncalibrated_map(
    client, tmp_path
) -> None:
    """Route/op parity on the calibrated-vs-uncalibrated collision.

    An uncalibrated map defaulted to (1.0, "px") is INDISTINGUISHABLE from a
    genuinely calibrated 1.0 px/px reference once the default is applied, so
    the op has to pass the raw calibration into the check — otherwise it
    accepts a pair the route rejects and compares σ_erf/σ_w across two maps
    that share no physical scale.
    """
    import fermiviewer.ops as ops
    from fermiviewer.calc.layers_multi import MapCalibrationError

    reference = _open_map_with_units(
        client, tmp_path, "px-cal-ref", 2.0, scale=1.0, units="px"
    )
    uncalibrated = _open_map_with_units(
        client, tmp_path, "px-uncal", 2.0, scale=1.0, units=""
    )
    ref_ds, other_ds = store.get(reference), store.get(uncalibrated)
    # the collision: the reference is GENUINELY calibrated at 1.0 px/px, and
    # the uncalibrated map defaults to the very same (1.0, "px") pair
    assert (ref_ds.pixel_size, ref_ds.pixel_unit) == (1.0, "px")
    assert not np.isfinite(other_ds.pixel_size)
    assert other_ds.pixel_unit == ""

    r = client.post("/api/analyze/layers/multi", json={
        "image_ids": [reference, uncalibrated],
    })
    assert r.status_code == 422
    assert "incompatible spatial calibration" in r.json()["detail"]

    with pytest.raises(MapCalibrationError, match="incompatible spatial calibration"):
        ops.run("layers_multi", ref_ds, {"axis": "y"}, inputs={"others": [other_ds]})


# ── ADR 0004 result records ──────────────────────────────────────────


def test_layers_records_nothing_unless_asked(client, image_id) -> None:
    """Sweeping `sensitivity` must not fill the results panel with runs the
    user never meant to keep — the same default `/measure/profile` takes."""
    r = client.post("/api/analyze/layers", json={"image_id": image_id})
    assert r.status_code == 200
    assert "result" not in r.json()
    assert client.get("/api/results").json()["results"] == []


def test_layers_captures_the_profile_it_measured_not_only_the_answer(
    client, image_id
) -> None:
    """The layer table is the conclusion; the depth profile is the evidence.

    A record holding only thicknesses cannot be checked — a reader has no
    way to see whether an interface sits on a real step or on noise. So the
    curve the detector actually ran on is persisted beside the tables.
    """
    r = client.post(
        "/api/analyze/layers", json={"image_id": image_id, "record": True}
    )
    assert r.status_code == 200
    body = r.json()
    result_id = body["result"]["id"]

    entry = client.get(f"/api/results/{result_id}").json()
    assert entry["analysis"] == "analyze.layers"
    assert entry["status"] == "completed"
    assert entry["missing_members"] == []
    assert "record" not in entry["params"]            # never the toggle itself
    assert entry["params"]["interface_origin"] == "detected"

    names = {o["name"]: o for o in entry["outputs"]}
    assert set(names) >= {
        "layers", "interfaces", "depth_profile",
        "n_layers", "tilt_deg", "orientation_coherence",
    }
    assert names["n_layers"]["data"]["value"] == len(body["layers"])

    curve = names["depth_profile"]
    data = client.get(
        f"/api/results/{result_id}/outputs/"
        f"{entry['outputs'].index(curve)}/data"
    ).json()
    # one (depth, intensity) pair per profile sample — the same curve the
    # on-screen plot draws, not a summary of it
    assert data["shape"] == [len(body["depth_profile"]), 2]
    assert data["values"][0][1] == pytest.approx(body["depth_profile"][0])

    ifaces = names["interfaces"]
    idata = client.get(
        f"/api/results/{result_id}/outputs/"
        f"{entry['outputs'].index(ifaces)}/data"
    ).json()
    assert idata["shape"] == [len(body["interfaces"]), 5]
    positions = [row[1] for row in idata["values"]]
    assert positions == pytest.approx(
        [i["position"] for i in body["interfaces"]], abs=1e-9
    )
    # σ_w is absent without `waviness`, and absent means null — a 0 there
    # would read as a perfectly flat interface (ADR 0004 §3)
    assert all(row[3] is None for row in idata["values"])


def test_an_edited_run_is_a_second_record_not_an_overwrite(
    client, image_id
) -> None:
    """The gap between where the detector put an interface and where the
    operator put it IS the finding — it says the automatic method could not
    be trusted here. Replacing the first record would erase exactly that.
    """
    detected = client.post(
        "/api/analyze/layers", json={"image_id": image_id, "record": True}
    ).json()
    moved = [i["position"] + 4.0 for i in detected["interfaces"]]
    edited = client.post(
        "/api/analyze/layers/edit",
        json={
            "image_id": image_id, "positions": moved,
            "axis": detected["axis"], "record": True,
        },
    )
    assert edited.status_code == 200

    entries = client.get("/api/results").json()["results"]
    assert len(entries) == 2
    origins = [e["params"]["interface_origin"] for e in entries]
    assert sorted(origins) == ["detected", "edited"]

    edit_entry = next(e for e in entries if e["params"]["interface_origin"] == "edited")
    # what the operator ASKED for is recorded, not merely what the refit
    # settled on — otherwise the record cannot show the disagreement
    assert edit_entry["params"]["given_positions"] == pytest.approx(moved)
    detect_entry = next(
        e for e in entries if e["params"]["interface_origin"] == "detected"
    )
    assert "given_positions" not in detect_entry["params"]


def test_an_uncalibrated_image_says_so_rather_than_implying_nanometres(
    client, tmp_path
) -> None:
    f = write_mini_dm4(
        tmp_path / "raw.dm4", dims=[W, H],
        data=_layered_image().ravel().astype(np.float32), data_type=2,
    )
    img = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]
    body = client.post(
        "/api/analyze/layers", json={"image_id": img, "record": True}
    ).json()
    entry = client.get(f"/api/results/{body['result']['id']}").json()
    assert any("not calibrated units" in w for w in entry["warnings"])


def test_the_route_distinguishes_a_measured_tilt_from_an_applied_one(
    client, image_id
) -> None:
    """`tilt_deg` describes the specimen; `applied_tilt_deg` changes every
    number in the response. Reporting only one would leave a reader unable
    to tell whether a correction had happened."""
    plain = client.post("/api/analyze/layers", json={"image_id": image_id}).json()
    assert plain["applied_tilt_deg"] is None
    assert plain["sampled_fraction"] == pytest.approx(1.0)

    tilted = client.post(
        "/api/analyze/layers", json={"image_id": image_id, "tilt_deg": 8.0}
    )
    assert tilted.status_code == 200
    body = tilted.json()
    assert body["applied_tilt_deg"] == pytest.approx(8.0)
    # the rotated box had to shrink to stay inside the ROI, and the response
    # says by how much rather than quietly returning a shorter profile
    assert body["sampled_fraction"] < 1.0
    assert len(body["depth_profile"]) < len(plain["depth_profile"])


def test_a_tilt_that_does_not_fit_is_a_422_not_a_silent_narrowing(
    client, image_id
) -> None:
    """A steep tilt on a NARROW strip leaves no box to average over.

    It takes a thin ROI to get there: on the full 120x60 frame even 80 deg
    still leaves 28 lateral pixels, so the refusal is about the box running
    out, not about the angle being large. Returning a one-pixel-wide
    "profile" instead would be a line sample wearing an average's name.
    """
    r = client.post(
        "/api/analyze/layers",
        json={"image_id": image_id, "roi": [1, 1, H, 5], "tilt_deg": 80.0},
    )
    assert r.status_code == 422
    assert "lateral pixels" in r.json()["detail"]
