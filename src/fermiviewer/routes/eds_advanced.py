"""Model-based EDS endpoints (PLAN_SPECTRAL_QUANT #4 + #5 + #8 + #9).

Thin adapters over calc/eds_continuum (Kramers bremsstrahlung background),
calc/eds_peakfit (constrained multi-Gaussian peak deconvolution),
calc/eds_artifacts (escape/sum peaks) and calc/eds_calib (energy
recalibration). Its own module because routes/analysis.py is at the
500-line ceiling. The continuum/peakfit endpoints operate on an image's
summed spectrum and return fitted curves for an overlay; /eds/peakfit can
also Cliff-Lorimer quantify, and /eds/recalibrate applies a linear
energy-axis correction to the image.

The shared peak-fit machinery lives in routes/_eds_common.py, and the
ζ-factor quantification endpoint in routes/eds_zeta.py — split out
2026-08-14 when this module reached 493/500 lines.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.eds import cliff_lorimer
from fermiviewer.calc.eds_artifacts import DEFAULT_ESCAPE_FRACTION
from fermiviewer.calc.eds_calib import (
    recalibrate as recalibrate_axis,
)
from fermiviewer.calc.eds_calib import (
    recalibrated_cal,
    resolve_anchors,
)
from fermiviewer.calc.eds_continuum import fit_continuum
from fermiviewer.calc.eds_peakfit import fit_peaks
from fermiviewer.calc.energy_units import to_kev
from fermiviewer.calc.fit_quality import r_squared
from fermiviewer.calc.uncertainty import cliff_lorimer_uncertainty
from fermiviewer.datastruct import DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.routes._eds_common import (
    artifact_block,
    artifact_prepass,
    background_component,
    fit_summed_peaks,
    spectral_dataset,
)
from fermiviewer.session import store

router = APIRouter(prefix="/api")


class EdsContinuumRequest(BaseModel):
    image_id: str
    e0_kev: float
    exclude_lines: list[str] = []
    exclude_windows: list[tuple[float, float]] = []
    fit_absorption: bool = True
    weights: str | None = "poisson"


@router.post("/eds/continuum")
def eds_continuum(req: EdsContinuumRequest) -> dict:
    """Fit the Kramers bremsstrahlung continuum to the summed spectrum.

    Masks the named elements' characteristic peaks and fits the smooth
    continuum through the gaps; returns the continuum curve for overlay.
    """
    ds = spectral_dataset(req.image_id)
    energy = to_kev(ds.energy_axis, ds.energy_cal.units)
    spectrum = ds.sum_spectrum()
    try:
        fit = fit_continuum(
            energy,
            spectrum,
            req.e0_kev,
            exclude_lines=list(req.exclude_lines),
            exclude_windows=list(req.exclude_windows),
            fit_absorption=req.fit_absorption,
            weights=req.weights,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    return {
        "energy": energy.tolist(),
        "spectrum": spectrum.tolist(),
        "continuum": fit.continuum.tolist(),
        "amp": fit.amp,
        "absorption": fit.absorption,
        "reduced_chi2": fit.fit.reduced_chi2,
        "success": fit.fit.success,
    }


class EdsPeakfitRequest(BaseModel):
    image_id: str
    elements: list[str]
    beam_kv: float = 200.0
    background: str = "linear"  # "none" | "linear" | "bremsstrahlung"
    e0_kev: float | None = None  # required when background="bremsstrahlung"
    center_tol_kev: float = 0.0
    quantify: bool = False
    k_factors: list[float] | None = None
    weights: str | None = "poisson"
    remove_artifacts: bool = False  # escape/sum pre-pass before the fit (#8)
    escape_fraction: float = DEFAULT_ESCAPE_FRACTION


@router.post("/eds/peakfit")
def eds_peakfit(req: EdsPeakfitRequest) -> dict:
    """Deconvolve overlapping EDS peaks; optionally Cliff-Lorimer quantify.

    Each element is one Gaussian (known energy, Fano width, free
    amplitude) fit jointly with the chosen background. Returns per-element
    net areas + 1σ errors + fitted curves; with ``quantify`` the at%/wt%
    from the deconvolved areas. ``remove_artifacts`` runs the escape/sum
    pre-pass (#8) and refits on the corrected spectrum.

    ``model_sigma`` (#3) is the fitted MODEL's per-point ±1σ, served rather
    than derived client-side — see ``spectral_fit.eels_fit``'s docstring
    for the full reasoning (same delta-method core).
    """
    ds = spectral_dataset(req.image_id)
    energy = to_kev(ds.energy_axis, ds.energy_cal.units)
    spectrum = ds.sum_spectrum()
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

    elements_out = [
        {
            "symbol": s,
            "line": pf.lines[s],
            "energy_kev": pf.line_energies[s],
            "net_area": pf.net_areas[s],
            "net_area_error": pf.net_area_errors[s],
            "curve": pf.fit.component_curves[s].tolist() if s in pf.fit.component_curves else None,
        }
        for s in req.elements
    ]
    resp: dict = {
        "energy": energy.tolist(),
        "spectrum": spectrum.tolist(),
        "model": pf.fit.model.tolist(),
        "elements": elements_out,
        "reduced_chi2": pf.fit.reduced_chi2,
        # plain unweighted R² (audit R4 / #2). fit_peaks never passes a
        # fit_range to fit_spectrum, so the fitted window IS the full
        # "spectrum"/"model" arrays above — no extra masking needed (unlike
        # /eels/fit, which windows to a sub-range of the returned axis).
        "r_squared": r_squared(spectrum, pf.fit.model),
        "success": pf.fit.success,
        # model-confidence band (#3, null when the covariance is unusable)
        "model_sigma": pf.model_sigma.tolist() if pf.model_sigma is not None else None,
    }
    if removal is not None:
        resp["artifacts"] = artifact_block(removal)

    if req.quantify:
        quant_elems = [s for s in req.elements if np.isfinite(pf.net_areas[s])]
        if quant_elems:
            maps = [np.array([[max(pf.net_areas[s], 0.0)]]) for s in quant_elems]
            k = None
            if req.k_factors is not None and len(quant_elems) == len(req.elements):
                k = np.asarray(req.k_factors, dtype=np.float64)
            cl = cliff_lorimer(maps, quant_elems, k_factors=k)
            # propagate each peak's amplitude 1σ (already in net_area_errors)
            # through Cliff-Lorimer to at%/wt% error bars
            net = [max(pf.net_areas[s], 0.0) for s in quant_elems]
            var = [pf.net_area_errors[s] ** 2 for s in quant_elems]
            unc = cliff_lorimer_uncertainty(net, var, quant_elems, cl.k_factors)
            resp["quant"] = {
                "elements": quant_elems,
                "atomic_percent": cl.mean_atomic_pct.tolist(),
                "atomic_percent_error": unc.atomic_pct_sigma.tolist(),
                "weight_percent": cl.mean_weight_pct.tolist(),
                "weight_percent_error": unc.weight_pct_sigma.tolist(),
            }

    return resp


class EdsArtifactsRequest(BaseModel):
    image_id: str
    elements: list[str]
    beam_kv: float = 200.0
    background: str = "linear"
    e0_kev: float | None = None
    weights: str | None = "poisson"
    escape_fraction: float = DEFAULT_ESCAPE_FRACTION


@router.post("/eds/artifacts")
def eds_artifacts(req: EdsArtifactsRequest) -> dict:
    """Detect + measure escape/sum/pile-up peaks for spectrum markers (#8).

    Fits the elements' characteristic peaks (choose the bremsstrahlung
    background when a continuum is present — a clean residual is what
    makes the artifact areas trustworthy), then predicts artifact
    positions and measures/models their areas. Returns per-artifact
    markers and the artifact-subtracted spectrum.
    """
    ds = spectral_dataset(req.image_id)
    energy = to_kev(ds.energy_axis, ds.energy_cal.units)
    spectrum = ds.sum_spectrum()
    try:
        pf = fit_peaks(
            energy,
            spectrum,
            req.elements,
            beam_kv=req.beam_kv,
            background=background_component(req.background, req.e0_kev),
            weights=req.weights,
        )
        removal = artifact_prepass(energy, spectrum, pf, req.escape_fraction)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    return {
        "energy": energy.tolist(),
        "spectrum": spectrum.tolist(),
        "artifacts": artifact_block(removal),
        "corrected": removal.corrected.tolist(),
    }


class EdsRecalibrateRequest(BaseModel):
    image_id: str
    elements: list[str] = []  # known lines (true energies looked up)
    pairs: list[tuple[float, float]] = []  # explicit (observed_kev, true_kev)
    beam_kv: float = 200.0
    search_kev: float = 0.15
    apply: bool = True  # apply to the image's energy axis


@router.post("/eds/recalibrate")
def eds_recalibrate(req: EdsRecalibrateRequest) -> dict:
    """Linear energy-axis recalibration from known characteristic lines (#9).

    Anchors are element symbols (their principal-line true energy is looked
    up, and the observed peak is auto-located in the summed spectrum) and/or
    explicit (observed_keV, true_keV) pairs. Computes ``E' = gain·E + offset``
    and, when ``apply``, rewrites the image's energy ``AxisCal``
    (``scale' = gain·scale``, ``origin' = origin − offset/scale'``).
    """
    ds = spectral_dataset(req.image_id)
    energy = to_kev(ds.energy_axis, ds.energy_cal.units)
    spectrum = ds.sum_spectrum()

    try:
        anchors, skipped = resolve_anchors(req.elements, req.pairs, req.beam_kv)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    res = recalibrate_axis(energy, spectrum, anchors, search_kev=req.search_kev)

    resp: dict = {
        "gain": res.gain,
        "offset": res.offset,
        "anchors": [list(p) for p in res.anchors],  # [[observed, true], ...]
        "skipped": skipped,
        "applied": False,
    }

    if req.apply:
        e_cal = ds.axes[-1]
        try:
            new_cal = recalibrated_cal(e_cal, res.gain, res.offset)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        new_ds = DataStruct(
            data=ds.data,
            kind=ds.kind,
            axes=(*ds.axes[:-1], new_cal),
            metadata=dict(ds.metadata),
        )
        store.replace(req.image_id, new_ds)
        resp.update(
            applied=True,
            scale=new_cal.scale,
            origin=new_cal.origin,
            units=new_cal.units,
            image=ImageMeta.from_datastruct(
                req.image_id, store.name(req.image_id), new_ds
            ).model_dump(),
        )

    return resp
