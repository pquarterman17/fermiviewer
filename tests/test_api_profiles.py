"""Calibration profiles over the wire (ADR 0009): the store's CRUD and
history, apply/unapply on an image, the legacy import, and -- the point of
the exercise -- a captured result carrying the profiles it was computed
with as an immutable copy that survives a later edit, a project save and
a reload, and reads as a difference when compared against a result that
used another version.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.calibration_db import save_calibration
from fermiviewer.io.project_file import load_project, save_project
from fermiviewer.io.results_model import CalibrationSnapshot, ResultRecord, snapshot_calibration
from fermiviewer.models import ImageMeta
from fermiviewer.project_session import project
from fermiviewer.result_capture import capture_result
from fermiviewer.results_calibration import calibration_agreement
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FV_PROFILES_PATH", str(tmp_path / "profiles.json"))
    monkeypatch.setenv("FV_CALIB_PATH", str(tmp_path / "calib.json"))
    store.clear()
    project.clear()
    yield
    store.clear()
    project.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _image(metadata: dict[str, Any] | None = None, calibrated: bool = False) -> str:
    axes = (
        (AxisCal(1.0, units="nm"), AxisCal(1.0, units="nm"))
        if calibrated
        else (AxisCal(), AxisCal())
    )
    ds = DataStruct(
        data=np.arange(24, dtype=np.float32).reshape(4, 6),
        kind=DataKind.IMAGE,
        axes=axes,
        metadata=dict(metadata or {}),
    )
    return store.add_parsed(ds, "frame.dm4")


DETECTOR = {
    "name": "Ultim Max",
    "kind": "detector",
    "fields": {
        "solid_angle": {"value": 0.7, "unit": "sr", "sigma": 0.05},
        "takeoff_angle": {"value": 22, "unit": "deg"},
    },
    "text": {"model": "Ultim Max 170"},
    "validity": {"beam_energy_kev": [80, 300]},
    "provenance": {"source": "datasheet", "date": "2026-01-15", "operator": "pq"},
}


def _create(client: TestClient, body: dict[str, Any] = DETECTOR) -> dict[str, Any]:
    r = client.post("/api/profiles", json=body)
    assert r.status_code == 200, r.text
    return r.json()["profile"]


# ── store over the wire ───────────────────────────────────────────────


def test_crud_history_and_kinds(client: TestClient) -> None:
    p = _create(client)
    assert p["version"] == 1
    assert p["fields"]["solid_angle"] == {"value": 0.7, "unit": "sr", "sigma": 0.05}
    assert p["fields"]["takeoff_angle"] == {"value": 22.0, "unit": "deg"}  # no sigma key
    assert client.get(f"/api/profiles/{p['id']}").json()["profile"] == p
    assert [x["id"] for x in client.get("/api/profiles").json()["profiles"]] == [p["id"]]
    assert client.get("/api/profiles", params={"kind": "camera"}).json()["profiles"] == []
    assert client.get("/api/profiles", params={"kind": "stage"}).status_code == 422

    up = client.put(
        f"/api/profiles/{p['id']}", json={"fields": {"takeoff_angle": {"value": 25, "unit": "deg"}}}
    )
    assert up.status_code == 200, up.text
    assert up.json()["profile"]["version"] == 2
    assert up.json()["profile"]["provenance"]["source"] == "datasheet"  # kept
    versions = client.get(f"/api/profiles/{p['id']}/history").json()["versions"]
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0] == p

    kinds = client.get("/api/profiles/kinds").json()
    assert kinds["kinds"] == ["acquisition", "camera", "detector", "microscope"]
    assert kinds["fields"]["acquisition"]["beam_energy"] == "keV"

    assert client.delete(f"/api/profiles/{p['id']}").status_code == 200
    assert client.get(f"/api/profiles/{p['id']}").status_code == 404
    assert client.get(f"/api/profiles/{p['id']}/history").status_code == 404
    assert client.put(f"/api/profiles/{p['id']}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/profiles/{p['id']}").status_code == 404


def test_an_unreadable_schema_is_a_422_on_every_write_route_too(
    tmp_path: Path, client: TestClient
) -> None:
    """A hand-edited `{"schema": "abc"}` used to raise a bare `ValueError`
    from `_load`, which the routes' `except ProfileError` misses -> a 500
    on every profiles endpoint. `profiles_delete` in particular had no
    `ProfileError` mapping at all, even for a valid int schema it cannot
    reach a profile through."""
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"schema": "abc", "profiles": {}}))
    assert client.get("/api/profiles").status_code == 422
    assert client.post("/api/profiles", json=DETECTOR).status_code == 422
    assert client.delete("/api/profiles/x").status_code == 422

    path.write_text(json.dumps({"schema": 9, "profiles": {}}))
    assert client.delete("/api/profiles/x").status_code == 422


def test_validation_errors_are_422(client: TestClient) -> None:
    bad_unit = {
        **DETECTOR,
        "kind": "acquisition",
        "fields": {"beam_energy": {"value": 200, "unit": "eV"}},
    }
    r = client.post("/api/profiles", json=bad_unit)
    assert r.status_code == 422 and "keV" in r.text
    assert client.post("/api/profiles", json={**DETECTOR, "kind": "stage"}).status_code == 422
    assert client.post("/api/profiles", json={**DETECTOR, "name": ""}).status_code == 422
    p = _create(client)
    r = client.put(f"/api/profiles/{p['id']}", json={"validity": {"magnification": [10, 1]}})
    assert r.status_code == 422
    assert (
        client.get(f"/api/profiles/{p['id']}").json()["profile"]["version"] == 1
    )  # nothing written


# ── apply ─────────────────────────────────────────────────────────────


def test_apply_writes_the_snapshot_and_reports_applicability(client: TestClient) -> None:
    p = _create(client)
    img = _image({"beam_kv": 30, "magnification": 20000})
    r = client.post("/api/profiles/apply", json={"image_id": img, "profile_id": p["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["applicability"] == [
        "beam_energy 30 keV is outside the profile's 80-300 keV range"
    ]
    meta = r.json()["image"]
    assert meta["profiles"]["detector"]["id"] == p["id"]
    assert meta["profiles"]["detector"]["version"] == 1
    assert meta["profiles"]["detector"]["applicability"] == r.json()["applicability"]
    assert meta["pixel_size"] is None  # a detector never touches the axes

    full = client.get(f"/api/profiles/applied/{img}").json()["profiles"]
    assert full["detector"]["fields"] == p["fields"]
    assert full["detector"]["applied_at"].endswith("+00:00")
    # the same profile shape reaches /image/{id}/meta
    assert (
        client.get(f"/api/image/{img}/meta").json()["profiles"]["detector"]["name"] == "Ultim Max"
    )

    # unapply drops it; a second unapply is a 404
    assert (
        client.post("/api/profiles/unapply", json={"image_id": img, "kind": "detector"}).status_code
        == 200
    )
    assert client.get(f"/api/image/{img}/meta").json()["profiles"] == {}
    assert (
        client.post("/api/profiles/unapply", json={"image_id": img, "kind": "detector"}).status_code
        == 404
    )
    assert (
        client.post("/api/profiles/unapply", json={"image_id": img, "kind": "stage"}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/profiles/apply", json={"image_id": "nope", "profile_id": p["id"]}
        ).status_code
        == 404
    )
    assert (
        client.post("/api/profiles/apply", json={"image_id": img, "profile_id": "nope"}).status_code
        == 404
    )


def test_a_malformed_snapshot_summarises_tolerantly_instead_of_raising(client: TestClient) -> None:
    """A hand-edited or future-build project can carry a `version` that
    isn't an int and an `applicability` that isn't a list (ADR 0009 §5);
    `_profile_refs` must coerce rather than raise, or every route that
    builds `ImageMeta` for that image (`/session/open`, `/session/images`,
    `/image/{id}/meta`) breaks."""
    img = _image(
        {
            "profiles": {
                "detector": {
                    "id": "d",
                    "name": "n",
                    "kind": "detector",
                    "version": "future",
                    "applicability": "nope",
                },
                "camera": 7,
                "microscope": {"version": 2.0, "applicability": ["a", 3]},
            }
        }
    )
    meta = ImageMeta.from_datastruct(img, store.name(img), store.get(img))
    profiles = meta.profiles
    assert profiles["detector"]["version"] == 0
    assert profiles["detector"]["applicability"] == []
    assert profiles["microscope"]["version"] == 2
    assert profiles["microscope"]["applicability"] == ["a", "3"]
    assert "camera" not in profiles

    r = client.get(f"/api/image/{img}/meta")
    assert r.status_code == 200, r.text
    assert r.json()["profiles"] == profiles


def test_a_spatial_acquisition_profile_writes_the_axes_per_axis(client: TestClient) -> None:
    p = _create(
        client,
        {
            "name": "AFM 2 um scan",
            "kind": "acquisition",
            "fields": {
                "pixel_size_row": {"value": 0.5, "unit": "nm"},
                "pixel_size_column": {"value": 2.0, "unit": "nm"},
                "beam_energy": {"value": 200, "unit": "keV"},
            },
        },
    )
    img = _image()
    r = client.post("/api/profiles/apply", json={"image_id": img, "profile_id": p["id"]})
    assert r.status_code == 200, r.text
    meta = r.json()["image"]
    assert meta["pixel_spacing"] == [0.5, 2.0]
    assert meta["pixel_size"] == 2.0
    ds = store.get(img)
    assert ds.metadata["calibration_source"] == f"profile:{p['id']}@1"
    assert ds.axes[0].scale == 0.5 and ds.axes[1].scale == 2.0
    # a profile with only ONE extent is malformed, not half a calibration:
    # refused when created, so nothing half-calibrated can ever be applied
    r = client.post(
        "/api/profiles",
        json={
            "name": "half",
            "kind": "acquisition",
            "fields": {"pixel_size_row": {"value": 0.5, "unit": "nm"}},
        },
    )
    assert r.status_code == 422 and "together" in r.text
    # unapply leaves the calibration the image now has
    client.post("/api/profiles/unapply", json={"image_id": img, "kind": "acquisition"})
    assert store.get(img).axes[1].scale == 2.0


def test_a_non_spatial_profile_leaves_a_calibrated_image_alone(client: TestClient) -> None:
    p = _create(
        client,
        {
            "name": "cond",
            "kind": "acquisition",
            "fields": {"live_time": {"value": 60, "unit": "s"}},
        },
    )
    img = _image(calibrated=True)
    r = client.post("/api/profiles/apply", json={"image_id": img, "profile_id": p["id"]})
    assert r.json()["image"]["pixel_size"] == 1.0
    assert "calibration_source" not in store.get(img).metadata


def test_legacy_import_route_is_idempotent(client: TestClient) -> None:
    save_calibration("Titan|50000", 0.42, "nm")
    save_calibration("AFM|1", None, "nm", pixel_spacing=(0.5, 2.0))
    r = client.post("/api/profiles/import-calibrations")
    assert r.status_code == 200, r.text
    assert sorted(p["name"] for p in r.json()["created"]) == ["AFM|1", "Titan|50000"]
    assert r.json()["skipped"] == []
    again = client.post("/api/profiles/import-calibrations").json()
    assert again["created"] == []
    assert len(again["skipped"]) == 2
    assert len(client.get("/api/profiles", params={"kind": "acquisition"}).json()["profiles"]) == 2
    # the imported profile applies exactly as the legacy key did
    afm = next(p for p in r.json()["created"] if p["name"] == "AFM|1")
    img = _image()
    applied = client.post(
        "/api/profiles/apply", json={"image_id": img, "profile_id": afm["id"]}
    ).json()
    assert applied["image"]["pixel_spacing"] == [0.5, 2.0]


# ── the point: results snapshot the profile they used ─────────────────


def test_a_captured_result_carries_the_profiles_and_a_later_edit_cannot_change_it(
    client: TestClient,
) -> None:
    p = _create(client)
    img = _image({"beam_kv": 200})
    client.post("/api/profiles/apply", json={"image_id": img, "profile_id": p["id"]})

    record = capture_result(
        analysis="eds.quantify",
        label="q",
        source_ids=[img],
        params={"kv": 200},
        clock=lambda: "2026-09-06T12:00:00+00:00",
    )
    (snap,) = record.calibration
    assert set(snap.profiles) == {"detector"}
    used = snap.profiles["detector"]
    assert (used["id"], used["version"]) == (p["id"], 1)
    assert used["fields"]["takeoff_angle"] == {"value": 22.0, "unit": "deg"}
    assert used["provenance"]["operator"] == "pq"

    # edit the profile: the store bumps to v2, the image's snapshot and the
    # record's copy both still say v1 with the old take-off angle
    client.put(
        f"/api/profiles/{p['id']}", json={"fields": {"takeoff_angle": {"value": 25, "unit": "deg"}}}
    )
    assert client.get(f"/api/profiles/{p['id']}").json()["profile"]["version"] == 2
    assert client.get(f"/api/image/{img}/meta").json()["profiles"]["detector"]["version"] == 1
    (again,) = project.current().results
    assert again.calibration[0].profiles["detector"]["fields"]["takeoff_angle"]["value"] == 22.0
    # and deleting the profile outright changes nothing either
    client.delete(f"/api/profiles/{p['id']}")
    assert project.current().results[0].calibration[0].profiles["detector"]["id"] == p["id"]


def test_profile_snapshots_round_trip_through_the_project_file(
    tmp_path: Path, client: TestClient
) -> None:
    p = _create(client)
    img = _image({"beam_kv": 200})
    client.post("/api/profiles/apply", json={"image_id": img, "profile_id": p["id"]})
    ds = store.get(img)
    record = ResultRecord(
        id="res1",
        analysis="eds.quantify",
        created_at="2026-09-06T12:00:00+00:00",
        status="completed",
        source_ids=(img,),
        calibration=(snapshot_calibration(img, ds),),
    )
    path = save_project(tmp_path / "p.fvp", [(img, "frame.dm4", ds)], results=[record])
    loaded = load_project(path)
    (back,) = loaded.results
    assert back.calibration == record.calibration  # `profiles` is modelled, not `extra`
    assert back.calibration[0].extra == {}
    # the image's own metadata carries the applied snapshot across the save too
    (image,) = loaded.images
    assert image.metadata["profiles"]["detector"]["id"] == p["id"]
    # on disk: the manifest states the profile under the calibration entry
    import zipfile

    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    cal = manifest["results"][0]["calibration"][0]
    assert cal["profiles"]["detector"]["version"] == 1
    assert cal["profiles"]["detector"]["kind"] == "detector"
    # a record with no profiles keeps the exact pre-ADR-0009 entry shape
    bare = ResultRecord(
        id="res2",
        analysis="x",
        created_at="t",
        status="completed",
        calibration=(CalibrationSnapshot(image_id=img, axes=ds.axes),),
    )
    path2 = save_project(tmp_path / "bare.fvp", [(img, "frame.dm4", ds)], results=[bare])
    with zipfile.ZipFile(path2) as zf:
        entry = json.loads(zf.read("manifest.json"))["results"][0]["calibration"][0]
    assert set(entry) == {"image_id", "axes", "source"}


def test_a_snapshot_key_this_build_does_not_model_still_rides_extra(tmp_path: Path) -> None:
    """The ADR 0004 promise, restated with `profiles` now modelled: a
    snapshot written by a LATER build with a key beside `profiles` keeps
    that key, and a malformed `profiles` value reads as none."""
    img = _image()
    ds = store.get(img)
    snap = CalibrationSnapshot(
        image_id=img,
        axes=ds.axes,
        profiles={"detector": {"id": "d", "name": "n", "kind": "detector", "version": 1}},
        extra={"standards": {"set": "nist-2027"}},
    )
    record = ResultRecord(
        id="r", analysis="x", created_at="t", status="completed", calibration=(snap,)
    )
    path = save_project(tmp_path / "p.fvp", [(img, "frame.dm4", ds)], results=[record])
    (back,) = load_project(path).results
    assert back.calibration[0].profiles == snap.profiles
    assert back.calibration[0].extra == {"standards": {"set": "nist-2027"}}


def test_comparison_notes_a_profile_version_difference() -> None:
    def rec(rid: str, version: int | None) -> ResultRecord:
        profiles = (
            {}
            if version is None
            else {"detector": {"id": "d1", "name": "Ultim", "kind": "detector", "version": version}}
        )
        return ResultRecord(
            id=rid,
            analysis="eds.quantify",
            created_at="t",
            status="completed",
            calibration=(
                CalibrationSnapshot(
                    image_id="img", axes=(AxisCal(1, units="nm"),) * 2, profiles=profiles
                ),
            ),
        )

    same = calibration_agreement(rec("a", 1), rec("b", 1))
    assert same.agrees and same.verified
    # `version` read two ways -- a string from one snapshot, an int from
    # another -- must still agree: both go through `snapshot_version`
    # (models.py and results_calibration.py used to coerce differently,
    # so the same profile could compare unequal to itself)
    string_version = rec("a", 1)
    string_version.calibration[0].profiles["detector"]["version"] = "1"
    coerced = calibration_agreement(string_version, rec("b", 1))
    assert coerced.agrees and coerced.verified
    edited = calibration_agreement(rec("a", 1), rec("b", 2))
    assert edited.differences == (
        "source image 'img': detector profile differs — reference a used d1@1, result b used d1@2",
    )
    missing = calibration_agreement(rec("a", 1), rec("b", None))
    assert missing.differences == (
        "source image 'img': detector profile differs — reference a used d1@1, result b used none",
    )
