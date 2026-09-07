"""Reading, comparing and transferring stored factor sets (ADR 0011).

Split from `routes/factors.py` on the seam this PR already draws
elsewhere: DERIVING a factor set is a measurement and needs the peak-fit
stack, while listing, comparing and transferring are arithmetic over
numbers already stored. A client browsing factor sets should not pull the
fitter in behind it, and the module ceiling forced the point.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.eds import K_FACTORS_200KV
from fermiviewer.calc.eds_factors import DerivedFactor, transfer_zeta
from fermiviewer.io.factors_db import (
    FactorSet,
    create_factor_set,
    delete_factor_set,
    factor_set_to_json,
    get_factor_set,
    list_factor_sets,
)

router = APIRouter(prefix="/api")

#: The built-in table's voltage. It is not recorded anywhere the table is
#: USED, which is the extrapolation `eds_qc.check_factor_conditions`
#: exists to surface; naming it here is what lets a comparison say which
#: voltage each side belongs to.
BUILTIN_K_KV = 200.0


def _set(set_id: str) -> FactorSet:
    fs = get_factor_set(set_id)
    if fs is None:
        raise HTTPException(404, f"unknown factor set id: {set_id}")
    return fs


def _factor_json(f: DerivedFactor) -> dict[str, Any]:
    return {
        "value": f.value,
        "sigma": f.sigma,
        "intensity": f.intensity,
        "intensity_sigma": f.intensity_sigma,
        "weight_fraction": f.weight_fraction,
        "weight_fraction_sigma": f.weight_fraction_sigma,
    }


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
                # None, not False, when there is no uncertainty to judge
                # against: a set derived without per-element counting
                # errors has sigma 0 everywhere, and reporting "does not
                # agree" for a factor matching to seven figures is the
                # ADR 0004 §3 rule (absent, never a stand-in zero) broken
                # in the other direction.
                "agrees_within_sigma": (
                    None
                    if ratio is None or rebased is None or entry.sigma <= 0.0
                    else bool(abs(entry.value - rebased) <= entry.sigma)
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
