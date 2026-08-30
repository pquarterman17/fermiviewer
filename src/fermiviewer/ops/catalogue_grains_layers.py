"""Grains & layers operation catalogue — that half of wave A (roadmap 3B,
matching the audit's "Grains & layers" domain): batch/scripting reach for
/analyze/grains, /analyze/layers and /analyze/layers/edit. Kept out of
``catalogue_structure.py`` so neither module grows past the 500-line
ceiling (the ``catalogue_analysis.py`` split precedent); the category is
still ``structure`` — one new category per wave (ADR 0005 §2).

Every op calls the SAME composition its route calls: `grains` runs
`calc.grains.segment_auto`/`segment_watershed` +
`calc.grain_report.grain_report` (the synchronous computation behind the
job-backed route, ADR 0005 §6); the layer ops run
`calc.layers.analyze_layers` / `recompute_layers`, then
`calc.layers_report.layer_result_to_dict` (the wave-A lift of the
roughness metrology + payload shaping that used to live in
`routes/layers.py`) — reshaped into ADR 0004 envelopes per ADR 0005 §5.
`positions` flattens to a CSV float list on `distribution_fit`'s
``values`` precedent; `roi` is the established ``"r1,c1,r2,c2"`` string.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from fermiviewer.calc.grain_report import grain_report
from fermiviewer.calc.grains import (
    GrainSegmentation,
    WatershedSegmentation,
    segment_auto,
    segment_watershed,
)
from fermiviewer.calc.layers import LayerResult, analyze_layers, recompute_layers
from fermiviewer.calc.layers_report import layer_result_to_dict
from fermiviewer.calc.raster import raster_of
from fermiviewer.calc.region_segment import place_labels
from fermiviewer.calc.roi import extract_rect_roi
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.ops._envelopes import nan_none as _nn
from fermiviewer.ops._envelopes import output, scalar
from fermiviewer.ops._parsing import parse_roi_param, split_csv
from fermiviewer.ops._parsing import pixel_cal as _px_cal
from fermiviewer.ops._region_param import (
    LABEL_CONTEXT_BBOX,
    LABEL_CONTEXT_EXACT,
    REGION_PARAM,
    region_output,
    scope_from_params,
)
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


def _image_cal(ds: DataStruct) -> tuple[float, str]:
    """The layer routes' calibration idiom: fall back to 1.0 px when the
    image carries no usable spatial calibration."""
    if ds.kind is not DataKind.IMAGE:
        raise ValueError("layer analysis needs a 2-D image — derive a map from a cube first")
    px = ds.pixel_size
    unit = ds.pixel_unit
    if not np.isfinite(px) or px <= 0:
        return 1.0, "px"
    return px, unit


def _layer_outputs(res: LayerResult) -> list[dict[str, Any]]:
    """A `LayerResult` as ADR 0004 envelopes. Numbers come straight from
    `layer_result_to_dict` — the route payload — so op and route cannot
    disagree; this only regroups that dict into typed outputs."""
    report = layer_result_to_dict(res)
    unit = report["unit"]
    outputs: list[dict[str, Any]] = []
    # absent — not null — when the estimator had nothing to say
    if report["tilt_deg"] is not None:
        outputs.append(scalar("tilt_deg", report["tilt_deg"], unit="deg"))
    if report["coherence"] is not None:
        outputs.append(scalar("coherence", report["coherence"]))
    outputs.append(
        output(
            "curve",
            "depth_profile",
            {
                "x_name": "depth",
                "x_unit": "px",
                "y_name": "intensity",
                "y_unit": "",
                "x": report["depth_pos"],
                "y": report["depth_profile"],
                "axis": report["axis"],
                "layers_horizontal": report["layers_horizontal"],
                "pixel_size": report["pixel_size"],
                "pixel_unit": unit,
            },
        )
    )
    outputs.append(
        output(
            "table",
            "layers",
            {
                "columns": ["index", "top", "bottom", "thickness", "thickness_std", "conformality"],
                "units": ["", "px", "px", unit, unit, ""],
                "rows": [
                    [
                        lyr["index"],
                        lyr["top"],
                        lyr["bottom"],
                        lyr["thickness"],
                        lyr["thickness_std"],
                        lyr["conformality"],
                    ]
                    for lyr in report["layers"]
                ],
            },
        )
    )
    for k, interface in enumerate(report["interfaces"]):
        outputs.append(
            output(
                "fit",
                f"interface_{k}",
                {
                    "model": "erf",
                    "coefficients": {
                        "position": interface["position"],
                        "sigma_erf": interface["sigma_erf"],
                        "sigma_w": interface["sigma_w"],
                    },
                    "r_squared": interface["r_squared"],
                    "position_unit": "px (profile depth)",
                    "sigma_unit": unit,
                    "trace": interface["trace"],
                    "roughness": interface["roughness"],
                },
            )
        )
    return outputs


def _layers(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    px, unit = _image_cal(ds)
    res = analyze_layers(
        ds.data,
        roi=parse_roi_param(params["roi"]),
        axis=params["axis"],
        sensitivity=params["sensitivity"],
        n_layers=params["n_layers"],
        reduce=params["reduce"],
        pixel_size=px,
        unit=unit,
        fit_window=params["fit_window"],
        waviness=params["waviness"],
        trace_window=params["trace_window"],
        modality=params["modality"],
        destripe_fib=params["destripe"],
    )
    return OpResult(
        op="layers",
        params=params,
        label="cross-section layer analysis",
        value={"outputs": _layer_outputs(res)},
    )


#: Shared by `layers` and `layers_edit` — the fields both routes carry with
#: identical meaning (LayersRequest / LayersEditRequest).
_COMMON_LAYER_PARAMS = {
    "roi": OpParam(
        str, "", doc="'r1,c1,r2,c2' 1-based inclusive analysis rectangle; empty = whole image"
    ),
    "reduce": OpParam(
        str,
        "mean",
        choices=("mean", "sum", "median"),
        doc="profile collapse (median is robust to streaks)",
    ),
    "fit_window": OpParam(int, 15, doc="erf-refinement window (profile px)"),
    "waviness": OpParam(
        bool, False, doc="trace each interface laterally (enables the roughness metrology and σ_w)"
    ),
    "trace_window": OpParam(int, 10, doc="per-column edge-search half-window (px)"),
    "destripe": OpParam(bool, False, doc="FFT notch out FIB curtaining first"),
}

register(
    OpSpec(
        name="layers",
        category="structure",
        produces_value=True,
        summary="Cross-section layer stack: auto-orient, depth profile, detect + "
        "erf-refine interfaces, thicknesses, σ_erf and (with waviness) the "
        "full roughness metrology (calc/layers.analyze_layers + "
        "calc/layers_report)",
        params={
            "axis": OpParam(
                str,
                "auto",
                choices=("auto", "y", "x"),
                doc="depth axis; auto detects from the image",
            ),
            "sensitivity": OpParam(float, 0.3, doc="interface detection sensitivity"),
            "n_layers": OpParam(int, 0, doc="expected layer count; 0 = auto"),
            "modality": OpParam(
                str,
                "haadf",
                choices=("haadf", "eels", "bf", "df"),
                doc="imaging modality (sets detection heuristics)",
            ),
            **_COMMON_LAYER_PARAMS,
        },
        fn=_layers,
    )
)


def _layers_edit(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    px, unit = _image_cal(ds)
    positions = [float(v) for v in split_csv(params["positions"])]
    res = recompute_layers(
        ds.data,
        positions,
        axis=params["axis"],
        roi=parse_roi_param(params["roi"]),
        reduce=params["reduce"],
        pixel_size=px,
        unit=unit,
        fit_window=params["fit_window"],
        waviness=params["waviness"],
        trace_window=params["trace_window"],
        destripe_fib=params["destripe"],
    )
    return OpResult(
        op="layers_edit",
        params=params,
        label="layer re-measure from edited interfaces",
        value={"outputs": _layer_outputs(res)},
    )


register(
    OpSpec(
        name="layers_edit",
        category="structure",
        produces_value=True,
        summary="Re-measure the layer stack from a user-edited interface list — "
        "no detection (calc/layers.recompute_layers + calc/layers_report)",
        params={
            "positions": OpParam(
                str,
                required=True,
                doc="comma-separated interface depths in profile pixels, e.g. '12.5,40,77.2'",
            ),
            "axis": OpParam(
                str, "y", choices=("y", "x"), doc="depth axis — editing assumes a known axis"
            ),
            **_COMMON_LAYER_PARAMS,
        },
        fn=_layers_edit,
    )
)


# ── grains ────────────────────────────────────────────────────────────


def _grains(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    scoped = scope_from_params(params, raster.shape)
    analysis_raster = (
        extract_rect_roi(raster, scoped.rect) if scoped is not None else raster
    )
    seg: GrainSegmentation | WatershedSegmentation
    if params["method"] == "kmeans":
        seg = segment_auto(
            analysis_raster,
            k=params["k"],
            min_area=params["min_area"],
            seed=params["seed"],
            replicates=params["replicates"],
        )
    else:
        seg = segment_watershed(
            analysis_raster,
            method=params["method"],
            granularity=params["granularity"],
            compactness=params["compactness"],
            min_area=params["min_area"],
            n_superpixels=params["n_superpixels"],
            merge_threshold=params["merge_threshold"],
            orientation_sigma=params["orientation_sigma"],
            denoise_sigma=params["denoise_sigma"],
            robust=params["robust"],
        )
    # The report is derived from these labels, so clipping BEFORE it runs
    # is what keeps the table, the boundary network and the map describing
    # one segmentation rather than three.
    labels = (
        place_labels(seg.labels, raster.shape, scoped.rect, scoped.mask)[0]
        if scoped is not None
        else seg.labels
    )
    px, unit = _px_cal(ds)
    report = grain_report(labels, raster, pixel_size=px, unit=unit)
    outputs = [
        scalar("n_grains", report.n_grains),
        scalar("boundary_network_px", report.boundary_network_px, unit="px"),
        scalar("n_boundary_segments", report.n_boundary_segments),
        scalar("n_triple_junctions", report.n_triple_junctions),
        scalar("mean_diameter_px", report.mean_diameter_px, unit="px"),
    ]
    # calibrated aggregates: absent — not null — when uncalibrated (ADR 0004's
    # "sigma absent, not zero" spirit)
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
            {
                "values": report.labels.tolist(),
                "convention": "0 = background; values are grain labels (table rows, ascending)",
            },
        )
    )
    if scoped is not None:
        outputs.append(
            region_output(
                scoped,
                # texture features and watershed basins read a
                # NEIGHBOURHOOD, which does not stop at a region edge
                label_context=(
                    LABEL_CONTEXT_EXACT if scoped.mask is None else LABEL_CONTEXT_BBOX
                ),
            )
        )
    return OpResult(
        op="grains",
        params=params,
        label=f"grain segmentation ({params['method']})",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="grains",
        category="structure",
        produces_value=True,
        summary="Grain segmentation + morphometrics and boundary-network stats "
        "(calc/grains.segment_auto/segment_watershed + "
        "calc/grain_report.grain_report) — the synchronous computation "
        "behind /analyze/grains; job orchestration stays in routes/ "
        "(ADR 0005 §6)",
        params={
            "roi": OpParam(
                str,
                "",
                doc="'r1,c1,r2,c2' 1-based inclusive analysis rectangle; empty = whole image",
            ),
            "region": REGION_PARAM,
            "method": OpParam(
                str,
                "gradient",
                choices=("kmeans", "gradient", "rag", "orientation"),
                doc="kmeans is the ported MATLAB texture-clustering path; "
                "the others are per-image-type watershed/RAG methods",
            ),
            "k": OpParam(int, 4, minimum=2, maximum=10, doc="k-means cluster count"),
            "seed": OpParam(int, 0, doc="k-means RNG seed"),
            "replicates": OpParam(int, 3, doc="k-means restarts"),
            "granularity": OpParam(
                float, 0.05, minimum=0.0, maximum=1.0, doc="watershed granularity"
            ),
            "compactness": OpParam(float, 0.001, minimum=0.0, maximum=1.0),
            "orientation_sigma": OpParam(float, 2.0, minimum=0.5, maximum=8.0),
            "n_superpixels": OpParam(int, 400, minimum=50, maximum=4000),
            "merge_threshold": OpParam(float, 0.08, minimum=0.0, maximum=1.0),
            "denoise_sigma": OpParam(
                float, 0.0, minimum=0.0, maximum=10.0, doc="denoise pre-pass (watershed methods)"
            ),
            "robust": OpParam(bool, True, doc="outlier-clipped stretch (watershed methods)"),
            "min_area": OpParam(int, 25, doc="drop grains smaller than this (px)"),
        },
        fn=_grains,
    )
)
