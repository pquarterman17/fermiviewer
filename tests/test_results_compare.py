"""Compatible-result query — roadmap item 2B's rule set and its messages.

Records are built directly (no HTTP, no project container): this is the
pure-logic half of 2B, and the route wiring is a separate surface.

Every rejection test asserts on the MESSAGE, not only the `code`. The
roadmap line is "explicit incompatibility messages" — a message that does
not name both records and the exact output/unit at fault would satisfy the
code assertion while failing the feature.

Covered: the reflexive case; analysis mismatch; failed and cancelled
records; kind mismatch; scalar, curve-axis and table-column unit
mismatches; the missing-vs-empty unit rule; dropped outputs as notes; the
nothing-comparable-left rejection; calibration disagreement arriving as a
note rather than a rejection; and deterministic ordering across several
candidates.

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
    INCOMPATIBILITY_CODES,
    CalibrationAgreement,
    Comparison,
    calibration_agreement,
    compare_results,
)

ANALYSIS = "eds.quantify"


def record(
    result_id: str,
    *,
    analysis: str = ANALYSIS,
    status: str = "completed",
    label: str | None = None,
    outputs: tuple[ResultOutput, ...] = (),
    calibration: tuple[CalibrationSnapshot, ...] = (),
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


def table(name: str, columns: list[str], units: list[Any]) -> ResultOutput:
    return ResultOutput(kind="table", name=name, data={"columns": columns, "units": units})


def snapshot(
    image_id: str, scale: float, units: str, source: str | None = None
) -> CalibrationSnapshot:
    return CalibrationSnapshot(
        image_id=image_id,
        axes=(AxisCal(scale=scale, units=units), AxisCal(scale=scale, units=units)),
        source=source,
    )


def rejection(comparison: Comparison, result_id: str) -> tuple[str, str]:
    """The `(code, message)` recorded for one rejected candidate."""
    (found,) = [inc for (rid, inc) in comparison.rejected if rid == result_id]
    return found.code, found.message


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
    agreement = calibration_agreement(record("aaa"), record("bbb"))
    assert isinstance(agreement, CalibrationAgreement)


# ── rule 6: reflexive ────────────────────────────────────────────────


def test_reference_compared_against_itself_is_compatible() -> None:
    ref = record("aaa", label="EDS A", outputs=(scalar("Fe", 12.0, unit="at.%"),))
    result = compare_results(ref, [ref])
    assert result.reference_id == "aaa"
    assert result.compatible == ("aaa",)
    assert result.rejected == ()
    assert result.outputs == ("Fe",)
    assert result.notes == ()


def test_reflexive_case_holds_even_for_a_record_nobody_could_compare() -> None:
    """A failed reference has no outputs, yet rule 6 must still hold."""
    ref = record("aaa", status="failed", error="solver diverged")
    result = compare_results(ref, [ref])
    assert result.compatible == ("aaa",)
    assert result.rejected == ()
    assert result.outputs == ()


def test_no_candidates_leaves_the_reference_outputs_unconstrained() -> None:
    ref = record("aaa", outputs=(scalar("Fe", 1.0, unit="at.%"), scalar("Cr", 2.0, unit="at.%")))
    result = compare_results(ref, [])
    assert result.compatible == ()
    assert result.outputs == ("Fe", "Cr")


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
        outputs=(table("grains", ["area", "label"], ["nm^2", ""]),),
    )
    other = record(
        "bbb",
        analysis="particles.table",
        outputs=(table("grains", ["label", "area"], ["", "nm^2"]),),
    )
    result = compare_results(ref, [other])
    assert result.compatible == ("bbb",)
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
    assert result.compatible == ("bbb",)
    assert result.outputs == ("grains",)
    joined = "\n".join(result.notes)
    assert "column 'aspect' is recorded by reference aaa ('Grains A')" in joined
    assert "column 'perimeter' is recorded by result bbb ('Grains B')" in joined


# ── missing unit vs empty unit ───────────────────────────────────────


def test_empty_unit_is_a_real_unit_and_mismatches_a_named_one() -> None:
    ref = record("aaa", label="A", outputs=(scalar("ratio", 1.0, unit=""),))
    other = record("bbb", label="B", outputs=(scalar("ratio", 1.0, unit="at.%"),))
    code, message = rejection(compare_results(ref, [other]), "bbb")
    assert code == "output_unit_mismatch"
    assert "unit is '' in reference aaa ('A')" in message


def test_two_empty_units_agree() -> None:
    ref = record("aaa", outputs=(scalar("ratio", 1.0, unit=""),))
    other = record("bbb", outputs=(scalar("ratio", 2.0, unit=""),))
    result = compare_results(ref, [other])
    assert result.compatible == ("bbb",)
    assert result.notes == ()


@pytest.mark.parametrize("data", [{}, {"unit": None}, {"unit": 7}])
def test_a_missing_or_non_string_unit_is_unknown_and_only_notes(data: dict[str, Any]) -> None:
    ref = record("aaa", label="A", outputs=(scalar("Fe", 1.0, unit="at.%"),))
    other = record("bbb", label="B", outputs=(ResultOutput(kind="scalar", name="Fe", data=data),))
    result = compare_results(ref, [other])
    assert result.rejected == ()
    assert result.compatible == ("bbb",)
    assert result.outputs == ("Fe",)
    (note,) = result.notes
    assert "units not verified for unit" in note
    assert "reference aaa ('A') has 'at.%'" in note
    assert "result bbb ('B') has no recorded unit" in note


def test_unknown_units_on_both_sides_still_only_note() -> None:
    ref = record("aaa", outputs=(ResultOutput(kind="scalar", name="Fe", data={"value": 1.0}),))
    other = record("bbb", outputs=(ResultOutput(kind="scalar", name="Fe", data={"value": 2.0}),))
    result = compare_results(ref, [other])
    assert result.compatible == ("bbb",)
    assert "units not verified" in result.notes[0]


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
    assert result.compatible == ("bbb",)
    assert result.notes == ()


# ── rule 5: dropped outputs and nothing-left ─────────────────────────


def test_an_output_the_candidate_lacks_is_dropped_with_a_note() -> None:
    ref = record(
        "aaa",
        label="EDS A",
        outputs=(scalar("Fe", 1.0, unit="at.%"), scalar("Cr", 2.0, unit="at.%")),
    )
    other = record("bbb", label="EDS B", outputs=(scalar("Fe", 3.0, unit="at.%"),))
    result = compare_results(ref, [other])
    assert result.compatible == ("bbb",)
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
    assert result.compatible == ("bbb", "ccc")
    assert result.outputs == ("Fe",)


def test_a_rejected_candidate_does_not_narrow_the_shared_set() -> None:
    ref = record("aaa", outputs=(scalar("Fe", 1.0, unit="at.%"), scalar("Cr", 1.0, unit="at.%")))
    good = record("bbb", outputs=(scalar("Fe", 2.0, unit="at.%"), scalar("Cr", 2.0, unit="at.%")))
    bad = record("ccc", analysis="other.thing", outputs=(scalar("Fe", 3.0, unit="at.%"),))
    result = compare_results(ref, [good, bad])
    assert result.compatible == ("bbb",)
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
    assert result.compatible == ("bbb",)
    assert result.rejected == ()
    joined = "\n".join(result.notes)
    assert "source image 'img1': axis 0 scale differs" in joined
    assert "reference aaa ('EDS A') has 0.5" in joined
    assert "result bbb ('EDS B') has 0.25" in joined
    assert "calibration provenance differs" in joined
    assert "'fei'" in joined and "'db:scope'" in joined


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
    assert first.compatible == ("c1", "c7")
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
    assert result.compatible == ("c1", "c2")
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
    assert result.compatible == ("bbb",)
    assert result.outputs == ("Fe",)
