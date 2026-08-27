"""The item-2B HTTP surface: `/api/results/compare` and `/api/results/report`.

The pure logic is covered by `test_results_compare.py`,
`test_results_calibration.py` and `test_results_report.py`. What is tested
HERE is only what the routes add: session lookup, id-error behaviour,
selection ORDER, and that the wire payload keeps the parts a Results
browser has to render — above all the rejection MESSAGE, which is the
reason this endpoint exists rather than a client-side filter.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api]


@pytest.fixture()
def client() -> TestClient:
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def _image(client: TestClient, tmp_path: Path, name: str, scale: float) -> str:
    """A tiny calibrated image; `scale` varies so two sources can disagree."""
    img = np.zeros((16, 16), dtype=np.float32)
    img[4:12, 4:12] = 100.0
    f = write_mini_dm4(
        tmp_path / f"{name}.dm4",
        dims=[16, 16],
        data=img.ravel(),
        data_type=2,
        cal=[
            {"scale": scale, "origin": 0, "units": "nm"},
            {"scale": scale, "origin": 0, "units": "nm"},
        ],
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def _profile(client: TestClient, image_id: str, *, width: float = 3.0) -> str:
    """A captured `measure.profile` record; returns its result id."""
    response = client.post(
        "/api/measure/profile",
        json={
            "image_id": image_id,
            "a": [2, 2],
            "b": [14, 14],
            "width": width,
            "reduce": "mean",
            "record": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["id"]


# ── /api/results/compare ─────────────────────────────────────────────


def test_two_profiles_on_matching_calibration_are_compatible(
    client, tmp_path
) -> None:
    a = _image(client, tmp_path, "a", 0.5)
    b = _image(client, tmp_path, "b", 0.5)
    first, second = _profile(client, a), _profile(client, b)

    body = client.post(
        "/api/results/compare", json={"reference_id": first}
    ).json()
    assert body["reference_id"] == first
    assert body["compatible"] == [second]
    assert body["rejected"] == []
    assert "profile" in body["outputs"]


def test_a_different_analysis_is_rejected_with_a_message_naming_both(
    client, tmp_path
) -> None:
    """The message is the payload: a browser that only greys the card out
    makes the user guess which rule bit."""
    image = _image(client, tmp_path, "a", 0.5)
    profile_id = _profile(client, image)
    index = client.post(
        "/api/diffraction/index",
        json={
            "image_id": image,
            "spots": [[6, 8], [10, 8]],
            "pixel_size_mm": 0.1,
            "camera_length_mm": 200,
            "record": True,
        },
    )
    assert index.status_code == 200, index.text
    index_id = index.json()["result"]["id"]

    body = client.post(
        "/api/results/compare", json={"reference_id": profile_id}
    ).json()
    assert body["compatible"] == []
    (rejection,) = body["rejected"]
    assert rejection["id"] == index_id
    assert rejection["code"] == "analysis_mismatch"
    # both sides named, not just "incompatible"
    assert "diffraction.index" in rejection["message"]
    assert "measure.profile" in rejection["message"]


def test_an_explicit_candidate_list_narrows_the_question(
    client, tmp_path
) -> None:
    a = _image(client, tmp_path, "a", 0.5)
    first, second, third = (
        _profile(client, a),
        _profile(client, a),
        _profile(client, a),
    )
    body = client.post(
        "/api/results/compare",
        json={"reference_id": first, "candidate_ids": [third]},
    ).json()
    # `second` exists in the session but was not asked about
    assert body["compatible"] == [third]
    assert second not in body["compatible"]


def test_omitting_candidates_never_compares_the_reference_to_itself(
    client, tmp_path
) -> None:
    image = _image(client, tmp_path, "a", 0.5)
    only = _profile(client, image)
    body = client.post(
        "/api/results/compare", json={"reference_id": only}
    ).json()
    assert body["compatible"] == []
    assert body["rejected"] == []


def test_unknown_ids_are_404s_on_both_sides_of_the_comparison(
    client, tmp_path
) -> None:
    image = _image(client, tmp_path, "a", 0.5)
    good = _profile(client, image)
    assert client.post(
        "/api/results/compare", json={"reference_id": "nope"}
    ).status_code == 404
    assert client.post(
        "/api/results/compare",
        json={"reference_id": good, "candidate_ids": ["nope"]},
    ).status_code == 404


# ── /api/results/report ──────────────────────────────────────────────


def test_report_preserves_the_callers_selection_order(client, tmp_path) -> None:
    """A report is a composed document — the author's order is the one that
    ships, not creation order re-sorted server-side."""
    image = _image(client, tmp_path, "a", 0.5)
    first, second = _profile(client, image), _profile(client, image)
    body = client.post(
        "/api/results/report", json={"result_ids": [second, first]}
    ).json()
    assert [r["id"] for r in body["results"]] == [second, first]


def test_report_carries_what_a_methods_section_needs(client, tmp_path) -> None:
    image = _image(client, tmp_path, "a", 0.5)
    result_id = _profile(client, image)
    body = client.post(
        "/api/results/report", json={"result_ids": [result_id]}
    ).json()

    assert body["version"] >= 1
    assert body["app_version"]
    assert body["generated_at"]
    assert body["methods"].strip()
    # the calibration summary reaches the source image it was snapshotted from
    assert [c["image_id"] for c in body["calibration"]] == [image]
    (entry,) = body["results"]
    assert entry["analysis"] == "measure.profile"
    assert entry["params"]["width"] == 3.0     # resolved params survive
    assert entry["methods"].strip()            # per-card prose, for 2C


def test_report_is_json_safe_end_to_end(client, tmp_path) -> None:
    """The bundle is a document that gets written to disk; a NaN anywhere in
    it would fail at encode time, far from where it entered."""
    image = _image(client, tmp_path, "a", 0.5)
    result_id = _profile(client, image)
    response = client.post(
        "/api/results/report", json={"result_ids": [result_id]}
    )
    assert response.status_code == 200
    round_tripped = json.loads(json.dumps(response.json()))
    assert round_tripped["results"][0]["id"] == result_id


def test_report_names_every_unknown_id_at_once(client, tmp_path) -> None:
    """Fixing a selection one 404 at a time is a guessing game."""
    image = _image(client, tmp_path, "a", 0.5)
    good = _profile(client, image)
    response = client.post(
        "/api/results/report", json={"result_ids": [good, "nope", "also-nope"]}
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "nope" in detail and "also-nope" in detail


def test_report_rejects_an_empty_selection(client) -> None:
    assert client.post(
        "/api/results/report", json={"result_ids": []}
    ).status_code == 422


def test_a_failed_record_reports_as_failed_rather_than_silently(
    client, tmp_path
) -> None:
    """A report that listed a failed record as ordinary science would be
    worse than one that omitted it."""
    image = _image(client, tmp_path, "a", 0.5)
    bad = client.post(
        "/api/measure/profile",
        json={
            "image_id": image,
            "a": [2, 2],
            "b": [14, 14],
            "tilt_angle_deg": 90.0,
            "record": True,
        },
    )
    assert bad.status_code == 422
    results = client.get("/api/results").json()["results"]
    (failed,) = [r for r in results if r["status"] == "failed"]
    body = client.post(
        "/api/results/report", json={"result_ids": [failed["id"]]}
    ).json()
    assert any(failed["id"] in w and "failed" in w for w in body["warnings"])
