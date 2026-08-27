"""Unit slots on a result output — the reading layer 2B's rule 4 sits on.

Split out of test_results_compare.py alongside the module itself: the
compatibility RULES are tested there, through `compare_results`; what is
tested here is the reading — which slots a kind defines, and whether a
recorded value counts as a verified unit at all.

The load-bearing case is `""`. It is overloaded across this codebase's
shipped records (a genuinely dimensionless particle-table column, but also
`measure.profile`'s uncalibrated raster intensity), so it is UNVERIFIED
unless the output opts in with `DIMENSIONLESS_KEY`.
"""

from __future__ import annotations

from typing import Any

import pytest

from fermiviewer.io.results_model import ResultOutput
from fermiviewer.results_units import (
    DIMENSIONLESS_KEY,
    UNIT_KEYS,
    UnitReading,
    read_unit,
    unit_slots,
)


def output(kind: str, **data: Any) -> ResultOutput:
    return ResultOutput(kind=kind, name="x", data=dict(data))


# ── which slots a kind defines (ADR 0004 §3) ─────────────────────────


def test_scalar_curve_and_fit_slots_follow_the_documented_keys() -> None:
    assert [s for s, _ in unit_slots(output("scalar", unit="at.%"))] == ["unit"]
    assert [s for s, _ in unit_slots(output("curve", x_unit="nm", y_unit="counts"))] == [
        "x_unit",
        "y_unit",
    ]
    assert UNIT_KEYS["fit"] == UNIT_KEYS["curve"]


@pytest.mark.parametrize("kind", ["map", "overlay", "figure"])
def test_kinds_with_no_unit_convention_define_no_slots(kind: str) -> None:
    """`data` is display hints for these, so there is nothing to compare."""
    assert unit_slots(output(kind, cmap="viridis", unit="at.%")) == ()


def test_table_slots_are_keyed_by_column_name_not_position() -> None:
    slots = unit_slots(output("table", columns=["area", "label"], units=["nm^2", ""]))
    assert [s for s, _ in slots] == ["column 'area'", "column 'label'"]
    assert slots[0][1].text == "nm^2"


def test_a_table_column_past_the_units_list_is_unrecorded() -> None:
    slots = dict(unit_slots(output("table", columns=["area", "perimeter"], units=["nm^2"])))
    assert slots["column 'perimeter'"].text is None
    assert slots["column 'perimeter'"].description == "no recorded unit"


def test_a_duplicated_column_name_keeps_the_first_slot() -> None:
    slots = unit_slots(output("table", columns=["area", "area"], units=["nm^2", "um^2"]))
    assert [s for s, _ in slots] == ["column 'area'"]
    assert slots[0][1].text == "nm^2"


def test_a_table_without_a_column_list_has_no_slots() -> None:
    assert unit_slots(output("table", units=["nm^2"])) == ()


def test_an_empty_data_payload_still_defines_the_kinds_slot_as_unrecorded() -> None:
    """The slot exists — the kind defines it — but nothing was recorded in
    it, which is what keeps "absent" distinguishable from "no convention"."""
    ((slot, reading),) = unit_slots(ResultOutput(kind="scalar", name="x", data={}))
    assert slot == "unit"
    assert reading.text is None


# ── recorded, or unverified ──────────────────────────────────────────


def test_a_non_empty_string_is_a_recorded_unit() -> None:
    assert read_unit("at.%", False) == UnitReading("at.%", "'at.%'")


@pytest.mark.parametrize("value", [None, 7, ["nm"], {}])
def test_a_missing_or_non_string_value_is_unverified(value: Any) -> None:
    reading = read_unit(value, False)
    assert reading.text is None
    assert reading.description == "no recorded unit"


def test_an_unmarked_empty_string_is_unverified_and_says_why() -> None:
    reading = read_unit("", False)
    assert reading.text is None
    assert reading.description == "an empty unit with no dimensionless marker"


def test_the_marker_turns_an_empty_string_into_a_real_unit() -> None:
    reading = read_unit("", True)
    assert reading.text == ""
    assert reading.description == "'' (marked dimensionless)"


def test_the_marker_is_read_from_the_output_data() -> None:
    marked = output("scalar", unit="", **{DIMENSIONLESS_KEY: True})
    ((_, reading),) = unit_slots(marked)
    assert reading.text == ""


@pytest.mark.parametrize("value", ["yes", 1, [True], None])
def test_only_the_literal_true_counts_as_the_marker(value: Any) -> None:
    """A truthy stray value is not an assertion about units."""
    ((_, reading),) = unit_slots(output("scalar", unit="", **{DIMENSIONLESS_KEY: value}))
    assert reading.text is None


def test_the_marker_does_not_touch_a_recorded_unit() -> None:
    ((_, reading),) = unit_slots(output("scalar", unit="at.%", **{DIMENSIONLESS_KEY: True}))
    assert reading.text == "at.%"


def test_the_marker_applies_to_every_empty_column_of_a_table() -> None:
    slots = dict(
        unit_slots(
            output(
                "table",
                columns=["area", "circularity", "solidity"],
                units=["nm^2", "", ""],
                **{DIMENSIONLESS_KEY: True},
            )
        )
    )
    assert slots["column 'circularity'"].text == ""
    assert slots["column 'solidity'"].text == ""
    assert slots["column 'area'"].text == "nm^2"
