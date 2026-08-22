"""Persistent analysis results in `.fvp` v2 — ADR 0004's verification list.

Covers: save/load round-trip of records with inline and member outputs;
member arrays never inline in the manifest; missing and unreadable members
degrading with `missing_members` set and surviving a re-save; hostile result
ids and member paths rejected before ZIP access; duplicate ids/members as
save errors; failed/cancelled records round-tripping with `error` and
without outputs; strict-JSON manifests under non-finite params; v1
migration yielding no results; unknown record/output keys carried verbatim;
`OpenProject`/`ProjectSession` carrying results through merges and through a
save the client never mentioned them in.

The container fundamentals (atomicity, schema identity, image handling) stay
in tests/test_project_format.py; the route surface conventions follow
tests/test_api_project_io.py.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.project_file import load_project, save_project
from fermiviewer.io.project_manifest import (
    MANIFEST_NAME,
    LoadedProject,
    ProjectFormatError,
)
from fermiviewer.io.project_results import (
    CalibrationSnapshot,
    ResultOutput,
    ResultRecord,
    new_result_id,
    snapshot_calibration,
)
from fermiviewer.project_session import ProjectSession, project
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.v1_session import write_v1_session

#: Fixed timestamp so saved manifests are deterministic run to run.
CREATED_AT = "2026-08-22T20:00:00+00:00"

SCALAR_DATA: dict[str, Any] = {"value": 99.2, "unit": "wt%", "sigma": 0.4}
TABLE_DATA: dict[str, Any] = {"columns": ["area", "ecd"], "units": ["nm^2", "nm"]}
CURVE_DATA: dict[str, Any] = {
    "x_name": "distance",
    "x_unit": "nm",
    "y_name": "intensity",
    "y_unit": "counts",
}
PARAMS: dict[str, Any] = {"kv": 200.0, "model": "cliff_lorimer", "window": [1.0, 2.0]}


def _image(
    value: int = 1, name: str = "frame.tif", img_id: str = "img1"
) -> tuple[str, str, DataStruct]:
    ds = DataStruct(
        data=np.full((3, 4), value, dtype=np.uint16),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        metadata={"vendor": "acme", "beam_kv": 200},
    )
    return (img_id, name, ds)


def _cal_ds() -> DataStruct:
    """A source image carrying the `calibration_source` provenance string."""
    return DataStruct(
        data=np.zeros((3, 4), dtype=np.uint16),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        metadata={"vendor": "acme", "calibration_source": "fei"},
    )


def _table_array() -> np.ndarray:
    # 777.25 is deliberately distinctive: its absence from manifest.json is
    # how the arrays-never-inline test proves no row data leaked into it.
    return np.array([[777.25, 2.5, 3.5], [10.0, 20.0, 30.0]], dtype=np.float64)


def _curve_array() -> np.ndarray:
    x = np.linspace(0.0, 1.0, 5)
    return np.column_stack([x, x * 2.0, np.full(5, 0.1)])  # (N, 3): x, y, sigma


def _record(rid: str = "res1") -> ResultRecord:
    """A completed EDS-quant-shaped record with all three output flavours:
    inline-only (scalar), inline + member (table), member-only data (curve)."""
    return ResultRecord(
        id=rid,
        analysis="eds.quantify",
        created_at=CREATED_AT,
        status="completed",
        label="Quant of frame.tif",
        app_version="0.1.32",
        source_ids=("img1",),
        derived_ids=("map-fe",),
        region_ids=("m1",),
        params=dict(PARAMS),
        calibration=(snapshot_calibration("img1", _cal_ds()),),
        warnings=("low counts in O K",),
        outputs=(
            ResultOutput(kind="scalar", name="total", data=dict(SCALAR_DATA)),
            ResultOutput(
                kind="table", name="particles", data=dict(TABLE_DATA), array=_table_array()
            ),
            ResultOutput(kind="curve", name="profile", data=dict(CURVE_DATA), array=_curve_array()),
        ),
    )


def _meta_record(rid: str, *, status: str = "completed", error: str | None = None) -> ResultRecord:
    """A metadata-only record (no arrays), safe to compare with `==`."""
    return ResultRecord(
        id=rid,
        analysis="measure.profile",
        created_at=CREATED_AT,
        status=status,
        error=error,
    )


def _manifest(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        loaded: dict[str, Any] = json.loads(zf.read(MANIFEST_NAME))
    return loaded


def _rewrite_manifest(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    """Edit manifest.json in place inside an existing container."""
    with zipfile.ZipFile(path) as zf:
        blobs = {name: zf.read(name) for name in zf.namelist()}
    manifest = json.loads(blobs[MANIFEST_NAME])
    mutate(manifest)
    blobs[MANIFEST_NAME] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, blob in blobs.items():
            zf.writestr(name, blob)


def _rewrite_entries(path: Path, mutate: Callable[[dict[str, bytes]], None]) -> None:
    """Rezip the container after editing its raw entry dict — for crafting a
    degraded container (a member dropped, or replaced with garbage)."""
    with zipfile.ZipFile(path) as zf:
        blobs = {name: zf.read(name) for name in zf.namelist()}
    mutate(blobs)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, blob in blobs.items():
            zf.writestr(name, blob)


# ── round trip (ADR 0004 §1–§3) ──────────────────────────────────────


def test_round_trip_is_deep_equal(tmp_path: Path) -> None:
    """Every field of a record must survive save → load: the record IS the
    project's memory of the analysis, so any field silently dropped here is
    provenance the reopened project can no longer produce (ADR 0004 §1)."""
    path = save_project(tmp_path / "study.fvp", [_image()], results=[_record()])

    loaded = load_project(path)
    (rec,) = loaded.results
    assert rec.id == "res1"
    assert rec.analysis == "eds.quantify"
    assert rec.created_at == CREATED_AT
    assert rec.status == "completed"
    assert rec.label == "Quant of frame.tif"
    assert rec.app_version == "0.1.32"
    assert rec.schema == 1
    assert rec.source_ids == ("img1",)
    assert rec.derived_ids == ("map-fe",)
    assert rec.region_ids == ("m1",)
    assert rec.params == PARAMS
    assert rec.warnings == ("low counts in O K",)
    assert rec.error is None  # a completed record records no failure
    assert rec.missing_members == ()
    assert rec.extra == {}

    # calibration came back as the snapshot taken at compute time (§5)
    (snap,) = rec.calibration
    assert snap.image_id == "img1"
    assert snap.axes == (AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm"))
    assert snap.source == "fei"

    scalar, table, curve = rec.outputs
    assert (scalar.kind, scalar.name, scalar.data) == ("scalar", "total", SCALAR_DATA)
    assert scalar.member is None and scalar.array is None
    assert (table.kind, table.name, table.data) == ("table", "particles", TABLE_DATA)
    # member names are allocated as results/<id>/<output-index>.npy (§2)
    assert table.member == "results/res1/1.npy"
    np.testing.assert_array_equal(table.array, _table_array())
    assert table.array is not None and table.array.dtype == np.float64
    assert (curve.kind, curve.name, curve.data) == ("curve", "profile", CURVE_DATA)
    assert curve.member == "results/res1/2.npy"
    np.testing.assert_array_equal(curve.array, _curve_array())
    assert curve.array is not None and curve.array.shape == (5, 3)


def test_arrays_are_zip_members_never_inline_json(tmp_path: Path) -> None:
    """A particle table inlined into manifest.json would make every load
    parse megabytes of numbers it may never look at — the manifest holds
    only the member reference (ADR 0004 §2)."""
    path = save_project(tmp_path / "study.fvp", [_image()], results=[_record()])

    with zipfile.ZipFile(path) as zf:
        raw = zf.read(MANIFEST_NAME)
        names = zf.namelist()
        assert "results/res1/1.npy" in names
        assert "results/res1/2.npy" in names
        with zf.open("results/res1/1.npy") as fh:
            member_array = np.load(fh, allow_pickle=False)
    # the distinctive table value appears in the member, not in the manifest
    assert b"777.25" not in raw
    np.testing.assert_array_equal(member_array, _table_array())

    (entry,) = _manifest(path)["results"]
    assert entry["outputs"][1]["member"] == "results/res1/1.npy"
    assert entry["outputs"][1]["data"] == TABLE_DATA  # inline half only


def test_a_loaded_project_resaves_its_results_losslessly(tmp_path: Path) -> None:
    """Feeding `loaded.results` straight back into `save_project` is exactly
    what the server-carried re-save does, so it must lose nothing."""
    first = save_project(tmp_path / "one.fvp", [_image()], results=[_record()])
    loaded = load_project(first)

    second = save_project(tmp_path / "two.fvp", loaded.images, results=loaded.results)
    (rec,) = load_project(second).results
    assert rec.id == "res1"
    assert rec.params == PARAMS
    assert rec.warnings == ("low counts in O K",)
    assert rec.calibration == (
        CalibrationSnapshot(
            image_id="img1",
            axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
            source="fei",
        ),
    )
    assert [o.member for o in rec.outputs] == [None, "results/res1/1.npy", "results/res1/2.npy"]
    np.testing.assert_array_equal(rec.outputs[1].array, _table_array())
    np.testing.assert_array_equal(rec.outputs[2].array, _curve_array())
    assert rec.missing_members == ()


# ── missing / unreadable members degrade, never fail (ADR 0004 §6) ───


def test_a_missing_member_degrades_the_record_and_survives_a_resave(
    tmp_path: Path,
) -> None:
    """Results are precious but secondary to the data they describe: a lost
    member must not fail the project load (the images still matter more),
    and a re-save must keep the dangling reference — opening a damaged
    project and pressing save cannot also destroy the evidence of what the
    record carried (ADR 0002 §4's guarantee, applied to results)."""
    path = save_project(tmp_path / "study.fvp", [_image(value=5)], results=[_record()])
    _rewrite_entries(path, lambda blobs: blobs.pop("results/res1/1.npy"))

    loaded = load_project(path)
    (img,) = loaded.images
    np.testing.assert_array_equal(img.data, np.full((3, 4), 5, np.uint16))  # images fine
    (rec,) = loaded.results
    assert rec.missing_members == ("results/res1/1.npy",)
    assert rec.status == "completed"  # metadata intact
    assert rec.params == PARAMS
    scalar, table, curve = rec.outputs
    assert table.array is None  # degraded, not invented
    assert table.member == "results/res1/1.npy"  # the reference is kept
    assert table.data == TABLE_DATA  # the inline half survived
    np.testing.assert_array_equal(curve.array, _curve_array())  # others unharmed

    # the re-save writes the dangling reference back, and flags it again
    resaved = save_project(tmp_path / "again.fvp", loaded.images, results=loaded.results)
    (entry,) = _manifest(resaved)["results"]
    assert entry["outputs"][1]["member"] == "results/res1/1.npy"  # evidence preserved
    with zipfile.ZipFile(resaved) as zf:
        assert "results/res1/1.npy" not in zf.namelist()  # nothing to write
        assert "results/res1/2.npy" in zf.namelist()  # the readable one is
    (again,) = load_project(resaved).results
    assert again.missing_members == ("results/res1/1.npy",)
    assert again.outputs[1].array is None


def test_an_unreadable_member_degrades_exactly_like_a_missing_one(
    tmp_path: Path,
) -> None:
    """Held-unreadably and not-held are the same failure to the user, so they
    degrade the same way instead of one raising (ADR 0004 §6)."""
    path = save_project(tmp_path / "study.fvp", [_image()], results=[_record()])
    _rewrite_entries(path, lambda blobs: blobs.__setitem__("results/res1/1.npy", b"not npy"))

    loaded = load_project(path)  # no exception
    (rec,) = loaded.results
    assert rec.missing_members == ("results/res1/1.npy",)
    assert rec.outputs[1].array is None
    assert rec.outputs[1].member == "results/res1/1.npy"
    assert rec.outputs[1].data == TABLE_DATA
    np.testing.assert_array_equal(rec.outputs[2].array, _curve_array())


# ── failed / cancelled records (ADR 0004 §4) ─────────────────────────


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_and_cancelled_records_round_trip_with_error_and_no_outputs(
    tmp_path: Path, status: str
) -> None:
    """`completed | failed | cancelled` is the vocabulary of a scientific
    record, deliberately not the job poller's queued/running/done/error: a
    run that did not finish is recorded separately from completed science,
    with the reason in `error` and no pretence of outputs (ADR 0004 §4)."""
    rec = ResultRecord(
        id="bad1",
        analysis="diffraction.index",
        created_at=CREATED_AT,
        status=status,
        error="beam blanked mid-acquisition",
        source_ids=("img1",),
    )
    path = save_project(tmp_path / "study.fvp", [_image()], results=[rec, _record("ok1")])

    bad, ok = load_project(path).results
    assert bad.status == status
    assert bad.error == "beam blanked mid-acquisition"
    assert bad.outputs == ()
    assert ok.status == "completed"
    assert ok.error is None


# ── save-side validation (before anything is written) ────────────────


def test_duplicate_result_ids_are_refused(tmp_path: Path) -> None:
    """The id names the results/<id>/ member directory, so a repeat would
    write duplicate ZIP entries and one record would shadow the other."""
    with pytest.raises(ProjectFormatError, match="duplicate result id"):
        save_project(tmp_path / "study.fvp", [_image()], results=[_record("dup"), _record("dup")])
    assert list(tmp_path.iterdir()) == []  # nothing was staged or committed


@pytest.mark.parametrize("rid", ["../evil", "a/b", "", "..", "C:"])
def test_hostile_result_ids_are_refused_on_save(tmp_path: Path, rid: str) -> None:
    """`unzip project.fvp` is an advertised inspection route, so an id that
    is not a single clean path component would plant a zip-slip entry for
    whoever does that (ADR 0004 §2's threat model)."""
    with pytest.raises(ProjectFormatError, match=r"results\[0\]\.id"):
        save_project(tmp_path / "study.fvp", [_image()], results=[_record(rid)])
    assert list(tmp_path.iterdir()) == []


def test_an_invalid_status_is_refused_on_save(tmp_path: Path) -> None:
    rec = ResultRecord(id="r1", analysis="eds.quantify", created_at=CREATED_AT, status="done")
    with pytest.raises(ProjectFormatError, match=r"results\[0\]\.status"):
        save_project(tmp_path / "study.fvp", [_image()], results=[rec])


def test_an_invalid_output_kind_is_refused_on_save(tmp_path: Path) -> None:
    """`kind` is a closed set (ADR 0004 §3): one shared envelope instead of a
    persistence format per workshop, so a stray kind is a bug, not data."""
    rec = ResultRecord(
        id="r1",
        analysis="eds.quantify",
        created_at=CREATED_AT,
        status="completed",
        outputs=(ResultOutput(kind="hologram", name="x"),),
    )
    with pytest.raises(ProjectFormatError, match=r"outputs\[0\]\.kind"):
        save_project(tmp_path / "study.fvp", [_image()], results=[rec])


def test_duplicate_explicit_member_paths_are_refused(tmp_path: Path) -> None:
    """A repeated member entry would write a duplicate ZIP entry and one
    output would silently read back the other's array — within a record and
    across records alike."""
    shared = "results/r1/0.npy"

    def out() -> ResultOutput:
        return ResultOutput(kind="map", name="x", member=shared, array=np.zeros((2, 2), np.float32))

    within = ResultRecord(
        id="r1",
        analysis="eds.maps",
        created_at=CREATED_AT,
        status="completed",
        outputs=(out(), out()),
    )
    with pytest.raises(ProjectFormatError, match="duplicate member entry"):
        save_project(tmp_path / "study.fvp", [_image()], results=[within])

    across = [
        ResultRecord(
            id=rid,
            analysis="eds.maps",
            created_at=CREATED_AT,
            status="completed",
            outputs=(out(),),
        )
        for rid in ("r1", "r2")
    ]
    with pytest.raises(ProjectFormatError, match="duplicate member entry"):
        save_project(tmp_path / "study.fvp", [_image()], results=across)


# ── load-side path safety (before any ZIP access) ────────────────────


@pytest.mark.parametrize(
    "member",
    [
        "pixels/img1.npy",  # inside the container but outside results/
        "../x.npy",
        "/abs.npy",
        "results/../evil.npy",
    ],
)
def test_a_hostile_member_path_in_the_manifest_is_refused(tmp_path: Path, member: str) -> None:
    """A .fvp is a file a stranger can send: a member reference that escapes
    `results/` invalidates the manifest before any ZIP access, rather than
    being skipped mid-read (same rule as image ids and rels)."""
    path = save_project(tmp_path / "study.fvp", [_image()], results=[_record()])
    _rewrite_manifest(path, lambda m: m["results"][0]["outputs"][0].__setitem__("member", member))

    with pytest.raises(ProjectFormatError, match=r"results\[0\]\.outputs\[0\]\.member"):
        load_project(path)


def test_a_hostile_result_id_in_the_manifest_is_refused(tmp_path: Path) -> None:
    path = save_project(tmp_path / "study.fvp", [_image()], results=[_record()])
    _rewrite_manifest(path, lambda m: m["results"][0].__setitem__("id", "../evil"))

    with pytest.raises(ProjectFormatError, match=r"results\[0\]\.id"):
        load_project(path)


# ── forward compatibility (ADR 0002 §6 applied to results) ───────────


def test_unknown_record_and_output_keys_round_trip_verbatim(tmp_path: Path) -> None:
    """A record written by a newer build and re-saved by this one must not
    lose what this one did not understand — at the record level and inside
    each output envelope."""
    path = save_project(tmp_path / "study.fvp", [_image()], results=[_record()])

    def inject(manifest: dict[str, Any]) -> None:
        manifest["results"][0]["reviewed_by"] = "paige"
        manifest["results"][0]["outputs"][0]["render_hint"] = {"digits": 3}

    _rewrite_manifest(path, inject)

    loaded = load_project(path)
    (rec,) = loaded.results
    assert rec.extra == {"reviewed_by": "paige"}
    assert rec.outputs[0].extra == {"render_hint": {"digits": 3}}

    resaved = save_project(tmp_path / "again.fvp", loaded.images, results=loaded.results)
    (entry,) = _manifest(resaved)["results"]
    assert entry["reviewed_by"] == "paige"
    assert entry["outputs"][0]["render_hint"] == {"digits": 3}


def test_a_project_without_results_loads_with_an_empty_tuple(tmp_path: Path) -> None:
    """The section is a non-breaking extension: a save writes an explicit
    empty list, and a manifest missing the key entirely (an older writer)
    loads the same way — never as an error (ADR 0004 §1)."""
    path = save_project(tmp_path / "study.fvp", [_image()])
    assert _manifest(path)["results"] == []
    assert load_project(path).results == ()

    _rewrite_manifest(path, lambda m: m.pop("results"))
    assert load_project(path).results == ()


# ── v1 migration ─────────────────────────────────────────────────────


def test_a_v1_workspace_migrates_with_no_results(tmp_path: Path) -> None:
    """A v1 file never carried results, so migration invents none — an empty
    tuple, not a fabricated record (ADR 0004 Consequences)."""
    json_path, _ = write_v1_session(tmp_path / "legacy.json", [_image(img_id="v1-a")], {})

    loaded = load_project(json_path)
    assert [img.id for img in loaded.images] == ["v1-a"]
    assert loaded.results == ()


# ── non-finite scrub (strict JSON, finite_json convention) ───────────


def test_non_finite_params_and_data_stay_out_of_the_manifest(tmp_path: Path) -> None:
    """`json.dumps` writes NaN as the bare token `NaN`, which strict readers
    (and the browser's JSON.parse) refuse — one non-finite float anywhere
    would produce a project this app can write and not read back. Per the
    `finite_json` convention a NaN-valued dict key is dropped and a list
    element becomes None so indices stay aligned."""
    rec = ResultRecord(
        id="r1",
        analysis="eds.quantify",
        created_at=CREATED_AT,
        status="completed",
        params={
            "good": 1.5,
            "nan": float("nan"),
            "inf": float("inf"),
            "trace": [1.0, float("nan"), 3.0],
        },
        outputs=(
            ResultOutput(
                kind="scalar",
                name="total",
                data={"value": 3.5, "sigma": float("nan")},
            ),
        ),
    )
    path = save_project(tmp_path / "study.fvp", [_image()], results=[rec])

    with zipfile.ZipFile(path) as zf:
        raw = zf.read(MANIFEST_NAME)
    assert b"NaN" not in raw and b"Infinity" not in raw

    def _reject_non_finite(token: str) -> float:
        raise ValueError(f"manifest.json is not strict JSON: {token!r} token present")

    json.loads(raw, parse_constant=_reject_non_finite)

    (loaded,) = load_project(path).results
    assert loaded.params == {"good": 1.5, "trace": [1.0, None, 3.0]}
    assert loaded.outputs[0].data == {"value": 3.5}


# ── calibration snapshots (ADR 0004 §5) ──────────────────────────────


def test_snapshot_calibration_copies_axes_and_provenance() -> None:
    """A copy taken at compute time, not a reference: recalibrating the image
    later must not silently rewrite what a stored composition meant when it
    was measured (the deliberate inverse of the `measures` rule)."""
    ds = _cal_ds()
    snap = snapshot_calibration("img1", ds)
    assert snap.image_id == "img1"
    assert snap.axes == tuple(ds.axes)
    assert snap.source == "fei"

    # no provenance string recorded → None, not an invented one
    bare = DataStruct(
        data=np.zeros((3, 4), dtype=np.uint16),
        kind=DataKind.IMAGE,
        axes=tuple(ds.axes),
        metadata={},
    )
    assert snapshot_calibration("img1", bare).source is None


def test_a_nan_snapshot_scale_is_written_as_zero_and_the_source_survives(
    tmp_path: Path,
) -> None:
    """Snapshots ride `axes_to_manifest`, so an uncalibrated axis's raw NaN
    scale becomes 0.0 in the manifest — the same lossless substitution the
    image axes use (0 and NaN both mean uncalibrated to `AxisCal`)."""
    rec = ResultRecord(
        id="r1",
        analysis="measure.profile",
        created_at=CREATED_AT,
        status="completed",
        calibration=(
            CalibrationSnapshot(
                image_id="img1",
                axes=(AxisCal(float("nan"), units=""), AxisCal(0.5, units="nm")),
                source="db:helios-450",
            ),
        ),
    )
    path = save_project(tmp_path / "study.fvp", [_image()], results=[rec])

    (loaded,) = load_project(path).results
    (snap,) = loaded.calibration
    assert snap.axes[0] == AxisCal(0.0, 0.0, "")
    assert snap.axes[0].calibrated is False
    assert snap.axes[1] == AxisCal(0.5, units="nm")  # the real axis untouched
    assert snap.source == "db:helios-450"


# ── ProjectSession carry (ADR 0004 §6) ───────────────────────────────


def test_adopt_replaces_results_and_a_merge_appends_and_dedupes(tmp_path: Path) -> None:
    """Results are server-carried exactly like placeholders: a replacing load
    swaps them, an append load must not drop the first project's records,
    and re-loading the same file must not double them (merge by record id)."""
    session = ProjectSession()
    rec_a = _meta_record("aaa")
    rec_b = _meta_record("bbb")

    session.adopt(LoadedProject(results=(rec_a,)), tmp_path / "one.fvp")
    assert session.current().results == (rec_a,)

    # a replacing load forgets the previous project's results with it
    session.adopt(LoadedProject(results=(rec_b,)), tmp_path / "two.fvp")
    assert session.current().results == (rec_b,)

    # an append load keeps what is open and adds the arriving records
    session.adopt(LoadedProject(results=(rec_a,)), tmp_path / "one.fvp", merge=True)
    assert session.current().results == (rec_b, rec_a)

    # re-adopting the same file does not double them
    session.adopt(LoadedProject(results=(rec_a,)), tmp_path / "one.fvp", merge=True)
    assert session.current().results == (rec_b, rec_a)


# ── the route surface (item 1A's slice only) ─────────────────────────
# Only what 1A guarantees is asserted here: loading exposes the records in
# manifest form, and a save the client drives preserves them without the
# client ever echoing them back. The creation/query API is item 1C.


@pytest.fixture()
def client() -> Any:
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


@pytest.mark.api
def test_load_route_exposes_results_and_save_route_preserves_them(
    client: TestClient, tmp_path: Path
) -> None:
    """ADR 0004 §6: the client never echoes results back, so a re-save that
    depended on it would silently destroy recorded science — the server
    carries them through the whole load → save cycle."""
    path = save_project(tmp_path / "study.fvp", [_image()], results=[_record()])

    r = client.post("/api/project/load", json={"path": str(path)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project"]["n_results"] == 1
    (entry,) = body["results"]  # manifest form: metadata + member references
    assert entry["id"] == "res1"
    assert entry["analysis"] == "eds.quantify"
    assert entry["status"] == "completed"
    assert entry["params"] == PARAMS
    assert [o["member"] for o in entry["outputs"]] == [
        None,
        "results/res1/1.npy",
        "results/res1/2.npy",
    ]
    assert "array" not in entry["outputs"][1]  # never the arrays themselves

    # the client sends only its own state — no mention of results anywhere
    saved = client.post(
        "/api/project/save",
        json={"path": str(tmp_path / "resaved.fvp"), "client_state": body["client_state"]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["n_results"] == 1

    (rec,) = load_project(tmp_path / "resaved.fvp").results
    assert rec.id == "res1"
    assert rec.params == PARAMS
    np.testing.assert_array_equal(rec.outputs[1].array, _table_array())
    np.testing.assert_array_equal(rec.outputs[2].array, _curve_array())
    assert rec.missing_members == ()


# ── id minting ───────────────────────────────────────────────────────


def test_new_result_id_follows_the_repo_convention() -> None:
    """uuid4().hex[:12] — the stable-id convention `session.py` set; the id
    must also be a legal member-directory component as minted."""
    a, b = new_result_id(), new_result_id()
    assert a != b
    assert len(a) == 12
    assert a.isalnum()
