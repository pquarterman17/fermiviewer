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
from fermiviewer.calc.eds_artifacts import (
    DEFAULT_ESCAPE_FRACTION,
    ArtifactRemoval,
    remove_artifacts,
)
from fermiviewer.calc.eds_calib import recalibrate as recalibrate_axis
from fermiviewer.calc.eds_continuum import bremsstrahlung_component, fit_continuum
from fermiviewer.calc.eds_peakfit import PeakFitResult, fit_peaks
from fermiviewer.calc.eds_zeta import dose_electrons, zeta_from_k_factors, zeta_quantify
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
    remove_artifacts: bool = False      # escape/sum pre-pass before the fit (#8)
    escape_fraction: float = DEFAULT_ESCAPE_FRACTION


def _background(background: str, e0_kev: float | None) -> Component | None:
    if background == "none":
        return None
    if background == "linear":
        return linear_background("bg")
    if background == "bremsstrahlung":
        if e0_kev is None:
            raise HTTPException(422, "background='bremsstrahlung' needs e0_kev")
        # pure Kramers (absorption fixed): keeps the joint peak+continuum fit
        # linear in all amplitudes and well-conditioned. The low-energy
        # detector rolloff is recovered separately by /eds/continuum, which
        # fits absorption with the peaks masked out.
        return bremsstrahlung_component(e0_kev, fit_absorption=False)
    raise HTTPException(422, f"unknown background '{background}'")


def _artifact_prepass(
    energy: np.ndarray,
    spectrum: np.ndarray,
    pf: PeakFitResult,
    escape_fraction: float,
) -> ArtifactRemoval:
    """Predict + measure/model escape and sum peaks from an initial fit."""
    lines = {s: e for s, e in pf.line_energies.items() if np.isfinite(e)}
    return remove_artifacts(
        energy, spectrum, lines,
        residual=spectrum - pf.fit.model,
        parent_areas=pf.net_areas,
        escape_fraction=escape_fraction,
    )


def _artifact_block(removal: ArtifactRemoval) -> list[dict]:
    """Serialise an ArtifactRemoval into per-peak marker dicts for the UI."""
    out = []
    for a in removal.artifacts:
        if a.name in removal.measured:
            status, area = "measured", removal.measured[a.name]
            err = removal.measured_errors.get(a.name)
        elif a.name in removal.modeled:
            status, area, err = "modeled", removal.modeled[a.name], None
        else:
            status, area, err = "skipped", None, None
        out.append({
            "name": a.name, "label": a.label, "kind": a.kind,
            "energy_kev": a.energy_kev, "status": status,
            "area": area, "area_error": err,
        })
    return out


def _fit_summed_peaks(
    energy: np.ndarray,
    spectrum: np.ndarray,
    elements: list[str],
    *,
    beam_kv: float,
    background: Component | None,
    weights: str | None,
    center_tol_kev: float,
    strip_artifacts: bool,
    escape_fraction: float,
) -> tuple[PeakFitResult, ArtifactRemoval | None]:
    """fit_peaks with an optional escape/sum-peak removal pre-pass (#8)."""
    try:
        pf = fit_peaks(
            energy, spectrum, elements,
            beam_kv=beam_kv, background=background,
            weights=weights, center_tol_kev=center_tol_kev,
        )
        if not strip_artifacts:
            return pf, None
        removal = _artifact_prepass(energy, spectrum, pf, escape_fraction)
        pf = fit_peaks(
            energy, removal.corrected, elements,
            beam_kv=beam_kv, background=background,
            weights=weights, center_tol_kev=center_tol_kev,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return pf, removal


@router.post("/eds/peakfit")
def eds_peakfit(req: EdsPeakfitRequest) -> dict:
    """Deconvolve overlapping EDS peaks; optionally Cliff-Lorimer quantify.

    Each element is one Gaussian (known energy, Fano width, free
    amplitude) fit jointly with the chosen background. Returns per-element
    net areas + 1σ errors + fitted curves; with ``quantify`` the at%/wt%
    from the deconvolved areas. ``remove_artifacts`` runs the escape/sum
    pre-pass (#8) and refits on the corrected spectrum.
    """
    ds = _spectral(req.image_id)
    energy = ds.energy_axis
    spectrum = ds.sum_spectrum()
    pf, removal = _fit_summed_peaks(
        energy, spectrum, req.elements,
        beam_kv=req.beam_kv, background=_background(req.background, req.e0_kev),
        weights=req.weights, center_tol_kev=req.center_tol_kev,
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
    if removal is not None:
        resp["artifacts"] = _artifact_block(removal)

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


class EdsZetaRequest(BaseModel):
    image_id: str
    elements: list[str]
    beam_kv: float = 200.0
    background: str = "linear"
    e0_kev: float | None = None
    center_tol_kev: float = 0.0
    weights: str | None = "poisson"
    zeta_factors: list[float] | None = None   # explicit per-element ζ (kg/m²)
    zeta_si: float | None = None              # or scale the 200 kV k table
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
    ds = _spectral(req.image_id)
    energy = ds.energy_axis
    spectrum = ds.sum_spectrum()

    if req.zeta_factors is not None:
        if len(req.zeta_factors) != len(req.elements):
            raise HTTPException(422, "zeta_factors must match elements length")
        zeta = np.asarray(req.zeta_factors, dtype=np.float64)
    elif req.zeta_si is not None:
        zeta = zeta_from_k_factors(req.elements, req.zeta_si)
    else:
        raise HTTPException(422, "provide zeta_factors or zeta_si")

    pf, removal = _fit_summed_peaks(
        energy, spectrum, req.elements,
        beam_kv=req.beam_kv, background=_background(req.background, req.e0_kev),
        weights=req.weights, center_tol_kev=req.center_tol_kev,
        strip_artifacts=req.remove_artifacts,
        escape_fraction=req.escape_fraction,
    )

    try:
        dose = dose_electrons(req.probe_current_na, req.live_time_s)
        net = np.array([max(pf.net_areas[s], 0.0) for s in req.elements])
        if not np.all(np.isfinite(net)):
            raise ValueError("an element has no fittable line")
        zr = zeta_quantify(
            [np.array([[v]]) for v in net], list(req.elements), zeta, dose,
            take_off_angle_deg=req.take_off_angle_deg,
            absorption=req.absorption,
            density_g_cm3=req.density_g_cm3,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    # counting/fit 1σ → at%/wt% error bars. The ζ normalisation
    # w_i = ζ_i·I_i/Σζ_j·I_j has the Cliff-Lorimer form with k→ζ, so the
    # same delta-method core applies; absorption factors are treated as
    # exact and scale value and σ alike.
    a_f = zr.absorption_factors
    var = np.array([pf.net_area_errors[s] ** 2 for s in req.elements])
    unc = cliff_lorimer_uncertainty(net * a_f, var * a_f**2, req.elements, zeta)
    rho_t_sigma = float(np.sqrt((zeta**2 * var * a_f**2).sum()) / dose)

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
                if s in pf.fit.component_curves else None,
            }
            for s in req.elements
        ],
        "reduced_chi2": pf.fit.reduced_chi2,
        "success": pf.fit.success,
        "quant": {
            "elements": list(req.elements),
            "atomic_percent": zr.mean_atomic_pct.tolist(),
            "atomic_percent_error": unc.atomic_pct_sigma.tolist(),
            "weight_percent": zr.mean_weight_pct.tolist(),
            "weight_percent_error": unc.weight_pct_sigma.tolist(),
            "mass_thickness_kg_m2": zr.mean_mass_thickness,
            "mass_thickness_error_kg_m2": rho_t_sigma,
            "mass_thickness_ug_cm2": zr.mean_mass_thickness * 1e5,
            "thickness_nm": None if not np.isfinite(zr.mean_thickness_nm)
            else zr.mean_thickness_nm,
            "absorption_factors": zr.absorption_factors.tolist(),
            "zeta_factors": zeta.tolist(),
            "dose_electrons": dose,
        },
    }
    if removal is not None:
        resp["artifacts"] = _artifact_block(removal)
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
    ds = _spectral(req.image_id)
    energy = ds.energy_axis
    spectrum = ds.sum_spectrum()
    try:
        pf = fit_peaks(
            energy, spectrum, req.elements,
            beam_kv=req.beam_kv,
            background=_background(req.background, req.e0_kev),
            weights=req.weights,
        )
        removal = _artifact_prepass(energy, spectrum, pf, req.escape_fraction)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    return {
        "energy": energy.tolist(),
        "spectrum": spectrum.tolist(),
        "artifacts": _artifact_block(removal),
        "corrected": removal.corrected.tolist(),
    }


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
