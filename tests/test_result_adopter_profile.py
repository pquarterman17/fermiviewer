"""The 1C `measure.profile` adopter: persisting an intensity profile.

The third representative adopter after EDS quantification and particle
analysis (tests/test_api_results.py), and the one that exercises the parts
of the ADR 0004 contract the first two do not: a **curve** output whose
member array is the science itself, a **region snapshot** (the line or
polyline the profile sampled, copied so an edited or deleted measure cannot
silently change what the record means), and **warnings** raised by the run
rather than by its inputs.

The capture boundary is the sharp edge here: the calc layer's ValueError is
a computation failure and must be recorded, while "need either a+b or
points" — and an unknown image id — are request validation, where no
computation was attempted and nothing may be recorded.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.io.project_file import load_project
from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.api


@pytest.fixture()
def client() -> TestClient:
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def _open(client: TestClient, path: Path) -> str:
    return client.post("/api/session/open", json={"paths": [str(path)]}).json()[0]["id"]


def _ramp(n: int = 8) -> np.ndarray:
    """8×8 with a distinct value per pixel — a row-varying ramp, so the
    perpendicular averaging width has a genuine spread to estimate σ from."""
    rows, cols = np.mgrid[0:n, 0:n]
    return (rows * 10 + cols).astype(np.float32)


@pytest.fixture()
def image_id(client: TestClient, tmp_path: Path) -> str:
    """Calibrated 8×8 image (2 nm pixels)."""
    img = _ramp()
    f = write_mini_dm4(
        tmp_path / "ramp.dm4",
        dims=[8, 8],
        data=img.ravel(),
        data_type=2,
        cal=[
            {"scale": 2.0, "origin": 0, "units": "nm"},
            {"scale": 2.0, "origin": 0, "units": "nm"},
        ],
    )
    return _open(client, f)


@pytest.fixture()
def uncalibrated_id(client: TestClient, tmp_path: Path) -> str:
    """The same raster with no pixel calibration — an empty unit string is
    what `AxisCal.calibrated` reads as uncalibrated."""
    img = _ramp()
    f = write_mini_dm4(
        tmp_path / "raw.dm4",
        dims=[8, 8],
        data=img.ravel(),
        data_type=2,
        cal=[
            {"scale": 1.0, "origin": 0, "units": ""},
            {"scale": 1.0, "origin": 0, "units": ""},
        ],
    )
    return _open(client, f)


def _profile(client: TestClient, **body) -> dict:
    r = client.post("/api/measure/profile", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ── capture ──────────────────────────────────────────────────────────


def test_record_defaults_off_and_captures_nothing(client, image_id) -> None:
    """Recording is a user decision, not a side effect of every exploratory
    run — and profiles are dragged out constantly while exploring."""
    body = _profile(client, image_id=image_id, a=[4, 1], b=[4, 8])
    assert "result" not in body
    assert client.get("/api/results").json()["results"] == []


def test_two_point_profile_captures_a_contract_conformant_record(
    client,
    image_id,
) -> None:
    """width>1 with reduce='mean' is the branch that estimates a per-point
    sem, so the curve member is (N, 3): x, y, sigma (ADR 0004 §3)."""
    body = _profile(
        client,
        image_id=image_id,
        a=[4, 1],
        b=[4, 8],
        width=3,
        reduce="mean",
        record=True,
    )
    assert "intensity_sigma" in body  # the σ branch really ran
    result_id = body["result"]["id"]

    (entry,) = client.get("/api/results").json()["results"]
    assert entry["id"] == result_id
    assert entry["analysis"] == "measure.profile"
    assert entry["status"] == "completed"
    assert entry["error"] is None
    assert entry["missing_members"] == []
    assert entry["source_ids"] == [image_id]
    assert entry["label"] == f"Intensity profile of {store.name(image_id)}"

    # resolved params, defaults filled — the reproduction key — and never
    # the capture toggle itself
    assert entry["params"]["a"] == [4.0, 1.0]
    assert entry["params"]["b"] == [4.0, 8.0]
    assert entry["params"]["width"] == pytest.approx(3.0)
    assert entry["params"]["reduce"] == "mean"
    assert entry["params"]["tilt_angle_deg"] == pytest.approx(0.0)
    assert entry["params"]["tilt_axis"] == "Y"
    assert entry["params"]["geometry"] == "cross-section"
    assert entry["params"]["points"] is None
    assert "record" not in entry["params"]

    # the geometry, snapshotted — the live measure may be edited later
    assert entry["regions"] == [
        {
            "kind": "line",
            "convention": "(row, col), 1-based",
            "a": [4.0, 1.0],
            "b": [4.0, 8.0],
            "width": 3.0,
        }
    ]

    # calibration snapshotted from the source at compute time
    (snap,) = entry["calibration"]
    assert snap["image_id"] == image_id
    assert snap["axes"][0]["units"] == "nm"

    curve, length, n_samples = entry["outputs"]
    assert (curve["kind"], curve["name"]) == ("curve", "profile")
    assert curve["member"] == f"results/{result_id}/0.npy"
    assert curve["data"] == {
        "x_name": "distance",
        "x_unit": "nm",
        "y_name": "intensity",
        "y_unit": "",
        "reduce": "mean",
    }
    assert (length["kind"], length["name"]) == ("scalar", "length")
    assert length["data"] == {"value": pytest.approx(body["length"]), "unit": "nm"}
    assert (n_samples["kind"], n_samples["name"]) == ("scalar", "n_samples")
    assert n_samples["data"] == {"value": len(body["dist"]), "unit": ""}

    # the curve is member-backed: [dist, intensity, sigma], matching the
    # wire body column for column
    data = client.get(f"/api/results/{result_id}/outputs/0/data").json()
    assert data["shape"] == [len(body["dist"]), 3]
    assert data["dtype"] == "float64"
    assert [row[0] for row in data["values"]] == pytest.approx(body["dist"])
    assert [row[1] for row in data["values"]] == pytest.approx(body["intensity"])
    assert [row[2] for row in data["values"]] == pytest.approx(body["intensity_sigma"])

    # a clean, calibrated, fully-on-raster run has nothing to warn about
    assert entry["warnings"] == []


def test_polyline_profile_captures_its_geometry_and_a_two_column_curve(
    client,
    image_id,
) -> None:
    """The polyline branch never estimates σ, so its member is (N, 2)."""
    body = _profile(
        client,
        image_id=image_id,
        points=[[2, 2], [2, 7], [6, 7]],
        width=3,
        record=True,
    )
    assert "intensity_sigma" not in body
    result_id = body["result"]["id"]

    entry = client.get(f"/api/results/{result_id}").json()
    assert entry["analysis"] == "measure.profile"
    assert entry["regions"] == [
        {
            "kind": "polyline",
            "convention": "(row, col), 1-based",
            "points": [[2.0, 2.0], [2.0, 7.0], [6.0, 7.0]],
            "width": 3.0,
        }
    ]
    assert entry["params"]["points"] == [[2.0, 2.0], [2.0, 7.0], [6.0, 7.0]]
    assert entry["params"]["a"] is None and entry["params"]["b"] is None

    data = client.get(f"/api/results/{result_id}/outputs/0/data").json()
    assert data["shape"] == [len(body["dist"]), 2]
    assert [row[0] for row in data["values"]] == pytest.approx(body["dist"])
    assert [row[1] for row in data["values"]] == pytest.approx(body["intensity"])


def test_uncalibrated_pixel_size_warns_only_when_uncalibrated(
    client,
    image_id,
    uncalibrated_id,
) -> None:
    """Distances silently falling back to pixels is exactly the kind of
    thing a record reopened months later must state, not imply."""
    raw = _profile(
        client, image_id=uncalibrated_id, a=[4, 1], b=[4, 8], record=True
    )
    entry = client.get(f"/api/results/{raw['result']['id']}").json()
    (warning,) = entry["warnings"]
    assert "pixel size" in warning and "pixels" in warning
    curve, length, _ = entry["outputs"]
    assert curve["data"]["x_unit"] == "px"
    assert length["data"]["unit"] == "px"

    calibrated = _profile(
        client, image_id=image_id, a=[4, 1], b=[4, 8], record=True
    )
    entry = client.get(f"/api/results/{calibrated['result']['id']}").json()
    assert entry["warnings"] == []
    assert entry["outputs"][0]["data"]["x_unit"] == "nm"


def test_off_raster_samples_warn_and_stay_nan_in_the_member(
    client,
    image_id,
) -> None:
    """A profile dragged past the image edge samples nothing there. The
    count is warned about, and the member array keeps NaN — it is .npy, not
    JSON, so the gap must not be flattened to a value; only the JSON
    surfaces scrub it to null."""
    body = _profile(
        client, image_id=image_id, a=[4, 1], b=[4, 14], record=True
    )
    n_missing = sum(v is None for v in body["intensity"])
    assert n_missing > 0

    result_id = body["result"]["id"]
    entry = client.get(f"/api/results/{result_id}").json()
    (warning,) = entry["warnings"]
    assert warning.startswith(f"{n_missing} of {len(body['intensity'])}")
    assert "non-finite" in warning

    (record,) = project.current().results
    array = record.outputs[0].array
    assert array is not None
    assert int(np.count_nonzero(np.isnan(array[:, 1]))) == n_missing

    # the JSON surface, by contrast, is scrubbed
    data = client.get(f"/api/results/{result_id}/outputs/0/data").json()
    assert sum(row[1] is None for row in data["values"]) == n_missing


# ── the capture boundary ─────────────────────────────────────────────


def test_a_computation_failure_is_captured_as_a_failed_record(
    client,
    image_id,
) -> None:
    """The calc layer refusing a tilt outside (-90, 90) happens after the
    inputs resolved — a computation failure, which the 1B contract requires
    be recorded rather than lost."""
    r = client.post(
        "/api/measure/profile",
        json={
            "image_id": image_id,
            "a": [4, 1],
            "b": [4, 8],
            "tilt_angle_deg": 90,
            "record": True,
        },
    )
    assert r.status_code == 422

    (entry,) = client.get("/api/results").json()["results"]
    assert entry["status"] == "failed"
    assert "tilt_angle_deg" in entry["error"]
    assert entry["outputs"] == []  # no fabricated science
    assert entry["params"]["tilt_angle_deg"] == pytest.approx(90.0)
    assert entry["source_ids"] == [image_id]
    # the geometry that was attempted is still worth knowing
    assert entry["regions"][0]["kind"] == "line"


def test_request_validation_failures_are_not_captured(client, image_id) -> None:
    """The documented capture boundary: neither an unresolvable image id nor
    a request that names no geometry at all reaches a computation, so with
    record:true they still record nothing."""
    r = client.post(
        "/api/measure/profile",
        json={"image_id": image_id, "record": True},
    )
    assert r.status_code == 422
    assert "need either" in r.json()["detail"]
    assert client.get("/api/results").json()["results"] == []

    # a one-vertex "polyline" satisfies neither branch either
    r = client.post(
        "/api/measure/profile",
        json={"image_id": image_id, "points": [[2, 2]], "record": True},
    )
    assert r.status_code == 422
    assert client.get("/api/results").json()["results"] == []

    r = client.post(
        "/api/measure/profile",
        json={"image_id": "nope", "a": [4, 1], "b": [4, 8], "record": True},
    )
    assert r.status_code == 404
    assert client.get("/api/results").json()["results"] == []


# ── the full loop: capture → save → reopen ───────────────────────────


def test_captured_profile_survives_save_and_reopen_with_arrays(
    client,
    image_id,
    tmp_path,
) -> None:
    """Run a profile, save the project, reopen it: the curve, its geometry
    snapshot and its calibration are all still there, with no client
    cooperation required."""
    body = _profile(
        client,
        image_id=image_id,
        a=[4, 1],
        b=[4, 8],
        width=3,
        record=True,
    )
    result_id = body["result"]["id"]
    n = len(body["dist"])

    path = tmp_path / "profile.fvp"
    assert client.post("/api/project/save", json={"path": str(path)}).status_code == 200

    loaded = client.post("/api/project/load", json={"path": str(path)})
    assert loaded.status_code == 200, loaded.text
    (entry,) = loaded.json()["results"]
    assert entry["id"] == result_id
    assert entry["analysis"] == "measure.profile"
    assert entry["missing_members"] == []
    assert entry["regions"][0]["convention"] == "(row, col), 1-based"

    data = client.get(f"/api/results/{result_id}/outputs/0/data").json()
    assert data["shape"] == [n, 3]

    # and the on-disk container holds the member, not inline samples
    (record,) = load_project(path).results
    curve = record.outputs[0]
    assert curve.member == f"results/{result_id}/0.npy"
    assert curve.array is not None and curve.array.shape == (n, 3)
    assert curve.array[:, 0] == pytest.approx(body["dist"])
