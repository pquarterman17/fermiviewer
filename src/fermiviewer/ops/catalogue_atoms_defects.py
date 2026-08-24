"""Atom-column, template-match and defect-line operation catalogue — the
structure half of wave B (roadmap 3C). New module because no existing
catalogue has the headroom (the ``catalogue_grains_layers.py`` compound-
name precedent). All three ops are ``structure`` — wave A's category,
which does NOT imply a value result, so each sets ``produces_value=True``
explicitly (ADR 0005 §3).

Every op calls the SAME calc composition its route calls: `atoms` runs
`calc.atom_report.atom_column_report` (the wave-B lift of the detect →
refine → lattice → sublattice → strain pipeline that lived in
`routes/structure.py`); `template_match` runs
`calc.texture.template_match_rect` (the lift of the route's rect
validation + template cut — note its rect is (row, col, height, width),
NOT the ``"r1,c1,r2,c2"`` corner ROI, so it deliberately does not reuse
``parse_roi_param``); `defects` runs `calc.defects.count_defect_lines` +
`calc.roi.embed_rect_roi` with zero lift work. `defects`' two diagnostic
maps — session images on the route — inline as ``map`` envelopes (the
grains/gpa precedent, ADR 0005 wave-B addendum).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from fermiviewer.calc.atom_report import atom_column_report, pair_strain_payload
from fermiviewer.calc.defects import count_defect_lines
from fermiviewer.calc.raster import raster_of
from fermiviewer.calc.roi import embed_rect_roi
from fermiviewer.calc.texture import template_match_rect
from fermiviewer.datastruct import DataStruct
from fermiviewer.ops._envelopes import nan_none as _nn
from fermiviewer.ops._envelopes import output, scalar
from fermiviewer.ops._parsing import parse_roi_param
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


# ── atoms ─────────────────────────────────────────────────────────────


def _atoms(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    report = atom_column_report(
        raster,
        sigma=params["sigma"],
        threshold=params["threshold"],
        min_separation=params["min_separation"],
        polarity=params["polarity"],
        refine=params["refine"],
        win_radius=params["win_radius"],
        strain=params["strain"],
        sublattices=params["sublattices"],
    )
    table_data: dict[str, Any] = {
        "columns": ["x", "y", "amplitude"],
        "units": ["px", "px", ""],
        # (x, y), 1-based — the wire convention (calc/atoms.py)
        "position_convention": "(x, y), 1-based",
        "rows": [
            [float(p[0]), float(p[1]), float(a)]
            for p, a in zip(report.positions, report.amplitude, strict=True)
        ],
        "converged": report.converged,
    }
    if report.sublattice is not None:
        table_data["sublattice"] = report.sublattice.tolist()
    lv = report.lattice
    outputs = [
        scalar("n_columns", report.n_columns),
        output("table", "columns", table_data),
        output(
            "fit",
            "lattice",
            {
                "model": "nearest-neighbour lattice basis",
                "valid": bool(lv.valid),
                "coefficients": {
                    "spacing": _nn(lv.spacing),
                    "a1": None if not lv.valid else lv.a1.tolist(),
                    "a2": None if not lv.valid else lv.a2.tolist(),
                },
                "unit": "px",
            },
        ),
    ]
    if report.strain is not None:
        payload = pair_strain_payload(report.strain)
        for key in ("exx_mean", "eyy_mean", "exy_mean"):
            if payload[key] is not None:
                outputs.append(scalar(key, payload[key]))
        outputs.append(
            output(
                "table",
                "strain",
                {
                    "columns": ["exx", "eyy", "exy", "rotation"],
                    "units": ["", "", "", "rad"],
                    "valid": payload["valid"],
                    "rows": [
                        list(row)
                        for row in zip(
                            payload["exx"],
                            payload["eyy"],
                            payload["exy"],
                            payload["rotation"],
                            strict=True,
                        )
                    ],
                    "displacement": payload["displacement"],
                },
            )
        )
    return OpResult(
        op="atoms", params=params, label="atom-column analysis", value={"outputs": outputs}
    )


register(
    OpSpec(
        name="atoms",
        category="structure",
        produces_value=True,
        summary="Atom-column detection + Gaussian refinement, lattice basis, "
        "optional sublattice labels and PPA strain "
        "(calc/atom_report.atom_column_report)",
        params={
            "sigma": OpParam(float, 2.0, doc="detection smoothing (px)"),
            "threshold": OpParam(float, 0.2, doc="relative detection threshold"),
            "min_separation": OpParam(float, 8.0, doc="minimum column separation (px)"),
            "polarity": OpParam(str, "bright", choices=("bright", "dark")),
            "refine": OpParam(bool, True, doc="per-column 2D Gaussian refinement"),
            "win_radius": OpParam(int, 6, doc="refinement window radius (px)"),
            "strain": OpParam(bool, False, doc="also compute peak-pair strain"),
            "sublattices": OpParam(
                int, 1, minimum=1, maximum=4, doc="cluster columns into this many sublattices"
            ),
        },
        fn=_atoms,
    )
)


# ── template match ────────────────────────────────────────────────────


def _template_match(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    res = template_match_rect(
        raster,
        (params["rect_row"], params["rect_col"], params["rect_height"], params["rect_width"]),
        threshold=params["threshold"],
        max_matches=params["max_matches"],
    )
    locations = res.locations.tolist()
    outputs = [
        scalar("n_matches", res.n_matches),
        output(
            "table",
            "matches",
            {
                "columns": ["row", "col", "score"],
                "units": ["px", "px", ""],
                # (row, col) match centres, 1-based (calc/texture.py)
                "position_convention": "(row, col) centres",
                "rows": [
                    [loc[0], loc[1], score]
                    for loc, score in zip(locations, res.scores.tolist(), strict=True)
                ],
            },
        ),
        output(
            "overlay",
            "locations",
            {
                "points": locations,
                "convention": "(row, col) match centres",
            },
        ),
    ]
    return OpResult(
        op="template_match", params=params, label="template match", value={"outputs": outputs}
    )


register(
    OpSpec(
        name="template_match",
        category="structure",
        produces_value=True,
        summary="FFT-based normalized cross-correlation matching of a template "
        "cut from the same image (calc/texture.template_match_rect). The "
        "rect is (row, col, height, width), 1-based — NOT the "
        "'r1,c1,r2,c2' corner ROI other ops use",
        params={
            "rect_row": OpParam(int, required=True, doc="template top row, 1-based"),
            "rect_col": OpParam(int, required=True, doc="template left col, 1-based"),
            "rect_height": OpParam(int, required=True, doc="template height (px)"),
            "rect_width": OpParam(int, required=True, doc="template width (px)"),
            "threshold": OpParam(float, 0.7, minimum=0.0, maximum=1.0, doc="NCC score floor"),
            "max_matches": OpParam(int, 100, doc="cap on returned matches"),
        },
        fn=_template_match,
    )
)


# ── defects ───────────────────────────────────────────────────────────


def _defects(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    roi = parse_roi_param(params["roi"])
    # the route's Field(gt=0) bound; OpParam has no exclusive minimum
    # (ADR 0005 wave-B addendum) — NaN stays the calc's own "not given"
    ft = params["foil_thickness"]
    if math.isfinite(ft) and ft <= 0:
        raise ValueError("foil_thickness must be > 0")
    px = ds.pixel_size if np.isfinite(ds.pixel_size) and ds.pixel_size > 0 else 1.0
    unit = ds.pixel_unit or "px"
    res = count_defect_lines(
        raster,
        roi=roi,
        direction=(params["direction"] if math.isfinite(params["direction"]) else None),
        kernel_length=params["kernel_length"],
        grid_spacing=params["grid_spacing"],
        foil_thickness=ft,
        pixel_size=px,
        pixel_unit=unit,
    )
    enhanced = embed_rect_roi(res.enhanced, raster.shape, roi)
    binary_mask = embed_rect_roi(res.binary_mask.astype(np.uint8), raster.shape, roi)
    outputs = [
        scalar("intersections", res.intersection_count),
        scalar("test_lines", res.num_test_lines),
        scalar("total_line_length", res.total_line_length, unit="px"),
        scalar("density", res.density, unit=res.density_unit),
        output(
            "overlay",
            "test_line_positions",
            {
                "h_rows": res.h_rows.tolist(),
                "v_cols": res.v_cols.tolist(),
                "convention": "1-based test-line positions",
            },
        ),
        output(
            "map",
            "enhanced",
            {
                "values": enhanced.tolist(),
                "quantity": "oriented-filter response",
            },
        ),
        output(
            "map",
            "mask",
            {
                "values": binary_mask.tolist(),
                "convention": "1 = defect-line pixel",
            },
        ),
    ]
    return OpResult(
        op="defects", params=params, label="defect-line density", value={"outputs": outputs}
    )


register(
    OpSpec(
        name="defects",
        category="structure",
        produces_value=True,
        summary="Line-defect density via oriented filtering + line intercepts "
        "(calc/defects.count_defect_lines); the two diagnostic maps "
        "inline as `map` envelopes — the route registers them as session "
        "images instead (grains precedent, ADR 0005 wave-B addendum)",
        params={
            "direction": OpParam(
                float,
                float("nan"),
                doc="defect direction (deg); leave unset (NaN) to sweep 0/45/90/135°",
            ),
            "kernel_length": OpParam(int, 15, minimum=1, doc="oriented-filter length (px)"),
            "grid_spacing": OpParam(int, 50, minimum=1, doc="test-line spacing (px)"),
            "roi": OpParam(
                str,
                "",
                doc="'r1,c1,r2,c2' 1-based inclusive analysis rectangle; empty = whole image",
            ),
            "foil_thickness": OpParam(
                float,
                float("nan"),
                doc="foil thickness in the image's calibrated "
                "unit; must be > 0 when given (NaN = "
                "unknown, areal density only)",
            ),
        },
        fn=_defects,
    )
)
