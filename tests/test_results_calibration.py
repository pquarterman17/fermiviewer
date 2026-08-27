"""Source-calibration agreement between result records — roadmap item 2B.

The comparison rules live in tests/test_results_compare.py; this file
covers the sibling module they fold notes in from. The two questions are
deliberately separate: "can these be compared" (compatibility) and "were
they measured the same way" (this module), and the second must never
answer the first — a calibration difference is a note, never a rejection.
That crossing point is asserted from the compare side.

Covered: shared vs unshared sources; scale, units, axis-count and
provenance differences; the "same units, different pixel size" case the
roadmap names; NaN-as-uncalibrated; `verified` and the coverage notes that
keep "nothing was compared" from reading as "everything agreed";
determinism of `differences`; and `record_name`, the naming convention
every 2B message shares.
"""

from __future__ import annotations

from fermiviewer.datastruct import AxisCal
from fermiviewer.io.results_model import CalibrationSnapshot, ResultRecord
from fermiviewer.results_calibration import (
    calibration_agreement,
    calibration_coverage_notes,
    record_name,
)


def notes(ref: ResultRecord, cand: ResultRecord) -> tuple[str, ...]:
    """The coverage notes for a pair, named the way a 2B message names it."""
    return calibration_coverage_notes(
        calibration_agreement(ref, cand), record_name(ref), record_name(cand)
    )


def record(
    result_id: str,
    *,
    label: str | None = None,
    calibration: tuple[CalibrationSnapshot, ...] = (),
) -> ResultRecord:
    return ResultRecord(
        id=result_id,
        analysis="eds.quantify",
        created_at="2026-08-27T10:00:00+00:00",
        status="completed",
        label=label,
        calibration=calibration,
    )


def snapshot(
    image_id: str, scale: float, units: str, source: str | None = None
) -> CalibrationSnapshot:
    """A two-axis (y, x) snapshot, the shape an image result records."""
    return CalibrationSnapshot(
        image_id=image_id,
        axes=(AxisCal(scale=scale, units=units), AxisCal(scale=scale, units=units)),
        source=source,
    )


# ── record naming ────────────────────────────────────────────────────


def test_record_name_uses_id_and_label_when_a_label_exists() -> None:
    assert record_name(record("aaa", label="EDS A")) == "aaa ('EDS A')"


def test_record_name_is_the_bare_id_without_a_label() -> None:
    """No empty `()` where a human-readable name would have gone."""
    assert record_name(record("aaa")) == "aaa"
    assert record_name(record("aaa", label="")) == "aaa"


# ── source inventories ───────────────────────────────────────────────


def test_shared_and_unshared_sources_are_reported_separately() -> None:
    ref = record("aaa", calibration=(snapshot("img1", 0.5, "nm"), snapshot("img2", 0.5, "nm")))
    other = record("bbb", calibration=(snapshot("img1", 0.5, "nm"), snapshot("img3", 0.5, "nm")))
    agreement = calibration_agreement(ref, other)
    assert agreement.reference_id == "aaa"
    assert agreement.candidate_id == "bbb"
    assert agreement.shared_sources == ("img1",)
    assert agreement.reference_only == ("img2",)
    assert agreement.candidate_only == ("img3",)
    assert agreement.differences == ()
    assert agreement.agrees is True


def test_records_over_different_images_share_no_source_to_disagree_about() -> None:
    """An empty `differences` here means "nothing in common", not "identical"."""
    ref = record("aaa", calibration=(snapshot("img1", 0.5, "nm"),))
    other = record("bbb", calibration=(snapshot("img9", 3.0, "um"),))
    agreement = calibration_agreement(ref, other)
    assert agreement.shared_sources == ()
    assert agreement.differences == ()
    assert agreement.agrees is True
    assert agreement.reference_only == ("img1",)
    assert agreement.candidate_only == ("img9",)


def test_records_with_no_snapshots_at_all_agree_vacuously() -> None:
    agreement = calibration_agreement(record("aaa"), record("bbb"))
    assert agreement.shared_sources == ()
    assert agreement.reference_only == ()
    assert agreement.candidate_only == ()
    assert agreement.agrees is True


def test_a_repeated_image_id_resolves_to_the_first_snapshot() -> None:
    ref = record("aaa", calibration=(snapshot("img1", 0.5, "nm"), snapshot("img1", 9.0, "um")))
    other = record("bbb", calibration=(snapshot("img1", 0.5, "nm"),))
    assert calibration_agreement(ref, other).agrees is True


# ── what counts as a disagreement ────────────────────────────────────


def test_same_units_different_pixel_size_is_distinguishable_from_same_everything() -> None:
    """The exact distinction the roadmap asks a caller to be able to draw."""
    ref = record("aaa", calibration=(snapshot("img1", 0.5, "nm"),))
    identical = record("bbb", calibration=(snapshot("img1", 0.5, "nm"),))
    rescaled = record("ccc", calibration=(snapshot("img1", 0.25, "nm"),))
    assert calibration_agreement(ref, identical).agrees is True
    rescaled_agreement = calibration_agreement(ref, rescaled)
    assert rescaled_agreement.agrees is False
    assert all("scale differs" in d for d in rescaled_agreement.differences)
    assert not any("units differ" in d for d in rescaled_agreement.differences)


def test_scale_difference_names_both_records_and_both_values() -> None:
    ref = record("aaa", label="EDS A", calibration=(snapshot("img1", 0.5, "nm"),))
    other = record("bbb", label="EDS B", calibration=(snapshot("img1", 0.25, "nm"),))
    joined = "\n".join(calibration_agreement(ref, other).differences)
    assert "source image 'img1': axis 0 scale differs" in joined
    assert "reference aaa ('EDS A') has 0.5" in joined
    assert "result bbb ('EDS B') has 0.25" in joined


def test_units_and_axis_count_differences_are_reported() -> None:
    ref = record("aaa", calibration=(snapshot("img1", 0.5, "nm"),))
    other = record(
        "bbb",
        calibration=(CalibrationSnapshot(image_id="img1", axes=(AxisCal(scale=0.5, units="um"),)),),
    )
    joined = "\n".join(calibration_agreement(ref, other).differences)
    assert "axis count differs" in joined
    assert "snapshotted 2 axes" in joined
    assert "snapshotted 1" in joined
    assert "axis 0 calibration units differ" in joined
    assert "'nm'" in joined and "'um'" in joined


def test_provenance_difference_names_both_calibration_sources() -> None:
    ref = record("aaa", label="A", calibration=(snapshot("img1", 0.5, "nm", source="fei"),))
    other = record("bbb", label="B", calibration=(snapshot("img1", 0.5, "nm", source="db:scope"),))
    (difference,) = calibration_agreement(ref, other).differences
    assert "source image 'img1': calibration provenance differs" in difference
    assert "reference aaa ('A') has 'fei'" in difference
    assert "result bbb ('B') has 'db:scope'" in difference


def test_an_origin_shift_alone_is_not_a_disagreement() -> None:
    """`origin` moves where zero sits, not what one step is worth."""
    ref = record(
        "aaa", calibration=(CalibrationSnapshot("img1", (AxisCal(0.5, 0.0, "nm"),)),)
    )
    other = record(
        "bbb", calibration=(CalibrationSnapshot("img1", (AxisCal(0.5, 128.0, "nm"),)),)
    )
    assert calibration_agreement(ref, other).agrees is True


def test_float_noise_in_a_scale_is_not_a_disagreement() -> None:
    ref = record("aaa", calibration=(snapshot("img1", 0.1 + 0.2, "nm"),))
    other = record("bbb", calibration=(snapshot("img1", 0.3, "nm"),))
    assert calibration_agreement(ref, other).agrees is True


def test_uncalibrated_nan_scales_agree_with_each_other() -> None:
    """NaN scale means uncalibrated (`AxisCal`); two uncalibrated axes agree."""
    nan = float("nan")
    ref = record("aaa", calibration=(snapshot("img1", nan, ""),))
    other = record("bbb", calibration=(snapshot("img1", nan, ""),))
    assert calibration_agreement(ref, other).agrees is True


def test_a_nan_scale_disagrees_with_a_real_one() -> None:
    ref = record("aaa", calibration=(snapshot("img1", float("nan"), "nm"),))
    other = record("bbb", calibration=(snapshot("img1", 0.5, "nm"),))
    assert calibration_agreement(ref, other).agrees is False


# ── determinism ──────────────────────────────────────────────────────


def test_differences_are_ordered_by_source_then_axis_and_reproducible() -> None:
    ref = record(
        "aaa",
        calibration=(snapshot("img1", 0.5, "nm", source="fei"), snapshot("img2", 1.0, "nm")),
    )
    other = record(
        "bbb",
        calibration=(snapshot("img2", 2.0, "nm"), snapshot("img1", 0.25, "um", source="db:x")),
    )
    first = calibration_agreement(ref, other)
    assert first.shared_sources == ("img1", "img2")
    assert [d.split(":")[0] for d in first.differences] == [
        "source image 'img1'",
        "source image 'img1'",
        "source image 'img1'",
        "source image 'img1'",
        "source image 'img1'",
        "source image 'img2'",
        "source image 'img2'",
    ]
    assert "axis 0 scale differs" in first.differences[0]
    assert "axis 0 calibration units differ" in first.differences[1]
    assert "axis 1 scale differs" in first.differences[2]
    assert "axis 1 calibration units differ" in first.differences[3]
    assert "calibration provenance differs" in first.differences[4]
    for _ in range(5):
        assert calibration_agreement(ref, other) == first


# ── coverage: what was never compared ────────────────────────────────


def test_full_overlap_and_agreement_produces_no_coverage_note() -> None:
    """The one case where an empty `differences` really does mean
    "same everything" — and the only case that stays silent."""
    ref = record("aaa", calibration=(snapshot("img1", 0.5, "nm"),))
    other = record("bbb", calibration=(snapshot("img1", 0.5, "nm"),))
    assert calibration_agreement(ref, other).verified is True
    assert notes(ref, other) == ()


def test_disjoint_sources_are_reported_as_not_verified_with_both_inventories() -> None:
    """The CROSS-IMAGE case 2B exists for: no shared source, no
    differences, and therefore nothing established."""
    ref = record("aaa", label="EDS A", calibration=(snapshot("img1", 0.5, "nm"),))
    other = record("bbb", label="EDS B", calibration=(snapshot("img9", 3.0, "um"),))
    assert calibration_agreement(ref, other).verified is False
    (note,) = notes(ref, other)
    assert note == (
        "calibration agreement not verified between reference aaa ('EDS A') and "
        "result bbb ('EDS B'): they share no source image — reference aaa ('EDS A') "
        "snapshotted 'img1', result bbb ('EDS B') snapshotted 'img9', so whether they "
        "were measured at the same pixel size is unknown"
    )


def test_neither_record_snapshotting_anything_says_so_in_those_words() -> None:
    (note,) = notes(record("aaa", label="A"), record("bbb", label="B"))
    assert "calibration agreement not verified between reference aaa ('A') and " in note
    assert "result bbb ('B'): neither record snapshotted any source calibration" in note
    assert "measured at the same pixel size is unknown" in note


def test_a_one_sided_inventory_names_which_side_is_empty() -> None:
    with_cal = record("aaa", label="A", calibration=(snapshot("img1", 0.5, "nm"),))
    without = record("bbb", label="B")
    (from_ref,) = notes(with_cal, without)
    assert "result bbb ('B') snapshotted no source calibration, while reference " in from_ref
    assert "aaa ('A') snapshotted 'img1'" in from_ref
    (from_cand,) = notes(without, with_cal)
    assert "reference bbb ('B') snapshotted no source calibration, while result " in from_cand
    assert "aaa ('A') snapshotted 'img1'" in from_cand


def test_partial_overlap_says_what_the_agreement_does_not_cover() -> None:
    """Some sources were compared; the leftovers must not ride along as if
    they had been."""
    ref = record(
        "aaa",
        label="A",
        calibration=(snapshot("img1", 0.5, "nm"), snapshot("img2", 0.5, "nm")),
    )
    other = record(
        "bbb",
        label="B",
        calibration=(snapshot("img1", 0.5, "nm"), snapshot("img3", 0.5, "nm")),
    )
    assert calibration_agreement(ref, other).verified is True
    (note,) = notes(ref, other)
    assert note == (
        "calibration agreement between reference aaa ('A') and result bbb ('B') "
        "covers only the shared source 'img1': reference aaa ('A') also snapshotted "
        "'img2'; result bbb ('B') also snapshotted 'img3', not compared"
    )


def test_a_one_sided_extra_source_is_reported_alone() -> None:
    ref = record(
        "aaa",
        label="A",
        calibration=(snapshot("img1", 0.5, "nm"), snapshot("img2", 0.5, "nm")),
    )
    other = record("bbb", label="B", calibration=(snapshot("img1", 0.5, "nm"),))
    (note,) = notes(ref, other)
    assert "covers only the shared source 'img1'" in note
    assert "reference aaa ('A') also snapshotted 'img2', not compared" in note
    assert "result bbb ('B') also" not in note


def test_coverage_notes_are_independent_of_the_differences() -> None:
    """A pair can disagree AND be incompletely covered; the two reports are
    separate so a caller can show both."""
    ref = record(
        "aaa",
        calibration=(snapshot("img1", 0.5, "nm"), snapshot("img2", 0.5, "nm")),
    )
    other = record("bbb", calibration=(snapshot("img1", 0.25, "nm"),))
    agreement = calibration_agreement(ref, other)
    assert agreement.agrees is False
    assert agreement.verified is True
    (note,) = notes(ref, other)
    assert "covers only the shared source 'img1'" in note
