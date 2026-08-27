"""Compatible-result query — the comparison half of roadmap item 2B.

The roadmap line is "compare compatible results across images or samples
with shared units and **explicit incompatibility messages**". The message
is the deliverable: a caller must be able to tell a user *why* two records
cannot be put side by side — naming both records and the exact output and
unit that disagree — rather than showing a greyed-out row.

So `compare_results` never returns a bare boolean. It returns a
`Comparison` carrying three separately-actionable things:

* `compatible` — one `CandidateMatch` per candidate that can be shown next
  to the reference, carrying the outputs comparable with THE REFERENCE and
  that pair's `CalibrationAgreement`;
* `rejected` — every other candidate with a stable `code` and a sentence
  naming both sides concretely;
* `notes` — non-fatal observations a view should surface but that
  disqualify nobody (an output only some records carry, a unit that could
  not be verified, a pixel size that changed between records).

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
   candidate lacks is dropped from that candidate's `outputs` with a note;
   the candidate is rejected (`no_shared_outputs`) only when nothing
   comparable is left.
6. **The reference is trivially comparable with itself.**

A kind or unit disagreement rejects the whole candidate rather than just
that output: same analysis and output name but different units is a
*discrepancy*, not an absence, and dropping it silently would hide the
mistake this query exists to catch. Absence (rule 5) is the benign case.

## Pairwise, with a cumulative summary

Every rule is decided PAIRWISE against the reference, so a
`CandidateMatch.outputs` is that one pair's comparable set and is never
empty — nothing comparable is rule 5's rejection. (The reflexive case is
the sole exception: a `failed` reference has no outputs yet rule 6 still
holds.)

`Comparison.outputs` is the intersection across every compatible
candidate: the outputs one side-by-side view can render for the WHOLE
group. It can therefore be empty while `compatible` is not — a reference
with outputs A and B, one candidate carrying only A and one carrying only
B are each pairwise comparable but share nothing between them. That case
emits a note rather than passing as an empty render.

## Units: where they live, and when they count (`results_units`)

The sibling module holds both answers — the per-kind `data` keys ADR 0004
§3 defines, and the rule that a unit is compared only when it was actually
RECORDED. A missing key, a null, a non-string value and a bare `""` are
all UNVERIFIED: rule 4 neither matches nor rejects on them, it emits a
note and the output stays comparable.

`""` counts as a real dimensionless unit only when its output opts in with
`DIMENSIONLESS_KEY` (re-exported here). `""` is overloaded across this
codebase's records — a genuinely dimensionless particle-table column, but
also `measure.profile`'s uncalibrated raster intensity — and reading the
two alike would certify unrelated intensity domains as sharing units with
no note at all. The full argument is that module's docstring.

Unknown must manufacture neither agreement nor rejection — hence the note.

## Calibration

The other half of "were these measured the same way" lives in the sibling
`results_calibration.py`: `calibration_agreement` reports whether two
records' SOURCE calibration snapshots agree, so a caller can tell "same
units, different pixel size" from "same everything". It is a NOTE, never a
rejection (the reasoning is in that module).

For every compatible candidate `compare_results` folds in both halves of
that report: the concrete `differences`, and `calibration_coverage_notes`
for what was never checked — records on different images share no snapshot
and so produce no differences at all, which must not read as agreement.
The full `CalibrationAgreement` stays reachable as
`CandidateMatch.calibration_agreement` so a route can return it
structured rather than re-deriving it from prose.

`CalibrationAgreement`, `calibration_agreement` and
`calibration_coverage_notes` are **re-exported from here**, so the whole
2B comparison surface stays one import site and the split remains an
implementation detail for callers.

Pure layer: stdlib over the frozen record types, no session/route imports.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fermiviewer.io.results_model import ResultOutput, ResultRecord
from fermiviewer.results_calibration import (
    # Re-exported below, with `DIMENSIONLESS_KEY`: routes and tests reach
    # the whole 2B comparison surface through this module, so the splits
    # stay an implementation detail rather than extra import sites.
    CalibrationAgreement,
    calibration_agreement,
    calibration_coverage_notes,
    record_name,
)
from fermiviewer.results_units import DIMENSIONLESS_KEY, unit_slots

__all__ = [
    "CODE_ANALYSIS_MISMATCH",
    "CODE_NO_SHARED_OUTPUTS",
    "CODE_OUTPUT_KIND_MISMATCH",
    "CODE_OUTPUT_UNIT_MISMATCH",
    "CODE_STATUS_NOT_COMPLETED",
    "COMPARABLE_STATUS",
    "DIMENSIONLESS_KEY",
    "INCOMPATIBILITY_CODES",
    "CalibrationAgreement",
    "CandidateMatch",
    "Comparison",
    "Incompatibility",
    "calibration_agreement",
    "calibration_coverage_notes",
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
class CandidateMatch:
    """One candidate that CAN be shown beside the reference.

    `outputs` are the output names comparable between this candidate and
    the reference alone, in the reference's own output order — the pair's
    verdict, not the group's. Non-empty, except for the reflexive match of
    a reference that has no outputs (rule 6).

    `calibration_agreement` is that pair's full source-calibration report,
    kept structured here so a caller can render it rather than parse the
    sentences `Comparison.notes` already carries.
    """

    id: str
    outputs: tuple[str, ...]
    calibration_agreement: CalibrationAgreement


@dataclass(frozen=True)
class Comparison:
    """The comparable set around one reference record.

    `outputs` are the output names comparable across the reference AND
    EVERY member of `compatible` — the cumulative intersection, in the
    reference's output order. It is honestly allowed to be empty while
    `compatible` is not (candidates comparable pairwise but sharing no
    output between them); that case is called out in `notes`. With no
    compatible candidates it is simply the reference's own output names:
    nothing constrains them yet.

    `rejected` pairs each rejected candidate id with its `Incompatibility`,
    in the order the candidates were given; every candidate appears in
    exactly one of `compatible` and `rejected`.
    """

    reference_id: str
    outputs: tuple[str, ...]
    compatible: tuple[CandidateMatch, ...]
    rejected: tuple[tuple[str, Incompatibility], ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class _Verdict:
    """A candidate that passed every rule: its match, plus its notes."""

    match: CandidateMatch
    notes: tuple[str, ...]


# ── output lookup ────────────────────────────────────────────────────


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
    ref_slots = dict(unit_slots(ref_output))
    cand_slots = dict(unit_slots(cand_output))
    notes: list[str] = []
    for slot, ref_unit in ref_slots.items():
        if slot not in cand_slots:
            notes.append(
                f"output {name!r}: {slot} is recorded by reference {ref_name} but not "
                f"by result {cand_name}, so it is not compared"
            )
            continue
        cand_unit = cand_slots[slot]
        if ref_unit.text is None or cand_unit.text is None:
            notes.append(
                f"output {name!r}: units not verified for {slot} — reference "
                f"{ref_name} has {ref_unit.description}, result "
                f"{cand_name} has {cand_unit.description}"
            )
        elif ref_unit.text != cand_unit.text:
            return (
                Incompatibility(
                    CODE_OUTPUT_UNIT_MISMATCH,
                    f"output {name!r}: {slot} is {ref_unit.text!r} in reference "
                    f"{ref_name} but {cand_unit.text!r} in result {cand_name} — "
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
) -> Incompatibility | _Verdict:
    """Rules 3-5: shared names, then kind and units on each, then calibration."""
    ref_name, cand_name = record_name(reference), record_name(candidate)
    cand_outputs = _outputs_by_name(candidate)
    shared = tuple(name for name in ref_outputs if name in cand_outputs)
    if not shared:
        ref_names = ", ".join(repr(n) for n in ref_outputs) or "no outputs"
        cand_names = ", ".join(repr(n) for n in cand_outputs) or "no outputs"
        return Incompatibility(
            CODE_NO_SHARED_OUTPUTS,
            f"result {cand_name} shares no output name with reference "
            f"{ref_name}: the reference has {ref_names}; the candidate has "
            f"{cand_names}",
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
            return Incompatibility(
                CODE_OUTPUT_KIND_MISMATCH,
                f"output {name!r} is a {ref_output.kind!r} in reference "
                f"{ref_name} but a {cand_output.kind!r} in result {cand_name}",
            )
        bad, slot_notes = _compare_units(reference, candidate, name, ref_output, cand_output)
        if bad is not None:
            return bad
        notes.extend(slot_notes)
    agreement = calibration_agreement(reference, candidate)
    notes.extend(agreement.differences)
    notes.extend(calibration_coverage_notes(agreement, ref_name, cand_name))
    return _Verdict(CandidateMatch(candidate.id, shared, agreement), tuple(notes))


def _check_candidate(
    reference: ResultRecord,
    ref_outputs: dict[str, ResultOutput],
    candidate: ResultRecord,
) -> Incompatibility | _Verdict:
    """All rules for one candidate, in rule order; the first failure wins."""
    ref_name, cand_name = record_name(reference), record_name(candidate)
    if candidate.analysis != reference.analysis:
        return Incompatibility(
            CODE_ANALYSIS_MISMATCH,
            f"result {cand_name} is analysis {candidate.analysis!r} but reference "
            f"{ref_name} is analysis {reference.analysis!r} — different analyses "
            f"are not comparable",
        )
    if candidate.status != COMPARABLE_STATUS:
        reason = f" (error: {candidate.error})" if candidate.error else ""
        return Incompatibility(
            CODE_STATUS_NOT_COMPLETED,
            f"result {cand_name} has status {candidate.status!r}{reason}, so it "
            f"carries no completed outputs to compare against reference {ref_name}",
        )
    return _check_outputs(reference, ref_outputs, candidate)


def _no_common_output_note(
    reference: ResultRecord, compatible: Sequence[CandidateMatch]
) -> str:
    """Rule for the honest empty `Comparison.outputs` (see the class docstring).

    Every candidate matched the reference, each on its own outputs, and the
    intersection came out empty — so a grouped view has nothing to render
    even though no candidate was rejected. The sentence names each
    candidate's own comparable set, since that is what the caller must look
    at to split the group into renderable subsets.
    """
    pairs = "; ".join(
        f"{match.id} on " + (", ".join(repr(n) for n in match.outputs) or "no outputs")
        for match in compatible
    )
    return (
        f"no output is comparable across all {len(compatible)} compatible results: "
        f"reference {record_name(reference)} matches each of them, but on different "
        f"outputs ({pairs}) — a single side-by-side view of the whole group has "
        f"nothing to show"
    )


# ── entry point ──────────────────────────────────────────────────────


def compare_results(reference: ResultRecord, candidates: Sequence[ResultRecord]) -> Comparison:
    """Which of `candidates` can be compared against `reference`, and why not.

    Candidates keep their given order in `compatible` and `rejected`, each
    appearing in exactly one of them; `outputs` follows the reference's
    output order and `notes` first-appearance order, deduplicated. Nothing
    here iterates a set, so the result is byte-identical run to run.

    A candidate whose id equals the reference's is trivially compatible
    and skips every rule (rule 6), notes included — a record cannot
    disagree with itself about units or calibration. Record ids are unique
    within a project (ADR 0004 §6 enforces it on save AND load), so an id
    match means the same record and the reflexive case holds even for a
    reference no other record could be compared against.
    """
    ref_outputs = _outputs_by_name(reference)
    surviving = list(ref_outputs)
    compatible: list[CandidateMatch] = []
    rejected: list[tuple[str, Incompatibility]] = []
    notes: list[str] = []
    for candidate in candidates:
        if candidate.id == reference.id:
            compatible.append(
                CandidateMatch(
                    candidate.id,
                    tuple(ref_outputs),
                    calibration_agreement(reference, candidate),
                )
            )
            continue
        verdict = _check_candidate(reference, ref_outputs, candidate)
        if isinstance(verdict, Incompatibility):
            rejected.append((candidate.id, verdict))
            continue
        compatible.append(verdict.match)
        notes.extend(verdict.notes)
        shared = set(verdict.match.outputs)
        surviving = [name for name in surviving if name in shared]
    if ref_outputs and compatible and not surviving:
        notes.append(_no_common_output_note(reference, compatible))
    return Comparison(
        reference_id=reference.id,
        outputs=tuple(surviving),
        compatible=tuple(compatible),
        rejected=tuple(rejected),
        notes=tuple(dict.fromkeys(notes)),
    )
