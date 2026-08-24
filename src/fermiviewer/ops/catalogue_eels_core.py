"""EELS core-loss operation catalogue — wave D (roadmap 3E): batch/
scripting reach for background subtraction, ELNES extraction, and edge
auto-identification. New module because no existing catalogue has the
headroom (the ``catalogue_analysis.py`` precedent); the shipped
``eels_quantify``/``eels_map`` stay in ``catalogue_spectral.py`` — §2
migrates a grandfathered op only when its wave touches its code.

The `eels` category does NOT imply a value result, so every op here sets
``produces_value=True`` explicitly (ADR 0005 §3; the `radial_profile`
precedent). Every op calls the SAME calc composition its route calls
(§1): ``calc.eels.background``, ``calc.eels_quant.elnes``,
``calc.eels_identify.identify_edges`` — wiring and schema only.

Route request models flatten per §4: the routes' ``fit_window`` tuples
become the ``fit_lo``/``fit_hi`` float pair (the ``eels_map``
signal_lo/hi precedent). `elnes` drops the route's OPTIONAL
``reference_id`` second image under the wave-D optional-input omission
rule — see its docstring.
"""

from __future__ import annotations

import math
from typing import Any

from fermiviewer.calc.eels import background
from fermiviewer.calc.eels_identify import (
    EDGE_FIT_GAP_EV,
    EDGE_FIT_WIDTH_EV,
    EDGE_SIGNAL_WIDTH_EV,
    identify_edges,
)
from fermiviewer.calc.eels_quant import elnes
from fermiviewer.datastruct import SPECTRAL_KINDS, DataStruct
from fermiviewer.ops._envelopes import output, scalar
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []

_METHOD = OpParam(
    str,
    "powerlaw",
    choices=("powerlaw", "exponential"),
    doc="pre-edge background model",
)


def _require_spectral(ds: DataStruct, opname: str) -> None:
    """The routes' `_spectral` 400 guard, as the op-layer ValueError."""
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError(f"{opname} requires spectral input (got {ds.kind.value})")


def _curve(name: str, x: list[float], y: list[float], x_name: str = "energy") -> dict[str, Any]:
    """A curve envelope on the EELS energy axis (native eV)."""
    return output(
        "curve",
        name,
        {
            "x_name": x_name,
            "x_unit": "eV",
            "y_name": "counts",
            "y_unit": "",
            "x": x,
            "y": y,
        },
    )


# ── background subtraction ────────────────────────────────────────────


def _eels_background(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    _require_spectral(ds, "eels_background")
    energy = ds.energy_axis
    spec = ds.sum_spectrum()
    signal, bg, params_out = background(
        energy, spec, (params["fit_lo"], params["fit_hi"]), params["method"]
    )
    x = energy.tolist()
    outputs = [
        _curve("spectrum", x, spec.tolist()),
        _curve("background", x, bg.tolist()),
        _curve("signal", x, signal.tolist()),
        output(
            "fit",
            "background_model",
            {"model": params["method"], "coefficients": params_out},
        ),
    ]
    return OpResult(
        op="eels_background",
        params=params,
        label="EELS pre-edge background subtraction",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eels_background",
        category="eels",
        produces_value=True,
        summary="Pre-edge background fit + subtraction on the summed "
        "spectrum (calc/eels.background)",
        params={
            "fit_lo": OpParam(float, required=True, doc="pre-edge fit window lower edge (eV)"),
            "fit_hi": OpParam(float, required=True, doc="pre-edge fit window upper edge (eV)"),
            "method": _METHOD,
        },
        fn=_eels_background,
    )
)


# ── ELNES fine structure ──────────────────────────────────────────────


def _elnes(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    """Near-edge fine-structure extraction (calc/eels_quant.elnes).

    The route's OPTIONAL ``reference_id`` — a second spectrum overlaid
    for comparison — is DROPPED here per the wave-D optional-input
    omission rule (ADR 0005 wave-D addendum): ``OpSpec.fn`` has exactly
    one ``DataStruct`` subject, so the op registers the single-spectrum
    form and the reference-overlay mode stays route-only ("no op" in the
    audit's note column). A caller who wants the comparison runs the op
    once per spectrum.
    """
    _require_spectral(ds, "elnes")
    res = elnes(
        ds.energy_axis,
        ds.sum_spectrum(),
        params["edge_onset"],
        (params["fit_lo"], params["fit_hi"]),
        (params["elnes_lo"], params["elnes_hi"]),
        params["method"],
        params["normalize"],
    )
    outputs = [
        _curve(
            "elnes",
            res.relative_energy.tolist(),
            res.intensity.tolist(),
            x_name="relative_energy",
        ),
        output(
            "fit",
            "background",
            {"model": params["method"], "coefficients": res.background_params},
        ),
    ]
    # non-finite scalars are ABSENT, not null (ADR 0005 §5)
    if math.isfinite(res.edge_jump):
        outputs.append(scalar("edge_jump", res.edge_jump))
    if math.isfinite(res.edge_onset):
        outputs.append(scalar("edge_onset", res.edge_onset, unit="eV"))
    return OpResult(
        op="elnes",
        params=params,
        label="ELNES fine-structure extraction",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="elnes",
        category="eels",
        produces_value=True,
        summary="Near-edge fine structure relative to the edge onset "
        "(calc/eels_quant.elnes); the route's optional reference_id "
        "overlay is route-only — run the op once per spectrum",
        params={
            "edge_onset": OpParam(float, required=True, doc="edge onset energy (eV)"),
            "fit_lo": OpParam(
                float,
                required=True,
                doc="pre-edge fit window lower edge (eV); the window must "
                "lie entirely below edge_onset",
            ),
            "fit_hi": OpParam(float, required=True, doc="pre-edge fit window upper edge (eV)"),
            "elnes_lo": OpParam(
                float, 0.0, doc="ELNES window lower edge, relative to the onset (eV)"
            ),
            "elnes_hi": OpParam(
                float, 30.0, doc="ELNES window upper edge, relative to the onset (eV)"
            ),
            "method": _METHOD,
            "normalize": OpParam(bool, True, doc="normalize intensity to the edge jump"),
        },
        fn=_elnes,
    )
)


# ── edge auto-identification ──────────────────────────────────────────


def _eels_auto_assign(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    _require_spectral(ds, "eels_auto_assign")
    rows = identify_edges(
        ds.energy_axis,
        ds.sum_spectrum(),
        fit_width_ev=params["fit_width_ev"],
        signal_width_ev=params["signal_width_ev"],
        fit_gap_ev=params["fit_gap_ev"],
        method=params["method"],
    )
    # an empty edge list is a VALID result (the route's own contract: a
    # narrow axis or flat spectrum legitimately shows no edges) — empty
    # rows, never a raise
    table = output(
        "table",
        "edges",
        {
            "columns": [
                "element",
                "edge",
                "symbol",
                "onset_ev",
                "fit_lo",
                "fit_hi",
                "signal_lo",
                "signal_hi",
                "net",
                "sigma",
                "significance",
                "confidence",
            ],
            "units": [
                "",
                "",
                "",
                "eV",
                "eV",
                "eV",
                "eV",
                "eV",
                "",
                "",
                "",
                "",
            ],
            "rows": [
                [
                    r.element,
                    r.edge,
                    r.symbol,
                    r.onset_ev,
                    r.fit_window[0],
                    r.fit_window[1],
                    r.signal_window[0],
                    r.signal_window[1],
                    r.net,
                    r.sigma,
                    r.significance,
                    r.confidence,
                ]
                for r in rows
            ],
        },
    )
    return OpResult(
        op="eels_auto_assign",
        params=params,
        label="EELS edge auto-identification",
        value={"outputs": [table]},
    )


register(
    OpSpec(
        name="eels_auto_assign",
        category="eels",
        produces_value=True,
        summary="Edge-jump significance for every tabulated EELS edge the "
        "energy axis supports (calc/eels_identify.identify_edges), "
        "sorted strongest first; an empty table is a valid result",
        params={
            # defaults imported from calc.eels_identify — the calc module
            # owns these numbers, never hard-code them here
            "fit_width_ev": OpParam(
                float,
                EDGE_FIT_WIDTH_EV,
                doc="pre-edge background-fit window width (eV)",
            ),
            "signal_width_ev": OpParam(
                float,
                EDGE_SIGNAL_WIDTH_EV,
                doc="post-onset signal window width (eV)",
            ),
            "fit_gap_ev": OpParam(
                float,
                EDGE_FIT_GAP_EV,
                doc="gap between the fit window's upper edge and the onset (eV)",
            ),
            "method": _METHOD,
        },
        fn=_eels_auto_assign,
    )
)
