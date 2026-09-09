"""`POST /factors/derive-eels` — EELS partial cross-sections from a
standard (roadmap 5b, the EELS half of the factor box).

The EDS counterpart lives in `routes/factors.py`. This is a separate
module rather than another `kind` on that route because the two
derivations share almost nothing past the standard: this one wants edges
(onset, signal and background windows), a collection semi-angle and an
atomic-basis composition, where that one wants element symbols, a peak
fit and a weight-basis composition. Folding them together would give one
request model whose every field is conditional on `kind`, which is the
shape that lets a user send a well-formed request that is silently
ignored.

What the two DO share -- resolving the standard and the pixels -- is in
`routes/_factors_common.py`, so a `region_label` cannot come to mean two
different things.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.composition import atomic_fractions
from fermiviewer.calc.eels_factors import DerivedCrossSection, derive_cross_sections
from fermiviewer.calc.eels_quant import ElementEdge, quantify
from fermiviewer.calc.uncertainty import eels_intensity_sigma
from fermiviewer.io.factors_db import (
    FactorSetError,
    create_factor_set,
    factor_set_to_json,
)
from fermiviewer.io.standards_model import StandardError
from fermiviewer.routes._eds_common import spectral_dataset
from fermiviewer.routes._eds_params import (
    ParamSpec,
    provenance_block,
    resolve_beam_kv,
    resolve_spec,
)
from fermiviewer.routes._factors_common import (
    measurement_scope,
    resolved_standard,
    scoped_spectrum,
)

router = APIRouter(prefix="/api")

#: The one acquisition parameter an applied profile supplies here. σ
#: depends on it strongly -- the angular term is a log of (β/θ_E)² -- so
#: a set derived at the wrong β is wrong by an amount that grows with
#: edge energy, and silently.
BETA_PARAM = ParamSpec(
    unit="mrad",
    candidates=(("detector", "collection_semi_angle"),),
    default=10.0,  # matches /eels/quantify's own literal
    gt=0.0,
)


class EelsEdgeSpec(BaseModel):
    element: str
    shell: Literal["K", "L"]
    z: int
    onset_ev: float
    signal_window: tuple[float, float]
    bg_window: tuple[float, float]


class CrossSectionDeriveRequest(BaseModel):
    """Either name a stored standard, or state its composition inline.

    Inline exists for the same reason it does on `/factors/derive`: a
    stored id resolves only on the machine holding that standard, so a
    recorded run is otherwise un-replayable elsewhere.
    """

    standard_id: str | None = None
    #: inline alternative to `standard_id` — element symbol -> percent
    composition: dict[str, float] | None = None
    basis: Literal["wt", "at"] | None = None
    #: the measurement. Omit `image_id` to use the standard's stored
    #: reference region named by `region_label`.
    image_id: str | None = None
    region_label: str | None = None
    region: str | None = None
    roi: str | None = None
    #: one per element to derive; the standard must state a composition
    #: for each
    edges: list[EelsEdgeSpec]
    #: which element defines the absolute scale; defaults to the major
    #: one (see `calc.eels_factors.derive_cross_sections`)
    reference_element: str | None = None
    #: an independently known σ for the reference, in m². Without it the
    #: hydrogenic model supplies the anchor and the set's absolute scale
    #: is only as good as the model was for that one edge.
    reference_value_m2: float | None = Field(default=None, gt=0)
    reference_value_sigma: float = Field(default=0.0, ge=0)
    method: str = "powerlaw"
    #: `None` means the applied profile supplies it, then the route
    #: default (ADR 0010 §2)
    beam_kv: float | None = None
    collection_semi_angle_mrad: float | None = None
    store: bool = False
    name: str = ""
    note: str = ""


def _factor_json(f: DerivedCrossSection) -> dict[str, Any]:
    return {
        "value": f.value,
        "sigma": f.sigma,
        "model_value": f.model_value,
        "intensity": f.intensity,
        "intensity_sigma": f.intensity_sigma,
        "atomic_fraction": f.atomic_fraction,
        "atomic_fraction_sigma": f.atomic_fraction_sigma,
    }


@router.post("/factors/derive-eels")
def factors_derive_eels(req: CrossSectionDeriveRequest) -> dict[str, Any]:
    """Derive EELS partial cross-sections by measuring a known standard."""
    if not req.edges:
        raise HTTPException(422, "give at least one edge to derive a cross-section for")
    std = resolved_standard(req.standard_id, req.composition, req.basis)
    image_id, region_ref, roi_ref = measurement_scope(
        std,
        image_id=req.image_id,
        region_label=req.region_label,
        region=req.region,
        roi=req.roi,
    )
    ds = spectral_dataset(image_id)
    cal = {
        "beam_kv": resolve_beam_kv(ds.metadata, req.beam_kv),
        "collection_semi_angle_mrad": resolve_spec(
            ds.metadata,
            "collection_semi_angle_mrad",
            BETA_PARAM,
            req.collection_semi_angle_mrad,
        ),
    }

    elements = [e.element for e in req.edges]
    dupes = sorted({s for s in elements if elements.count(s) > 1})
    if dupes:
        raise HTTPException(
            422,
            f"give one edge per element; {dupes} appear more than once and there is "
            "no way to say which σ the element's fraction belongs to",
        )
    missing = [s for s in elements if s not in std.composition]
    if missing:
        raise HTTPException(422, f"the standard states no composition for {missing}")

    pct = {sym: std.composition[sym].value for sym in elements}
    sig = {
        sym: std.composition[sym].sigma or 0.0
        for sym in elements
        if std.composition[sym].sigma is not None
    }
    try:
        # ATOMIC, not weight: `eels_quant.quantify` reports at%, so this
        # is the basis its inversion is defined on (calc.composition)
        af, af_sigma = atomic_fractions(pct, std.basis, sigma_pct=sig)
    except (ValueError, StandardError) as exc:
        raise HTTPException(422, str(exc)) from None

    spectrum, scope = scoped_spectrum(ds, image_id, region_ref, roi_ref)
    edges = [
        ElementEdge(
            e.element, e.shell, e.z, e.onset_ev, e.signal_window, e.bg_window
        )
        for e in req.edges
    ]
    # `ds.energy_axis` raw, in eV -- the same axis /eels/quantify passes,
    # deliberately without the `to_kev` conversion the EDS derivation
    # applies. Converting here and not there would make the two disagree
    # about the same data, which is worse than sharing one assumption.
    try:
        res = quantify(
            ds.energy_axis,
            spectrum,
            edges,
            cal["beam_kv"].value,
            cal["collection_semi_angle_mrad"].value,
            req.method,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    # counting-statistics 1σ on each edge intensity, from the same helper
    # /eels/quantify's at% error is built on -- so the two cannot report
    # different errors for one measurement
    net_sigma = eels_intensity_sigma(
        ds.energy_axis, spectrum, [e.signal_window for e in edges]
    )
    try:
        derived, reference = derive_cross_sections(
            elements,
            res.intensity.tolist(),
            res.sigma.tolist(),
            af,
            intensity_sigma=list(net_sigma),
            atomic_fraction_sigma=af_sigma,
            reference=req.reference_element,
            reference_value_m2=req.reference_value_m2,
            reference_value_sigma=req.reference_value_sigma,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    conditions = {
        "beam_kv": cal["beam_kv"].value,
        "collection_semi_angle_mrad": cal["collection_semi_angle_mrad"].value,
        # σ is integrated over the signal window, so a set derived with
        # one window is not a set for another — the windows are part of
        # what the numbers ARE, not merely how they were obtained
        "windows": {
            e.element: {
                "onset_ev": e.onset_ev,
                "shell": e.shell,
                "signal_window": list(e.signal_window),
                "bg_window": list(e.bg_window),
            }
            for e in req.edges
        },
        "background_method": req.method,
    }
    derived_from = {
        "standard_id": std.id,
        "standard_version": std.version,
        "standard_name": std.name,
        "basis": std.basis,
        "image_id": image_id,
        "region_label": req.region_label,
        "region": scope["region"],
        "roi": scope["roi"],
        "scope": scope,
        "anchor": (
            "request"
            if req.reference_value_m2 is not None
            else "hydrogenic model (calc.eels_quant.cross_section)"
        ),
    }
    body: dict[str, Any] = {
        "kind": "sigma",
        "reference_element": reference,
        "elements": elements,
        "factors": {f.element: _factor_json(f) for f in derived},
        "model_ratio": {f.element: f.model_ratio for f in derived},
        "conditions": conditions,
        "derived_from": derived_from,
        "calibration": provenance_block(cal),
    }
    if req.store:
        try:
            fs = create_factor_set(
                name=req.name
                or f"{std.name} σ @ {cal['beam_kv'].value:g} kV",
                kind="sigma",
                factors=body["factors"],
                reference_element=reference,
                conditions=conditions,
                derived_from=derived_from,
                provenance={"source": "derived from standard", "note": req.note},
                note=req.note,
            )
        except FactorSetError as exc:
            raise HTTPException(422, str(exc)) from None
        body["factor_set"] = factor_set_to_json(fs)
    return body
