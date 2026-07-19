"""API tests for the item-28 analysis surface (imaging_ops + structure).

Calc-level numerics are golden-tested elsewhere; these verify the wire
contracts: request validation, derived-image registration, JSON shapes.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

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


def _open(client, tmp_path, data: np.ndarray, name: str = "img.dm4") -> str:
    h, w = data.shape
    f = write_mini_dm4(
        tmp_path / name, dims=[w, h], data=data.ravel(),
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


@pytest.fixture()
def lattice_id(client, tmp_path) -> str:
    x = np.arange(96, dtype=np.float64)[None, :]
    y = np.arange(64, dtype=np.float64)[:, None]
    latt = (
        np.cos(2 * np.pi * 12 * x / 96) + np.cos(2 * np.pi * 10 * y / 64)
    )
    scaled = ((latt + 2) * 1000).astype(np.int64)
    return _open(client, tmp_path, scaled.astype(np.float64))


def test_gpa_endpoint(client, lattice_id) -> None:
    r = client.post(
        "/api/analyze/gpa",
        json={"image_id": lattice_id, "g1": [12, 0], "g2": [0, 10]},
    )
    assert r.status_code == 200
    body = r.json()
    assert [m["name"].split("(")[0] for m in body["maps"]] == [
        "exx", "eyy", "exy", "rotation",
    ]
    for m in body["maps"]:  # registered + renderable
        assert client.get(f"/api/image/{m['id']}/render").status_code == 200
    assert abs(body["mean"]["exx"]) < 0.05
    # collinear g-vectors rejected
    assert (
        client.post(
            "/api/analyze/gpa",
            json={"image_id": lattice_id, "g1": [12, 0], "g2": [24, 0]},
        ).status_code
        == 422
    )


def test_vdf_and_radial(client, lattice_id) -> None:
    r = client.post(
        "/api/analyze/vdf",
        json={"image_id": lattice_id, "center": [33, 61], "radius": 4},
    )
    assert r.status_code == 200
    assert r.json()["image"]["shape"] == [64, 96]

    r2 = client.post("/api/analyze/radial", json={"image_id": lattice_id})
    body = r2.json()
    assert body["unit"] == "nm"
    assert len(body["radii"]) == len(body["intensity"]) == 32

    r3 = client.post(
        "/api/analyze/radial",
        json={
            "image_id": lattice_id,
            "azimuthal": True,
            "sector_min": 300,
            "sector_max": 60,
        },
    )
    assert r3.status_code == 200


def test_roughness_lattice_interface(client, lattice_id) -> None:
    r = client.post(
        "/api/analyze/roughness",
        json={"image_id": lattice_id, "level": "quadratic"},
    )
    body = r.json()
    assert body["Ra"] > 0 and body["unit"] == "nm"

    r2 = client.post(
        "/api/analyze/lattice",
        json={
            "image_id": lattice_id,
            "spot1": [33, 61],
            "spot2": [43, 49],
        },
    )
    assert r2.status_code == 200
    assert r2.json()["d_spacing1"] > 0

    from scipy.special import erf

    xs = np.linspace(0, 20, 81)
    ys = 1 + 2 * 0.5 * (1 + erf((xs - 9.7) / (1.3 * np.sqrt(2))))
    r3 = client.post(
        "/api/analyze/interface-width",
        json={"x": xs.tolist(), "y": ys.tolist(), "model": "erf"},
    )
    fit = r3.json()
    assert fit["center"] == pytest.approx(9.7, abs=0.05)
    assert len(fit["x_fit"]) == 500


def test_particles_endpoint(client, tmp_path) -> None:
    img = np.zeros((40, 50))
    img[5:12, 6:13] = 10
    img[20:30, 25:38] = 12
    img_id = _open(client, tmp_path, img + 1)
    r = client.post(
        "/api/analyze/particles",
        json={"image_id": img_id, "threshold": 5, "min_area": 10},
    )
    body = r.json()
    assert body["n_particles"] == 2
    areas = sorted(p["area"] for p in body["particles"])
    assert areas == [49, 130]
    assert body["particles"][0]["area_calibrated"] is not None
    # labels registered as a derived image
    assert client.get(
        f"/api/image/{body['labels']['id']}/render"
    ).status_code == 200


def test_atoms_endpoint(client, tmp_path) -> None:
    xx, yy = np.meshgrid(
        np.arange(1, 61, dtype=np.float64),
        np.arange(1, 51, dtype=np.float64),
    )
    img = 0.05 * np.ones_like(xx)
    for gi in range(5):
        for gj in range(6):
            img += np.exp(
                -((xx - (6 + gj * 9.5)) ** 2 + (yy - (5 + gi * 9.0)) ** 2)
                / (2 * 1.6**2)
            )
    img_id = _open(client, tmp_path, img * 1000)
    r = client.post(
        "/api/analyze/atoms",
        json={
            "image_id": img_id,
            "sigma": 2,
            "threshold": 0.2,
            "min_separation": 5,
            "win_radius": 4,
            "strain": True,
        },
    )
    body = r.json()
    assert body["n_columns"] == 30
    assert body["lattice"]["valid"] is True
    assert body["strain"]["valid"] is True
    assert len(body["positions"]) == 30


def test_template_and_stitch(client, tmp_path) -> None:
    r = np.arange(1, 49, dtype=np.float64)[:, None]
    c = np.arange(1, 65, dtype=np.float64)[None, :]
    img = np.sin(r / 3) * np.cos(c / 5) * 100 + 200
    img_id = _open(client, tmp_path, img)

    rt = client.post(
        "/api/analyze/template-match",
        json={"image_id": img_id, "rect": [10, 12, 9, 11], "threshold": 0.9},
    )
    body = rt.json()
    assert body["n_matches"] >= 1
    # the template's own location is the top match
    top = body["locations"][0]
    assert top == [10 + 4, 12 + 5]  # centre = top-left + floor(size/2)

    a_id = _open(client, tmp_path, img[:, :40], name="a.dm4")
    b_id = _open(client, tmp_path, img[:, 24:], name="b.dm4")
    rs = client.post(
        "/api/analyze/stitch",
        json={
            "image_ids": [a_id, b_id],
            "layout": "horizontal",
            "overlap_frac": 0.4,
        },
    )
    sbody = rs.json()
    assert sbody["offsets"][1][1] == 24  # recovered tile offset
    assert sbody["mosaic"]["shape"] == [48, 64]
    assert (
        client.post(
            "/api/analyze/stitch", json={"image_ids": [a_id]}
        ).status_code
        == 422
    )


def test_grains_endpoint(client, tmp_path) -> None:
    r = np.arange(1, 49, dtype=np.float64)[:, None]
    c = np.arange(1, 65, dtype=np.float64)[None, :]
    left = np.sin(r / 7) * np.cos(c[:, :32] / 11)
    right = np.sin(13 * r + 7 * c[:, 32:]) * 0.5 + 2.0
    img = np.hstack([np.broadcast_to(left, (48, 32)), right])
    img_id = _open(client, tmp_path, img * 100)
    rg = client.post(
        "/api/analyze/grains",
        json={"image_id": img_id, "method": "kmeans", "k": 2, "min_area": 25},
    )
    body = rg.json()
    assert body["method"] == "kmeans"
    assert body["n_grains"] >= 2
    assert body["boundary_length_px"] > 0
    # modern metrics are present on every method's response
    assert body["boundary_network_px"] > 0
    assert "n_triple_junctions" in body
    assert len(body["eccentricity"]) == body["n_grains"]
    assert client.get(
        f"/api/image/{body['labels']['id']}/render"
    ).status_code == 200


def test_grains_gradient_method(client, tmp_path) -> None:
    # three intensity bands tiling the field → gradient watershed default
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :30] = 20.0
    img[:, 30:60] = 60.0
    img[:, 60:] = 100.0
    img_id = _open(client, tmp_path, img)
    rg = client.post(
        "/api/analyze/grains",  # no method → server default ("gradient")
        json={"image_id": img_id, "granularity": 0.05, "min_area": 50},
    )
    body = rg.json()
    assert body["method"] == "gradient"
    assert body["n_grains"] == 3
    assert body["boundary_network_px"] > 0


def test_grains_roi_returns_full_size_editable_label_map(client, tmp_path) -> None:
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :30] = 20.0
    img[:, 30:60] = 60.0
    img[:, 60:] = 100.0
    img_id = _open(client, tmp_path, img)
    roi = [1, 31, 60, 90]
    response = client.post(
        "/api/analyze/grains",
        json={"image_id": img_id, "roi": roi, "min_area": 50},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    labels = store.get(body["labels"]["id"])
    assert labels.data.shape == img.shape
    assert np.all(labels.data[:, :30] == 0)
    assert np.all(labels.data[:, 30:] > 0)
    assert body["labels"]["meta"]["grain_roi"] == "1,31,60,90"

    # ROI provenance survives a later merge/split-derived label map.
    edited = client.post(
        "/api/grains/edit",
        json={
            "labels_id": body["labels"]["id"],
            "op": "merge",
            "points": [[40, 30], [70, 30]],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["labels"]["meta"]["grain_roi"] == "1,31,60,90"


def test_grains_can_be_measured_in_reviewed_layers(client, tmp_path) -> None:
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :30] = 20.0
    img[:, 30:60] = 60.0
    img[:, 60:] = 100.0
    img_id = _open(client, tmp_path, img)
    segmented = client.post(
        "/api/analyze/grains",
        json={"image_id": img_id, "granularity": 0.05, "min_area": 50},
    ).json()

    response = client.post(
        "/api/analyze/layers/grains",
        json={
            "labels_id": segmented["labels"]["id"], "axis": "y",
            "layers": [
                {"index": 0, "top": 0.0, "bottom": 30.0},
                {"index": 1, "top": 30.0, "bottom": 60.0},
            ],
            "selected_indices": [0, 1], "roi": None, "interface_traces": [],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [layer["n_grains"] for layer in body["layers"]] == [3, 3]
    assert [layer["cross_layer_grains"] for layer in body["layers"]] == [3, 3]
    assert body["assignment"]["meta"]["layer_assignment"] is True
    assert body["assignment"]["meta"].get("grain_labels") is None
    assert client.get(
        f"/api/image/{body['assignment']['id']}/render"
    ).status_code == 200


def test_grains_robust_denoise_params_accepted(client, tmp_path) -> None:
    # a noisy 2-band field: denoise + robust stretch should still resolve it
    rng = np.random.default_rng(0)
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :45] = 30.0
    img[:, 45:] = 70.0
    img += rng.normal(0.0, 8.0, img.shape)
    img[5, 5] = 1e6                      # hot pixel — robust stretch must absorb it
    img_id = _open(client, tmp_path, img)
    rg = client.post(
        "/api/analyze/grains",
        json={
            "image_id": img_id, "method": "rag", "n_superpixels": 200,
            "merge_threshold": 0.2, "min_area": 50,
            "denoise_sigma": 1.5, "robust": True,
        },
    )
    assert rg.status_code == 200
    body = rg.json()
    assert body["method"] == "rag"
    assert body["n_grains"] >= 2          # the two bands survive the spike + noise


def test_grains_map_is_tagged_for_the_editor(client, tmp_path) -> None:
    # the stage shows the grain editor iff the active image's meta carries
    # grain_labels — verify that tag survives ImageMeta serialization and
    # that an edited map stays tagged (so editing stays available)
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :30] = 20.0
    img[:, 30:60] = 60.0
    img[:, 60:] = 100.0
    img_id = _open(client, tmp_path, img)
    seg = client.post(
        "/api/analyze/grains",
        json={"image_id": img_id, "granularity": 0.05, "min_area": 50},
    ).json()
    lm = seg["labels"]["meta"]
    assert lm.get("grain_labels") is True
    assert lm.get("grain_source") == img_id
    merged = client.post(
        "/api/grains/edit",
        json={"labels_id": seg["labels"]["id"], "op": "merge",
              "points": [[15, 30], [45, 30]]},
    ).json()
    assert merged["n_grains"] == 2
    assert merged["labels"]["meta"].get("grain_labels") is True


def test_grains_edit_merge(client, tmp_path) -> None:
    # three bands → 3 grains; merge the left two by clicking one point in each
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :30] = 20.0
    img[:, 30:60] = 60.0
    img[:, 60:] = 100.0
    img_id = _open(client, tmp_path, img)
    seg = client.post(
        "/api/analyze/grains",
        json={"image_id": img_id, "granularity": 0.05, "min_area": 50},
    ).json()
    assert seg["n_grains"] == 3
    labels_id = seg["labels"]["id"]
    # click band 1 (x=15) and band 2 (x=45), same row
    merged = client.post(
        "/api/grains/edit",
        json={"labels_id": labels_id, "op": "merge",
              "points": [[15, 30], [45, 30]]},
    ).json()
    assert merged["n_grains"] == 2
    assert "+merge" in merged["method"]
    # the merged map is itself editable (tagged) + renderable
    assert client.get(
        f"/api/image/{merged['labels']['id']}/render"
    ).status_code == 200


def test_grains_edit_errors(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, np.zeros((20, 20)) + 5.0)
    # editing a non-grain image id is a 422
    assert client.post(
        "/api/grains/edit",
        json={"labels_id": img_id, "op": "merge", "points": [[1, 1], [2, 2]]},
    ).status_code == 422
    # unknown id → 404
    assert client.post(
        "/api/grains/edit",
        json={"labels_id": "nope", "op": "split", "points": [[1, 1]]},
    ).status_code == 404
