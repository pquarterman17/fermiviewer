"""EELS spectrum-image map operation catalogue — wave D (roadmap 3E):
batch/scripting reach for thickness mapping, per-pixel composition
mapping (window quantification and model fit), and batch species maps.
Split from ``catalogue_eels_core.py`` per the 500-line module ceiling
(the ``catalogue_analysis.py`` precedent).

The `eels` category does NOT imply a value result, so every op here sets
``produces_value=True`` explicitly (ADR 0005 §3). Every op calls the
SAME calc composition its route calls (§1): ``calc.eels.thickness_map``
+ ``calc.eels_report.thickness_summary``,
``calc.eels_quant.quantify_map`` + ``calc.eels_report
.mean_atomic_percent``, ``calc.eels_model.fit_edges_map``, and
``calc.eels_species_maps.species_maps`` (the wave-D lift shared with
``/eels/maps``). Job orchestration for ``/eels/quantify-map``'s
``run_async`` mode stays route-only (§6) — the op registers the
synchronous computation.

Per the wave-B standing rule, each raster the routes register as a
session image inlines here as a `map` envelope; every map is H×W floats
per run, so batch scripts over large cubes should expect large value
payloads (the `diffraction_simulate` size caveat, repeated on each op's
summary). NaN cells inline as null (``nan_none``); non-finite scalars
are ABSENT, not null.

Envelope names must be unique within an op (ADR 0005 §5), and two ops
here name map envelopes after CALLER-SUPPLIED strings (element symbols,
species labels) — a duplicate or a clash with a fixed envelope name is a
hard ValueError rather than a silently shadowed output.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.eels import thickness_map
from fermiviewer.calc.eels_model import fit_edges_map
from fermiviewer.calc.eels_quant import quantify_map
from fermiviewer.calc.eels_report import mean_atomic_percent, thickness_summary
from fermiviewer.calc.eels_species_maps import SpeciesSpec, species_maps
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.ops._envelopes import nan_none, output, scalar
from fermiviewer.ops._parsing import clean_values, edges_from_params, parse_windows, split_csv
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []

_METHOD = OpParam(
    str,
    "powerlaw",
    choices=("powerlaw", "exponential"),
    doc="pre-edge background model",
)


def _require_cube(ds: DataStruct, opname: str) -> None:
    """The routes' `_cube` 400 guard, as the op-layer ValueError."""
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise ValueError(f"{opname} requires a spectrum-image cube (got {ds.kind.value})")


def _nan_none_raster(arr: np.ndarray) -> list[list[float | None]]:
    """A 2-D raster as inline lists with NaN/inf -> None, cell-wise."""
    return [clean_values(row) for row in np.asarray(arr)]


def _check_unique_names(names: list[str], reserved: set[str], opname: str) -> None:
    """Caller-supplied envelope names must not collide with each other or
    with the op's fixed envelope names (ADR 0005 §5 unique-name rule)."""
    seen: set[str] = set()
    for name in names:
        if name in seen or name in reserved:
            raise ValueError(
                f"{opname}: duplicate/reserved output name {name!r} — envelope "
                f"names must be unique within an op"
            )
        seen.add(name)


# ── t/λ thickness map ─────────────────────────────────────────────────


def _eels_thickness(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    """Log-ratio t/λ map + summary statistics.

    ONE deliberate divergence from the route (recorded in the ADR 0005
    wave-D addendum and on the audit row): the route registers
    ``nan_to_num(t)`` as the session image (invalid pixels render as 0)
    but reports statistics over raw ``t``; this op inlines the RAW map
    with NaN -> null cell-wise — zero-filling invalid pixels in a
    headless array would silently bias any downstream mean.
    """
    _require_cube(ds, "eels_thickness")
    t, valid = thickness_map(
        ds.data, ds.energy_axis, (params["zlp_lo"], params["zlp_hi"]), params["min_counts"]
    )
    mean_t, valid_frac = thickness_summary(t, valid)
    outputs = [
        output(
            "map",
            "t_over_lambda",
            {
                "values": _nan_none_raster(t),
                "quantity": "t/lambda (log-ratio relative thickness)",
                "convention": "null = invalid pixel (below min_counts or no ZLP)",
            },
        ),
        scalar("mean_t_over_lambda", mean_t),
        scalar("valid_fraction", valid_frac),
    ]
    return OpResult(
        op="eels_thickness",
        params=params,
        label="EELS t/λ thickness map",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eels_thickness",
        category="eels",
        produces_value=True,
        summary="Log-ratio t/λ relative-thickness map over an SI cube "
        "(calc/eels.thickness_map + calc/eels_report"
        ".thickness_summary). The raw map inlines with NaN -> null "
        "(the route zero-fills its session image instead), H×W "
        "floats per run — large cubes make large value payloads",
        params={
            "zlp_lo": OpParam(float, -5.0, doc="zero-loss-peak window lower edge (eV)"),
            "zlp_hi": OpParam(float, 5.0, doc="zero-loss-peak window upper edge (eV)"),
            "min_counts": OpParam(float, 100.0, doc="minimum total counts for a pixel to be valid"),
        },
        fn=_eels_thickness,
    )
)


# ── per-pixel window quantification maps ──────────────────────────────


def _eels_quantify_map(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    _require_cube(ds, "eels_quantify_map")
    edges = edges_from_params(params, "eels_quantify_map")
    res = quantify_map(
        ds.data,
        ds.energy_axis,
        edges,
        params["e0_kv"],
        params["beta_mrad"],
        params["method"],
        None,
    )
    means = mean_atomic_percent(res.atomic_percent)
    _check_unique_names(res.elements, {"composition"}, "eels_quantify_map")
    outputs: list[dict[str, Any]] = [
        output(
            "map",
            sym,
            {
                "values": _nan_none_raster(res.atomic_percent[:, :, k]),
                "quantity": "atomic percent",
            },
        )
        for k, sym in enumerate(res.elements)
    ]
    outputs.append(
        output(
            "table",
            "composition",
            {
                "columns": ["element", "sigma", "mean_atomic_percent"],
                "units": ["", "", "at%"],
                "rows": [
                    [sym, nan_none(float(res.sigma[k])), nan_none(means[k])]
                    for k, sym in enumerate(res.elements)
                ],
            },
        )
    )
    return OpResult(
        op="eels_quantify_map",
        params=params,
        label="EELS per-pixel at% composition maps",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eels_quantify_map",
        category="eels",
        produces_value=True,
        summary="Per-pixel SI at% composition maps from core-loss edges "
        "(calc/eels_quant.quantify_map); one H×W map per element "
        "inlines in the value — large cubes make large payloads. "
        "The route's run_async job mode stays route-only (ADR 0005 "
        "§6): this op is the synchronous computation",
        params={
            "elements": OpParam(
                str, required=True, doc="comma-separated element symbols, e.g. 'Fe,O'"
            ),
            "shells": OpParam(
                str,
                required=True,
                doc="comma-separated shells matching elements, 'K'|'L', e.g. 'L,K'",
            ),
            "z": OpParam(
                str,
                required=True,
                doc="comma-separated atomic numbers matching elements, e.g. '26,8'",
            ),
            "onset_ev": OpParam(
                str, required=True, doc="comma-separated edge onsets (eV), e.g. '708,532'"
            ),
            "signal_windows": OpParam(
                str,
                required=True,
                doc="comma-separated 'lo:hi' signal windows (eV), e.g. '708:758,532:582'",
            ),
            "bg_windows": OpParam(
                str,
                required=True,
                doc="comma-separated 'lo:hi' pre-edge fit windows (eV), e.g. '650:700,490:520'",
            ),
            "e0_kv": OpParam(float, 200.0, minimum=0.0, doc="beam energy (kV)"),
            "beta_mrad": OpParam(float, 10.0, minimum=0.0, doc="collection semi-angle (mrad)"),
            "method": _METHOD,
        },
        fn=_eels_quantify_map,
    )
)


# ── per-pixel model-fit maps ──────────────────────────────────────────


def _eels_fit_map(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    _require_cube(ds, "eels_fit_map")
    edges = edges_from_params(params, "eels_fit_map")
    fit_range = None
    if np.isfinite(params["fit_range_lo"]) and np.isfinite(params["fit_range_hi"]):
        fit_range = (params["fit_range_lo"], params["fit_range_hi"])
    res = fit_edges_map(
        ds.data,
        ds.energy_axis,
        edges,
        params["e0_kv"],
        params["beta_mrad"],
        fit_range=fit_range,
    )
    # the route's per-element nanmean aggregate — the same arithmetic
    # calc/eels_report.mean_atomic_percent owns for /eels/quantify-map
    means = mean_atomic_percent(res.atomic_percent)
    _check_unique_names(res.elements, {"composition", "background_exponent"}, "eels_fit_map")
    outputs: list[dict[str, Any]] = [
        output(
            "map",
            sym,
            {
                "values": _nan_none_raster(res.atomic_percent[:, :, k]),
                "quantity": "atomic percent",
            },
        )
        for k, sym in enumerate(res.elements)
    ]
    outputs.append(scalar("background_exponent", res.background_exponent))
    outputs.append(
        output(
            "table",
            "composition",
            {
                "columns": ["element", "mean_atomic_percent"],
                "units": ["", "at%"],
                "rows": [[sym, nan_none(means[k])] for k, sym in enumerate(res.elements)],
            },
        )
    )
    return OpResult(
        op="eels_fit_map",
        params=params,
        label="EELS per-pixel model-fit at% maps",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eels_fit_map",
        category="eels",
        produces_value=True,
        summary="Per-pixel model fit over an SI cube (calc/eels_model"
        ".fit_edges_map) — background exponent fixed from the "
        "summed-spectrum fit, at% from per-pixel edge amplitudes; "
        "one H×W map per element inlines in the value, so large "
        "cubes make large payloads",
        params={
            "elements": OpParam(
                str, required=True, doc="comma-separated element symbols, e.g. 'Fe,O'"
            ),
            "shells": OpParam(
                str,
                required=True,
                doc="comma-separated shells matching elements, 'K'|'L', e.g. 'L,K'",
            ),
            "z": OpParam(
                str,
                required=True,
                doc="comma-separated atomic numbers matching elements, e.g. '26,8'",
            ),
            "onset_ev": OpParam(
                str, required=True, doc="comma-separated edge onsets (eV), e.g. '708,532'"
            ),
            "signal_windows": OpParam(
                str,
                required=True,
                doc="comma-separated 'lo:hi' signal windows (eV), "
                "e.g. '708:758,532:582' (unused by the fit itself, "
                "kept for parity with eels_quantify's edge schema)",
            ),
            "bg_windows": OpParam(
                str,
                required=True,
                doc="comma-separated 'lo:hi' pre-edge windows (eV); the "
                "first edge's lower bound seeds the default fit range",
            ),
            "e0_kv": OpParam(float, 200.0, minimum=0.0, doc="beam energy (kV)"),
            "beta_mrad": OpParam(float, 10.0, minimum=0.0, doc="collection semi-angle (mrad)"),
            "fit_range_lo": OpParam(
                float,
                float("nan"),
                doc="fit window lower edge (eV); leave unset (with "
                "fit_range_hi) to use the resolved default",
            ),
            "fit_range_hi": OpParam(float, float("nan"), doc="fit window upper edge (eV)"),
        },
        fn=_eels_fit_map,
    )
)


# ── batch species maps ────────────────────────────────────────────────


def _eels_maps(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    """N species → N background-subtracted rasters, without going through
    quantification (calc/eels_species_maps.species_maps — the wave-D lift
    shared with /eels/maps).

    Two documented narrowings of the route's request model (§4's CSV
    flattening cannot express the nested per-species model; both mirror
    the shipped eds_element_maps divergence precedent):

    - ``bg_windows`` is all-or-nothing: an empty string means NO
      background fit for ALL species; otherwise it must parse to one
      'lo:hi' window per species. A blank entry cannot express
      per-species "none".
    - ``method`` is a single shared choice applied to every species; the
      route allows a per-species method.

    ``save_derived`` (session image registration) is session-specific and
    dropped — the maps inline as envelopes instead. Per-species failures
    keep the route's semantics: a failed species keeps its row in the
    "species" table with its reason string (numeric cells null) and emits
    no map envelope; the op itself does not raise.
    """
    _require_cube(ds, "eels_maps")
    labels = split_csv(params["labels"])
    if not labels:
        raise ValueError("eels_maps: 'labels' must list at least one species")
    sig_windows = parse_windows(params["signal_windows"])
    if len(sig_windows) != len(labels):
        raise ValueError(
            f"eels_maps: labels and signal_windows must list the same number "
            f"of species (got {len(labels)} vs {len(sig_windows)})"
        )
    bg_windows: list[tuple[float, float] | None]
    if not params["bg_windows"].strip():
        bg_windows = [None] * len(labels)
    else:
        parsed = parse_windows(params["bg_windows"])
        if len(parsed) != len(labels):
            raise ValueError(
                f"eels_maps: bg_windows must be empty (no background fit for "
                f"any species) or list one 'lo:hi' window per species "
                f"(got {len(parsed)} for {len(labels)} species)"
            )
        bg_windows = list(parsed)
    _check_unique_names(labels, {"species"}, "eels_maps")

    rows = species_maps(
        ds.data,
        ds.energy_axis,
        [
            SpeciesSpec(
                label=label,
                signal_window=sig_windows[i],
                bg_window=bg_windows[i],
                method=params["method"],
            )
            for i, label in enumerate(labels)
        ],
    )

    outputs: list[dict[str, Any]] = []
    table_rows: list[list[Any]] = []
    for row in rows:
        if row.error is not None:
            table_rows.append([row.label, None, None, None, None, None, row.error])
            continue
        assert row.map is not None and row.signal_window is not None
        outputs.append(
            output(
                "map",
                row.label,
                {
                    "values": _nan_none_raster(row.map),
                    "quantity": "background-subtracted counts",
                },
            )
        )
        bg_lo, bg_hi = row.bg_window if row.bg_window is not None else (None, None)
        table_rows.append(
            [
                row.label,
                row.signal_window[0],
                row.signal_window[1],
                bg_lo,
                bg_hi,
                row.total_counts,
                None,
            ]
        )
    outputs.append(
        output(
            "table",
            "species",
            {
                "columns": [
                    "label",
                    "signal_lo",
                    "signal_hi",
                    "bg_lo",
                    "bg_hi",
                    "total_counts",
                    "error",
                ],
                "units": ["", "eV", "eV", "eV", "eV", "", ""],
                "rows": table_rows,
            },
        )
    )
    return OpResult(
        op="eels_maps",
        params=params,
        label="EELS batch species maps",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eels_maps",
        category="eels",
        produces_value=True,
        summary="Batch background-subtracted species maps over an SI cube "
        "(calc/eels_species_maps.species_maps) — one H×W map "
        "envelope per successful species plus a per-species status "
        "table (failed species keep their reason, the op never "
        "raises for them); large cubes make large payloads. "
        "bg_windows is all-or-nothing and method is shared across "
        "species — see the op docstring",
        params={
            "labels": OpParam(
                str,
                required=True,
                doc="comma-separated species labels, e.g. 'Fe-L23,O-K' (free text; must be unique)",
            ),
            "signal_windows": OpParam(
                str,
                required=True,
                doc="comma-separated 'lo:hi' signal windows (eV), "
                "one per label, e.g. '708:758,532:582'",
            ),
            "bg_windows": OpParam(
                str,
                "",
                doc="comma-separated 'lo:hi' pre-edge fit windows (eV), "
                "one per label; empty = direct window sum (no "
                "background fit) for ALL species — a blank entry "
                "cannot express per-species none",
            ),
            "method": _METHOD,
        },
        fn=_eels_maps,
    )
)
