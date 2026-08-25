"""Point-list operations: conic fitting and pair strain from already-picked
coordinates (the last two gap-2 bounces, ADR 0005 §9).

Both ops take a coordinate list and NO image content — `fit_shape` fits a
ring the operator drew, `atoms_strain` measures strain from column
positions a previous step found. They still take the subject positional
(the wave-A `distribution_fit`/`interface_width` no-subject precedent) and
ignore it: the subject is the provenance spine even when the numbers come
entirely from params.

The two coordinate conventions differ and are NOT interchangeable —
`fit_shape`'s points are 1-based (row, col), `atoms_strain`'s are 1-based
(x, y). Each mirrors its route's request model (§4); silently unifying them
would rotate every result by 90°.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.atom_report import pair_strain_payload
from fermiviewer.calc.atom_strain import peak_pair_strain
from fermiviewer.calc.shape_fit import fit_circle, fit_ellipse
from fermiviewer.datastruct import DataStruct
from fermiviewer.ops._envelopes import output, scalar
from fermiviewer.ops._parsing import sentinel_group
from fermiviewer.ops.base import OpParam, OpResult, OpSpec, RowSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


# ── fit_shape (analysis) ──────────────────────────────────────────────


def _fit_shape(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    pts = np.asarray(params["points"], dtype=np.float64)
    # circle first, then ellipse — the route's order, which is what makes a
    # too-short input name the shape it actually failed for
    circle = fit_circle(pts)
    ellipse = fit_ellipse(pts)
    outputs = [
        output(
            "fit",
            "circle",
            {
                "model": "circle",
                "params": {"cy": circle.cy, "cx": circle.cx, "r": circle.r},
                "rms": circle.rms,
            },
        ),
        output(
            "fit",
            "ellipse",
            {
                "model": "ellipse",
                "params": {
                    "cy": ellipse.cy,
                    "cx": ellipse.cx,
                    "a": ellipse.a,
                    "b": ellipse.b,
                    "theta_rad": ellipse.theta_rad,
                },
                "rms": ellipse.rms,
            },
        ),
        scalar("circle_rms", circle.rms, unit="px"),
        scalar("ellipse_rms", ellipse.rms, unit="px"),
    ]
    return OpResult(
        op="fit_shape",
        params=params,
        label="circle + ellipse fit",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="fit_shape",
        category="analysis",
        summary="Least-squares circle AND ellipse through a drawn ring of "
        "points (calc/shape_fit.py); both are always fitted so their RMS "
        "can be compared",
        params={
            "points": OpParam(
                list,
                required=True,
                row=RowSpec(width=2, columns=("row", "col"), min_rows=3),
                doc="the ring, 1-based (row, col) px; calc enforces its own "
                "per-shape minimums (circle >= 3, ellipse >= 5)",
            ),
        },
        fn=_fit_shape,
    )
)


# ── atoms_strain (structure) ──────────────────────────────────────────


def _atoms_strain(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    positions = np.asarray(params["positions"], dtype=np.float64)
    ref = params["ref_vectors"]
    origin = sentinel_group(params, ("origin_x", "origin_y"))
    strain = peak_pair_strain(
        positions,
        ref_vectors=np.asarray(ref, dtype=np.float64) if ref else None,
        origin=np.asarray(origin, dtype=np.float64) if origin is not None else None,
        neighbors=params["neighbors"],
    )
    payload = pair_strain_payload(strain)
    outputs = [
        scalar("exx_mean", payload["exx_mean"]),
        scalar("eyy_mean", payload["eyy_mean"]),
        scalar("exy_mean", payload["exy_mean"]),
        output(
            "table",
            "per_column_strain",
            {
                "columns": ["exx", "eyy", "exy", "rotation"],
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
            },
        ),
    ]
    return OpResult(
        op="atoms_strain",
        params=params,
        label="pair strain from atom columns",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="atoms_strain",
        category="structure",
        produces_value=True,
        summary="Peak-pair strain from already-fitted atom-column positions "
        "(calc/atom_strain.peak_pair_strain) — no re-detection",
        params={
            "positions": OpParam(
                list,
                required=True,
                row=RowSpec(width=2, columns=("x", "y")),
                doc="column positions, 1-based (x, y) — note this is (x, y), "
                "unlike fit_shape's (row, col)",
            ),
            "ref_vectors": OpParam(
                list,
                default=(),
                row=RowSpec(width=2, columns=("x", "y"), max_rows=2),
                doc="the two reference lattice vectors [[a1x,a1y],[a2x,a2y]]; "
                "empty to derive them from the positions",
            ),
            # a fixed-arity optional pair, so the frozen NaN-sentinel group
            # (§4), not a one-row list — the route's field is a flat [x0, y0]
            "origin_x": OpParam(
                float,
                float("nan"),
                doc="reference origin x, 1-based; give both origin_* or "
                "neither (derived from the positions when absent)",
            ),
            "origin_y": OpParam(float, float("nan"), doc="reference origin y"),
            "neighbors": OpParam(
                int, 8, minimum=3, maximum=32, doc="neighbours per column"
            ),
        },
        fn=_atoms_strain,
    )
)
