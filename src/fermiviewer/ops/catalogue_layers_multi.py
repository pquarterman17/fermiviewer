"""Cross-section layer operations over more than one dataset — the last two
gap-1 bounces (ADR 0005 §8).

`layers_multi` compares interface roughness across several maps of the same
region; `layers_grains` assigns a grain-label map to reviewed layer bands,
which needs the label map AND the intensity image it came from.

New module rather than growing `catalogue_grains_layers.py` (395 lines) past
the ratchet (§2).

Two subject choices worth stating, because both are judgement calls:

- `layers_multi`'s subject is the REFERENCE map, and the route's `reference`
  index param is dropped. The reference is what governs the detected axis
  and the interface positions every other map is re-measured against, so it
  is the provenance spine in the sense §8 means; `align_stack` and `mip`
  already set that precedent. A caller who wants a different reference
  passes a different subject.
- `layers_grains`'s subject is the LABEL map (the route's `labels_id`), with
  the intensity image as a named input — the route recovers the latter from
  `metadata["grain_source"]` plus a store read, which the pure layer cannot
  do.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np

from fermiviewer.calc.grain_layers import LayerBounds, measure_grains_by_layer
from fermiviewer.calc.layers_multi import compare_layers_across_maps
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.ops._envelopes import output, scalar
from fermiviewer.ops._parsing import parse_roi_param, pixel_cal_or_default, split_csv
from fermiviewer.ops.base import (
    OpInput,
    OpParam,
    OpResult,
    OpSpec,
    RecordSpec,
    RowSpec,
)
from fermiviewer.ops.registry import register

__all__: list[str] = []

_RASTER_KINDS = (DataKind.IMAGE, DataKind.RGB_IMAGE, DataKind.SPECTRUM_IMAGE)


# ── layers_multi (analysis; variadic input) ───────────────────────────


def _layers_multi(
    ds: DataStruct, params: dict[str, Any], inputs: dict[str, Any]
) -> OpResult:
    frames = [ds, *inputs["others"]]
    if any(f.kind is not DataKind.IMAGE for f in frames):
        raise ValueError("layer comparison needs 2D images")
    shapes = {f.data.shape[:2] for f in frames}
    if len(shapes) != 1:
        raise ValueError("every compared map must have the same pixel grid")

    cals = [pixel_cal_or_default(f) for f in frames]
    roi = parse_roi_param(params["roi"])
    result = compare_layers_across_maps(
        [np.asarray(f.data) for f in frames],
        [px for px, _ in cals],
        [unit for _, unit in cals],
        reference=0,  # the subject IS the reference (see the module docstring)
        roi=roi,  # RectRoi IS the (r1, c1, r2, c2) tuple, 1-based inclusive
        axis=params["axis"],
        sensitivity=params["sensitivity"],
        n_layers=params["n_layers"],
        modality=params["modality"],
        waviness=params["waviness"],
    )

    outputs: list[dict[str, Any]] = [
        scalar("n_maps", len(frames)),
        scalar("pixel_size", result.pixel_size, unit=result.unit),
        output(
            "curve",
            "reference_positions",
            {
                "x": list(range(len(result.reference_positions))),
                "y": result.reference_positions,
                "x_label": "interface",
                "y_label": "position (profile px)",
            },
        ),
    ]
    for index, block in enumerate(result.maps):
        outputs.append(
            output(
                "table",
                f"map_{index}_interfaces",
                {
                    "columns": ["position", "sigma_erf", "sigma_w"],
                    "rows": [
                        [row["position"], row["sigma_erf"], row["sigma_w"]]
                        for row in block["interfaces"]
                    ],
                },
            )
        )
        outputs.append(
            output(
                "table",
                f"map_{index}_layers",
                {
                    "columns": ["index", "thickness", "thickness_std"],
                    "rows": [
                        [row["index"], row["thickness"], row["thickness_std"]]
                        for row in block["layers"]
                    ],
                },
            )
        )
    return OpResult(
        op="layers_multi",
        params=params,
        label=f"layer comparison across {len(frames)} maps (axis {result.axis})",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="layers_multi",
        category="analysis",
        summary="Compare interface positions and roughness across several "
        "maps of one cross-section (calc/layers_multi). The SUBJECT is the "
        "reference map: its detected axis and interface positions govern "
        "every other map, so the route's `reference` index is not a param",
        params={
            "roi": OpParam(
                str, "", doc="'r1,c1,r2,c2', 1-based inclusive; empty = whole image"
            ),
            "axis": OpParam(
                str, "auto", choices=("auto", "x", "y"), doc="depth axis"
            ),
            "sensitivity": OpParam(float, 0.3, doc="interface detection sensitivity"),
            "n_layers": OpParam(int, 0, minimum=0, doc="0 = auto"),
            "modality": OpParam(str, "haadf", doc="imaging modality"),
            "waviness": OpParam(
                bool,
                True,
                doc="separate waviness from roughness (the /layers/multi "
                "default; the single-map /analyze/layers route defaults False)",
            ),
        },
        inputs={
            "others": OpInput(
                doc="the maps to compare against the subject, in order",
                variadic=True,
                min_count=1,
                kinds=_RASTER_KINDS,
            ),
        },
        fn=_layers_multi,
    )
)


# ── layers_grains (analysis; one named input) ─────────────────────────


def _layers_grains(
    ds: DataStruct, params: dict[str, Any], inputs: dict[str, Any]
) -> OpResult:
    if ds.kind is not DataKind.IMAGE:
        raise ValueError("the subject must be a grain-label map")
    source = inputs["source"]
    px, unit = pixel_cal_or_default(source)
    bands = [
        LayerBounds(int(row["index"]), float(row["top"]), float(row["bottom"]))
        for row in params["layers"]
    ]
    traces = [
        None if not trace else np.asarray(trace, dtype=np.float64)
        for trace in params["interface_traces"]
    ]
    roi = parse_roi_param(params["roi"])
    result = measure_grains_by_layer(
        np.asarray(ds.data),
        bands,
        selected_indices=[int(v) for v in split_csv(params["selected_indices"])],
        axis=params["axis"],
        roi=roi,  # RectRoi IS the (r1, c1, r2, c2) tuple, 1-based inclusive
        interface_traces=traces,
        pixel_size=px,
        unit=unit,
    )
    layer_rows = [asdict(layer) for layer in result.layers]
    columns = list(layer_rows[0]) if layer_rows else []
    outputs = [
        scalar("pixel_size", result.pixel_size, unit=result.unit),
        output(
            "table",
            "layer_grains",
            {"columns": columns, "rows": [list(row.values()) for row in layer_rows]},
        ),
        # the assignment raster: the route registers it as a session image,
        # the op inlines it (the wave-B standing rule for extra rasters)
        output(
            "map",
            "assignment",
            {
                "values": np.asarray(
                    result.assignment, dtype=np.float64
                ).tolist(),
                "unit": "",
            },
        ),
    ]
    return OpResult(
        op="layers_grains",
        params=params,
        label=f"grains by layer ({len(layer_rows)} bands)",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="layers_grains",
        category="analysis",
        summary="Assign a grain-label map to reviewed cross-section layer "
        "bands (calc/grain_layers.measure_grains_by_layer). Shape angle is "
        "morphological, not crystallographic; grains crossing a reviewed "
        "interface are clipped and reported in each layer",
        params={
            "axis": OpParam(
                str, required=True, choices=("x", "y"), doc="depth axis"
            ),
            "layers": OpParam(
                list,
                required=True,
                record=RecordSpec(
                    fields={
                        "index": OpParam(int, required=True),
                        "top": OpParam(float, required=True),
                        "bottom": OpParam(float, required=True),
                    },
                    min_rows=1,
                ),
                doc="the reviewed layer bands",
            ),
            "selected_indices": OpParam(
                str, "", doc="comma-separated layer indices to report"
            ),
            "interface_traces": OpParam(
                list,
                default=(),
                row=RowSpec(width=None, allow_none_rows=True),
                doc="per-interface traces; ragged, and an entry may be null "
                "for an interface with no measured trace",
            ),
            "roi": OpParam(
                str, "", doc="'r1,c1,r2,c2', 1-based inclusive; empty = whole image"
            ),
        },
        inputs={
            "source": OpInput(
                doc="the intensity image the label map was derived from "
                "(the route recovers this from the map's metadata)",
                kinds=_RASTER_KINDS,
            ),
        },
        fn=_layers_grains,
    )
)
