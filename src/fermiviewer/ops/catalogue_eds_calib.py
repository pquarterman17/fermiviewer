"""EDS calibration/assignment operation catalogue — wave D (roadmap 3E):
batch/scripting reach for energy-axis recalibration (POST /eds/recalibrate)
and peak auto-assignment (POST /eds/auto-assign). Split from
``catalogue_eds_model.py`` so neither module nears the 500-line ceiling.

``eds_recalibrate`` is this wave's derived-DataStruct op: the route's
``apply`` flag is dropped because in op-land the derived DataStruct IS the
application — same pixels, new energy ``AxisCal`` — and its scalar
diagnostics (gain/offset/anchors/skipped) ride ``derived.metadata``, the
``savgol_derivative`` precedent (ADR 0005 wave-D addendum). The route's
OPTIONAL ``pairs`` field (explicit ``(observed_keV, true_keV)`` anchors,
a non-coordinate float-pair list — gap 2) is omitted under the
optional-input omission rule: the op registers the element-symbol anchor
mode only, and the pairs mode is annotated "no op" in the coverage audit.
``produces_value`` stays UNSET — ``produces_value_result`` must be False
for a derived-image producer.

``eds_auto_assign`` flattens the route's ragged peak → candidates nest
into one row per candidate (``peak_index`` joins back to the ``peaks``
table); empty results (no detected peaks, or no candidates in tolerance)
are valid, mirroring the route.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.eds import assign_elements, detect_peaks
from fermiviewer.calc.eds_calib import recalibrate, recalibrated_cal, resolve_anchors
from fermiviewer.calc.energy_units import to_kev
from fermiviewer.datastruct import SPECTRAL_KINDS, DataStruct
from fermiviewer.ops._envelopes import output
from fermiviewer.ops._parsing import split_csv
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


def _spectral_energy_kev(ds: DataStruct, opname: str) -> np.ndarray:
    """The routes' spectral guard + keV axis conversion, mirrored."""
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError(f"{opname} requires spectral input (got {ds.kind.value})")
    return to_kev(ds.energy_axis, ds.energy_cal.units)


# ── eds_recalibrate: linear energy-axis correction (derived) ───────────


def _eds_recalibrate(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    energy = _spectral_energy_kev(ds, "eds_recalibrate")
    spectrum = ds.sum_spectrum()
    # pairs mode omitted (module docstring) — symbols are the only anchors;
    # no usable anchors raises ValueError, mirroring the route's 422
    anchors, skipped = resolve_anchors(split_csv(params["elements"]), [], params["beam_kv"])
    res = recalibrate(energy, spectrum, anchors, search_kev=params["search_kev"])
    # a degenerate resulting scale raises ValueError, mirroring the route
    new_cal = recalibrated_cal(ds.axes[-1], res.gain, res.offset)
    derived = DataStruct(
        # same pixels — the route replaces only the energy AxisCal too
        data=ds.data,
        kind=ds.kind,
        axes=(*ds.axes[:-1], new_cal),
        metadata={
            "parser": "derived",
            "source": "eds_recalibrate",
            "gain": res.gain,
            "offset": res.offset,
            "skipped": skipped,
            "anchors": [list(p) for p in res.anchors],
        },
    )
    return OpResult(
        op="eds_recalibrate",
        params=params,
        label="EDS energy-axis recalibration",
        derived=derived,
    )


register(
    OpSpec(
        name="eds_recalibrate",
        category="eds",
        summary="Linear energy-axis recalibration E' = gain*E + offset from "
        "known characteristic lines (calc/eds_calib.resolve_anchors + "
        "recalibrate + recalibrated_cal); the derived DataStruct IS the "
        "application (the route's apply flag) — pixels unchanged, new "
        "energy AxisCal, diagnostics in derived.metadata. The route's "
        "optional explicit (observed, true) pairs mode has no op "
        "(optional-input omission)",
        params={
            "elements": OpParam(
                str,
                "",
                doc="comma-separated element symbols whose principal-line true "
                "energies anchor the fit, e.g. 'Fe,Cu'; symbols with no "
                "known line are skipped (derived.metadata['skipped']); "
                "no usable anchors at all is an error",
            ),
            "beam_kv": OpParam(
                float, 200.0, minimum=0.0, doc="beam energy (kV), selects K/L/M line"
            ),
            "search_kev": OpParam(
                float,
                0.15,
                doc="half-width for locating each observed peak centroid "
                "around its true energy (keV)",
            ),
        },
        fn=_eds_recalibrate,
    )
)


# ── eds_auto_assign: peak detection + candidate element lines ──────────


def _eds_auto_assign(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    energy = _spectral_energy_kev(ds, "eds_auto_assign")
    counts = ds.sum_spectrum()
    peak_kev = detect_peaks(energy, counts, threshold=params["threshold"])
    assignments = assign_elements(peak_kev, tolerance_kev=params["tolerance_kev"])
    # flatten the route's ragged peak -> candidates nest: one row per
    # candidate; peak_index joins back to the peaks table. Empty is valid.
    rows = [
        [i, pa.peak_kev, ca.symbol, ca.line, ca.energy_kev, ca.delta_kev]
        for i, pa in enumerate(assignments)
        for ca in pa.candidates
    ]
    outputs = [
        output(
            "table",
            "assignments",
            {
                "columns": [
                    "peak_index",
                    "peak_kev",
                    "symbol",
                    "line",
                    "energy_kev",
                    "delta_kev",
                ],
                "units": ["", "keV", "", "", "keV", "keV"],
                "rows": rows,
            },
        ),
        output(
            "table",
            "peaks",
            {
                "columns": ["peak_index", "peak_kev"],
                "units": ["", "keV"],
                "rows": [[i, float(e)] for i, e in enumerate(peak_kev)],
            },
        ),
    ]
    return OpResult(
        op="eds_auto_assign",
        params=params,
        label="EDS peak auto-assignment",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eds_auto_assign",
        category="eds",
        produces_value=True,
        summary="Local-maxima peak detection + candidate K/L/M line matching "
        "(calc/eds.detect_peaks -> assign_elements); one assignments row "
        "per candidate, sorted closest-first within each peak",
        params={
            "tolerance_kev": OpParam(float, 0.15, doc="line-match window half-width (keV)"),
            "threshold": OpParam(
                float, 0.05, doc="peak detection floor (fraction of the spectrum maximum)"
            ),
        },
        fn=_eds_auto_assign,
    )
)
