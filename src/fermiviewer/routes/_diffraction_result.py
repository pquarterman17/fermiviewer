"""1C result capture for `/api/diffraction/index` — the diffraction-indexing
adopter (roadmap item 1, ADR 0004 §3).

Lives beside the route rather than inside it because `routes/analysis.py`
sits at the 500-line god-module ceiling: the route keeps the `record` flag
and two call sites, every capture decision lives here (the same split
`routes/eds_quant.py` and `routes/structure_particles.py` already made).

Shape of the record, and why:

* the two big tables are **member-backed** — one matched reflection per
  spot per candidate, and one row per input spot, both of which grow with
  the pattern and must never inline into `manifest.json` (ADR 0004 §2);
* the `candidates` table is inline (at most `top_n` rows) and holds only
  SCALAR cells: the zone axis is split into `zone_u/v/w` columns rather
  than nesting a 3-vector in one cell, which the `{columns, units, rows}`
  table contract does not admit;
* the pattern centre is recorded as scalars in the FULL-image, 1-based
  frame `IndexedPattern` documents, so a reopened record can be laid back
  over its source image even when an ROI scoped the indexing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from fermiviewer.calc.diffraction_index import IndexedPattern
from fermiviewer.io.project_results import ResultOutput
from fermiviewer.result_capture import capture_result
from fermiviewer.session import store

if TYPE_CHECKING:  # the request model lives with the route it belongs to
    from fermiviewer.routes.analysis import IndexRequest

__all__ = ["capture_index", "capture_index_failure"]

ANALYSIS = "diffraction.index"

#: Inline candidate table. `zone_axis` is a 3-vector, and a table cell must
#: be a scalar, so it becomes three columns.
_CANDIDATE_COLUMNS = ("phase", "formula", "score", "n_matched", "zone_u", "zone_v", "zone_w")
_CANDIDATE_UNITS = ("", "", "", "", "", "", "")

#: Member-backed, one row per matched spot per candidate.
_REFLECTION_COLUMNS = (
    "candidate_index",
    "spot_index",
    "h",
    "k",
    "l",
    "measured_d",
    "ref_d",
)
_REFLECTION_UNITS = ("", "", "", "", "", "A", "A")

#: Member-backed, one row per input spot, in request order.
_SPOT_COLUMNS = ("row", "col", "measured_r")
_SPOT_UNITS = ("px", "px", "px")

#: The ROI conventions `calc/diffraction.apply_roi` / `roi_frame` actually
#: implement — recorded with the snapshot so a reopened record cannot be
#: re-read under a different one. rect crops `img[r0:r1, c0:c1]` (0-based,
#: r1/c1 exclusive); circle keeps pixels within `radius` of a 0-based
#: (cr, cc), the radius itself included.
_ROI_CONVENTIONS = {
    "rect": "0-based, half-open rect: rows [r0, r1), cols [c0, c1)",
    "circle": "0-based centre (cr, cc), radius in px, inclusive",
}
#: Which of `_Roi`'s fields each kind actually uses — the model defaults the
#: rest to 0, and snapshotting those would describe geometry no one asked for.
_ROI_FIELDS = {
    "rect": ("r0", "c0", "r1", "c1"),
    "circle": ("cr", "cc", "radius"),
}


def _label(req: IndexRequest) -> str:
    return f"Diffraction indexing of {store.name(req.image_id)}"


def _regions(req: IndexRequest) -> list[dict[str, Any]]:
    """The request's ROI as a compute-time geometry snapshot (ADR 0004 §6).

    The ROI arrives in the request body rather than as a stored region, so
    there is no `region_ids` link to make — the snapshot IS the record of
    what geometry produced these numbers.
    """
    if req.roi is None:
        return []
    roi = req.roi.model_dump()
    kind = str(roi.get("kind"))
    fields = _ROI_FIELDS.get(kind)
    snapshot: dict[str, Any] = {"kind": kind}
    if kind in _ROI_CONVENTIONS:
        snapshot["convention"] = _ROI_CONVENTIONS[kind]
    # An unrecognised kind never reaches a completed capture (`roi_frame`
    # refuses it upstream), but a failed one records what was asked for.
    for name in fields if fields is not None else sorted(roi):
        if name != "kind":
            snapshot[name] = roi[name]
    return [snapshot]


def _warnings(req: IndexRequest, pattern: IndexedPattern) -> list[str]:
    out = []
    if req.camera_length_mm is None:
        out.append(
            "No camera length: d-spacings come from the uncalibrated "
            "width-scaled branch (d = width x pixel_size / r), not the "
            "calibrated camera-length geometry (d = lambda L / r), so they "
            "are only as absolute as pixel_size_mm is."
        )
    if not any(c.n_matched for c in pattern.candidates):
        out.append(
            f"No candidate phase matched any spot within the relative "
            f"d tolerance of {req.tolerance}."
        )
    return out


def _reflection_rows(pattern: IndexedPattern) -> np.ndarray:
    """(M, 7) float64: every matched reflection, candidate-major.

    `candidate_index` indexes `candidates` (0-based) and `spot_index` is the
    candidate's own `matched_idx` — a 0-based index into the request's
    `spots`, so a stored row can be walked back to the pixel it came from.
    """
    rows = [
        [
            float(ci),
            float(idx),
            float(hkl[0]),
            float(hkl[1]),
            float(hkl[2]),
            float(measured),
            float(ref),
        ]
        for ci, cand in enumerate(pattern.candidates)
        for hkl, idx, measured, ref in zip(
            cand.matched_hkl,
            cand.matched_idx,
            cand.matched_d,
            cand.ref_d,
            strict=True,
        )
    ]
    return np.array(rows, dtype=np.float64).reshape(len(rows), len(_REFLECTION_COLUMNS))


def _spot_rows(req: IndexRequest, pattern: IndexedPattern) -> np.ndarray:
    """(N, 3) float64: the input spots, in request order, with the radius
    each contributed — full-image 1-based (row, col), per `IndexedPattern`."""
    rows = [
        [float(row), float(col), float(radius)]
        for (row, col), radius in zip(req.spots, pattern.measured_r, strict=True)
    ]
    return np.array(rows, dtype=np.float64).reshape(len(rows), len(_SPOT_COLUMNS))


def _outputs(req: IndexRequest, pattern: IndexedPattern) -> list[ResultOutput]:
    center_row, center_col = pattern.center
    convention = "1-based (row, col), full image — the overlay frame, not the ROI's"
    return [
        ResultOutput(
            kind="scalar",
            name="n_spots",
            data={"value": len(req.spots), "unit": ""},
        ),
        ResultOutput(
            kind="scalar",
            name="center_row",
            data={"value": int(center_row), "unit": "px", "convention": convention},
        ),
        ResultOutput(
            kind="scalar",
            name="center_col",
            data={"value": int(center_col), "unit": "px", "convention": convention},
        ),
        ResultOutput(
            kind="table",
            name="candidates",
            data={
                "columns": list(_CANDIDATE_COLUMNS),
                "units": list(_CANDIDATE_UNITS),
                # inline: at most `top_n` rows, and every cell a scalar —
                # the zone axis is split across zone_u/zone_v/zone_w
                "rows": [
                    [
                        c.phase_name,
                        c.formula,
                        float(c.score),
                        int(c.n_matched),
                        *(float(v) for v in c.zone_axis),
                    ]
                    for c in pattern.candidates
                ],
            },
        ),
        ResultOutput(
            kind="table",
            name="matched_reflections",
            data={
                "columns": list(_REFLECTION_COLUMNS),
                "units": list(_REFLECTION_UNITS),
                "index_convention": (
                    "candidate_index indexes the candidates table (0-based); "
                    "spot_index indexes the request spots (0-based)"
                ),
            },
            array=_reflection_rows(pattern),
        ),
        ResultOutput(
            kind="table",
            name="spots",
            data={
                "columns": list(_SPOT_COLUMNS),
                "units": list(_SPOT_UNITS),
                "coordinate_convention": (
                    "(row, col), 1-based, full image; measured_r is px from "
                    "the full-image centre"
                ),
                "row_order": "one row per input spot, in request order",
            },
            array=_spot_rows(req, pattern),
        ),
    ]


def capture_index(req: IndexRequest, pattern: IndexedPattern) -> dict[str, str]:
    """Persist this indexing run and return the response's `result` stub."""
    record = capture_result(
        analysis=ANALYSIS,
        label=_label(req),
        source_ids=[req.image_id],
        # the reproduction key, defaults filled — never the capture toggle
        params=req.model_dump(exclude={"record"}),
        outputs=_outputs(req, pattern),
        regions=_regions(req),
        warnings=_warnings(req, pattern),
    )
    return {"id": record.id, "created_at": record.created_at}


def capture_index_failure(req: IndexRequest, error: str) -> None:
    """Record a COMPUTATION failure (the 1B contract's failed-state rule).

    Reached only from the `value_error_as_422()` conversion — a degenerate
    or out-of-image ROI, or spots that are not an (N, 2) array. The unknown
    image id `_get` rejects is request validation, so it never lands here.
    """
    capture_result(
        analysis=ANALYSIS,
        label=_label(req),
        source_ids=[req.image_id],
        params=req.model_dump(exclude={"record"}),
        regions=_regions(req),
        status="failed",
        error=error,
    )
