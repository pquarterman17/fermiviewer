"""Trained (scribble-taught) grain segmentation — `train_segment` and
`train_preview`.

Split out of `catalogue_grains_edit` when 4C-3 pushed that module past the
500-line ratchet. The two ops share their whole front half — rasterize the
strokes, scope them, fit a model — so they belong together and apart from
the label-editing op they used to sit beside.

The envelope helpers stay in `catalogue_grains_edit` and are imported
here, following `catalogue_montage`'s use of `catalogue_stack`: one
definition of a grain-report envelope is worth more than a tidy
dependency graph, since two copies drift.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.grain_report import grain_report
from fermiviewer.calc.grains_trained import (
    confidence_summary,
    preview_trained,
    rasterize_strokes,
    segment_trained,
    train_from_scribbles,
)
from fermiviewer.calc.raster import raster_of
from fermiviewer.calc.region_segment import place_labels, place_values
from fermiviewer.calc.roi import extract_rect_roi, roi_slices
from fermiviewer.datastruct import DataStruct
from fermiviewer.ops._envelopes import output, scalar
from fermiviewer.ops._parsing import pixel_cal as _px_cal
from fermiviewer.ops._region_param import (
    LABEL_CONTEXT_BBOX,
    LABEL_CONTEXT_EXACT,
    REGION_PARAM,
    ScopedRegion,
    region_output,
    scope_from_params,
)
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.catalogue_grains_edit import (
    _BOUNDARY_CLASS_PARAM,
    _CLASSIFIER_PARAM,
    _CONFIDENCE_THRESHOLD,
    _GRADIENT_SIGMA_PARAM,
    _ROI_PARAM,
    _SCALES_PARAM,
    _STROKES_PARAM,
    _flat,
    _grain_outputs,
    _roi_text,
)
from fermiviewer.ops.registry import register

__all__: list[str] = []


# ── the trained pair's shared front half ──────────────────────────────


def _train(
    ds: DataStruct, params: dict[str, Any]
) -> tuple[np.ndarray, ScopedRegion | None, Any]:
    """(full-image raster, scope, fitted model) — the block both trained
    routes run verbatim before they diverge: rasterize the strokes over the
    WHOLE image, then slice both raster and mask to the scope's rect so the
    stroke coordinates stay in full-image space.

    A stroke OUTSIDE an irregular region is dropped rather than trained on.
    A stroke is a claim about the specimen the user is analyzing, and the
    region says which specimen that is; letting a stroke the region
    excludes still shape the classifier would make the region mean
    something different for the model than it means for the labels.
    """
    raster = raster_of(ds)
    h, w = raster.shape
    label_mask = rasterize_strokes((h, w), list(params["strokes"]))
    scoped = scope_from_params(params, raster.shape)
    rect = scoped.rect if scoped is not None else None
    rows, cols = roi_slices(raster.shape, rect)
    analysis_raster = extract_rect_roi(raster, rect)
    analysis_mask = label_mask[rows, cols]
    if scoped is not None and scoped.mask is not None:
        analysis_mask = np.where(scoped.mask[rows, cols], analysis_mask, 0)
    scales = tuple(float(s) for s in _flat(params["scales"])) or (2.0, 4.0)
    model = train_from_scribbles(
        analysis_raster,
        analysis_mask,
        scales=scales,
        gradient_sigma=params["gradient_sigma"],
        classifier=params["classifier"],
    )
    return raster, scoped, model


# ── train_segment ─────────────────────────────────────────────────────


def _train_segment(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster, scoped, model = _train(ds, params)
    rect = scoped.rect if scoped is not None else None
    seg = segment_trained(
        extract_rect_roi(raster, rect),
        model,
        boundary_class=tuple(_flat(params["boundary_class"])),
        min_area=params["min_area"],
    )
    if seg.n_grains == 0:
        # the route's 422, kept because it IS part of the composition: an
        # all-background label map is not a segmentation a caller can use
        raise ValueError("no grains found — paint more strokes or lower min area")
    labels, _ = place_labels(
        seg.labels,
        raster.shape,
        rect,
        scoped.mask if scoped is not None else None,
    )
    px, unit = _px_cal(ds)
    report = grain_report(
        labels, np.asarray(raster, dtype=np.float64), pixel_size=px, unit=unit
    )
    outputs = _grain_outputs(
        report,
        "0 = background/boundary class; values are grain labels "
        "(table rows, ascending)",
        {"method": "trained", "roi": _roi_text(rect)},
    )
    if scoped is not None:
        outputs.append(
            region_output(
                scoped,
                label_context=(
                    LABEL_CONTEXT_EXACT if scoped.mask is None else LABEL_CONTEXT_BBOX
                ),
            )
        )
    return OpResult(
        op="train_segment",
        params=params,
        label=f"scribble-trained grains ({report.n_grains} grains)",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="train_segment",
        category="structure",
        produces_value=True,
        summary="Scribble-trained grain segmentation: fit a pixel classifier "
        "on painted strokes, label connected components per class, and "
        "report the same morphometrics as `grains` "
        "(calc/grains_trained + calc/grain_report)",
        params={
            "strokes": _STROKES_PARAM,
            "roi": _ROI_PARAM,
            "region": REGION_PARAM,
            "scales": _SCALES_PARAM,
            "gradient_sigma": _GRADIENT_SIGMA_PARAM,
            "min_area": OpParam(
                int, 25, minimum=0,
                doc="drop connected components smaller than this (px) — "
                "train_segment only; the preview labels no grains",
            ),
            "boundary_class": _BOUNDARY_CLASS_PARAM,
            "classifier": _CLASSIFIER_PARAM,
        },
        fn=_train_segment,
    )
)


# ── train_preview ─────────────────────────────────────────────────────


def _train_preview(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    """The non-committing half: classify every pixel and report where the
    paint generalizes, WITHOUT labelling grains. Two rasters come back, one
    more than `OpResult.derived` holds, so both inline as `map` envelopes
    (the wave-B standing rule) while the route registers session images."""
    raster, scoped, model = _train(ds, params)
    rect = scoped.rect if scoped is not None else None
    region_mask = scoped.mask if scoped is not None else None
    prev = preview_trained(extract_rect_roi(raster, rect), model)
    boundary = {int(b) for b in _flat(params["boundary_class"])}
    # place_values, NOT place_labels: these are class ids and
    # probabilities, so renumbering survivors would relabel the specimen
    class_map = place_values(prev.class_map, raster.shape, rect, region_mask)
    confidence_map = place_values(prev.max_prob, raster.shape, rect, region_mask)
    mean_confidence, low_confidence_fraction = confidence_summary(
        prev.max_prob, threshold=_CONFIDENCE_THRESHOLD
    )
    outputs = [
        output(
            "table",
            "classes",
            {
                "columns": ["class_id", "fraction", "is_boundary"],
                "units": ["", "", ""],
                "rows": [
                    [int(c), prev.fractions[int(c)], int(c) in boundary]
                    for c in prev.classes
                ],
            },
        ),
        scalar("mean_confidence", mean_confidence),
        scalar("low_confidence_fraction", low_confidence_fraction),
        scalar("confidence_threshold", _CONFIDENCE_THRESHOLD),
        output(
            "map",
            "class_map",
            {
                "values": class_map.tolist(),
                "convention": "predicted class id per pixel; 0 outside the ROI",
                "roi": _roi_text(rect),
            },
        ),
        output(
            "map",
            "confidence_map",
            {
                "values": confidence_map.tolist(),
                "convention": "winning-class probability per pixel (0..1); "
                "0 outside the ROI",
                "roi": _roi_text(rect),
            },
        ),
    ]
    return OpResult(
        op="train_preview",
        params=params,
        label=f"trained-classifier preview ({len(prev.classes)} classes)",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="train_preview",
        category="structure",
        produces_value=True,
        summary="Non-committing preview of the scribble-trained classifier: "
        "per-pixel class + confidence rasters and the class composition, "
        "with no grain labelling — shows where the paint generalizes "
        "before train_segment commits (calc/grains_trained."
        "preview_trained + confidence_summary)",
        params={
            "strokes": _STROKES_PARAM,
            "roi": _ROI_PARAM,
            "region": REGION_PARAM,
            "scales": _SCALES_PARAM,
            "gradient_sigma": _GRADIENT_SIGMA_PARAM,
            # NOTE: no min_area — the preview labels no connected
            # components, so its route model deliberately omits the field
            "boundary_class": _BOUNDARY_CLASS_PARAM,
            "classifier": _CLASSIFIER_PARAM,
        },
        fn=_train_preview,
    )
)
