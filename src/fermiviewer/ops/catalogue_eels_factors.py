"""EELS cross-section derivation as a registered operation (ADR 0011).

The EDS sibling is `ops/catalogue_eds_factors.py`, and the same reason
applies: `POST /factors/derive-eels` accepts a stored `standard_id`,
which resolves only on the machine holding that standard, so the op takes
the composition INLINE and stays replayable.

`produces_value=True`: a set of cross-sections is a table of numbers, not
a derived image.
"""

from __future__ import annotations

from typing import Any

from fermiviewer.calc.composition import atomic_fractions
from fermiviewer.calc.eels_factors import derive_cross_sections
from fermiviewer.calc.eels_quant import ElementEdge, quantify
from fermiviewer.calc.raster import masked_sum_spectrum
from fermiviewer.calc.uncertainty import eels_intensity_sigma
from fermiviewer.datastruct import SPECTRAL_KINDS, DataKind, DataStruct
from fermiviewer.ops._envelopes import output
from fermiviewer.ops._parsing import split_csv
from fermiviewer.ops._region_param import REGION_PARAM, region_from_params
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []

_EDGE_HELP = (
    "'Symbol:shell:Z:onset_eV:sigLo-sigHi:bgLo-bgHi', e.g. "
    "'Fe:L:26:708:700-800:600-690'"
)


def _window(raw: str, what: str) -> tuple[float, float]:
    lo, sep, hi = raw.partition("-")
    if not sep:
        raise ValueError(f"{what} {raw!r} must be 'lo-hi' in eV")
    try:
        pair = (float(lo), float(hi))
    except ValueError:
        raise ValueError(f"{what} {raw!r} has a non-numeric bound") from None
    if not pair[1] > pair[0]:
        raise ValueError(f"{what} {raw!r} must have hi > lo")
    return pair


def _edges(raw: str) -> list[ElementEdge]:
    """``"Fe:L:26:708:700-800:600-690,O:K:8:532:..."`` -> edges.

    Flat strings because an op param is a scalar by contract; the route
    takes a list of objects. Every field is required — a defaulted window
    would put a number in the answer that the caller never chose.
    """
    out: list[ElementEdge] = []
    for item in split_csv(raw):
        parts = item.split(":")
        if len(parts) != 6:
            raise ValueError(f"edge {item!r} must be {_EDGE_HELP}")
        symbol, shell, z_raw, onset_raw, sig_raw, bg_raw = (p.strip() for p in parts)
        if shell not in ("K", "L"):
            raise ValueError(f"edge {item!r}: shell must be 'K' or 'L'")
        try:
            z, onset = int(z_raw), float(onset_raw)
        except ValueError:
            raise ValueError(f"edge {item!r} has a non-numeric Z or onset") from None
        if not onset > 0:
            raise ValueError(f"edge {item!r}: onset must be positive")
        out.append(
            ElementEdge(
                element=symbol,
                shell=shell,
                z=z,
                onset_ev=onset,
                signal_window=_window(sig_raw, f"edge {item!r} signal window"),
                bg_window=_window(bg_raw, f"edge {item!r} background window"),
            )
        )
    if not out:
        raise ValueError("eels_derive_cross_sections needs at least one edge")
    symbols = [e.element for e in out]
    dupes = sorted({s for s in symbols if symbols.count(s) > 1})
    if dupes:
        raise ValueError(
            f"give one edge per element; {dupes} appear more than once and there "
            "is no way to say which σ the element's fraction belongs to"
        )
    return out


def _composition(raw: str, elements: list[str]) -> dict[str, float]:
    """``"Fe:70,Cr:30"`` -> ``{"Fe": 70.0, "Cr": 30.0}``."""
    out: dict[str, float] = {}
    for item in split_csv(raw):
        symbol, sep, value = item.partition(":")
        if not sep:
            raise ValueError(
                f"composition entry {item!r} must be 'Symbol:percent', e.g. 'Fe:70'"
            )
        try:
            out[symbol.strip()] = float(value)
        except ValueError:
            raise ValueError(
                f"composition entry {item!r} has a non-numeric percent"
            ) from None
    missing = [s for s in elements if s not in out]
    if missing:
        raise ValueError(f"composition states nothing for {missing}")
    return out


def _eels_derive_cross_sections(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError(
            f"eels_derive_cross_sections requires spectral input (got {ds.kind.value})"
        )
    edges = _edges(params["edges"])
    elements = [e.element for e in edges]
    pct = _composition(params["composition"], elements)
    basis = params["basis"]
    if basis not in ("wt", "at"):
        raise ValueError("basis must be 'wt' or 'at'")
    # ATOMIC, not weight: `eels_quant.quantify` reports at%, so this is
    # the basis its inversion is defined on (calc/composition)
    af, _sig = atomic_fractions({s: pct[s] for s in elements}, basis)

    # Inline geometry, per ADR 0007 §11 — a recipe carrying a region
    # replays on a machine with no project.
    scoped = region_from_params(params, ds.data.shape[:2])
    if scoped is not None and ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise ValueError("a region needs a spectrum-image cube")
    spectrum = (
        ds.sum_spectrum()
        if scoped is None
        else masked_sum_spectrum(ds.data, scoped.rect, scoped.mask)
    )

    # raw eV axis, matching /eels/quantify and the route (see there)
    res = quantify(
        ds.energy_axis,
        spectrum,
        edges,
        params["beam_kv"],
        params["collection_semi_angle_mrad"],
        params["background"],
    )
    net_sigma = eels_intensity_sigma(
        ds.energy_axis, spectrum, [e.signal_window for e in edges]
    )
    anchor = float(params["reference_value_m2"])
    derived, reference = derive_cross_sections(
        elements,
        res.intensity.tolist(),
        res.sigma.tolist(),
        af,
        intensity_sigma=list(net_sigma),
        reference=params["reference_element"] or None,
        reference_value_m2=anchor if anchor > 0 else None,
    )
    rows = [
        [
            f.element,
            f.value,
            f.sigma,
            f.model_value,
            f.intensity,
            f.intensity_sigma,
            f.atomic_fraction,
        ]
        for f in derived
    ]
    return OpResult(
        op="eels_derive_cross_sections",
        params=params,
        label="experimental EELS cross-sections",
        value={
            "outputs": [
                output(
                    "table",
                    "cross_sections",
                    {
                        "columns": [
                            "element",
                            "cross_section",
                            "cross_section_sigma",
                            "model_cross_section",
                            "net_intensity",
                            "net_intensity_sigma",
                            "atomic_fraction",
                        ],
                        "units": [
                            "",
                            "m2",
                            "m2",
                            "m2",
                            "counts",
                            "counts",
                            "",
                        ],
                        "rows": rows,
                    },
                ),
            ],
            # a NAME, not a number, so it rides here rather than in a
            # scalar envelope that would encode it as a list index
            "reference_element": reference,
            "kind": "sigma",
        },
    )


register(
    OpSpec(
        name="eels_derive_cross_sections",
        category="eels",
        produces_value=True,
        summary="Experimental EELS partial cross-sections derived by measuring "
        "a standard of known composition (calc/eels_factors). Inverting "
        "quantify's N ∝ I/σ gives σ_i ∝ I_i/a_i, on the ATOMIC basis — the "
        "opposite of the weight basis Cliff-Lorimer uses. Only RATIOS are "
        "measurable, so the absolute scale is anchored to the reference "
        "element's hydrogenic σ unless one is supplied. The composition is "
        "stated INLINE rather than by stored id so the step replays on any "
        "machine (ADR 0011)",
        params={
            "edges": OpParam(
                str,
                "",
                doc=f"comma-separated edges, each {_EDGE_HELP}; one per element",
            ),
            "composition": OpParam(
                str,
                "",
                doc="the standard's certified composition as 'Symbol:percent' "
                "pairs, e.g. 'Fe:70,Cr:30'; every measured element must appear",
            ),
            "basis": OpParam(
                str,
                "wt",
                doc="'wt' or 'at' — which basis the percentages are on. NOT "
                "interchangeable: wt% is converted by a ∝ w/M, and reading one "
                "as the other is an error of tens of percent for a pair with "
                "dissimilar masses",
            ),
            "reference_element": OpParam(
                str,
                "",
                doc="which element defines the absolute scale; empty picks the "
                "major one, whose relative counting error is smallest",
            ),
            "reference_value_m2": OpParam(
                float,
                0.0,
                minimum=0.0,
                doc="an independently known σ for the reference element (m²); "
                "0 means use the hydrogenic model's own value, and the set's "
                "absolute scale is then only as good as that model was for "
                "that one edge",
            ),
            "region": REGION_PARAM,
            "beam_kv": OpParam(
                float, 200.0, minimum=0.0, doc="beam energy (kV) for the σ model"
            ),
            "collection_semi_angle_mrad": OpParam(
                float,
                10.0,
                minimum=0.0,
                doc="spectrometer collection semi-angle β. σ depends on it "
                "strongly and in an energy-dependent way, so a set derived at "
                "the wrong β is wrong by more at higher-energy edges",
            ),
            "background": OpParam(
                str,
                "powerlaw",
                doc="'powerlaw' | 'exponential' — must match what "
                "/factors/derive-eels uses, or the same data yields different "
                "net intensities and so different cross-sections",
            ),
        },
        fn=_eels_derive_cross_sections,
    )
)
