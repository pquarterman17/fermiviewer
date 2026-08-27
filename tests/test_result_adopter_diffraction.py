"""The diffraction-indexing 1C adopter: `/api/diffraction/index` with
`record: true` (roadmap item 1, ADR 0004).

The third adopter, and the one that exercises the parts the EDS and
particle adopters do not (tests/test_api_results.py owns those): TWO
member-backed tables in one record, an inline table whose cells must stay
scalar (the zone axis is a 3-vector), a compute-time REGION snapshot, and
warnings that describe which physics branch produced the numbers.
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

pytestmark = [pytest.mark.diffraction, pytest.mark.api]

#: The four cardinal spots of the fixture pattern, 30 px from the 1-based
#: centre (65, 65) of a 128×128 image.
SPOTS = [[65, 95], [65, 35], [95, 65], [35, 65]]


@pytest.fixture()
def client() -> TestClient:
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


@pytest.fixture()
def diff_image_id(client: TestClient, tmp_path: Path) -> str:
    """128×128 synthetic diffraction pattern with four cardinal spots."""
    img = np.zeros((128, 128), dtype=np.float32)
    for r, c in SPOTS:
        img[r - 1, c - 1] = 1.0
    f = write_mini_dm4(
        tmp_path / "diff.dm4",
        dims=[128, 128],
        data=img.reshape(-1, order="F").astype(np.float32),
        data_type=2,
        cal=[
            {"scale": 0.05, "origin": 0, "units": "nm"},
            {"scale": 0.05, "origin": 0, "units": "nm"},
        ],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def _index(client: TestClient, image_id: str, **extra) -> dict:
    body = {
        "image_id": image_id,
        "spots": SPOTS,
        "pixel_size_mm": 0.05,
        "camera_length_mm": 200.0,
        "acc_voltage_kv": 200,
        **extra,
    }
    r = client.post("/api/diffraction/index", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _output(entry: dict, name: str) -> tuple[int, dict]:
    """The named output and its index — the index names the member path and
    the `/outputs/{i}/data` route, so tests must not assume an order."""
    return next((i, o) for i, o in enumerate(entry["outputs"]) if o["name"] == name)


# ── capture on the route ─────────────────────────────────────────────


def test_record_defaults_off_and_captures_nothing(client, diff_image_id) -> None:
    """Recording is a user decision, not a side effect of every exploratory
    index — without record:true the session stays free of records."""
    body = _index(client, diff_image_id)
    assert "result" not in body
    assert client.get("/api/results").json()["results"] == []


def test_index_captures_a_contract_conformant_record(client, diff_image_id) -> None:
    body = _index(client, diff_image_id, record=True, top_n=3)
    result_id = body["result"]["id"]

    (entry,) = client.get("/api/results").json()["results"]
    assert entry["id"] == result_id
    # the exact string the frontend's ANALYSIS_LABELS maps
    assert entry["analysis"] == "diffraction.index"
    assert entry["status"] == "completed"
    assert entry["missing_members"] == []
    assert entry["source_ids"] == [diff_image_id]
    assert entry["label"].startswith("Diffraction indexing of ")
    # resolved params, defaults filled — the reproduction key — and never
    # the capture toggle itself
    assert entry["params"]["tolerance"] == pytest.approx(0.05)
    assert entry["params"]["camera_length_mm"] == pytest.approx(200.0)
    assert entry["params"]["spots"] == SPOTS
    assert "record" not in entry["params"]
    # calibration snapshotted from the source at compute time
    (snap,) = entry["calibration"]
    assert snap["image_id"] == diff_image_id
    assert snap["axes"][0]["units"] == "nm"

    # scalars: spot count and the pattern centre, full-image 1-based
    _, n_spots = _output(entry, "n_spots")
    assert n_spots["kind"] == "scalar"
    assert n_spots["data"]["value"] == len(SPOTS)
    _, center_row = _output(entry, "center_row")
    _, center_col = _output(entry, "center_col")
    assert [center_row["data"]["value"], center_col["data"]["value"]] == body["center"]
    assert "1-based" in center_row["data"]["convention"]

    # the two big tables are member-backed — they grow with the pattern and
    # must never inline into manifest.json (ADR 0004 §2)
    refl_i, refl = _output(entry, "matched_reflections")
    assert refl["member"] == f"results/{result_id}/{refl_i}.npy"
    assert "rows" not in refl["data"]
    assert refl["data"]["columns"] == [
        "candidate_index",
        "spot_index",
        "h",
        "k",
        "l",
        "measured_d",
        "ref_d",
    ]
    n_matched = sum(c["n_matched"] for c in body["candidates"])
    refl_data = client.get(f"/api/results/{result_id}/outputs/{refl_i}/data").json()
    assert refl_data["dtype"] == "float64"
    assert refl_data["shape"] == [n_matched, 7]
    # every stored reflection points back at a real candidate and a real spot
    for row in refl_data["values"]:
        assert 0 <= row[0] < len(body["candidates"])
        assert 0 <= row[1] < len(SPOTS)

    spots_i, spots = _output(entry, "spots")
    assert spots["member"] == f"results/{result_id}/{spots_i}.npy"
    assert spots["data"]["columns"] == ["row", "col", "measured_r"]
    assert "1-based" in spots["data"]["coordinate_convention"]
    spot_data = client.get(f"/api/results/{result_id}/outputs/{spots_i}/data").json()
    assert spot_data["shape"] == [len(SPOTS), 3]
    # one row per input spot, in request order, with its measured radius
    for row, spot, radius in zip(spot_data["values"], SPOTS, body["measured_r"], strict=True):
        assert row[:2] == pytest.approx(spot)
        assert row[2] == pytest.approx(radius)

    # a well-calibrated run carries no uncalibrated-branch warning
    assert not any("camera length" in w for w in entry["warnings"])


def test_candidates_table_cells_are_scalars(client, diff_image_id) -> None:
    """A table cell must be a scalar: the zone axis is a 3-vector, so it is
    split into zone_u/zone_v/zone_w rather than nested in one cell."""
    body = _index(client, diff_image_id, record=True, top_n=3)
    entry = client.get(f"/api/results/{body['result']['id']}").json()
    _, table = _output(entry, "candidates")

    assert table["kind"] == "table"
    assert table["member"] is None  # at most top_n rows: inline is honest
    assert table["data"]["columns"] == [
        "phase",
        "formula",
        "score",
        "n_matched",
        "zone_u",
        "zone_v",
        "zone_w",
    ]
    assert len(table["data"]["rows"]) == len(body["candidates"])
    for row, cand in zip(table["data"]["rows"], body["candidates"], strict=True):
        assert len(row) == len(table["data"]["columns"])
        for cell in row:
            assert isinstance(cell, (str, int, float)) or cell is None
        assert row[0] == cand["phase"]
        assert row[3] == cand["n_matched"]
        # NaN zone-axis components scrub to null for strict JSON, so compare
        # only the components the live response reports as finite
        for stored, live in zip(row[4:], cand["zone_axis"], strict=True):
            assert stored == pytest.approx(live) if live is not None else stored is None


# ── warnings, regions, failures ──────────────────────────────────────


def test_uncalibrated_run_warns_about_the_width_scaled_branch(
    client,
    diff_image_id,
) -> None:
    """Without a camera length `index_spots` falls back to d = W·px/r, which
    is a different measurement — the record has to say so."""
    uncal = _index(client, diff_image_id, record=True, camera_length_mm=None)
    entry = client.get(f"/api/results/{uncal['result']['id']}").json()
    (warning,) = [w for w in entry["warnings"] if "camera length" in w]
    assert "width" in warning
    assert entry["params"]["camera_length_mm"] is None

    cal = _index(client, diff_image_id, record=True)
    entry = client.get(f"/api/results/{cal['result']['id']}").json()
    assert not any("camera length" in w for w in entry["warnings"])


def test_no_match_within_tolerance_is_warned(client, diff_image_id) -> None:
    """An indexing that matched nothing is still a record — but one that
    says the phases did not fit, rather than a table of empty candidates."""
    body = _index(client, diff_image_id, record=True, tolerance=1e-9)
    entry = client.get(f"/api/results/{body['result']['id']}").json()
    assert all(c["n_matched"] == 0 for c in body["candidates"])
    assert any("tolerance" in w for w in entry["warnings"])
    # the empty member-backed table still exists, with the right width
    refl_i, _ = _output(entry, "matched_reflections")
    data = client.get(f"/api/results/{body['result']['id']}/outputs/{refl_i}/data").json()
    assert data["shape"] == [0, 7]


def test_roi_request_snapshots_the_region(client, diff_image_id) -> None:
    """Regions are mutable and an ROI arrives in the request body, so the
    record keeps a copy of the geometry — with the convention it was
    interpreted under (calc/diffraction.apply_roi)."""
    roi = {"kind": "rect", "r0": 20, "c0": 20, "r1": 110, "c1": 110}
    body = _index(client, diff_image_id, record=True, roi=roi)
    entry = client.get(f"/api/results/{body['result']['id']}").json()

    (region,) = entry["regions"]
    assert region["kind"] == "rect"
    assert region["convention"] == "0-based, half-open rect: rows [r0, r1), cols [c0, c1)"
    assert {k: region[k] for k in ("r0", "c0", "r1", "c1")} == {
        k: v for k, v in roi.items() if k != "kind"
    }
    # the circle's own convention, not the rect's, and no rect fields
    circle = {"kind": "circle", "cr": 65, "cc": 65, "radius": 40}
    body = _index(client, diff_image_id, record=True, roi=circle)
    entry = client.get(f"/api/results/{body['result']['id']}").json()
    (region,) = entry["regions"]
    assert region == {
        "kind": "circle",
        "convention": "0-based centre (cr, cc), radius in px, inclusive",
        "cr": 65,
        "cc": 65,
        "radius": 40,
    }
    # a run without an ROI invents no geometry
    plain = _index(client, diff_image_id, record=True)
    assert client.get(f"/api/results/{plain['result']['id']}").json()["regions"] == []


def test_a_computation_failure_is_captured_as_a_failed_record(
    client,
    diff_image_id,
) -> None:
    """A degenerate ROI is a post-validation computation failure: the 422
    still propagates, but the attempt is recorded, not lost."""
    r = client.post(
        "/api/diffraction/index",
        json={
            "image_id": diff_image_id,
            "spots": SPOTS,
            "roi": {"kind": "rect", "r0": 40, "c0": 40, "r1": 40, "c1": 40},
            "record": True,
        },
    )
    assert r.status_code == 422

    (entry,) = client.get("/api/results").json()["results"]
    assert entry["analysis"] == "diffraction.index"
    assert entry["status"] == "failed"
    assert "roi selects no pixels" in entry["error"]
    assert entry["outputs"] == []
    assert entry["params"]["spots"] == SPOTS  # the reproduction key
    assert entry["regions"][0]["kind"] == "rect"  # and the geometry that failed


def test_an_unknown_image_id_is_not_captured(client) -> None:
    """The documented capture boundary: an unknown image id is request
    validation — no computation was attempted, so nothing is recorded even
    with record:true."""
    r = client.post(
        "/api/diffraction/index",
        json={"image_id": "nope", "spots": SPOTS, "record": True},
    )
    assert r.status_code == 404
    assert client.get("/api/results").json()["results"] == []


# ── the full loop: capture → save → reopen ───────────────────────────


def test_captured_record_survives_save_and_reopen_with_arrays(
    client,
    diff_image_id,
    tmp_path,
) -> None:
    """Run an indexing, save the project, reopen it — the record is still
    there with BOTH member arrays intact and no client cooperation."""
    body = _index(client, diff_image_id, record=True, top_n=3)
    result_id = body["result"]["id"]
    n_matched = sum(c["n_matched"] for c in body["candidates"])

    path = tmp_path / "indexed.fvp"
    assert client.post("/api/project/save", json={"path": str(path)}).status_code == 200

    loaded = client.post("/api/project/load", json={"path": str(path)})
    assert loaded.status_code == 200, loaded.text
    (entry,) = loaded.json()["results"]
    assert entry["id"] == result_id
    assert entry["missing_members"] == []

    refl_i, _ = _output(entry, "matched_reflections")
    spots_i, _ = _output(entry, "spots")
    refl = client.get(f"/api/results/{result_id}/outputs/{refl_i}/data").json()
    spots = client.get(f"/api/results/{result_id}/outputs/{spots_i}/data").json()
    assert refl["shape"] == [n_matched, 7]
    assert spots["shape"] == [len(SPOTS), 3]

    # and the on-disk container holds the members, not inline rows
    (record,) = load_project(path).results
    for index, rows in ((refl_i, n_matched), (spots_i, len(SPOTS))):
        output = record.outputs[index]
        assert output.member == f"results/{result_id}/{index}.npy"
        assert output.array is not None and output.array.shape[0] == rows
        assert "rows" not in output.data
