"""ζ-factor EDS quantification endpoint (PLAN_SPECTRAL_QUANT #7).

Thin adapter over calc/eds_zeta. Split out of routes/eds_advanced.py
(2026-08-14, at 493/500 lines) rather than trimmed to fit — the shared
peak-fit machinery both modules use lives in routes/_eds_common.py.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.eds_artifacts import DEFAULT_ESCAPE_FRACTION
from fermiviewer.calc.eds_zeta import (
    dose_electrons,
    zeta_from_k_factors,
    zeta_quantify,
    zeta_uncertainty,
)
from fermiviewer.calc.energy_units import to_kev
from fermiviewer.calc.fit_quality import r_squared
from fermiviewer.routes._eds_common import (
    artifact_block,
    background_component,
    fit_summed_peaks,
    spectral_dataset,
)

router = APIRouter(prefix="/api")


class EdsZetaRequest(BaseModel):
    image_id: str
    elements: list[str]
    beam_kv: float = 200.0
    background: str = "linear"
    e0_kev: float | None = None
    center_tol_kev: float = 0.0
    weights: str | None = "poisson"
    zeta_factors: list[float] | None = None  # explicit per-element ζ (kg/m²)
    zeta_si: float | None = None  # or scale the 200 kV k table
    probe_current_na: float = 1.0
    live_time_s: float = 100.0
    take_off_angle_deg: float = 20.0
    absorption: bool = True
    density_g_cm3: float | None = None
    remove_artifacts: bool = False
    escape_fraction: float = DEFAULT_ESCAPE_FRACTION


@router.post("/eds/zeta")
def eds_zeta(req: EdsZetaRequest) -> dict:
    """ζ-factor (Watanabe) quantification of the summed spectrum (#7).

    Deconvolves the elements' peaks, then converts net areas to
    composition **and mass-thickness** via C_i·ρt = ζ_i·I_i/D_e with a
    self-consistent thin-film absorption correction. ζ comes either
    explicitly per element or scaled from the built-in 200 kV k-factor
    table by one absolute ``zeta_si``.
    """
    ds = spectral_dataset(req.image_id)
    energy = to_kev(ds.energy_axis, ds.energy_cal.units)
    spectrum = ds.sum_spectrum()

    if req.zeta_factors is not None:
        if len(req.zeta_factors) != len(req.elements):
            raise HTTPException(422, "zeta_factors must match elements length")
        zeta = np.asarray(req.zeta_factors, dtype=np.float64)
    elif req.zeta_si is not None:
        zeta = zeta_from_k_factors(req.elements, req.zeta_si)
    else:
        raise HTTPException(422, "provide zeta_factors or zeta_si")

    pf, removal = fit_summed_peaks(
        energy,
        spectrum,
        req.elements,
        beam_kv=req.beam_kv,
        background=background_component(req.background, req.e0_kev),
        weights=req.weights,
        center_tol_kev=req.center_tol_kev,
        strip_artifacts=req.remove_artifacts,
        escape_fraction=req.escape_fraction,
    )

    try:
        dose = dose_electrons(req.probe_current_na, req.live_time_s)
        net = np.array([max(pf.net_areas[s], 0.0) for s in req.elements])
        if not np.all(np.isfinite(net)):
            raise ValueError("an element has no fittable line")
        zr = zeta_quantify(
            [np.array([[v]]) for v in net],
            list(req.elements),
            zeta,
            dose,
            take_off_angle_deg=req.take_off_angle_deg,
            absorption=req.absorption,
            density_g_cm3=req.density_g_cm3,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    # counting/fit 1σ → at%/wt% + ρt error bars (the ζ↔Cliff-Lorimer
    # correspondence is documented on calc.eds_zeta.zeta_uncertainty)
    unc, rho_t_sigma = zeta_uncertainty(
        net,
        [pf.net_area_errors[s] for s in req.elements],
        req.elements,
        zeta,
        zr.absorption_factors,
        dose,
    )

    resp: dict = {
        "energy": energy.tolist(),
        "spectrum": spectrum.tolist(),
        "model": pf.fit.model.tolist(),
        "elements": [
            {
                "symbol": s,
                "line": pf.lines[s],
                "energy_kev": pf.line_energies[s],
                "net_area": pf.net_areas[s],
                "net_area_error": pf.net_area_errors[s],
                "curve": pf.fit.component_curves[s].tolist()
                if s in pf.fit.component_curves
                else None,
            }
            for s in req.elements
        ],
        "reduced_chi2": pf.fit.reduced_chi2,
        # see /eds/peakfit — same fit_peaks call, same "whole array is the
        # fit window" reasoning.
        "r_squared": r_squared(spectrum, pf.fit.model),
        "success": pf.fit.success,
        # model-confidence band (#3) — same fit_peaks call as /eds/peakfit
        "model_sigma": pf.model_sigma.tolist() if pf.model_sigma is not None else None,
        "quant": {
            "elements": list(req.elements),
            "atomic_percent": zr.mean_atomic_pct.tolist(),
            "atomic_percent_error": unc.atomic_pct_sigma.tolist(),
            "weight_percent": zr.mean_weight_pct.tolist(),
            "weight_percent_error": unc.weight_pct_sigma.tolist(),
            "mass_thickness_kg_m2": zr.mean_mass_thickness,
            "mass_thickness_error_kg_m2": rho_t_sigma,
            "mass_thickness_ug_cm2": zr.mean_mass_thickness * 1e5,
            "thickness_nm": None if not np.isfinite(zr.mean_thickness_nm) else zr.mean_thickness_nm,
            "absorption_factors": zr.absorption_factors.tolist(),
            "zeta_factors": zeta.tolist(),
            "dose_electrons": dose,
        },
    }
    if removal is not None:
        resp["artifacts"] = artifact_block(removal)
    return resp
