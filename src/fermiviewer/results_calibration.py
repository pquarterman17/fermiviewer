"""Source-calibration agreement between result records — roadmap item 2B.

The compatibility half of 2B (`results_compare.py`) answers "can these two
records be shown side by side". This module answers the question that sits
just underneath it and has a different answer shape: **were they measured
the same way?** A caller needs to tell "same units, different pixel size"
apart from "same everything", and neither is a reason to refuse the
comparison.

Why this is never a rejection: ADR 0004 §5 snapshots each source image's
`AxisCal` tuple and its `metadata["calibration_source"]` provenance as a
COPY taken at compute time, deliberately so that recalibrating an image
later cannot rewrite what a stored number meant. The outputs of a result
already carry their own units (ADR 0004 §3), so two records computed at
different pixel sizes are still legitimately comparable — the pixel size
is context the reader must be told, not a disqualification. So
`compare_results` folds `differences` into its `notes`, never into an
`Incompatibility`.

## Shape

Sources are matched by `image_id`, so the verdict is per source image
rather than one global boolean. Records over different images share no
source and therefore have nothing to disagree about, which is emphatically
not the same as agreeing — `shared_sources`, `reference_only` and
`candidate_only` make that visible instead of letting an empty
`differences` read as "same everything".

## What counts as a disagreement

Per shared source: the number of snapshotted axes, then per axis the
`scale` (the pixel size) and the `units`, then the record's calibration
provenance string. `origin` is deliberately excluded — it shifts where
zero sits on an axis, not what one step is worth, and no result output
carries it.

Scale comparison tolerates float noise (`math.isclose`, rel_tol 1e-12) and
treats NaN as `AxisCal` does: NaN scale means uncalibrated, and two
uncalibrated axes agree with each other rather than being incomparable.

`record_name` lives here rather than in `results_compare` because both
modules format messages with it and the dependency runs one way
(compare → calibration); it is the naming convention every 2B message
uses, so a message that says `aaa ('EDS A')` reads the same everywhere.

Pure layer: stdlib over the frozen record types, no session/route imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fermiviewer.io.results_model import CalibrationSnapshot, ResultRecord

__all__ = [
    "CalibrationAgreement",
    "calibration_agreement",
    "record_name",
]


def record_name(record: ResultRecord) -> str:
    """Name a record the way a 2B message should: id, plus label when set.

    Bare id when the record has no label, so a message never carries an
    empty `()` where a human-readable name would have gone.
    """
    if record.label:
        return f"{record.id} ({record.label!r})"
    return record.id


@dataclass(frozen=True)
class CalibrationAgreement:
    """Whether two records' source-calibration snapshots say the same thing.

    `shared_sources` are the image ids both records snapshotted, in the
    reference's order; `reference_only`/`candidate_only` are the ids only
    one of them carries. `differences` are human-readable sentences naming
    both records, empty when every shared source agrees.

    See the module docstring: an empty `differences` with an empty
    `shared_sources` means "nothing in common to compare", not "identical".
    """

    reference_id: str
    candidate_id: str
    shared_sources: tuple[str, ...]
    reference_only: tuple[str, ...]
    candidate_only: tuple[str, ...]
    differences: tuple[str, ...]

    @property
    def agrees(self) -> bool:
        """True when no shared source disagrees — vacuously true when the
        records share no source image at all (see `shared_sources`)."""
        return not self.differences


def _same_scale(left: float, right: float) -> bool:
    """Pixel-size equality, tolerant of float noise and NaN-as-uncalibrated."""
    if math.isnan(left) or math.isnan(right):
        return math.isnan(left) and math.isnan(right)
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=0.0)


def _axis_differences(
    image_id: str,
    ref_snap: CalibrationSnapshot,
    cand_snap: CalibrationSnapshot,
    ref_name: str,
    cand_name: str,
) -> list[str]:
    """Per-axis scale/units disagreements for one shared source image.

    `origin` is deliberately not compared: it shifts where zero sits, not
    what a step is worth, and a result's outputs never carry it.
    """
    out: list[str] = []
    if len(ref_snap.axes) != len(cand_snap.axes):
        out.append(
            f"source image {image_id!r}: axis count differs — reference {ref_name} "
            f"snapshotted {len(ref_snap.axes)} axes, result {cand_name} snapshotted "
            f"{len(cand_snap.axes)}"
        )
    pairs = zip(ref_snap.axes, cand_snap.axes, strict=False)  # excess reported above
    for index, (ref_axis, cand_axis) in enumerate(pairs):
        if not _same_scale(ref_axis.scale, cand_axis.scale):
            out.append(
                f"source image {image_id!r}: axis {index} scale differs — reference "
                f"{ref_name} has {ref_axis.scale!r}, result {cand_name} has "
                f"{cand_axis.scale!r}"
            )
        if ref_axis.units != cand_axis.units:
            out.append(
                f"source image {image_id!r}: axis {index} calibration units differ — "
                f"reference {ref_name} has {ref_axis.units!r}, result {cand_name} has "
                f"{cand_axis.units!r}"
            )
    if ref_snap.source != cand_snap.source:
        out.append(
            f"source image {image_id!r}: calibration provenance differs — reference "
            f"{ref_name} has {ref_snap.source!r}, result {cand_name} has "
            f"{cand_snap.source!r}"
        )
    return out


def _snapshots_by_image(record: ResultRecord) -> dict[str, CalibrationSnapshot]:
    """Snapshots keyed by image id, in record order; a repeat keeps the first."""
    by_image: dict[str, CalibrationSnapshot] = {}
    for snap in record.calibration:
        by_image.setdefault(snap.image_id, snap)
    return by_image


def calibration_agreement(reference: ResultRecord, candidate: ResultRecord) -> CalibrationAgreement:
    """Compare two records' source-calibration snapshots (ADR 0004 §5).

    Never a rejection reason — `differences` are notes. The outputs carry
    their own units, so records taken at different pixel sizes stay
    comparable; the caller just needs to be able to say so out loud.

    Deterministic: sources are visited in the reference's snapshot order,
    then each source's axes in index order, so `differences` is stable.
    """
    ref_snaps = _snapshots_by_image(reference)
    cand_snaps = _snapshots_by_image(candidate)
    ref_name, cand_name = record_name(reference), record_name(candidate)
    shared = tuple(image_id for image_id in ref_snaps if image_id in cand_snaps)
    differences: list[str] = []
    for image_id in shared:
        differences.extend(
            _axis_differences(
                image_id, ref_snaps[image_id], cand_snaps[image_id], ref_name, cand_name
            )
        )
    return CalibrationAgreement(
        reference_id=reference.id,
        candidate_id=candidate.id,
        shared_sources=shared,
        reference_only=tuple(i for i in ref_snaps if i not in cand_snaps),
        candidate_only=tuple(i for i in cand_snaps if i not in ref_snaps),
        differences=tuple(differences),
    )
