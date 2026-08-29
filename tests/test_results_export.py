"""Self-contained export archives (roadmap item 2's last box):
`fermiviewer.results_export`.

The one property this module exists for is that **every citation in the
manifest resolves inside the archive**. `/results/report` already produces
the manifest; what is tested here is that the container beside it actually
holds what the manifest names — above all for the large arrays the report
can only cite, which is the exact case that kept the roadmap box open.

Records are built directly, like `test_results_report.py`: this is pure
logic over the item-1 contract, not route behaviour.
"""

from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pytest

from fermiviewer.io.project_manifest import ProjectFormatError
from fermiviewer.io.results_model import ResultOutput, ResultRecord
from fermiviewer.results_export import (
    ARCHIVE_VERSION,
    MANIFEST_NAME,
    METHODS_NAME,
    README_NAME,
    archive_bytes,
    build_archive,
)
from fermiviewer.results_report import MAX_INLINE_ARRAY_VALUES
from test_results_report import APP, fixed_clock, make_record


def export(*records: ResultRecord) -> zipfile.ZipFile:
    """Build and open an archive over `records`."""
    archive = build_archive(records, app_version=APP, clock=fixed_clock)
    return zipfile.ZipFile(io.BytesIO(archive_bytes(archive)))


def manifest_of(zf: zipfile.ZipFile) -> dict:
    return json.loads(zf.read(MANIFEST_NAME))


def with_array(array: np.ndarray, *, result_id: str = "aaa111", **kw) -> ResultRecord:
    """A record whose single curve output carries `array`."""
    return make_record(
        result_id=result_id,
        analysis="measure.profile",
        outputs=(
            ResultOutput(
                kind="curve",
                name="profile",
                data={"x_name": "distance", "x_unit": "nm", "y_name": "intensity"},
                array=array,
            ),
        ),
        **kw,
    )


# ── the reason this module exists ────────────────────────────────────


def test_an_array_too_large_to_inline_still_travels_with_the_manifest() -> None:
    """The whole point. The report can only CITE an array over the inline
    limit; the archive has to carry it, or the export is the same document
    that could not reconstruct what it named."""
    big = np.arange(MAX_INLINE_ARRAY_VALUES * 2, dtype=np.float64).reshape(-1, 2)
    zf = export(with_array(big))
    (output,) = manifest_of(zf)["results"][0]["outputs"]

    # the manifest declines to inline it, exactly as the report does
    assert output["values_inlined"] is False
    assert output["values"] is None
    # ...and the citation it offers instead RESOLVES, in this archive
    assert output["member"] in zf.namelist()
    with zf.open(output["member"]) as fh:
        restored = np.load(fh, allow_pickle=False)
    assert np.array_equal(restored, big)
    assert restored.dtype == big.dtype


def test_every_member_the_manifest_cites_is_present() -> None:
    """Not just the large one: no output may cite an entry the archive
    lacks, or a reader hits a hole the manifest never warned about."""
    zf = export(
        with_array(np.linspace(0, 1, 8).reshape(-1, 2), result_id="aaa111"),
        with_array(np.zeros((3, 2)), result_id="bbb222"),
    )
    names = set(zf.namelist())
    cited = [
        output["member"]
        for record in manifest_of(zf)["results"]
        for output in record["outputs"]
        if output["member"] is not None
    ]
    assert cited, "fixture produced no citations to check"
    assert set(cited) <= names


def test_the_npy_keeps_values_the_json_view_cannot_carry() -> None:
    """`values` is JSON-safe, so NaN becomes null; the `.npy` is the exact
    array. The archive claims the `.npy` is authoritative — that claim has
    to be true, or the two copies quietly disagree."""
    array = np.array([[0.0, 1.0], [1.0, np.nan]], dtype=np.float64)
    zf = export(with_array(array))
    (output,) = manifest_of(zf)["results"][0]["outputs"]

    assert output["values"] == [[0.0, 1.0], [1.0, None]]  # null, position kept
    with zf.open(output["member"]) as fh:
        restored = np.load(fh, allow_pickle=False)
    assert np.isnan(restored[1][1])                       # the real value survives


# ── degraded records ─────────────────────────────────────────────────


def test_a_lost_member_leaves_a_gap_the_manifest_explains_not_invented_zeros() -> None:
    """An output whose array was already lost writes no entry. Filling the
    hole with zeros would turn a missing array into a wrong one."""
    record = make_record(
        analysis="measure.profile",
        missing_members=("results/aaa111/0.npy",),
        outputs=(
            ResultOutput(
                kind="curve",
                name="profile",
                data={"x_name": "distance"},
                member="results/aaa111/0.npy",
                array=None,          # the degraded state a bad load leaves
            ),
        ),
    )
    zf = export(record)
    manifest = manifest_of(zf)
    (output,) = manifest["results"][0]["outputs"]

    assert output["member"] == "results/aaa111/0.npy"   # citation preserved
    assert output["member"] not in zf.namelist()        # but nothing invented
    assert any(
        "aaa111" in w and "missing or unreadable" in w for w in manifest["warnings"]
    )


def test_a_failed_record_exports_as_failed() -> None:
    zf = export(make_record(status="failed", error="tilt 90 deg is degenerate"))
    manifest = manifest_of(zf)
    assert manifest["results"][0]["status"] == "failed"
    assert any("degenerate" in w for w in manifest["warnings"])


# ── archive shape and determinism ────────────────────────────────────


def test_the_archive_explains_itself_without_the_app() -> None:
    """A reader who has only the file needs to know how to resolve a
    member; the README is the only place that can tell them."""
    zf = export(with_array(np.zeros((2, 2))))
    assert {MANIFEST_NAME, README_NAME, METHODS_NAME} <= set(zf.namelist())
    readme = zf.read(README_NAME).decode()
    assert "numpy.load" in readme
    assert "member" in readme
    assert APP in readme
    assert manifest_of(zf)["archive_version"] == ARCHIVE_VERSION


def test_two_exports_of_one_selection_are_byte_identical() -> None:
    """An archive someone may hash and cite must not change because the
    clock moved or the umask differs."""
    records = (with_array(np.linspace(0, 1, 64).reshape(-1, 2)),)
    first = archive_bytes(build_archive(records, app_version=APP, clock=fixed_clock))
    second = archive_bytes(build_archive(records, app_version=APP, clock=fixed_clock))
    assert first == second


def test_every_host_derived_header_field_is_pinned() -> None:
    """Byte-reproducibility has to hold ACROSS hosts, not just across two
    runs on one machine — the determinism test above compares two archives
    built by the same process, so it cannot see a field that varies by
    platform. Each of these is one `zipfile` would otherwise take from the
    environment:

    * `date_time` — the wall clock;
    * `external_attr` — the process umask;
    * `create_system` — `sys.platform`; `ZipInfo.__init__` writes 0 on
      Windows and 3 elsewhere, into the central directory, so an archive
      built on a Windows runner would not hash equal to a Linux one.
    """
    zf = export(with_array(np.zeros((4, 2))))
    infos = zf.infolist()
    assert infos, "fixture produced no entries to check"
    for info in infos:
        assert info.date_time == (1980, 1, 1, 0, 0, 0), info.filename
        assert info.create_system == 3, info.filename        # Unix, not the host
        assert info.external_attr == (0o644 << 16), info.filename


def test_the_creator_system_is_pinned_rather_than_inherited(monkeypatch) -> None:
    """The assertion above reads `create_system == 3`, which a Linux host
    satisfies by accident — it only discriminates on the Windows runner.
    Pretending to be Windows makes the check bite everywhere: `ZipInfo`
    reads `sys.platform` in its constructor, so an unpinned entry would
    come back 0 here.
    """
    monkeypatch.setattr(zipfile.sys, "platform", "win32")
    assert zipfile.ZipInfo("probe").create_system == 0     # the default we override
    zf = export(with_array(np.zeros((4, 2))))
    assert [i.create_system for i in zf.infolist()] == [3] * len(zf.infolist())


def test_selection_order_is_the_archive_order() -> None:
    """A report is a composed document; the export inherits that, so the
    author's order is what ships."""
    zf = export(
        with_array(np.zeros((2, 2)), result_id="bbb222"),
        with_array(np.zeros((2, 2)), result_id="aaa111"),
    )
    assert [r["id"] for r in manifest_of(zf)["results"]] == ["bbb222", "aaa111"]


def test_a_member_is_allocated_for_a_record_whose_project_was_never_saved() -> None:
    """Capture allocates members, but a record built in memory may not have
    one. The export must not silently drop its array for want of a name."""
    record = with_array(np.zeros((2, 2)))
    assert record.outputs[0].member is None
    zf = export(record)
    (output,) = manifest_of(zf)["results"][0]["outputs"]
    assert output["member"] == "results/aaa111/0.npy"
    assert output["member"] in zf.namelist()


# ── validation ───────────────────────────────────────────────────────


def test_a_malformed_selection_fails_before_any_bytes_are_produced() -> None:
    """Ids name the member directory, so a duplicate would silently
    overwrite one record's arrays with another's."""
    duplicate = with_array(np.zeros((2, 2)), result_id="aaa111")
    with pytest.raises(ProjectFormatError, match="duplicate result id"):
        build_archive([duplicate, duplicate], app_version=APP, clock=fixed_clock)
