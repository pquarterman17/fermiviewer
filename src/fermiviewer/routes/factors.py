"""Derive, store and compare experimental factor sets (roadmap 5b).

`POST /factors/derive` measures a standard's reference region, inverts
the quantification the repo already ships, and stores the result with
enough provenance to say what it is a factor FOR. Reading, comparing and
transferring stored sets lives in `routes/factors_store.py`: deriving is
a MEASUREMENT and needs the peak-fit stack, while those are arithmetic
over numbers already stored.

Split from `routes/standards.py` for the same reason — listing standards
should not pull the fitter in.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.eds_factors import (
    DerivedFactor,
    derive_k_factors,
    derive_zeta_factors,
    weight_fractions,
)
from fermiviewer.calc.eds_qc import (
    check_counting_statistics,
    check_fit_quality,
    check_peak_interference,
    check_resolved_parameters,
    findings_to_json,
)
from fermiviewer.calc.eds_zeta import dose_electrons
from fermiviewer.calc.energy_units import to_kev
from fermiviewer.io.factors_db import (
    FactorSetError,
    create_factor_set,
    factor_set_to_json,
)
from fermiviewer.io.standards_model import Standard, StandardError
from fermiviewer.routes._eds_common import (
    background_component,
    fit_summed_peaks,
    spectral_dataset,
)
from fermiviewer.routes._eds_params import (
    provenance_block,
    resolve_beam_kv,
    resolve_eds_param,
    resolve_live_time_s,
)
from fermiviewer.routes._factors_common import (
    measurement_scope,
    resolved_standard,
    scoped_spectrum,
)

router = APIRouter(prefix="/api")

class FactorDeriveRequest(BaseModel):
    """Either name a stored standard, or state its composition inline.

    Inline exists so a derivation is PORTABLE: a stored id resolves only
    on the machine holding that standard, which makes a recorded run
    un-replayable elsewhere and is why the registered op takes the
    composition rather than the id.
    """

    standard_id: str | None = None
    #: inline alternative to `standard_id` — element symbol -> percent
    composition: dict[str, float] | None = None
    basis: Literal["wt", "at"] | None = None
    mass_thickness_kg_m2: float | None = None
    #: the measurement. Omit `image_id` to use the standard's stored
    #: reference region named by `region_label`.
    image_id: str | None = None
    region_label: str | None = None
    region: str | None = None
    roi: str | None = None
    #: which elements to measure; defaults to every element the standard
    #: states a composition for
    elements: list[str] | None = None
    kind: Literal["k", "zeta"] = "k"
    #: k only — defaults to Si when the standard contains it, else the
    #: major element (see `derive_k_factors`)
    reference_element: str | None = None
    background: str = "linear"
    e0_kev: float | None = None
    weights: str | None = "poisson"
    #: acquisition parameters; `None` means the applied profile supplies
    #: it, then the route default (ADR 0010 §2)
    beam_kv: float | None = None
    probe_current_na: float | None = None
    live_time_s: float | None = None
    #: store the derived set, or just report it. Off by default: deriving
    #: is exploratory until the user says otherwise, the same call the
    #: `record` flag makes on /eds/quantify.
    store: bool = False
    name: str = ""
    note: str = ""


def _measure(
    req: FactorDeriveRequest, std: Standard
) -> tuple[Any, Any, dict, list[str], str, dict[str, Any]]:
    """Fit the standard's reference spectrum and return the pieces every
    derivation needs: the fit, the resolved calibration, the element
    order, the image actually measured, and the region scope applied.

    The measured image is returned rather than re-read from the request
    because `region_label` resolves to one and the request's own
    `image_id` is then None -- recording that would give a factor set a
    null provenance for the one thing it is a factor for.
    """
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
        "probe_current_na": resolve_eds_param(
            ds.metadata, "probe_current_na", req.probe_current_na
        ),
        "live_time_s": resolve_live_time_s(ds.metadata, req.live_time_s),
    }
    elements = list(req.elements) if req.elements else sorted(std.composition)
    missing = [s for s in elements if s not in std.composition]
    if missing:
        raise HTTPException(
            422, f"the standard states no composition for {missing}"
        )
    energy = to_kev(ds.energy_axis, ds.energy_cal.units)
    spectrum, scope = scoped_spectrum(ds, image_id, region_ref, roi_ref)
    pf, _ = fit_summed_peaks(
        energy,
        spectrum,
        elements,
        beam_kv=cal["beam_kv"].value,
        background=background_component(req.background, req.e0_kev),
        weights=req.weights,
        center_tol_kev=0.0,
        strip_artifacts=False,
        escape_fraction=0.0,
    )
    return pf, ds, cal, elements, image_id, scope


def _factor_json(f: DerivedFactor) -> dict[str, Any]:
    return {
        "value": f.value,
        "sigma": f.sigma,
        "intensity": f.intensity,
        "intensity_sigma": f.intensity_sigma,
        "weight_fraction": f.weight_fraction,
        "weight_fraction_sigma": f.weight_fraction_sigma,
    }


@router.post("/factors/derive")
def factors_derive(req: FactorDeriveRequest) -> dict[str, Any]:
    """Derive a k or ζ factor set by measuring a known standard."""
    std = resolved_standard(
        req.standard_id, req.composition, req.basis, req.mass_thickness_kg_m2
    )
    pf, ds, cal, elements, image_id, scope = _measure(req, std)

    pct = {sym: std.composition[sym].value for sym in elements}
    sig = {
        sym: std.composition[sym].sigma or 0.0
        for sym in elements
        if std.composition[sym].sigma is not None
    }
    try:
        wf, wf_sigma = weight_fractions(pct, std.basis, sigma_pct=sig)
    except (ValueError, StandardError) as exc:
        raise HTTPException(422, str(exc)) from None

    net = [max(float(pf.net_areas[s]), 0.0) for s in elements]
    net_sigma = [float(pf.net_area_errors[s]) for s in elements]

    try:
        if req.kind == "zeta":
            if std.mass_thickness is None:
                raise HTTPException(
                    422,
                    "ζ needs the standard's certified mass-thickness; there is no way "
                    "to infer it that does not invent the answer",
                )
            dose = dose_electrons(cal["probe_current_na"].value, cal["live_time_s"].value)
            derived = derive_zeta_factors(
                elements,
                net,
                wf,
                mass_thickness_kg_m2=std.mass_thickness.value,
                dose_electrons=dose,
                intensity_sigma=net_sigma,
                weight_fraction_sigma=wf_sigma,
                mass_thickness_sigma=std.mass_thickness.sigma or 0.0,
            )
            reference = ""
        else:
            derived, reference = derive_k_factors(
                elements,
                net,
                wf,
                intensity_sigma=net_sigma,
                weight_fraction_sigma=wf_sigma,
                reference=req.reference_element,
            )
            dose = float("nan")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    findings = [
        *check_counting_statistics(elements, net, net_sigma),
        *check_peak_interference(elements, beam_kv=cal["beam_kv"].value),
        *check_fit_quality(reduced_chi2=pf.fit.reduced_chi2),
        *check_resolved_parameters(provenance_block(cal)),
    ]

    conditions = {
        "beam_kv": cal["beam_kv"].value,
        **({"dose_electrons": dose} if req.kind == "zeta" else {}),
    }
    derived_from = {
        "standard_id": std.id,
        "standard_version": std.version,
        "standard_name": std.name,
        "basis": std.basis,
        # the image actually measured, not the request's (which is None
        # when a stored reference region supplied it)
        "image_id": image_id,
        "region_label": req.region_label,
        # the scope ACTUALLY applied (a stored reference region supplies
        # its own when the request names none), and what it selected --
        # so the record says how many pixels the factor came from, not
        # merely which string asked
        "region": scope["region"],
        "roi": scope["roi"],
        "scope": scope,
    }
    body: dict[str, Any] = {
        "kind": req.kind,
        "reference_element": reference,
        "elements": elements,
        "factors": {f.element: _factor_json(f) for f in derived},
        "conditions": conditions,
        "derived_from": derived_from,
        "calibration": provenance_block(cal),
        "reduced_chi2": pf.fit.reduced_chi2,
        "qc": findings_to_json(findings),
    }
    if req.store:
        try:
            fs = create_factor_set(
                name=req.name or f"{std.name} {req.kind} @ {cal['beam_kv'].value:g} kV",
                kind=req.kind,
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
