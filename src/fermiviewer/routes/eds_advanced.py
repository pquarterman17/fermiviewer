"""Model-based EDS endpoints (PLAN_SPECTRAL_QUANT #4 + #5 + #9).

Thin adapters over calc/eds_continuum (Kramers bremsstrahlung background),
calc/eds_peakfit (constrained multi-Gaussian peak deconvolution) and
calc/eds_calib (energy recalibration). Its own module because
routes/analysis.py is at the 500-line ceiling. The continuum/peakfit
endpoints operate on an image's summed spectrum and return fitted curves
for an overlay; /eds/peakfit can also Cliff-Lorimer quantify, and
/eds/recalibrate applies a linear energy-axis correction to the image.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.eds import cliff_lorimer, line_energy
from fermiviewer.calc.eds_calib import recalibrate as recalibrate_axis
from fermiviewer.calc.eds_continuum import bremsstrahlung_component, fit_continuum
from fermiviewer.calc.eds_peakfit import fit_peaks
from fermiviewer.calc.spectral_fit import Component, linear_background
from fermiviewer.calc.uncertainty import cliff_lorimer_uncertainty
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _spectral(img_id: str) -> DataStruct:
    """Fetch an image and require a spectral axis (SPECTRUM / SI cube)."""
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    if ds.kind is DataKind.IMAGE:
        raise HTTPException(400, "image has no spectral axis")
    return ds


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
    ds = _spectral(req.image_id)
    energy = ds.energy_axis
    spectrum = ds.sum_spectrum()
    try:
        fit = fit_continuum(
            energy, spectrum, req.e0_kev,
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
    background: str = "linear"          # "none" | "linear" | "bremsstrahlung"
    e0_kev: float | None = None         # required when background="bremsstrahlung"
    center_tol_kev: float = 0.0
    quantify: bool = False
    k_factors: list[float] | None = None
    weights: str | None = "poisson"


def _background(req: EdsPeakfitRequest) -> Component | None:
    if req.background == "none":
        return None
    if req.background == "linear":
        return linear_background("bg")
    if req.background == "bremsstrahlung":
        if req.e0_kev is None:
            raise HTTPException(422, "background='bremsstrahlung' needs e0_kev")
        # pure Kramers (absorption fixed): keeps the joint peak+continuum fit
        # linear in all amplitudes and well-conditioned. The low-energy
        # detector rolloff is recovered separately by /eds/continuum, which
        # fits absorption with the peaks masked out.
        return bremsstrahlung_component(req.e0_kev, fit_absorption=False)
    raise HTTPException(422, f"unknown background '{req.background}'")


@router.post("/eds/peakfit")
def eds_peakfit(req: EdsPeakfitRequest) -> dict:
    """Deconvolve overlapping EDS peaks; optionally Cliff-Lorimer quantify.

    Each element is one Gaussian (known energy, Fano width, free
    amplitude) fit jointly with the chosen background. Returns per-element
    net areas + 1σ errors + fitted curves; with ``quantify`` the at%/wt%
    from the deconvolved areas.
    """
    ds = _spectral(req.image_id)
    energy = ds.energy_axis
    spectrum = ds.sum_spectrum()
    bg = _background(req)
    try:
        pf = fit_peaks(
            energy, spectrum, req.elements,
            beam_kv=req.beam_kv, background=bg,
            weights=req.weights, center_tol_kev=req.center_tol_kev,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    elements_out = [
        {
            "symbol": s,
            "line": pf.lines[s],
            "energy_kev": pf.line_energies[s],
            "net_area": pf.net_areas[s],
            "net_area_error": pf.net_area_errors[s],
            "curve": pf.fit.component_curves[s].tolist()
            if s in pf.fit.component_curves else None,
        }
        for s in req.elements
    ]
    resp: dict = {
        "energy": energy.tolist(),
        "spectrum": spectrum.tolist(),
        "model": pf.fit.model.tolist(),
        "elements": elements_out,
        "reduced_chi2": pf.fit.reduced_chi2,
        "success": pf.fit.success,
    }

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


class EdsRecalibrateRequest(BaseModel):
    image_id: str
    elements: list[str] = []                  # known lines (true energies looked up)
    pairs: list[tuple[float, float]] = []     # explicit (observed_kev, true_kev)
    beam_kv: float = 200.0
    search_kev: float = 0.15
    apply: bool = True                        # apply to the image's energy axis


@router.post("/eds/recalibrate")
def eds_recalibrate(req: EdsRecalibrateRequest) -> dict:
    """Linear energy-axis recalibration from known characteristic lines (#9).

    Anchors are element symbols (their principal-line true energy is looked
    up, and the observed peak is auto-located in the summed spectrum) and/or
    explicit (observed_keV, true_keV) pairs. Computes ``E' = gain·E + offset``
    and, when ``apply``, rewrites the image's energy ``AxisCal``
    (``scale' = gain·scale``, ``origin' = origin − offset/scale'``).
    """
    ds = _spectral(req.image_id)
    energy = ds.energy_axis
    spectrum = ds.sum_spectrum()

    anchors: list[float | tuple[float, float]] = []
    skipped: list[str] = []
    for sym in req.elements:
        e, fam = line_energy(sym, beam_kv=req.beam_kv)
        if fam and np.isfinite(e):
            anchors.append(float(e))
        else:
            skipped.append(sym)
    anchors.extend((float(a), float(b)) for a, b in req.pairs)
    if not anchors:
        raise HTTPException(422, "no usable anchors (unknown elements and no pairs)")

    res = recalibrate_axis(energy, spectrum, anchors, search_kev=req.search_kev)

    resp: dict = {
        "gain": res.gain,
        "offset": res.offset,
        "anchors": [list(p) for p in res.anchors],   # [[observed, true], ...]
        "skipped": skipped,
        "applied": False,
    }

    if req.apply:
        e_cal = ds.axes[-1]
        scale2 = res.gain * e_cal.scale
        if not np.isfinite(scale2) or scale2 == 0:
            raise HTTPException(422, "recalibration produced a degenerate energy scale")
        origin2 = e_cal.origin - res.offset / scale2
        new_cal = AxisCal(scale=scale2, origin=origin2, units=e_cal.units)
        new_ds = DataStruct(
            data=ds.data, kind=ds.kind,
            axes=(*ds.axes[:-1], new_cal), metadata=dict(ds.metadata),
        )
        store.replace(req.image_id, new_ds)
        resp.update(
            applied=True, scale=scale2, origin=origin2, units=e_cal.units,
            image=ImageMeta.from_datastruct(
                req.image_id, store.name(req.image_id), new_ds
            ).model_dump(),
        )

    return resp
