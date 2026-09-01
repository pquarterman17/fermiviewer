"""Grain-edit and scribble-trained grain ops — the three endpoints the
grains domain still owed after the contract re-opening (ADR 0005 §8/§9):
/api/grains/edit, /api/grains/train-segment and /api/grains/train-preview.

Kept out of ``catalogue_grains_layers.py`` (395 lines) so neither module
grows past the 500-line ceiling — the ``catalogue_analysis.py`` split
precedent; the category stays ``structure``, the one wave-A opened, and
every op sets ``produces_value=True`` explicitly because that category
does not imply a value result.

What the re-opened contract buys each op:

- ``grains_edit`` is the §8 case: it edits a grain-LABEL map, but the
  split watershed needs the INTENSITY image that map was derived from.
  The route recovers that id from ``metadata["grain_source"]`` and looks
  it up in the session store; a pure op cannot, so the label map is the
  subject and the image arrives as the named ``source`` input.
- ``train_segment``/``train_preview`` are the §9 RECORD case: ``strokes``
  is a list of ``{class_id, radius, points}`` where ``points`` is itself a
  coordinate-pair row list. That parameter — not the two preview maps —
  is what bounced these two in wave A (the wave-B addendum's
  clarification).

Every op runs the SAME composition its route runs (§1):
``calc.grain_edit.edit_grains`` + ``calc.grain_report.grain_report`` for
the edit, and ``rasterize_strokes`` -> ``train_from_scribbles`` ->
``segment_trained``/``preview_trained`` (+ ``confidence_summary``) for the
trained pair, with ``calc.roi`` doing the ROI extract/embed either side.
No numerics live here.

Every op inlines its rasters as ``map`` envelopes in ``value`` while the
route registers session images — the wave-A ``grains`` precedent, and the
wave-B standing rule for ``train_preview``, whose TWO rasters exceed what
``OpResult.derived`` can hold.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from fermiviewer.calc.grain_edit import edit_grains
from fermiviewer.calc.grain_report import GrainReport, grain_report
from fermiviewer.calc.raster import raster_of
from fermiviewer.calc.roi import RectRoi
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.ops._envelopes import nan_none as _nn
from fermiviewer.ops._envelopes import output, scalar
from fermiviewer.ops._parsing import parse_roi_param
from fermiviewer.ops._parsing import pixel_cal as _px_cal
from fermiviewer.ops.base import OpInput, OpParam, OpResult, OpSpec, RecordSpec, RowSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []

#: kinds ``raster_of`` can reduce to a 2-D raster (a spectrum image sums to
#: its raster) — the ``catalogue_stack`` spelling, reused for ``source``.
_RASTER_KINDS = (DataKind.IMAGE, DataKind.RGB_IMAGE, DataKind.SPECTRUM_IMAGE)

#: Probability below which a preview pixel counts as "uncertain". Mirrors
#: ``routes/grains_trained._CONFIDENCE_THRESHOLD`` — the routes module is
#: not importable from the pure layer, so the value is restated here and
#: emitted alongside the two summary numbers (as the route does) so a
#: consumer never has to assume which threshold they were measured at.
_CONFIDENCE_THRESHOLD = 0.6

#: The route's ``roi`` field is a real ``tuple[int, int, int, int] | None``;
#: the op takes the frozen ``"r1,c1,r2,c2"`` string every other ROI-scoped
#: op already spells (§4's shipped compromise, NOT a new flattening — §9
#: freezes the existing CSV params rather than migrating them).
_ROI_PARAM = OpParam(
    str, "", doc="'r1,c1,r2,c2' 1-based inclusive rectangle; empty = whole image"
)

#: ``strokes``: the §9 record list. One level deep — a record whose
#: ``points`` field is itself a (x, y) row list — which is exactly the
#: depth ``RecordSpec`` allows and all this endpoint pair needs.
_STROKES_PARAM = OpParam(
    list,
    required=True,
    record=RecordSpec(
        fields={
            "class_id": OpParam(
                int,
                required=True,
                minimum=1,
                maximum=16,
                doc="painted class (1..16); which ones are boundary/background "
                "is declared separately by boundary_class",
            ),
            "radius": OpParam(
                float, 4.0, minimum=0.5, maximum=200.0, doc="brush radius (px)"
            ),
            "points": OpParam(
                list,
                required=True,
                row=RowSpec(width=2, columns=("x", "y")),
                doc="the painted polyline, 0-based (x, y) image px — note "
                "(x, y), unlike diffraction_index's 1-based (row, col)",
            ),
        },
        min_rows=1,
    ),
    doc="painted class scribbles; the classifier needs >= 2 distinct "
    "class_ids among them (calc enforces that)",
)

#: A flat list of scalars is spelled as width-1 rows: ``[[2.0], [4.0]]``.
#: §9 says a new list param takes the native list shape and explicitly
#: forbids minting a NEW CSV flattening, and ``RowSpec`` is the only native
#: list vocabulary the contract has — so the one-column row is the shape,
#: even though it costs one bracket pair against the route's ``[2.0, 4.0]``.
_SCALES_PARAM = OpParam(
    list,
    default=((2.0,), (4.0,)),
    row=RowSpec(width=1, columns=("scale",), item_type=float),
    minimum=0.0,
    doc="feature-stack smoothing scales (px), one per row: [[2],[4]]; "
    "empty falls back to the (2, 4) default, as in the route",
)

_BOUNDARY_CLASS_PARAM = OpParam(
    list,
    default=(),
    row=RowSpec(width=1, columns=("class_id",), item_type=int),
    doc="class id(s) painted on grain boundaries / background, one per row: [[1]]",
)

_GRADIENT_SIGMA_PARAM = OpParam(
    float, 0.0, minimum=0.0, maximum=10.0,
    doc="extra gradient-magnitude feature sigma (px); 0 disables it",
)

_CLASSIFIER_PARAM = OpParam(
    str, "softmax", choices=("softmax", "forest"),
    doc="'softmax' is the linear ported path; 'forest' is the nonlinear "
    "random forest, for texture classes that are not linearly separable",
)


def _flat(rows: Any) -> list[Any]:
    """A width-1 row list back to the flat sequence the calc functions take."""
    return [row[0] for row in rows]


def _grain_outputs(
    report: GrainReport, labels_convention: str, map_extra: dict[str, Any]
) -> list[dict[str, Any]]:
    """A `GrainReport` as ADR 0004 envelopes — the wave-A `grains` op's
    payload shape, shared here by the two ops whose routes both call
    `routes/structure_grains._grains_payload`. Numbers come straight from
    `calc.grain_report`, so op and route cannot disagree."""
    unit = report.unit
    outputs = [
        scalar("n_grains", report.n_grains),
        scalar("boundary_network_px", report.boundary_network_px, unit="px"),
        scalar("n_boundary_segments", report.n_boundary_segments),
        scalar("n_triple_junctions", report.n_triple_junctions),
        scalar("mean_diameter_px", report.mean_diameter_px, unit="px"),
    ]
    # calibrated aggregates: absent — not null — when uncalibrated
    if math.isfinite(report.boundary_network_calibrated):
        outputs.append(
            scalar(
                "boundary_network_calibrated",
                report.boundary_network_calibrated,
                unit=unit,
            )
        )
    if math.isfinite(report.astm_grain_size):
        outputs.append(scalar("astm_grain_size", report.astm_grain_size))
    outputs.append(
        output(
            "table",
            "grains",
            {
                "columns": [
                    "area_px",
                    "perimeter_crofton_px",
                    "eccentricity",
                    "equiv_diameter_px",
                    "diameter_calibrated",
                ],
                "units": ["px^2", "px", "", "px", unit],
                "rows": [
                    [float(a), float(p), float(e), float(d), _nn(float(dc))]
                    for a, p, e, d, dc in zip(
                        report.area_px,
                        report.perimeter_crofton_px,
                        report.eccentricity,
                        report.equiv_diameter_px,
                        report.diameter_calibrated,
                        strict=True,
                    )
                ],
            },
        )
    )
    outputs.append(
        output(
            "map",
            "labels",
            {"values": report.labels.tolist(), "convention": labels_convention}
            | map_extra,
        )
    )
    return outputs


def _roi_text(roi: RectRoi | None) -> str:
    """The resolved ROI back as the op's own param spelling, so a caller can
    feed it straight into the NEXT `grains_edit` — the carry-forward the
    route does through `metadata["grain_roi"]`, which a pure op has no
    metadata chain to reach."""
    return ",".join(str(int(v)) for v in roi) if roi is not None else ""


# ── grains_edit ───────────────────────────────────────────────────────


def _grains_edit(
    ds: DataStruct, params: dict[str, Any], inputs: dict[str, Any]
) -> OpResult:
    """The subject is the LABEL map being edited (the route's `labels_id`) —
    the thing the edit mutates and the provenance parent. The intensity
    image the split watershed needs arrives as the `source` input, because
    the route reaches it through `metadata["grain_source"]` + a store
    lookup and `ops/` may not read the store (§8)."""
    if ds.kind is not DataKind.IMAGE:
        # the route's own precondition ("labels_id must be an editable
        # grain-label map", a 400). `_RASTER_KINDS` is right for the SOURCE
        # input — `raster_of` reduces a cube or an RGB frame to a raster —
        # but a label map is not reducible: summing a 3-D subject would
        # invent label ids that were never segmented.
        raise ValueError("the subject must be a grain-label map (a 2-D image)")
    source_ds: DataStruct = inputs["source"]
    raster = raster_of(source_ds)
    edit = edit_grains(
        np.asarray(ds.data, dtype=np.int64),
        raster,
        params["op"],
        [(float(x), float(y)) for x, y in params["points"]],
        granularity=params["granularity"],
    )
    # calibration comes from the SOURCE image, as in the route
    # (`_grains_payload(..., source_ds, ...)`); a label map registered by
    # /analyze/grains inherits exactly these axes, so the two agree.
    px, unit = _px_cal(source_ds)
    report = grain_report(edit.labels, raster, pixel_size=px,
        pixel_area=ds.pixel_area, unit=unit)
    outputs = _grain_outputs(
        report,
        "0 = background; values are grain labels (table rows, ascending)",
        {
            "method": edit.op,
            "roi": _roi_text(parse_roi_param(params["roi"])),
        },
    )
    return OpResult(
        op="grains_edit",
        params=params,
        label=f"grain {edit.op} edit ({report.n_grains} grains)",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="grains_edit",
        category="structure",
        produces_value=True,
        summary="Interactive merge/split of a grain-label map at clicked "
        "points, re-enforcing connectivity and re-measuring the "
        "morphometrics (calc/grain_edit.edit_grains + "
        "calc/grain_report.grain_report)",
        params={
            "op": OpParam(
                str,
                required=True,
                choices=("merge", "split"),
                doc="'merge' fuses every distinct grain under the points "
                "(needs >= 2 of them); 'split' watersheds the grain under "
                "the FIRST point",
            ),
            "points": OpParam(
                list,
                required=True,
                row=RowSpec(width=2, columns=("x", "y"), min_rows=1),
                doc="clicks in 0-BASED (x, y) image px — note (x, y) and "
                "0-based, the OPPOSITE of diffraction_index's 1-based "
                "(row, col); order matters, split acts on the first click "
                "that lands inside the image",
            ),
            "granularity": OpParam(
                float, 0.03, minimum=0.0, maximum=1.0,
                doc="split watershed granularity (unused by merge)",
            ),
            "roi": OpParam(
                str,
                "",
                doc="the rectangle the label map was segmented in, "
                "'r1,c1,r2,c2' 1-based inclusive; carried through to the "
                "result map so a follow-up edit can pass it back (the route "
                "carries it in metadata['grain_roi'], which a pure op has "
                "no chain to read)",
            ),
        },
        inputs={
            "source": OpInput(
                doc="the intensity image the label map was segmented from "
                "(the route's metadata['grain_source']); the split watershed "
                "runs on it, and its calibration measures the grains",
                required=True,
                kinds=_RASTER_KINDS,
            ),
        },
        fn=_grains_edit,
    )
)
