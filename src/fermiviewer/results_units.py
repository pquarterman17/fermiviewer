"""Where a result output's units live, and when they may be trusted — 2B.

Extracted from `results_compare.py` so the compatibility rules and the
unit-reading convention they depend on stay separately readable, both
under the module ceiling. `results_compare` re-exports `DIMENSIONLESS_KEY`
so callers keep one import site for the whole 2B comparison surface.

## Where units live, per kind (ADR 0004 §3)

* `scalar` — `data["unit"]`.
* `curve` and `fit` — `data["x_unit"]` and `data["y_unit"]` (a fit is a
  curve plus model/coefficient keys, so it carries the same axis units).
* `table` — `data["units"]`, positionally aligned to `data["columns"]`,
  but reported per COLUMN NAME so reordering columns is not a unit change
  and a column only one side carries can be treated as an absence.
* `map`, `overlay`, `figure` — ADR 0004 §3 defines no unit convention for
  these (`data` is display hints / caption inputs), so they have no slots.

## Recorded, or unverified

**A unit may be compared only when it was actually recorded.** A non-empty
string is a recorded unit: `'at.%'` matches `'at.%'` and mismatches
`'wt.%'`.

Everything else is UNVERIFIED — `UnitReading.text` is None, and a caller
must neither match nor reject on it. That covers a missing key, a null or
a non-string value (nothing was recorded), and also a bare `""`.

`""` is UNVERIFIED BY DEFAULT because it is overloaded across this
codebase's shipped records. A particle table writes `""` for a genuinely
dimensionless column such as circularity, while `measure.profile` writes
`y_unit=""` because a raster intensity has no calibrated unit at all —
`routes/measure.py::_capture_profile` says so in as many words. Reading
those alike would certify two unrelated intensity domains as sharing
units, silently, which is the exact failure the shared-units requirement
exists to prevent.

**The opt-in:** an output whose `data` carries `DIMENSIONLESS_KEY` set to
exactly `True` states that its empty unit strings are real, dimensionless
units. Such a `""` then behaves like any recorded unit — it matches
another marked `""` and MISMATCHES `'at.%'`. The marker is per OUTPUT, so
on a table it asserts this of every empty column unit in that output; an
output that needs to say it of some columns and not others must record
real unit strings for the rest.

`description` travels with `text` because "no recorded unit" and "an empty
unit with no dimensionless marker" are both unverified but are not the
same mistake, and 2B's deliverable is the sentence a user reads.

Pure layer: stdlib over the frozen record types, no session/route imports.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fermiviewer.io.results_model import ResultOutput

__all__ = [
    "DIMENSIONLESS_KEY",
    "UNIT_KEYS",
    "UNMARKED_EMPTY",
    "UNRECORDED",
    "UnitReading",
    "read_unit",
    "unit_slots",
]

#: `ResultOutput.data` key by which an output opts its EMPTY unit strings
#: in as real dimensionless units. Only the value `True` counts; without
#: it, `""` is unverified — see the module docstring for why `""` alone
#: cannot be trusted in this codebase.
DIMENSIONLESS_KEY = "dimensionless"

#: Per-kind unit keys in `ResultOutput.data`, in slot order. `table` is
#: positional against `data["columns"]` and handled separately; the raster
#: and figure kinds define no unit convention, so are absent here.
UNIT_KEYS: dict[str, tuple[str, ...]] = {
    "scalar": ("unit",),
    "curve": ("x_unit", "y_unit"),
    "fit": ("x_unit", "y_unit"),
}


@dataclass(frozen=True)
class UnitReading:
    """One unit slot as read from `data`.

    `text` is the comparable unit, or None when nothing was VERIFIED —
    absent, null, non-string, or an unmarked `""`. `description` is how a
    message should say what was found.
    """

    text: str | None
    description: str


#: The two ways a slot can be unverified, kept distinct in prose.
UNRECORDED = UnitReading(None, "no recorded unit")
UNMARKED_EMPTY = UnitReading(None, "an empty unit with no dimensionless marker")


def read_unit(value: Any, dimensionless: bool) -> UnitReading:
    """One recorded unit value, resolved against the dimensionless marker."""
    if not isinstance(value, str):
        return UNRECORDED
    if value:
        return UnitReading(value, repr(value))
    return UnitReading("", "'' (marked dimensionless)") if dimensionless else UNMARKED_EMPTY


def _table_slots(data: dict[str, Any], dimensionless: bool) -> tuple[tuple[str, UnitReading], ...]:
    """Table unit slots keyed by column NAME, from positional `units`."""
    columns = data.get("columns")
    if not isinstance(columns, (list, tuple)):
        return ()
    raw_units = data.get("units")
    units: Sequence[Any] = raw_units if isinstance(raw_units, (list, tuple)) else ()
    slots: list[tuple[str, UnitReading]] = []
    seen: set[str] = set()
    for index, column in enumerate(columns):
        label = f"column {str(column)!r}"
        if label in seen:  # a duplicated column name: the first one wins
            continue
        seen.add(label)
        raw = units[index] if index < len(units) else None
        slots.append((label, read_unit(raw, dimensionless)))
    return tuple(slots)


def unit_slots(output: ResultOutput) -> tuple[tuple[str, UnitReading], ...]:
    """The `(slot label, reading)` pairs this output's kind defines, in order.

    Empty for a kind with no unit convention, so a caller compares such
    outputs on `kind` alone. Deterministic: slots follow `UNIT_KEYS` order,
    or the table's own column order.
    """
    data = output.data if isinstance(output.data, dict) else {}
    # Exactly `True`: a truthy stray value is not an assertion about units.
    dimensionless = data.get(DIMENSIONLESS_KEY) is True
    if output.kind == "table":
        return _table_slots(data, dimensionless)
    return tuple(
        (key, read_unit(data.get(key), dimensionless)) for key in UNIT_KEYS.get(output.kind, ())
    )
