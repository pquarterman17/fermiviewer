"""Derive, store and compare experimental factor sets (roadmap 5b).

`POST /factors/derive` measures a standard's reference region, inverts
the quantification the repo already ships, and stores the result with
enough provenance to say what it is a factor FOR. `GET /factors/compare`
puts a stored set beside the built-in table WITHOUT either replacing the
other — the roadmap box is explicit about that, and it is the right call:
a large disagreement is information about the instrument, and silently
adopting one number hides it.

Split from `routes/standards.py` because deriving needs the peak-fit
stack and listing standards should not pull it in.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.eds import K_FACTORS_200KV
from fermiviewer.calc.eds_factors import (
    DerivedFactor,
    derive_k_factors,
    derive_zeta_factors,
    transfer_zeta,
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
    FactorSet,
    FactorSetError,
    create_factor_set,
    delete_factor_set,
    factor_set_to_json,
    get_factor_set,
    list_factor_sets,
)
from fermiviewer.io.standards_db import get_standard
from fermiviewer.io.standards_model import Standard, StandardError, standard_from_json
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

router = APIRouter(prefix="/api")

#: The built-in table's voltage. It is not recorded anywhere the table is
#: USED, which is the extrapolation `eds_qc.check_factor_conditions`
#: exists to surface; naming it here is what lets a comparison say which
#: voltage each side belongs to.
BUILTIN_K_KV = 200.0


def _standard(standard_id: str) -> Standard:
    std = get_standard(standard_id)
    if std is None:
        raise HTTPException(404, f"unknown standard id: {standard_id}")
    return std


def _resolved_standard(req: FactorDeriveRequest) -> Standard:
    """The stored standard, or a throwaway one built from the request.

    An inline composition is validated by exactly the same
    `standard_from_json` the store uses, so the two paths cannot diverge
    on what counts as a valid composition.
    """
    if req.standard_id:
        if req.composition is not None:
            raise HTTPException(
                422, "give a standard_id or an inline composition, not both"
            )
        return _standard(req.standard_id)
    if not req.composition or req.basis is None:
        raise HTTPException(
            422, "give a standard_id, or an inline composition with its basis"
        )
    body: dict[str, Any] = {
        "id": "inline",
        "name": "inline composition",
        "version": 0,
        "created_at": "-",
        "updated_at": "-",
        "basis": req.basis,
        "composition": dict(req.composition),
    }
    if req.mass_thickness_kg_m2 is not None:
        body["mass_thickness"] = {"value": req.mass_thickness_kg_m2, "unit": "kg/m2"}
    try:
        return standard_from_json(body)
    except StandardError as exc:
        raise HTTPException(422, str(exc)) from None


def _set(set_id: str) -> FactorSet:
    fs = get_factor_set(set_id)
    if fs is None:
        raise HTTPException(404, f"unknown factor set id: {set_id}")
    return fs


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


def _measure(req: FactorDeriveRequest, std: Standard) -> tuple[Any, Any, dict, list[str]]:
    """Fit the standard's reference spectrum and return the pieces every
    derivation needs: the fit, the resolved calibration, and the element
    order."""
    image_id = req.image_id
    if image_id is None:
        if not req.region_label:
            raise HTTPException(
                422, "give an image_id, or a region_label naming a stored reference region"
            )
        stored = next((r for r in std.regions if r.label == req.region_label), None)
        if stored is None:
            raise HTTPException(
                404, f"standard has no reference region labelled {req.region_label!r}"
            )
        if not stored.image_id:
            raise HTTPException(
                422,
                f"reference region {stored.label!r} records no image; it cannot be "
                "measured until one is given",
            )
        image_id = stored.image_id

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
    pf, _ = fit_summed_peaks(
        energy,
        ds.sum_spectrum(),
        elements,
        beam_kv=cal["beam_kv"].value,
        background=background_component(req.background, req.e0_kev),
        weights=req.weights,
        center_tol_kev=0.0,
        strip_artifacts=False,
        escape_fraction=0.0,
    )
    return pf, ds, cal, elements


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
    std = _resolved_standard(req)
    pf, ds, cal, elements = _measure(req, std)

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
        "image_id": req.image_id,
        "region_label": req.region_label,
        "region": req.region or "",
        "roi": req.roi or "",
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


@router.get("/factors")
def factors_list(kind: str | None = None) -> dict[str, Any]:
    return {"factor_sets": [factor_set_to_json(f) for f in list_factor_sets(kind)]}


@router.get("/factors/{set_id}")
def factors_get(set_id: str) -> dict[str, Any]:
    return {"factor_set": factor_set_to_json(_set(set_id))}


@router.delete("/factors/{set_id}")
def factors_delete(set_id: str) -> dict[str, Any]:
    if not delete_factor_set(set_id):
        raise HTTPException(404, f"unknown factor set id: {set_id}")
    return {"deleted": set_id}


@router.get("/factors/{set_id}/compare")
def factors_compare(set_id: str) -> dict[str, Any]:
    """A measured k set beside the built-in table, replacing neither.

    Both are reported per element with their ratio, and the disagreement
    is left as a fact about the instrument rather than resolved. A ζ set
    has no built-in counterpart at all — there is no absolute ζ table —
    and says so instead of comparing against something else.
    """
    fs = _set(set_id)
    if fs.kind != "k":
        return {
            "id": fs.id,
            "kind": fs.kind,
            "comparable": False,
            "reason": (
                "ζ is absolute and instrument-specific; this build ships no ζ table "
                "to compare against"
            ),
            "rows": [],
        }
    # the built-in table is relative to Si; a derived set is relative to
    # whatever element it chose, so rebase the built-in onto the same one
    # before comparing — otherwise every ratio carries a constant offset
    # that looks like disagreement.
    ref = fs.reference_element
    ref_builtin = K_FACTORS_200KV.get(ref)
    rows: list[dict[str, Any]] = []
    for sym, entry in sorted(fs.factors.items()):
        builtin = K_FACTORS_200KV.get(sym)
        rebased = (
            builtin / ref_builtin
            if builtin is not None and ref_builtin not in (None, 0)
            else None
        )
        ratio = (
            entry.value / rebased if rebased not in (None, 0) and rebased is not None else None
        )
        rows.append(
            {
                "element": sym,
                "measured": entry.value,
                "measured_sigma": entry.sigma,
                "builtin_200kv": builtin,
                "builtin_rebased": rebased,
                "ratio": ratio,
                "agrees_within_sigma": (
                    None
                    if ratio is None or rebased is None
                    else bool(abs(entry.value - rebased) <= max(entry.sigma, 1e-12))
                ),
            }
        )
    return {
        "id": fs.id,
        "kind": "k",
        "comparable": bool(ref_builtin),
        "reason": (
            ""
            if ref_builtin
            else f"the built-in table has no entry for the reference element {ref!r}"
        ),
        "reference_element": ref,
        "measured_kv": fs.conditions.get("beam_kv"),
        "builtin_kv": BUILTIN_K_KV,
        "rows": rows,
    }


class ZetaTransferRequest(BaseModel):
    from_solid_angle_sr: float = Field(gt=0)
    to_solid_angle_sr: float = Field(gt=0)
    from_efficiency: float = Field(default=1.0, gt=0)
    to_efficiency: float = Field(default=1.0, gt=0)
    name: str = ""
    store: bool = False


@router.post("/factors/{set_id}/transfer")
def factors_transfer(set_id: str, req: ZetaTransferRequest) -> dict[str, Any]:
    """Rescale a ζ set for a different detector geometry.

    ζ ∝ 1/(Ω·ε), so moving a set between detectors is a ratio of collected
    signal. This is the one calculation that reads `detector.solid_angle`
    and `detector.efficiency`, and it is approximate in a way the σ is
    widened to reflect: a single efficiency ratio is only right when the
    two detectors' efficiency curves have the same shape.
    """
    fs = _set(set_id)
    if fs.kind != "zeta":
        raise HTTPException(422, "only a ζ set has a detector geometry to transfer")
    factors = [
        DerivedFactor(
            element=sym,
            value=e.value,
            sigma=e.sigma,
            intensity=e.intensity or float("nan"),
            intensity_sigma=e.intensity_sigma or 0.0,
            weight_fraction=e.weight_fraction or float("nan"),
            weight_fraction_sigma=e.weight_fraction_sigma or 0.0,
        )
        for sym, e in fs.factors.items()
    ]
    try:
        moved = transfer_zeta(
            factors,
            from_solid_angle_sr=req.from_solid_angle_sr,
            to_solid_angle_sr=req.to_solid_angle_sr,
            from_efficiency=req.from_efficiency,
            to_efficiency=req.to_efficiency,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    out = {f.element: _factor_json(f) for f in moved}
    body: dict[str, Any] = {
        "source_id": fs.id,
        "kind": "zeta",
        "factors": out,
        "scale": (req.from_solid_angle_sr * req.from_efficiency)
        / (req.to_solid_angle_sr * req.to_efficiency),
    }
    if req.store:
        stored = create_factor_set(
            name=req.name or f"{fs.name} (transferred)",
            kind="zeta",
            factors=out,
            conditions=dict(fs.conditions),
            derived_from={
                **fs.derived_from,
                "transferred_from": fs.id,
                "from_solid_angle_sr": req.from_solid_angle_sr,
                "to_solid_angle_sr": req.to_solid_angle_sr,
                "from_efficiency": req.from_efficiency,
                "to_efficiency": req.to_efficiency,
            },
            provenance={"source": f"transferred from factor set {fs.id}"},
        )
        body["factor_set"] = factor_set_to_json(stored)
    return body
