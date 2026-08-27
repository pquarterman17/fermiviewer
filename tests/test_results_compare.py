"""Compatible-result query — roadmap item 2B's rule set and its messages.

Records are built directly (no HTTP, no project container): this is the
pure-logic half of 2B, and the route wiring is a separate surface.

Every rejection test asserts on the MESSAGE, not only the `code`. The
roadmap line is "explicit incompatibility messages" — a message that does
not name both records and the exact output/unit at fault would satisfy the
code assertion while failing the feature.

Covered: the reflexive case; analysis mismatch; failed and cancelled
records; kind mismatch; scalar, curve-axis and table-column unit
mismatches; unverified units and the dimensionless opt-in (including a
realistic `measure.profile` pair, whose `y_unit=""` must NOT certify);
dropped outputs as notes; per-candidate matches and the honestly-empty
cumulative intersection; the nothing-comparable-left rejection;
calibration disagreement AND unverified calibration arriving as notes
rather than rejections; and deterministic ordering across candidates.

`calibration_agreement` itself — source inventories, which fields count as
a disagreement, NaN handling — is tests/test_results_calibration.py, one
test file per module. Only the crossing point is asserted from here.
"""

from __future__ import annotations

from typing import Any

import pytest

from fermiviewer import results_calibration, results_compare
from fermiviewer.datastruct import AxisCal
from fermiviewer.io.results_model import (
    RESULT_STATUSES,
    CalibrationSnapshot,
    ResultOutput,
    ResultRecord,
)
from fermiviewer.results_compare import (
    CODE_ANALYSIS_MISMATCH,
    CODE_NO_SHARED_OUTPUTS,
    CODE_OUTPUT_KIND_MISMATCH,
    CODE_OUTPUT_UNIT_MISMATCH,
    CODE_STATUS_NOT_COMPLETED,
    COMPARABLE_STATUS,
    DIMENSIONLESS_KEY,
    INCOMPATIBILITY_CODES,
    CalibrationAgreement,
    CandidateMatch,
    Comparison,
    calibration_agreement,
    calibration_coverage_notes,
    compare_results,
)

ANALYSIS = "eds.quantify"


def snapshot(
    image_id: str, scale: float, units: str, source: str | None = None
) -> CalibrationSnapshot:
    return CalibrationSnapshot(
        image_id=image_id,
        axes=(AxisCal(scale=scale, units=units), AxisCal(scale=scale, units=units)),
        source=source,
    )


#: The quiet baseline: both records snapshotted the SAME source image and
#: agree about it, so calibration is verified and adds no note. Tests that
#: are about calibration — or about the cross-image case — pass their own.
SAME_SOURCE: tuple[CalibrationSnapshot, ...] = (snapshot("img1", 0.5, "nm"),)


def record(
    result_id: str,
    *,
    analysis: str = ANALYSIS,
    status: str = "completed",
    label: str | None = None,
    outputs: tuple[ResultOutput, ...] = (),
    calibration: tuple[CalibrationSnapshot, ...] = SAME_SOURCE,
    error: str | None = None,
) -> ResultRecord:
    return ResultRecord(
        id=result_id,
        analysis=analysis,
        created_at="2026-08-27T10:00:00+00:00",
        status=status,
        label=label,
        outputs=outputs,
        calibration=calibration,
        error=error,
    )


def scalar(name: str, value: float, **data: Any) -> ResultOutput:
    return ResultOutput(kind="scalar", name=name, data={"value": value, **data})


def curve(name: str, **data: Any) -> ResultOutput:
    return ResultOutput(kind="curve", name=name, data=dict(data))


def table(
    name: str, columns: list[str], units: list[Any], *, dimensionless: bool = False
) -> ResultOutput:
    data: dict[str, Any] = {"columns": columns, "units": units}
    if dimensionless:
        data[DIMENSIONLESS_KEY] = True
    return ResultOutput(kind="table", name=name, data=data)


def profile_record(result_id: str, *, label: str, image_id: str, length: float) -> ResultRecord:
    """A `measure.profile` record shaped the way routes/measure.py writes one.

    `x_unit` is the image's calibrated length unit; `y_unit` is `""`
    because a raster intensity carries no calibrated unit in this build —
    `_capture_profile` says exactly that in a comment. It is the overload
    that makes a bare `""` untrustworthy, so these records are the
    regression case for the dimensionless rule.
    """
    return ResultRecord(
        id=result_id,
        analysis="measure.profile",
        created_at="2026-08-27T10:00:00+00:00",
        status="completed",
        label=label,
        outputs=(
            curve(
                "profile",
                x_name="distance",
                x_unit="nm",
                y_name="intensity",
                y_unit="",
                reduce="mean",
            ),
            ResultOutput(kind="scalar", name="length", data={"value": length, "unit": "nm"}),
        ),
        calibration=(snapshot(image_id, 0.5, "nm"),),
    )


def rejection(comparison: Comparison, result_id: str) -> tuple[str, str]:
    """The `(code, message)` recorded for one rejected candidate."""
    (found,) = [inc for (rid, inc) in comparison.rejected if rid == result_id]
    return found.code, found.message


def compatible_ids(comparison: Comparison) -> tuple[str, ...]:
    """Just the ids of the compatible matches, in order."""
    return tuple(m.id for m in comparison.compatible)


def match(comparison: Comparison, result_id: str) -> CandidateMatch:
    """The one `CandidateMatch` recorded for a compatible candidate."""
    (found,) = [m for m in comparison.compatible if m.id == result_id]
    return found


# ── vocabulary ───────────────────────────────────────────────────────


def test_codes_are_a_deterministic_tuple_and_status_matches_the_model() -> None:
    assert isinstance(INCOMPATIBILITY_CODES, tuple)
    assert len(set(INCOMPATIBILITY_CODES)) == len(INCOMPATIBILITY_CODES)
    assert COMPARABLE_STATUS in RESULT_STATUSES


def test_every_code_constant_is_part_of_the_exported_surface() -> None:
    """Callers match on `code`; the constants must be importable, not
    incidental module attributes."""
    names = [
        "CODE_ANALYSIS_MISMATCH",
        "CODE_STATUS_NOT_COMPLETED",
        "CODE_NO_SHARED_OUTPUTS",
        "CODE_OUTPUT_KIND_MISMATCH",
        "CODE_OUTPUT_UNIT_MISMATCH",
    ]
    assert set(names) <= set(results_compare.__all__)
    assert {"CandidateMatch", "DIMENSIONLESS_KEY"} <= set(results_compare.__all__)
    assert {getattr(results_compare, n) for n in names} == set(INCOMPATIBILITY_CODES)
    assert {
        CODE_ANALYSIS_MISMATCH,
        CODE_STATUS_NOT_COMPLETED,
        CODE_NO_SHARED_OUTPUTS,
        CODE_OUTPUT_KIND_MISMATCH,
        CODE_OUTPUT_UNIT_MISMATCH,
    } == set(INCOMPATIBILITY_CODES)


def test_the_calibration_half_is_re_exported_from_this_module() -> None:
    """The split is an implementation detail: one import site for callers."""
    assert calibration_agreement is results_calibration.calibration_agreement
    assert CalibrationAgreement is results_calibration.CalibrationAgreement
    assert calibration_coverage_notes is results_calibration.calibration_coverage_notes
    agreement = calibration_agreement(record("aaa"), record("bbb"))
    assert isinstance(agreement, CalibrationAgreement)


# ── rule 6: reflexive ────────────────────────────────────────────────


def test_reference_compared_against_itself_is_compatible() -> None:
    ref = record("aaa", label="EDS A", outputs=(scalar("Fe", 12.0, unit="at.%"),))
    result = compare_results(ref, [ref])
    assert result.reference_id == "aaa"
    assert compatible_ids(result) == ("aaa",)
    assert match(result, "aaa").outputs == ("Fe",)
    assert result.rejected == ()
    assert result.outputs == ("Fe",)
    assert result.notes == ()


def test_the_reflexive_match_still_carries_its_calibration_agreement() -> None:
    """A record agrees with itself about every source it snapshotted, so the
    route has a structured verdict to render even for the reference row."""
    ref = record("aaa", outputs=(scalar("Fe", 1.0, unit="at.%"),))
    agreement = match(compare_results(ref, [ref]), "aaa").calibration_agreement
    assert agreement.shared_sources == ("img1",)
    assert agreement.differences == ()
    assert agreement.agrees and agreement.verified


def test_reflexive_case_holds_even_for_a_record_nobody_could_compare() -> None:
    """A failed reference has no outputs, yet rule 6 must still hold."""
    ref = record("aaa", status="failed", error="solver diverged")
    result = compare_results(ref, [ref])
    assert compatible_ids(result) == ("aaa",)
    assert match(result, "aaa").outputs == ()
    assert result.rejected == ()
    assert result.outputs == ()
    # No "nothing in common" note: the emptiness is the reference's own,
    # not two candidates failing to overlap.
    assert result.notes == ()


def test_no_candidates_leaves_the_reference_outputs_unconstrained() -> None:
    ref = record("aaa", outputs=(scalar("Fe", 1.0, unit="at.%"), scalar("Cr", 2.0, unit="at.%")))
    result = compare_results(ref, [])
    assert result.compatible == ()
    assert result.outputs == ("Fe", "Cr")
    assert result.notes == ()


# ── rule 1: analysis ─────────────────────────────────────────────────


def test_analysis_mismatch_names_both_analyses_and_both_records() -> None:
    ref = record("aaa", label="EDS A", outputs=(scalar("Fe", 1.0, unit="at.%"),))
    other = record(
        "bbb",
        label="Profile B",
        analysis="profile.line",
        outputs=(scalar("Fe", 1.0, unit="at.%"),),
    )
    result = compare_results(ref, [other])
    code, message = rejection(result, "bbb")
    assert code == "analysis_mismatch"
    assert "bbb ('Profile B')" in message
    assert "aaa ('EDS A')" in message
    assert "'profile.line'" in message
    assert "'eds.quantify'" in message
    assert result.compatible == ()


# ── rule 2: status ───────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_non_completed_records_are_rejected_with_their_reason(status: str) -> None:
    ref = record("aaa", label="EDS A", outputs=(scalar("Fe", 1.0, unit="at.%"),))
    other = record(
        "bbb",
        label="EDS B",
        status=status,
        error="detector saturated",
        outputs=(scalar("Fe", 1.0, unit="at.%"),),
    )
    result = compare_results(ref, [other])
    code, message = rejection(result, "bbb")
    assert code == "status_not_completed"
    assert f"status {status!r}" in message
    assert "detector saturated" in message
    assert "bbb ('EDS B')" in message
    assert "aaa ('EDS A')" in message


def test_status_rejection_survives_a_record_with_no_error_text() -> None:
    ref = record("aaa", outputs=(scalar("Fe", 1.0, unit="at.%"),))
    other = record("bbb", status="cancelled")
    code, message = rejection(compare_results(ref, [other]), "bbb")
    assert code == "status_not_completed"
    assert "()" not in message


# ── rule 3: kind ─────────────────────────────────────────────────────


def test_kind_mismatch_names_the_output_and_both_kinds() -> None:
    ref = record("aaa", label="EDS A", outputs=(scalar("Fe", 1.0, unit="at.%"),))
    other = record("bbb", label="EDS B", outputs=(curve("Fe", x_unit="keV", y_unit="counts"),))
    code, message = rejection(compare_results(ref, [other]), "bbb")
    assert code == "output_kind_mismatch"
    assert "output 'Fe'" in message
    assert "'scalar' in reference aaa ('EDS A')" in message
    assert "'curve' in result bbb ('EDS B')" in message


# ── rule 4: units ────────────────────────────────────────────────────


def test_scalar_unit_mismatch_names_both_units_and_both_records() -> None:
    ref = record("aaa", label="EDS A", outputs=(scalar("Fe", 12.0, unit="at.%"),))
    other = record("bbb", label="EDS B", outputs=(scalar("Fe", 15.0, unit="wt.%"),))
    result = compare_results(ref, [other])
    code, message = rejection(result, "bbb")
    assert code == "output_unit_mismatch"
    assert "output 'Fe'" in message
    assert "unit is 'at.%' in reference aaa ('EDS A')" in message
    assert "'wt.%' in result bbb ('EDS B')" in message
    assert "mix units" in message
    assert result.compatible == ()


def test_curve_axis_unit_mismatch_names_the_axis_slot() -> None:
    ref = record(
        "aaa",
        label="Profile A",
        analysis="profile.line",
        outputs=(curve("profile", x_name="distance", x_unit="nm", y_unit="counts"),),
    )
    other = record(
        "bbb",
        label="Profile B",
        analysis="profile.line",
        outputs=(curve("profile", x_name="distance", x_unit="um", y_unit="counts"),),
    )
    code, message = rejection(compare_results(ref, [other]), "bbb")
    assert code == "output_unit_mismatch"
    assert "output 'profile'" in message
    assert "x_unit is 'nm' in reference aaa ('Profile A')" in message
    assert "'um' in result bbb ('Profile B')" in message


def test_curve_y_axis_is_checked_too() -> None:
    counts = curve("p", x_unit="nm", y_unit="counts")
    ref = record("aaa", analysis="profile.line", outputs=(counts,))
    other = record("bbb", analysis="profile.line", outputs=(curve("p", x_unit="nm", y_unit="e-"),))
    code, message = rejection(compare_results(ref, [other]), "bbb")
    assert code == "output_unit_mismatch"
    assert "y_unit is 'counts'" in message


def test_fit_outputs_use_the_same_axis_unit_keys_as_curves() -> None:
    ref = record(
        "aaa",
        analysis="eels.fit",
        outputs=(ResultOutput(kind="fit", name="edge", data={"x_unit": "eV", "y_unit": "counts"}),),
    )
    other = record(
        "bbb",
        analysis="eels.fit",
        outputs=(
            ResultOutput(kind="fit", name="edge", data={"x_unit": "keV", "y_unit": "counts"}),
        ),
    )
    code, message = rejection(compare_results(ref, [other]), "bbb")
    assert code == "output_unit_mismatch"
    assert "x_unit is 'eV'" in message


def test_table_column_unit_mismatch_names_the_column() -> None:
    ref = record(
        "aaa",
        label="Grains A",
        analysis="particles.table",
        outputs=(table("grains", ["label", "area", "circularity"], ["", "nm^2", ""]),),
    )
    other = record(
        "bbb",
        label="Grains B",
        analysis="particles.table",
        outputs=(table("grains", ["label", "area", "circularity"], ["", "um^2", ""]),),
    )
    code, message = rejection(compare_results(ref, [other]), "bbb")
    assert code == "output_unit_mismatch"
    assert "output 'grains'" in message
    assert "column 'area' is 'nm^2' in reference aaa ('Grains A')" in message
    assert "'um^2' in result bbb ('Grains B')" in message


def test_table_columns_are_matched_by_name_not_position() -> None:
    """Reordering a table's columns is not a unit change."""
    ref = record(
        "aaa",
        analysis="particles.table",
        outputs=(table("grains", ["area", "label"], ["nm^2", ""], dimensionless=True),),
    )
    other = record(
        "bbb",
        analysis="particles.table",
        outputs=(table("grains", ["label", "area"], ["", "nm^2"], dimensionless=True),),
    )
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    assert result.notes == ()


def test_a_column_only_one_side_carries_is_a_note_not_a_rejection() -> None:
    ref = record(
        "aaa",
        label="Grains A",
        analysis="particles.table",
        outputs=(table("grains", ["area", "aspect"], ["nm^2", ""]),),
    )
    other = record(
        "bbb",
        label="Grains B",
        analysis="particles.table",
        outputs=(table("grains", ["area", "perimeter"], ["nm^2", "nm"]),),
    )
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    assert match(result, "bbb").outputs == ("grains",)
    assert result.outputs == ("grains",)
    joined = "\n".join(result.notes)
    assert "column 'aspect' is recorded by reference aaa ('Grains A')" in joined
    assert "column 'perimeter' is recorded by result bbb ('Grains B')" in joined


# ── unverified units and the dimensionless opt-in ────────────────────


def marked(name: str, value: float, unit: str = "") -> ResultOutput:
    """A scalar that opts its empty unit in as genuinely dimensionless."""
    return scalar(name, value, unit=unit, **{DIMENSIONLESS_KEY: True})


def test_an_unmarked_empty_unit_is_unverified_and_only_notes() -> None:
    """`""` is overloaded in this codebase, so on its own it certifies
    nothing — and, just as importantly, rejects nothing."""
    ref = record("aaa", label="A", outputs=(scalar("ratio", 1.0, unit=""),))
    other = record("bbb", label="B", outputs=(scalar("ratio", 1.0, unit="at.%"),))
    result = compare_results(ref, [other])
    assert result.rejected == ()
    assert compatible_ids(result) == ("bbb",)
    (note,) = result.notes
    assert "output 'ratio': units not verified for unit" in note
    assert "reference aaa ('A') has an empty unit with no dimensionless marker" in note
    assert "result bbb ('B') has 'at.%'" in note


def test_two_unmarked_empty_units_do_not_certify_silently() -> None:
    """The heart of the finding: two `""` outputs must not read as
    "shared units" just because the strings match."""
    ref = record("aaa", label="A", outputs=(scalar("ratio", 1.0, unit=""),))
    other = record("bbb", label="B", outputs=(scalar("ratio", 2.0, unit=""),))
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    (note,) = result.notes
    assert "units not verified for unit" in note
    assert note.count("an empty unit with no dimensionless marker") == 2


def test_two_measure_profile_records_do_not_certify_their_intensity_axis() -> None:
    """The shipped case, end to end: `measure.profile` writes `y_unit=""`
    for an uncalibrated raster intensity, so two profiles from unrelated
    intensity domains must be flagged, not silently certified."""
    ref = profile_record("aaa", label="Profile A", image_id="img1", length=120.0)
    other = profile_record("bbb", label="Profile B", image_id="img1", length=95.0)
    result = compare_results(ref, [other])
    assert result.rejected == ()
    assert compatible_ids(result) == ("bbb",)
    assert match(result, "bbb").outputs == ("profile", "length")
    joined = "\n".join(result.notes)
    assert "output 'profile': units not verified for y_unit" in joined
    assert "reference aaa ('Profile A') has an empty unit with no dimensionless marker" in joined
    assert "result bbb ('Profile B') has an empty unit with no dimensionless marker" in joined
    # The calibrated axis and the calibrated length are verified as ever.
    assert "x_unit" not in joined
    assert "output 'length'" not in joined


def test_marked_dimensionless_outputs_verify_against_each_other() -> None:
    ref = record("aaa", outputs=(marked("ratio", 1.0),))
    other = record("bbb", outputs=(marked("ratio", 2.0),))
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    assert match(result, "bbb").outputs == ("ratio",)
    assert result.notes == ()


def test_a_marked_dimensionless_unit_still_mismatches_a_named_one() -> None:
    """Opting in makes `""` a real unit, rejection included."""
    ref = record("aaa", label="A", outputs=(marked("ratio", 1.0),))
    other = record("bbb", label="B", outputs=(scalar("ratio", 1.0, unit="at.%"),))
    code, message = rejection(compare_results(ref, [other]), "bbb")
    assert code == "output_unit_mismatch"
    assert "unit is '' in reference aaa ('A')" in message
    assert "'at.%' in result bbb ('B')" in message


def test_the_marker_only_counts_when_it_is_exactly_true() -> None:
    """A truthy stray value is not an assertion about units."""
    ref = record("aaa", outputs=(scalar("ratio", 1.0, unit="", **{DIMENSIONLESS_KEY: "yes"}),))
    other = record("bbb", outputs=(marked("ratio", 2.0),))
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    (note,) = result.notes
    assert "units not verified for unit" in note
    assert "an empty unit with no dimensionless marker" in note
    assert "'' (marked dimensionless)" in note


def test_the_marker_covers_every_empty_column_unit_of_a_table() -> None:
    ref = record(
        "aaa",
        analysis="particles.table",
        outputs=(table("grains", ["area", "circularity"], ["nm^2", ""], dimensionless=True),),
    )
    other = record(
        "bbb",
        analysis="particles.table",
        outputs=(table("grains", ["area", "circularity"], ["nm^2", ""], dimensionless=True),),
    )
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    assert result.notes == ()


def test_an_unmarked_empty_table_column_is_unverified() -> None:
    ref = record(
        "aaa",
        label="Grains A",
        analysis="particles.table",
        outputs=(table("grains", ["area", "circularity"], ["nm^2", ""]),),
    )
    other = record(
        "bbb",
        label="Grains B",
        analysis="particles.table",
        outputs=(table("grains", ["area", "circularity"], ["nm^2", ""]),),
    )
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    (note,) = result.notes
    assert "output 'grains': units not verified for column 'circularity'" in note
    assert "reference aaa ('Grains A') has an empty unit with no dimensionless marker" in note


@pytest.mark.parametrize("data", [{}, {"unit": None}, {"unit": 7}])
def test_a_missing_or_non_string_unit_is_unknown_and_only_notes(data: dict[str, Any]) -> None:
    ref = record("aaa", label="A", outputs=(scalar("Fe", 1.0, unit="at.%"),))
    other = record("bbb", label="B", outputs=(ResultOutput(kind="scalar", name="Fe", data=data),))
    result = compare_results(ref, [other])
    assert result.rejected == ()
    assert compatible_ids(result) == ("bbb",)
    assert result.outputs == ("Fe",)
    (note,) = result.notes
    assert "units not verified for unit" in note
    assert "reference aaa ('A') has 'at.%'" in note
    assert "result bbb ('B') has no recorded unit" in note


def test_unknown_units_on_both_sides_still_only_note() -> None:
    ref = record("aaa", outputs=(ResultOutput(kind="scalar", name="Fe", data={"value": 1.0}),))
    other = record("bbb", outputs=(ResultOutput(kind="scalar", name="Fe", data={"value": 2.0}),))
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    assert "units not verified" in result.notes[0]
    assert result.notes[0].count("no recorded unit") == 2


def test_kinds_without_a_unit_convention_compare_on_kind_alone() -> None:
    ref = record(
        "aaa",
        analysis="eds.maps",
        outputs=(ResultOutput(kind="map", name="Fe map", data={"cmap": "viridis"}),),
    )
    other = record(
        "bbb",
        analysis="eds.maps",
        outputs=(ResultOutput(kind="map", name="Fe map", data={"cmap": "magma"}),),
    )
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    assert result.notes == ()


# ── rule 5: dropped outputs, per-candidate matches, nothing-left ─────


def test_an_output_the_candidate_lacks_is_dropped_with_a_note() -> None:
    ref = record(
        "aaa",
        label="EDS A",
        outputs=(scalar("Fe", 1.0, unit="at.%"), scalar("Cr", 2.0, unit="at.%")),
    )
    other = record("bbb", label="EDS B", outputs=(scalar("Fe", 3.0, unit="at.%"),))
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    assert match(result, "bbb").outputs == ("Fe",)
    assert result.rejected == ()
    assert result.outputs == ("Fe",)
    (note,) = result.notes
    assert note == (
        "output 'Cr' is not compared: reference aaa ('EDS A') has it but result "
        "bbb ('EDS B') does not"
    )


def test_the_shared_set_narrows_across_all_compatible_candidates() -> None:
    ref = record(
        "aaa",
        outputs=(
            scalar("Fe", 1.0, unit="at.%"),
            scalar("Cr", 1.0, unit="at.%"),
            scalar("Ni", 1.0, unit="at.%"),
        ),
    )
    keeps_two = record(
        "bbb", outputs=(scalar("Fe", 2.0, unit="at.%"), scalar("Cr", 2.0, unit="at.%"))
    )
    keeps_one = record(
        "ccc", outputs=(scalar("Fe", 3.0, unit="at.%"), scalar("Ni", 3.0, unit="at.%"))
    )
    result = compare_results(ref, [keeps_two, keeps_one])
    assert compatible_ids(result) == ("bbb", "ccc")
    assert match(result, "bbb").outputs == ("Fe", "Cr")
    assert match(result, "ccc").outputs == ("Fe", "Ni")
    assert result.outputs == ("Fe",)


def test_candidates_comparable_pairwise_can_share_no_common_output() -> None:
    """Each candidate is comparable WITH THE REFERENCE, on its own output;
    the group has nothing in common. `compatible` says so per candidate,
    the empty `outputs` is honest, and a note explains the combination
    rather than leaving a UI with an empty render and no reason."""
    ref = record(
        "aaa",
        label="EDS A",
        outputs=(scalar("Fe", 1.0, unit="at.%"), scalar("Cr", 1.0, unit="at.%")),
    )
    only_fe = record("bbb", label="EDS B", outputs=(scalar("Fe", 2.0, unit="at.%"),))
    only_cr = record("ccc", label="EDS C", outputs=(scalar("Cr", 3.0, unit="at.%"),))
    result = compare_results(ref, [only_fe, only_cr])
    assert result.rejected == ()
    assert compatible_ids(result) == ("bbb", "ccc")
    assert match(result, "bbb").outputs == ("Fe",)
    assert match(result, "ccc").outputs == ("Cr",)
    assert result.outputs == ()
    joined = "\n".join(result.notes)
    assert "no output is comparable across all 2 compatible results" in joined
    assert "reference aaa ('EDS A') matches each of them, but on different outputs" in joined
    assert "(bbb on 'Fe'; ccc on 'Cr')" in joined
    assert "nothing to show" in joined


def test_a_non_empty_cumulative_intersection_carries_no_such_note() -> None:
    ref = record("aaa", outputs=(scalar("Fe", 1.0, unit="at.%"),))
    other = record("bbb", outputs=(scalar("Fe", 2.0, unit="at.%"),))
    result = compare_results(ref, [other])
    assert result.outputs == ("Fe",)
    assert not any("no output is comparable" in n for n in result.notes)


def test_a_rejected_candidate_does_not_narrow_the_shared_set() -> None:
    ref = record("aaa", outputs=(scalar("Fe", 1.0, unit="at.%"), scalar("Cr", 1.0, unit="at.%")))
    good = record("bbb", outputs=(scalar("Fe", 2.0, unit="at.%"), scalar("Cr", 2.0, unit="at.%")))
    bad = record("ccc", analysis="other.thing", outputs=(scalar("Fe", 3.0, unit="at.%"),))
    result = compare_results(ref, [good, bad])
    assert compatible_ids(result) == ("bbb",)
    assert result.outputs == ("Fe", "Cr")


def test_nothing_comparable_left_rejects_and_lists_both_inventories() -> None:
    ref = record("aaa", label="EDS A", outputs=(scalar("Fe", 1.0, unit="at.%"),))
    other = record("bbb", label="EDS B", outputs=(scalar("Ni", 1.0, unit="at.%"),))
    result = compare_results(ref, [other])
    code, message = rejection(result, "bbb")
    assert code == "no_shared_outputs"
    assert "result bbb ('EDS B') shares no output name with reference aaa ('EDS A')" in message
    assert "the reference has 'Fe'" in message
    assert "the candidate has 'Ni'" in message
    assert result.compatible == ()


def test_a_completed_record_with_no_outputs_is_rejected_explicitly() -> None:
    ref = record("aaa", label="EDS A", outputs=(scalar("Fe", 1.0, unit="at.%"),))
    other = record("bbb", label="Empty")
    code, message = rejection(compare_results(ref, [other]), "bbb")
    assert code == "no_shared_outputs"
    assert "the candidate has no outputs" in message


# ── calibration crossing point ───────────────────────────────────────


def test_calibration_disagreement_is_a_note_not_a_rejection() -> None:
    """`calibration_agreement` itself is covered by test_results_calibration;
    what matters here is that `compare_results` folds its differences into
    `notes` and never into a rejection."""
    ref = record(
        "aaa",
        label="EDS A",
        outputs=(scalar("Fe", 1.0, unit="at.%"),),
        calibration=(snapshot("img1", 0.5, "nm", source="fei"),),
    )
    other = record(
        "bbb",
        label="EDS B",
        outputs=(scalar("Fe", 2.0, unit="at.%"),),
        calibration=(snapshot("img1", 0.25, "nm", source="db:scope"),),
    )
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    assert result.rejected == ()
    joined = "\n".join(result.notes)
    assert "source image 'img1': axis 0 scale differs" in joined
    assert "reference aaa ('EDS A') has 0.5" in joined
    assert "result bbb ('EDS B') has 0.25" in joined
    assert "calibration provenance differs" in joined
    assert "'fei'" in joined and "'db:scope'" in joined


def test_records_on_different_images_say_calibration_was_not_verified() -> None:
    """2B's primary CROSS-IMAGE case: no shared source produces no
    differences, which must not be allowed to read as agreement."""
    ref = record(
        "aaa",
        label="EDS A",
        outputs=(scalar("Fe", 1.0, unit="at.%"),),
        calibration=(snapshot("img1", 0.5, "nm"),),
    )
    other = record(
        "bbb",
        label="EDS B",
        outputs=(scalar("Fe", 2.0, unit="at.%"),),
        calibration=(snapshot("img2", 0.5, "nm"),),
    )
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    assert result.rejected == ()
    (note,) = result.notes
    assert note == (
        "calibration agreement not verified between reference aaa ('EDS A') and "
        "result bbb ('EDS B'): they share no source image — reference aaa ('EDS A') "
        "snapshotted 'img1', result bbb ('EDS B') snapshotted 'img2', so whether they "
        "were measured at the same pixel size is unknown"
    )


def test_records_with_no_calibration_snapshots_are_flagged_too() -> None:
    ref = record("aaa", label="A", outputs=(scalar("Fe", 1.0, unit="at.%"),), calibration=())
    other = record("bbb", label="B", outputs=(scalar("Fe", 2.0, unit="at.%"),), calibration=())
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    (note,) = result.notes
    assert "calibration agreement not verified between reference aaa ('A')" in note
    assert "neither record snapshotted any source calibration" in note


def test_each_compatible_candidate_carries_its_own_calibration_agreement() -> None:
    """The structured verdict stays reachable so a route can return it
    rather than re-derive it from the note sentences."""
    ref = record(
        "aaa",
        outputs=(scalar("Fe", 1.0, unit="at.%"),),
        calibration=(snapshot("img1", 0.5, "nm"),),
    )
    same = record(
        "bbb",
        outputs=(scalar("Fe", 2.0, unit="at.%"),),
        calibration=(snapshot("img1", 0.5, "nm"),),
    )
    elsewhere = record(
        "ccc",
        outputs=(scalar("Fe", 3.0, unit="at.%"),),
        calibration=(snapshot("img2", 0.25, "nm"),),
    )
    result = compare_results(ref, [same, elsewhere])
    agreed = match(result, "bbb").calibration_agreement
    assert isinstance(agreed, CalibrationAgreement)
    assert agreed.candidate_id == "bbb"
    assert agreed.shared_sources == ("img1",)
    assert agreed.agrees and agreed.verified
    unverified = match(result, "ccc").calibration_agreement
    assert unverified.shared_sources == ()
    assert unverified.reference_only == ("img1",)
    assert unverified.candidate_only == ("img2",)
    assert unverified.agrees and not unverified.verified


# ── determinism ──────────────────────────────────────────────────────


def _many_candidates() -> list[ResultRecord]:
    return [
        record("c1", label="ok one", outputs=(scalar("Fe", 1.0, unit="at.%"),)),
        record("c2", label="wrong analysis", analysis="other", outputs=(scalar("Fe", 1.0),)),
        record("c3", label="failed", status="failed", error="boom"),
        record("c4", label="wrong unit", outputs=(scalar("Fe", 1.0, unit="wt.%"),)),
        record("c5", label="wrong kind", outputs=(curve("Fe", x_unit="nm", y_unit="c"),)),
        record("c6", label="nothing shared", outputs=(scalar("Ni", 1.0, unit="at.%"),)),
        record(
            "c7",
            label="ok two",
            outputs=(scalar("Fe", 2.0, unit="at.%"), scalar("Cr", 2.0, unit="at.%")),
        ),
    ]


def test_ordering_follows_candidate_order_and_is_reproducible() -> None:
    ref = record(
        "aaa",
        label="EDS A",
        outputs=(scalar("Fe", 1.0, unit="at.%"), scalar("Cr", 1.0, unit="at.%")),
        calibration=(snapshot("img1", 0.5, "nm"),),
    )
    first = compare_results(ref, _many_candidates())
    assert compatible_ids(first) == ("c1", "c7")
    assert [rid for (rid, _) in first.rejected] == ["c2", "c3", "c4", "c5", "c6"]
    assert [inc.code for (_, inc) in first.rejected] == [
        "analysis_mismatch",
        "status_not_completed",
        "output_unit_mismatch",
        "output_kind_mismatch",
        "no_shared_outputs",
    ]
    assert first.outputs == ("Fe",)
    assert first.notes == (
        "output 'Cr' is not compared: reference aaa ('EDS A') has it but result "
        "c1 ('ok one') does not",
    )
    for _ in range(5):
        again = compare_results(ref, _many_candidates())
        assert again == first


def test_repeated_notes_are_deduplicated_in_first_appearance_order() -> None:
    ref = record(
        "aaa",
        label="EDS A",
        outputs=(scalar("Fe", 1.0, unit="at.%"), scalar("Cr", 1.0, unit="at.%")),
    )
    lacking = [
        record("c1", label="B", outputs=(scalar("Fe", 1.0, unit="at.%"),)),
        record("c2", label="B", outputs=(scalar("Fe", 1.0, unit="at.%"),)),
    ]
    result = compare_results(ref, lacking)
    assert compatible_ids(result) == ("c1", "c2")
    assert len(result.notes) == 2
    assert result.notes[0].endswith("c1 ('B') does not")
    assert result.notes[1].endswith("c2 ('B') does not")


def test_a_record_without_a_label_is_named_by_id_alone() -> None:
    ref = record("aaa", outputs=(scalar("Fe", 1.0, unit="at.%"),))
    other = record("bbb", outputs=(scalar("Fe", 1.0, unit="wt.%"),))
    _, message = rejection(compare_results(ref, [other]), "bbb")
    assert "in reference aaa but" in message
    assert "in result bbb " in message
    assert "(" not in message  # no empty parentheses where a label would go


def test_a_repeated_output_name_resolves_to_the_first_occurrence() -> None:
    ref = record(
        "aaa",
        outputs=(scalar("Fe", 1.0, unit="at.%"), scalar("Fe", 9.0, unit="wt.%")),
    )
    other = record("bbb", outputs=(scalar("Fe", 2.0, unit="at.%"),))
    result = compare_results(ref, [other])
    assert compatible_ids(result) == ("bbb",)
    assert result.outputs == ("Fe",)
