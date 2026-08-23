"""EFD similarity ranking over a particle-label image — the composition
behind POST /analyze/efd-similarity, lifted out of `routes/shape_id.py`
(wave A, ADR 0005 §1) so the registered `efd_similarity` op and the HTTP
route run the SAME trace → describe → rank loop.

Skip-and-note, not fail-the-query: one tiny speck that cannot support the
harmonic count must not kill ranking across hundreds of good particles;
undescribable regions land in `skipped` with the reason. The ONE region
that cannot be skipped is the reference itself — with no reference
descriptor there is nothing to rank against, so that raises ValueError
naming the region (the route maps it to 422).

The `reason` strings are built HERE from request-known quantities, never
from exception text — CodeQL (py/stack-trace-exposure) treats
exception-derived strings in responses as information exposure, and a
static message is equally informative: the only two failure modes are an
untraceable mask and a ring too small for the harmonic count.

Contour tracing passes `tolerance=0` — NO simplification — unlike
`trace_outer_contour`'s own default (2.0px, the hand-correction outline
target, a different job): Douglas-Peucker collapses straight edges to
their endpoints at ANY tolerance, so a plain square particle came back as
4 corner vertices and could not clear `calc/efd.py`'s harmonic point
floor. EFD's own harmonic truncation IS its smoothing; the raw
marching-squares ring is its honest input. The vertex cap stays as the
decimation safety net for enormous regions only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.contours import NoContourError, trace_outer_contour
from fermiviewer.calc.efd import (
    DEFAULT_N_HARMONICS,
    EfdDescriptor,
    efd_descriptor,
    efd_distance,
)

__all__ = ["EFD_TRACE_MAX_VERTICES", "EFD_TRACE_TOLERANCE", "EfdRanking", "rank_by_efd"]

# See module docstring: tolerance 0 = the raw marching-squares ring; the
# vertex cap is the safety net for enormous regions only.
EFD_TRACE_TOLERANCE = 0.0
EFD_TRACE_MAX_VERTICES = 2000


@dataclass(frozen=True)
class EfdRanking:
    """`ranked`: every describable region as `{"id", "distance"}`, ascending
    EFD distance to the reference (the reference itself ranks first at 0).
    `skipped`: undescribable regions as `{"id", "reason"}`."""

    ranked: list[dict]
    skipped: list[dict]


def rank_by_efd(
    labels: np.ndarray,
    ids: Sequence[int],
    ref_id: int,
    *,
    n_harmonics: int = DEFAULT_N_HARMONICS,
) -> EfdRanking:
    """Rank every labelled region by EFD distance to region `ref_id`."""
    if ref_id not in set(ids):
        raise ValueError(f"unknown ref_id: {ref_id}")
    descriptors: dict[int, EfdDescriptor] = {}
    skipped: list[dict] = []
    for pid in ids:
        mask = labels == pid
        try:
            contour = trace_outer_contour(
                mask,
                tolerance=EFD_TRACE_TOLERANCE,
                max_vertices=EFD_TRACE_MAX_VERTICES,
            )
        except NoContourError:
            reason = "no traceable outer contour"
            contour = None
        if contour is not None:
            try:
                descriptors[pid] = efd_descriptor(contour.points, n_harmonics=n_harmonics)
                continue
            except ValueError:
                reason = f"contour cannot support {n_harmonics} harmonics"
        if pid == ref_id:
            raise ValueError(
                f"reference region {pid} cannot be described ({reason}) — nothing to rank against"
            )
        skipped.append({"id": pid, "reason": reason})

    ref_descriptor = descriptors[ref_id]
    ranked = sorted(
        (
            {"id": pid, "distance": efd_distance(ref_descriptor, d)}
            for pid, d in descriptors.items()
        ),
        key=lambda r: r["distance"],
    )
    return EfdRanking(ranked=ranked, skipped=skipped)
