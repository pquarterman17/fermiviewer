"""Experimental factor derivation as a registered operation (ADR 0011).

`POST /factors/derive` accepts a stored `standard_id`, which resolves only
on the machine holding that standard. An op has to be REPLAYABLE — a
recipe is a portable record, and a step naming a per-user store id is not
one — so this op takes the composition inline instead, which is the same
path the route offers and the same `standards_model` validation.

That is why the profile and standard STORES have no ops (they are
per-user state) while this does: the derivation is a calculation over a
spectrum, and the standard is one of its inputs, not a place.

`produces_value=True`: a factor set is a table of numbers, not a derived
image.
"""

from __future__ import annotations

from typing import Any

from fermiviewer.calc.eds_factors import derive_k_factors, derive_zeta_factors, weight_fractions
from fermiviewer.calc.eds_peakfit import fit_peaks
from fermiviewer.calc.eds_zeta import dose_electrons
from fermiviewer.calc.energy_units import to_kev
from fermiviewer.datastruct import SPECTRAL_KINDS, DataStruct
from fermiviewer.ops._envelopes import output
from fermiviewer.ops._parsing import split_csv
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


def _composition(raw: str, elements: list[str]) -> dict[str, float]:
    """``"Fe:70,Cr:30"`` -> ``{"Fe": 70.0, "Cr": 30.0}``.

    A flat string because an op param is a scalar by contract; the route
    takes a mapping. Every measured element must appear — a derivation
    against a composition that omits one silently drops it from the set.
    """
    out: dict[str, float] = {}
    for item in split_csv(raw):
        symbol, _, value = item.partition(":")
        if not _:
            raise ValueError(
                f"composition entry {item!r} must be 'Symbol:percent', e.g. 'Fe:70'"
            )
        try:
            out[symbol.strip()] = float(value)
        except ValueError:
            raise ValueError(f"composition entry {item!r} has a non-numeric percent") from None
    missing = [s for s in elements if s not in out]
    if missing:
        raise ValueError(f"composition states nothing for {missing}")
    return out


def _eds_derive_factors(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError(f"eds_derive_factors requires spectral input (got {ds.kind.value})")
    elements = split_csv(params["elements"])
    if not elements:
        raise ValueError("eds_derive_factors needs at least one element")
    pct = _composition(params["composition"], elements)
    basis = params["basis"]
    if basis not in ("wt", "at"):
        raise ValueError("basis must be 'wt' or 'at'")
    wf, _sig = weight_fractions({s: pct[s] for s in elements}, basis)

    energy = to_kev(ds.energy_axis, ds.energy_cal.units)
    pf = fit_peaks(
        energy, ds.sum_spectrum(), elements, beam_kv=params["beam_kv"], background=None
    )
    net = [max(float(pf.net_areas[s]), 0.0) for s in elements]
    net_sigma = [float(pf.net_area_errors[s]) for s in elements]

    kind = params["kind"]
    if kind == "zeta":
        rho_t = float(params["mass_thickness_kg_m2"])
        if not rho_t > 0:
            raise ValueError("ζ needs a positive certified mass-thickness")
        dose = dose_electrons(params["probe_current_na"], params["live_time_s"])
        derived = derive_zeta_factors(
            elements,
            net,
            wf,
            mass_thickness_kg_m2=rho_t,
            dose_electrons=dose,
            intensity_sigma=net_sigma,
        )
        reference = ""
    elif kind == "k":
        derived, reference = derive_k_factors(
            elements, net, wf, intensity_sigma=net_sigma,
            reference=params["reference_element"] or None,
        )
    else:
        raise ValueError("kind must be 'k' or 'zeta'")

    unit = "kg/m2" if kind == "zeta" else ""
    rows = [
        [
            f.element,
            f.value,
            f.sigma,
            f.intensity,
            f.intensity_sigma,
            f.weight_fraction,
        ]
        for f in derived
    ]
    return OpResult(
        op="eds_derive_factors",
        params=params,
        label=f"experimental {kind} factors",
        value={
            "outputs": [
                output(
                    "table",
                    "factors",
                    {
                        "columns": [
                            "element",
                            "factor",
                            "factor_sigma",
                            "net_intensity",
                            "net_intensity_sigma",
                            "weight_fraction",
                        ],
                        "units": [
                            "",
                            unit,
                            unit,
                            "counts",
                            "counts",
                            "",
                        ],
                        "rows": rows,
                    },
                ),
            ],
            # the reference element is a NAME, not a number, so it rides
            # here rather than in a scalar envelope that would have to
            # encode it as an index into the element list
            "reference_element": reference,
            "kind": kind,
        },
    )


register(
    OpSpec(
        name="eds_derive_factors",
        category="eds",
        produces_value=True,
        summary="Experimental Cliff-Lorimer k or Watanabe ζ factors derived by "
        "measuring a standard of known composition (calc/eds_factors). "
        "k_i ∝ w_i/I_i normalised to a reference element; "
        "ζ_i = C_i·ρt·D_e/I_i, which additionally needs the standard's "
        "certified mass-thickness and the electron dose. The composition "
        "is stated INLINE rather than by stored id so the step replays on "
        "any machine (ADR 0011)",
        params={
            "elements": OpParam(
                str, "", doc="comma-separated element symbols to measure, e.g. 'Fe,Cr'"
            ),
            "composition": OpParam(
                str,
                "",
                doc="the standard's certified composition as "
                "'Symbol:percent' pairs, e.g. 'Fe:70,Cr:30'; every measured "
                "element must appear",
            ),
            "basis": OpParam(
                str,
                "wt",
                doc="'wt' or 'at' — which basis the percentages are on. NOT "
                "interchangeable: at% is converted by w ∝ a·M, and reading "
                "one as the other is an error of tens of percent for a pair "
                "with dissimilar masses",
            ),
            "kind": OpParam(str, "k", doc="'k' (dimensionless, relative) or 'zeta' (absolute)"),
            "reference_element": OpParam(
                str,
                "",
                doc="k only: which element is defined as 1.0; empty picks Si "
                "when present (matching the built-in table) else the major "
                "element",
            ),
            "beam_kv": OpParam(
                float, 200.0, minimum=0.0, doc="beam energy (kV), selects K/L/M lines"
            ),
            "mass_thickness_kg_m2": OpParam(
                float,
                0.0,
                minimum=0.0,
                doc="ζ only: the standard's certified mass-thickness. There is "
                "no way to infer it that does not invent the answer, so ζ "
                "without it is an error",
            ),
            "probe_current_na": OpParam(
                float, 1.0, minimum=0.0, doc="ζ only: beam current for the dose integral"
            ),
            "live_time_s": OpParam(
                float, 100.0, minimum=0.0, doc="ζ only: live time for the dose integral"
            ),
        },
        fn=_eds_derive_factors,
    )
)
