"""Scribble-trained grain segmentation (parity item #8): the softmax
classifier, the calc train/segment path, the stroke rasterizer, and the
/grains/train-segment endpoint."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.grains_trained import (
    preview_trained,
    rasterize_strokes,
    segment_trained,
    train_from_scribbles,
)
from fermiviewer.calc.ml import softmax_predict, softmax_train
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.imaging

# ── softmax classifier ───────────────────────────────────────────────


def test_softmax_separates_two_clusters() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(loc=[-3.0, -3.0], scale=0.3, size=(40, 2))
    b = rng.normal(loc=[3.0, 3.0], scale=0.3, size=(40, 2))
    x = np.vstack([a, b])
    y = np.array([1] * 40 + [2] * 40)
    model = softmax_train(x, y)
    labels, probs = softmax_predict(model, x)
    assert np.array_equal(model.classes, [1, 2])
    assert (labels == y).mean() == 1.0  # perfectly separable
    assert np.allclose(probs.sum(axis=1), 1.0)


def test_softmax_baked_standardization_applies_to_new_data() -> None:
    # train on a scaled feature; a fresh point on the class-2 side must
    # classify as 2 even though predict re-applies the baked mu/sigma
    x = np.array([[0.0], [1.0], [100.0], [101.0]])
    y = np.array([1, 1, 2, 2])
    model = softmax_train(x, y, max_iter=2000)
    assert model.standardize and model.mu is not None
    labels, _ = softmax_predict(model, np.array([[99.0], [2.0]]))
    assert list(labels) == [2, 1]


def test_softmax_size_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="rows"):
        softmax_train(np.zeros((4, 2)), np.array([1, 2, 1]))


# ── stroke rasterizer ────────────────────────────────────────────────


def test_rasterize_stamps_disk_at_point() -> None:
    mask = rasterize_strokes(
        (20, 20), [{"class_id": 2, "radius": 2.0, "points": [[10, 10]]}]
    )
    assert mask[10, 10] == 2
    assert mask[10, 12] == 2  # within radius 2
    assert mask[10, 15] == 0  # outside
    assert (mask > 0).sum() >= 9


def test_rasterize_densifies_a_dragged_segment() -> None:
    # two endpoints far apart with radius 1 must paint a connected band,
    # not two isolated dots
    mask = rasterize_strokes(
        (10, 40), [{"class_id": 1, "radius": 1.0, "points": [[2, 5], [37, 5]]}]
    )
    painted_cols = np.where(mask[5] > 0)[0]
    # contiguous from ~1 to ~38 with no gap larger than the brush
    assert painted_cols.min() <= 3 and painted_cols.max() >= 36
    assert np.diff(painted_cols).max() <= 2


# ── calc train + segment ─────────────────────────────────────────────


def _two_region_image() -> np.ndarray:
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :45] = 20.0
    img[:, 45:] = 100.0
    return img


def test_train_and_segment_recovers_two_regions() -> None:
    img = _two_region_image()
    mask = rasterize_strokes(
        (60, 90),
        [
            {"class_id": 1, "radius": 3.0, "points": [[10, 20], [30, 40]]},
            {"class_id": 2, "radius": 3.0, "points": [[65, 20], [80, 40]]},
        ],
    )
    model = train_from_scribbles(img, mask)
    seg = segment_trained(img, model, min_area=50)
    assert seg.n_grains == 2
    # the left region's pixels all carry one grain id, the right another
    assert len({int(seg.labels[30, 10]), int(seg.labels[30, 80])}) == 2
    assert seg.max_prob.shape == img.shape


def test_forest_classifier_recovers_two_regions() -> None:
    img = _two_region_image()
    mask = rasterize_strokes(
        (60, 90),
        [
            {"class_id": 1, "radius": 3.0, "points": [[10, 20], [30, 40]]},
            {"class_id": 2, "radius": 3.0, "points": [[65, 20], [80, 40]]},
        ],
    )
    model = train_from_scribbles(img, mask, classifier="forest")
    assert model.classifier == "forest"
    seg = segment_trained(img, model, min_area=50)
    assert seg.n_grains == 2
    assert len({int(seg.labels[30, 10]), int(seg.labels[30, 80])}) == 2


def test_unknown_classifier_raises() -> None:
    img = _two_region_image()
    mask = rasterize_strokes(
        (60, 90),
        [
            {"class_id": 1, "radius": 3.0, "points": [[10, 20]]},
            {"class_id": 2, "radius": 3.0, "points": [[80, 20]]},
        ],
    )
    with pytest.raises(ValueError, match="unknown classifier"):
        train_from_scribbles(img, mask, classifier="svm")


def test_train_requires_two_classes() -> None:
    img = _two_region_image()
    mask = rasterize_strokes(
        (60, 90), [{"class_id": 1, "radius": 3.0, "points": [[10, 20]]}]
    )
    with pytest.raises(ValueError, match="2 distinct classes"):
        train_from_scribbles(img, mask)


def test_train_requires_some_labels() -> None:
    img = _two_region_image()
    with pytest.raises(ValueError, match="no labelled"):
        train_from_scribbles(img, np.zeros((60, 90), dtype=np.int64))


def test_preview_reports_class_composition() -> None:
    # the two-region image is a 50/50 split, so a trained preview should put
    # ~half the pixels in each class and the fractions must sum to 1
    img = _two_region_image()
    mask = rasterize_strokes(
        (60, 90),
        [
            {"class_id": 1, "radius": 3.0, "points": [[10, 20], [30, 40]]},
            {"class_id": 2, "radius": 3.0, "points": [[65, 20], [80, 40]]},
        ],
    )
    model = train_from_scribbles(img, mask)
    prev = preview_trained(img, model)
    assert list(prev.classes) == [1, 2]
    assert prev.class_map.shape == img.shape
    assert sum(prev.fractions.values()) == pytest.approx(1.0)
    assert prev.fractions[1] == pytest.approx(0.5, abs=0.1)
    assert prev.fractions[2] == pytest.approx(0.5, abs=0.1)


def test_boundary_class_is_excluded_from_grains() -> None:
    img = _two_region_image()
    mask = rasterize_strokes(
        (60, 90),
        [
            {"class_id": 1, "radius": 3.0, "points": [[10, 30]]},
            {"class_id": 2, "radius": 3.0, "points": [[80, 30]]},
            {"class_id": 3, "radius": 3.0, "points": [[44, 30]]},
        ],
    )
    model = train_from_scribbles(img, mask)
    seg = segment_trained(img, model, boundary_class=(3,), min_area=10)
    # class 3 pixels are never assigned a grain id
    assert (seg.labels[seg.class_map == 3] == 0).all()


# ── endpoint ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_store() -> None:
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open(client: TestClient, tmp_path, data: np.ndarray) -> str:
    h, w = data.shape
    f = write_mini_dm4(
        tmp_path / "img.dm4", dims=[w, h], data=data.ravel(),
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def test_train_segment_endpoint(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _two_region_image())
    r = client.post(
        "/api/grains/train-segment",
        json={
            "image_id": img_id,
            "strokes": [
                {"class_id": 1, "radius": 3, "points": [[10, 20], [30, 40]]},
                {"class_id": 2, "radius": 3, "points": [[65, 20], [80, 40]]},
            ],
            "min_area": 50,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "trained"
    assert body["n_grains"] == 2
    # result is tagged as an editable grain map (merge/split works on it)
    lm = body["labels"]["meta"]
    assert lm.get("grain_labels") is True
    assert lm.get("grain_source") == img_id
    # the registered label map renders
    assert client.get(
        f"/api/image/{body['labels']['id']}/render"
    ).status_code == 200


def test_train_segment_forest_endpoint(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _two_region_image())
    r = client.post(
        "/api/grains/train-segment",
        json={
            "image_id": img_id,
            "strokes": [
                {"class_id": 1, "radius": 3, "points": [[10, 20], [30, 40]]},
                {"class_id": 2, "radius": 3, "points": [[65, 20], [80, 40]]},
            ],
            "min_area": 50,
            "classifier": "forest",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["n_grains"] == 2


def test_train_segment_one_class_is_422(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _two_region_image())
    r = client.post(
        "/api/grains/train-segment",
        json={
            "image_id": img_id,
            "strokes": [
                {"class_id": 1, "radius": 3, "points": [[10, 20], [30, 40]]},
            ],
        },
    )
    assert r.status_code == 422


def test_train_segment_unknown_image_is_404(client) -> None:
    r = client.post(
        "/api/grains/train-segment",
        json={
            "image_id": "nope",
            "strokes": [
                {"class_id": 1, "radius": 3, "points": [[1, 1]]},
                {"class_id": 2, "radius": 3, "points": [[2, 2]]},
            ],
        },
    )
    assert r.status_code == 404


def test_train_preview_endpoint_reports_classes(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _two_region_image())
    before = set(store.ids())
    r = client.post(
        "/api/grains/train-preview",
        json={
            "image_id": img_id,
            "strokes": [
                {"class_id": 1, "radius": 3, "points": [[10, 20], [30, 40]]},
                {"class_id": 2, "radius": 3, "points": [[65, 20], [80, 40]]},
            ],
        },
    )
    assert r.status_code == 200, r.text
    classes = r.json()["classes"]
    assert [c["class_id"] for c in classes] == [1, 2]
    assert sum(c["fraction"] for c in classes) == pytest.approx(1.0)
    assert all(c["is_boundary"] is False for c in classes)
    # non-committing: the preview must NOT register a derived image
    assert set(store.ids()) == before


def test_train_preview_marks_boundary_class(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _two_region_image())
    r = client.post(
        "/api/grains/train-preview",
        json={
            "image_id": img_id,
            "strokes": [
                {"class_id": 1, "radius": 3, "points": [[10, 20]]},
                {"class_id": 2, "radius": 3, "points": [[80, 20]]},
                {"class_id": 3, "radius": 3, "points": [[44, 30]]},
            ],
            "boundary_class": [3],
        },
    )
    assert r.status_code == 200, r.text
    by_id = {c["class_id"]: c for c in r.json()["classes"]}
    assert by_id[3]["is_boundary"] is True
    assert by_id[1]["is_boundary"] is False


def test_train_preview_one_class_is_422(client, tmp_path) -> None:
    img_id = _open(client, tmp_path, _two_region_image())
    r = client.post(
        "/api/grains/train-preview",
        json={
            "image_id": img_id,
            "strokes": [
                {"class_id": 1, "radius": 3, "points": [[10, 20], [30, 40]]},
            ],
        },
    )
    assert r.status_code == 422
