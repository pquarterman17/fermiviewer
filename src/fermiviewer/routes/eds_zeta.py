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
from fermiviewer.routes._eds_params import (
    provenance_block,
    resolve_beam_kv,
    resolve_eds_param,
    resolve_live_time_s,
)

router = APIRouter(prefix="/api")


class EdsZetaRequest(BaseModel):
    """`None` on an acquisition parameter means "not stated by the caller",
    not "zero": the image's applied calibration profiles supply it, and
    failing those the literal this route documents (ADR 0010 §2). A value
    the caller DID type always wins — a profile is a default, never an
    override."""

    image_id: str
    elements: list[str]
    #: kV; acquisition.beam_energy, else microscope.accelerating_voltage,
    #: else 200
    beam_kv: float | None = None
    background: str = "linear"
    e0_kev: float | None = None
    center_tol_kev: float = 0.0
    weights: str | None = "poisson"
    zeta_factors: list[float] | None = None  # explicit per-element ζ (kg/m²)
    zeta_si: float | None = None  # or scale the 200 kV k table
    #: nA; acquisition.probe_current (stored in pA), else 1.0
    probe_current_na: float | None = None
    #: s; acquisition.live_time, else real_time x (1 - dead_time), else 100
    live_time_s: float | None = None
    #: deg; detector.takeoff_angle, else 20
    take_off_angle_deg: float | None = None
    absorption: bool = True
    #: a property of the SPECIMEN — no instrument profile states it
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
    # Resolve every acquisition parameter BEFORE any numerics, so a
    # profile whose unit this build cannot read fails the request instead
    # of contributing an unknown magnitude to a published composition.
    cal = {
        "beam_kv": resolve_beam_kv(ds.metadata, req.beam_kv),
        "probe_current_na": resolve_eds_param(
            ds.metadata, "probe_current_na", req.probe_current_na
        ),
        "live_time_s": resolve_live_time_s(ds.metadata, req.live_time_s),
        "take_off_angle_deg": resolve_eds_param(
            ds.metadata, "take_off_angle_deg", req.take_off_angle_deg
        ),
    }
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
        beam_kv=cal["beam_kv"].value,
        background=background_component(req.background, req.e0_kev),
        weights=req.weights,
        center_tol_kev=req.center_tol_kev,
        strip_artifacts=req.remove_artifacts,
        escape_fraction=req.escape_fraction,
    )

    try:
        dose = dose_electrons(cal["probe_current_na"].value, cal["live_time_s"].value)
        net = np.array([max(pf.net_areas[s], 0.0) for s in req.elements])
        if not np.all(np.isfinite(net)):
            raise ValueError("an element has no fittable line")
        zr = zeta_quantify(
            [np.array([[v]]) for v in net],
            list(req.elements),
            zeta,
            dose,
            take_off_angle_deg=cal["take_off_angle_deg"].value,
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
        # What each acquisition parameter was, and where it came from —
        # reported for the defaults too, so a run on a placeholder 20 deg
        # takeoff angle does not look like one on a measured value.
        "calibration": provenance_block(cal),
    }
    if removal is not None:
        resp["artifacts"] = artifact_block(removal)
    return resp
