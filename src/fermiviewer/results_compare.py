"""Compatible-result query — the comparison half of roadmap item 2B.

The roadmap line is "compare compatible results across images or samples
with shared units and **explicit incompatibility messages**". The message
is the deliverable: a caller must be able to tell a user *why* two records
cannot be put side by side — naming both records and the exact output and
unit that disagree — rather than showing a greyed-out row.

So `compare_results` never returns a bare boolean. It returns a
`Comparison` carrying three separately-actionable things:

* `compatible` — the candidate ids that can be shown next to the reference;
* `rejected` — every other candidate with a stable `code` and a sentence
  naming both sides concretely;
* `notes` — non-fatal observations a view should surface but that
  disqualify nobody (an output only some records carry, an unrecorded
  unit, a pixel size that changed between records).

## The rules

1. **`analysis` must match exactly** (`analysis_mismatch`). Two analyses
   that both emit an output called `Fe` are not thereby comparable; the
   analysis key is the contract for what the number means.
2. **Status must be `completed`** (`status_not_completed`). ADR 0004 §4
   keeps `failed`/`cancelled` distinct from completed science: such a
   record has no outputs and must not be quietly read as zeros.
3. **Shared output names must agree on `kind`** (`output_kind_mismatch`).
4. **Shared output names must agree on units** (`output_unit_mismatch`),
   read per kind from where ADR 0004 §3 keeps them (see below).
5. **A missing output is not fatal.** An output the reference has and a
   candidate lacks is dropped from `outputs` with a note; the candidate is
   rejected (`no_shared_outputs`) only when nothing comparable is left.
6. **The reference is trivially comparable with itself.**

A kind or unit disagreement rejects the whole candidate rather than just
that output: same analysis and output name but different units is a
*discrepancy*, not an absence, and dropping it silently would hide the
mistake this query exists to catch. Absence (rule 5) is the benign case.

## Where units live, per kind (ADR 0004 §3)

* `scalar` — `data["unit"]`.
* `curve` and `fit` — `data["x_unit"]` and `data["y_unit"]` (a fit is a
  curve plus model/coefficient keys, so it carries the same axis units).
* `table` — `data["units"]`, positionally aligned to `data["columns"]`;
  compared per COLUMN NAME, so reordering columns is not a unit change and
  a column only one side carries is a note.
* `map`, `overlay`, `figure` — ADR 0004 §3 defines no unit convention for
  these (`data` is display hints / caption inputs), so only rule 3 applies.

## Missing unit vs empty unit

**A missing unit key is UNKNOWN; an explicitly empty string is a real,
dimensionless unit.** `{"unit": ""}` matches only another `""` and
mismatches `{"unit": "at.%"}`; `{}` (or a `None`/non-string value) matches
nothing and mismatches nothing — it notes that the unit could not be
verified, and the output stays comparable.

The asymmetry follows `AxisCal.units`, where `""` already means
"uncalibrated" as a recorded fact. Treating an absent key as `""` would let
a record that never recorded units certify as "same units" against one that
did; treating `""` as unknown would discard a real statement. Unknown must
manufacture neither agreement nor rejection — hence the note.

## Calibration

The other half of "were these measured the same way" lives in the sibling
`results_calibration.py`: `calibration_agreement` reports whether two
records' SOURCE calibration snapshots agree, so a caller can tell "same
units, different pixel size" from "same everything". It is a NOTE, never a
rejection (the reasoning is in that module), and `compare_results` folds
its `differences` into `notes` for every compatible candidate.

`CalibrationAgreement` and `calibration_agreement` are **re-exported from
here**, so the whole 2B comparison surface stays one import site and the
split remains an implementation detail for callers.

Pure layer: stdlib over the frozen record types, no session/route imports.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fermiviewer.io.results_model import ResultOutput, ResultRecord
from fermiviewer.results_calibration import (
    # Re-exported below: routes and tests reach the whole 2B comparison
    # surface through this module, so the split stays an implementation
    # detail rather than a second import site for callers.
    CalibrationAgreement,
    calibration_agreement,
    record_name,
)

__all__ = [
    "CODE_ANALYSIS_MISMATCH",
    "CODE_NO_SHARED_OUTPUTS",
    "CODE_OUTPUT_KIND_MISMATCH",
    "CODE_OUTPUT_UNIT_MISMATCH",
    "CODE_STATUS_NOT_COMPLETED",
    "COMPARABLE_STATUS",
    "INCOMPATIBILITY_CODES",
    "CalibrationAgreement",
    "Comparison",
    "Incompatibility",
    "calibration_agreement",
    "compare_results",
]

#: The one status whose outputs are real science (ADR 0004 §4).
COMPARABLE_STATUS = "completed"

CODE_ANALYSIS_MISMATCH = "analysis_mismatch"
CODE_STATUS_NOT_COMPLETED = "status_not_completed"
CODE_OUTPUT_KIND_MISMATCH = "output_kind_mismatch"
CODE_OUTPUT_UNIT_MISMATCH = "output_unit_mismatch"
CODE_NO_SHARED_OUTPUTS = "no_shared_outputs"

#: Every code `compare_results` can emit, in rule order — a tuple, not a
#: set: everything this module hands back is deterministically ordered.
INCOMPATIBILITY_CODES: tuple[str, ...] = (
    CODE_ANALYSIS_MISMATCH,
    CODE_STATUS_NOT_COMPLETED,
    CODE_NO_SHARED_OUTPUTS,
    CODE_OUTPUT_KIND_MISMATCH,
    CODE_OUTPUT_UNIT_MISMATCH,
)

#: Per-kind unit keys in `ResultOutput.data` (ADR 0004 §3). `table` is
#: positional against `data["columns"]` and handled separately; the raster
#: and figure kinds define no unit convention, so are absent here.
_UNIT_KEYS: dict[str, tuple[str, ...]] = {
    "scalar": ("unit",),
    "curve": ("x_unit", "y_unit"),
    "fit": ("x_unit", "y_unit"),
}


# ── structures ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Incompatibility:
    """Why one candidate cannot be compared against the reference.

    `code` is stable and machine-readable (one of `INCOMPATIBILITY_CODES`);
    `message` is the user-facing sentence, always naming BOTH records.
    """

    code: str
    message: str


@dataclass(frozen=True)
class Comparison:
    """The comparable set around one reference record.

    `outputs` are the output names comparable across the reference AND
    every id in `compatible`, in the reference's own output order. With no
    compatible candidates it is simply the reference's own output names:
    nothing constrains them yet.

    `rejected` pairs each rejected candidate id with its `Incompatibility`,
    in the order the candidates were given; every candidate appears in
    exactly one of `compatible` and `rejected`.
    """

    reference_id: str
    outputs: tuple[str, ...]
    compatible: tuple[str, ...]
    rejected: tuple[tuple[str, Incompatibility], ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class _Check:
    """One candidate's verdict, before it joins the accumulated sets."""

    incompatibility: Incompatibility | None
    shared: tuple[str, ...]
    notes: tuple[str, ...]


# ── naming and unit reading ──────────────────────────────────────────


def _unit_text(value: Any) -> str | None:
    """A recorded unit, or None for UNKNOWN (absent, null, or not a string).

    `""` is a recorded unit meaning dimensionless — see the module
    docstring's missing-vs-empty rule.
    """
    return value if isinstance(value, str) else None


def _describe_unit(unit: str | None) -> str:
    return "no recorded unit" if unit is None else repr(unit)


def _table_slots(data: dict[str, Any]) -> tuple[tuple[str, str | None], ...]:
    """Table unit slots keyed by column NAME, from positional `units`."""
    columns = data.get("columns")
    if not isinstance(columns, (list, tuple)):
        return ()
    raw_units = data.get("units")
    units: Sequence[Any] = raw_units if isinstance(raw_units, (list, tuple)) else ()
    slots: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for index, column in enumerate(columns):
        label = f"column {str(column)!r}"
        if label in seen:  # a duplicated column name: the first one wins
            continue
        seen.add(label)
        slots.append((label, _unit_text(units[index]) if index < len(units) else None))
    return tuple(slots)


def _unit_slots(output: ResultOutput) -> tuple[tuple[str, str | None], ...]:
    """The `(slot label, unit)` pairs this output's kind defines, in order."""
    data = output.data if isinstance(output.data, dict) else {}
    if output.kind == "table":
        return _table_slots(data)
    return tuple((key, _unit_text(data.get(key))) for key in _UNIT_KEYS.get(output.kind, ()))


def _outputs_by_name(record: ResultRecord) -> dict[str, ResultOutput]:
    """Outputs keyed by name, in record order; a repeated name keeps the first."""
    by_name: dict[str, ResultOutput] = {}
    for output in record.outputs:
        by_name.setdefault(output.name, output)
    return by_name


# ── per-candidate rules ──────────────────────────────────────────────


def _compare_units(
    reference: ResultRecord,
    candidate: ResultRecord,
    name: str,
    ref_output: ResultOutput,
    cand_output: ResultOutput,
) -> tuple[Incompatibility | None, tuple[str, ...]]:
    """Rule 4 for one shared output: a mismatch, or notes for what is unknown."""
    ref_name, cand_name = record_name(reference), record_name(candidate)
    ref_slots = dict(_unit_slots(ref_output))
    cand_slots = dict(_unit_slots(cand_output))
    notes: list[str] = []
    for slot, ref_unit in ref_slots.items():
        if slot not in cand_slots:
            notes.append(
                f"output {name!r}: {slot} is recorded by reference {ref_name} but not "
                f"by result {cand_name}, so it is not compared"
            )
            continue
        cand_unit = cand_slots[slot]
        if ref_unit is None or cand_unit is None:
            notes.append(
                f"output {name!r}: units not verified for {slot} — reference "
                f"{ref_name} has {_describe_unit(ref_unit)}, result "
                f"{cand_name} has {_describe_unit(cand_unit)}"
            )
        elif ref_unit != cand_unit:
            return (
                Incompatibility(
                    CODE_OUTPUT_UNIT_MISMATCH,
                    f"output {name!r}: {slot} is {ref_unit!r} in reference "
                    f"{ref_name} but {cand_unit!r} in result {cand_name} — "
                    f"comparing them would mix units",
                ),
                (),
            )
    for slot in cand_slots:
        if slot not in ref_slots:
            notes.append(
                f"output {name!r}: {slot} is recorded by result {cand_name} but not "
                f"by reference {ref_name}, so it is not compared"
            )
    return None, tuple(notes)


def _check_outputs(
    reference: ResultRecord,
    ref_outputs: dict[str, ResultOutput],
    candidate: ResultRecord,
) -> _Check:
    """Rules 3-5: shared names, then kind and units on each."""
    ref_name, cand_name = record_name(reference), record_name(candidate)
    cand_outputs = _outputs_by_name(candidate)
    shared = tuple(name for name in ref_outputs if name in cand_outputs)
    if not shared:
        ref_names = ", ".join(repr(n) for n in ref_outputs) or "no outputs"
        cand_names = ", ".join(repr(n) for n in cand_outputs) or "no outputs"
        return _Check(
            Incompatibility(
                CODE_NO_SHARED_OUTPUTS,
                f"result {cand_name} shares no output name with reference "
                f"{ref_name}: the reference has {ref_names}; the candidate has "
                f"{cand_names}",
            ),
            (),
            (),
        )
    notes: list[str] = [
        f"output {name!r} is not compared: reference {ref_name} has it but result "
        f"{cand_name} does not"
        for name in ref_outputs
        if name not in cand_outputs
    ]
    for name in shared:
        ref_output, cand_output = ref_outputs[name], cand_outputs[name]
        if ref_output.kind != cand_output.kind:
            return _Check(
                Incompatibility(
                    CODE_OUTPUT_KIND_MISMATCH,
                    f"output {name!r} is a {ref_output.kind!r} in reference "
                    f"{ref_name} but a {cand_output.kind!r} in result "
                    f"{cand_name}",
                ),
                (),
                (),
            )
        bad, slot_notes = _compare_units(reference, candidate, name, ref_output, cand_output)
        if bad is not None:
            return _Check(bad, (), ())
        notes.extend(slot_notes)
    notes.extend(calibration_agreement(reference, candidate).differences)
    return _Check(None, shared, tuple(notes))


def _check_candidate(
    reference: ResultRecord,
    ref_outputs: dict[str, ResultOutput],
    candidate: ResultRecord,
) -> _Check:
    """All rules for one candidate, in rule order; the first failure wins."""
    ref_name, cand_name = record_name(reference), record_name(candidate)
    if candidate.analysis != reference.analysis:
        return _Check(
            Incompatibility(
                CODE_ANALYSIS_MISMATCH,
                f"result {cand_name} is analysis {candidate.analysis!r} but reference "
                f"{ref_name} is analysis {reference.analysis!r} — different analyses "
                f"are not comparable",
            ),
            (),
            (),
        )
    if candidate.status != COMPARABLE_STATUS:
        reason = f" (error: {candidate.error})" if candidate.error else ""
        return _Check(
            Incompatibility(
                CODE_STATUS_NOT_COMPLETED,
                f"result {cand_name} has status {candidate.status!r}{reason}, so it "
                f"carries no completed outputs to compare against reference "
                f"{ref_name}",
            ),
            (),
            (),
        )
    return _check_outputs(reference, ref_outputs, candidate)


# ── entry point ──────────────────────────────────────────────────────


def compare_results(reference: ResultRecord, candidates: Sequence[ResultRecord]) -> Comparison:
    """Which of `candidates` can be compared against `reference`, and why not.

    Candidates keep their given order in `compatible` and `rejected`, each
    appearing in exactly one of them; `outputs` follows the reference's
    output order and `notes` first-appearance order, deduplicated. Nothing
    here iterates a set, so the result is byte-identical run to run.

    A candidate whose id equals the reference's is trivially compatible
    and skips every rule (rule 6). Record ids are unique within a project
    (ADR 0004 §6 enforces it on save AND load), so an id match means the
    same record and the reflexive case holds even for a reference no other
    record could be compared against.
    """
    ref_outputs = _outputs_by_name(reference)
    surviving = list(ref_outputs)
    compatible: list[str] = []
    rejected: list[tuple[str, Incompatibility]] = []
    notes: list[str] = []
    for candidate in candidates:
        if candidate.id == reference.id:
            compatible.append(candidate.id)
            continue
        check = _check_candidate(reference, ref_outputs, candidate)
        if check.incompatibility is not None:
            rejected.append((candidate.id, check.incompatibility))
            continue
        compatible.append(candidate.id)
        notes.extend(check.notes)
        shared = set(check.shared)
        surviving = [name for name in surviving if name in shared]
    return Comparison(
        reference_id=reference.id,
        outputs=tuple(surviving),
        compatible=tuple(compatible),
        rejected=tuple(rejected),
        notes=tuple(dict.fromkeys(notes)),
    )
