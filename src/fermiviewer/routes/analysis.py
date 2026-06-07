"""Analysis endpoints: EELS, EDS quant, diffraction (handoff §8 + plan).

Thin adapters over calc/ — spectra cross the wire as JSON arrays (uPlot
sized), maps register as derived images and return ImageMeta.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc import diffraction as diff
from fermiviewer.calc.eds import ClResult, ZafResult, cliff_lorimer, zaf_correction
from fermiviewer.calc.eds_maps import extract_element_maps
from fermiviewer.calc.eels import background, extract_map, thickness_map
from fermiviewer.calc.eels_advanced import (
    align_zlp,
    fourier_log,
    kramers_kronig,
    svd,
)
from fermiviewer.calc.eels_quant import ElementEdge, quantify
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _get(img_id: str) -> DataStruct:
    try:
        return store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None


def _spectral(img_id: str) -> DataStruct:
    ds = _get(img_id)
    if ds.kind is DataKind.IMAGE:
        raise HTTPException(400, "image has no spectral axis")
    return ds


def _cube(img_id: str) -> DataStruct:
    ds = _get(img_id)
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise HTTPException(400, "requires a spectrum-image cube")
    return ds


def _register_map(arr: np.ndarray, name: str, parent: DataStruct,
                  parent_id: str) -> ImageMeta:
    spatial = parent.axes[:2] if parent.kind is DataKind.SPECTRUM_IMAGE \
        else (AxisCal(), AxisCal())
    derived = DataStruct(
        data=np.ascontiguousarray(arr), kind=DataKind.IMAGE,
        axes=(spatial[0], spatial[1]),
        metadata={"source": name, "parser": "derived"},
    )
    new_id = store.add_derived(derived, name, parent_id)
    return ImageMeta.from_datastruct(new_id, name, derived)


# ── EELS ─────────────────────────────────────────────────────────────

class EelsBackgroundRequest(BaseModel):
    image_id: str
    fit_window: tuple[float, float]
    method: str = "powerlaw"


@router.post("/eels/background")
def eels_background(req: EelsBackgroundRequest) -> dict:
    ds = _spectral(req.image_id)
    energy = ds.energy_axis
    spec = ds.sum_spectrum()
    try:
        signal, bg, params = background(energy, spec, req.fit_window, req.method)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {
        "energy": energy.tolist(),
        "spectrum": spec.tolist(),
        "background": bg.tolist(),
        "signal": signal.tolist(),
        "params": params,
    }


class EelsMapRequest(BaseModel):
    image_id: str
    signal_window: tuple[float, float]
    background_window: tuple[float, float] | None = None
    method: str = "powerlaw"


@router.post("/eels/map")
def eels_map(req: EelsMapRequest) -> ImageMeta:
    ds = _cube(req.image_id)
    try:
        m = extract_map(ds.data, ds.energy_axis, req.signal_window,
                        req.background_window, req.method)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    name = f"map {req.signal_window[0]:.0f}-{req.signal_window[1]:.0f} eV"
    return _register_map(m, name, ds, req.image_id)


class EelsEdgeModel(BaseModel):
    element: str
    shell: str
    z: int
    onset_ev: float
    signal_window: tuple[float, float]
    bg_window: tuple[float, float]


class EelsQuantifyRequest(BaseModel):
    image_id: str
    edges: list[EelsEdgeModel]
    e0_kv: float = 200
    beta_mrad: float = 10
    method: str = "powerlaw"


@router.post("/eels/quantify")
def eels_quantify(req: EelsQuantifyRequest) -> dict:
    ds = _spectral(req.image_id)
    edges = [ElementEdge(e.element, e.shell, e.z, e.onset_ev,
                         e.signal_window, e.bg_window) for e in req.edges]
    try:
        res = quantify(ds.energy_axis, ds.sum_spectrum(), edges,
                       req.e0_kv, req.beta_mrad, req.method)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {
        "elements": res.elements,
        "atomic_percent": res.atomic_percent.tolist(),
        "intensity": res.intensity.tolist(),
        "sigma": res.sigma.tolist(),
    }


def _register_cube(arr: np.ndarray, name: str, parent: DataStruct,
                   parent_id: str) -> ImageMeta:
    """Register a derived SI cube (aligned / denoised) with the parent's
    spatial + energy calibration intact."""
    derived = DataStruct(
        data=np.ascontiguousarray(arr), kind=DataKind.SPECTRUM_IMAGE,
        axes=parent.axes,
        metadata={"source": name, "parser": "derived"},
    )
    new_id = store.add_derived(derived, name, parent_id)
    return ImageMeta.from_datastruct(new_id, name, derived)


class EelsThicknessRequest(BaseModel):
    image_id: str
    zlp_window: tuple[float, float] = (-5.0, 5.0)
    min_counts: float = 100.0


@router.post("/eels/thickness")
def eels_thickness(req: EelsThicknessRequest) -> dict:
    """Log-ratio t/λ map (eelsThicknessMap.m). Registers the map as a
    derived image; NaN (invalid) pixels render as 0."""
    ds = _cube(req.image_id)
    try:
        t, valid = thickness_map(ds.data, ds.energy_axis,
                                 req.zlp_window, req.min_counts)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    meta = _register_map(np.nan_to_num(t), "t/λ map", ds, req.image_id)
    return {
        "map": meta.model_dump(),
        "mean_t_over_lambda": float(np.nanmean(t)) if valid.any() else 0.0,
        "valid_fraction": float(valid.mean()),
    }


class EelsKKRequest(BaseModel):
    image_id: str
    zlp_window: tuple[float, float] = (-5.0, 5.0)
    refractive_index: float | None = None     # None → unnormalised ELF
    collection_angle_mrad: float = 10.0
    acc_voltage_kv: float = 200.0
    thickness_nm: float | None = None         # None → estimate from t/λ


@router.post("/eels/kk")
def eels_kk(req: EelsKKRequest) -> dict:
    """Kramers-Kronig dielectric analysis of the sum spectrum
    (eelsKramersKronig.m, Egerton Ch. 4)."""
    ds = _spectral(req.image_id)
    nan = float("nan")
    try:
        res = kramers_kronig(
            ds.energy_axis, ds.sum_spectrum(), req.zlp_window,
            refractive_index=req.refractive_index
            if req.refractive_index is not None else nan,
            collection_angle=req.collection_angle_mrad,
            acc_voltage=req.acc_voltage_kv,
            thickness=req.thickness_nm
            if req.thickness_nm is not None else nan,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {
        "energy": res.energy.tolist(),
        "eps1": res.eps1.tolist(),
        "eps2": res.eps2.tolist(),
        "elf": res.elf.tolist(),
        "optical_conductivity": res.optical_conductivity.tolist(),
        "refractive_index": res.refractive_index.tolist(),
        "thickness_nm": res.thickness,
        "t_over_lambda": res.t_over_lambda,
    }


class EelsFourierLogRequest(BaseModel):
    image_id: str
    zlp_window: tuple[float, float] = (-5.0, 5.0)
    regularize: float = 1e-6


@router.post("/eels/fourier-log")
def eels_fourier_log(req: EelsFourierLogRequest) -> dict:
    """Fourier-log plural-scattering removal on the sum spectrum
    (eelsFourierLog.m). Returns the single-scattering distribution."""
    ds = _spectral(req.image_id)
    energy = ds.energy_axis
    spec = ds.sum_spectrum()
    try:
        ssd, t_l = fourier_log(energy, spec, req.zlp_window,
                               regularize=req.regularize)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {
        "energy": energy.tolist(),
        "spectrum": spec.tolist(),
        "ssd": ssd.tolist(),
        "t_over_lambda": t_l,
    }


class EelsSvdRequest(BaseModel):
    image_id: str
    n_components: int = 0                      # 0 → min(20, rank)
    denoise: bool = False
    n_score_maps: int = 4


@router.post("/eels/svd")
def eels_svd(req: EelsSvdRequest) -> dict:
    """SVD/MSA decomposition of an SI cube (eelsSVD.m). Score maps
    register as derived images; denoise=true registers a derived cube."""
    ds = _cube(req.image_id)
    try:
        res = svd(ds.data, ds.energy_axis, req.n_components, req.denoise)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    k_show = min(req.n_score_maps, res.singular_values.size)
    maps = [
        _register_map(res.score_maps[:, :, j], f"SVD score {j + 1}",
                      ds, req.image_id).model_dump()
        for j in range(k_show)
    ]
    out: dict = {
        "explained": res.explained.tolist(),
        "cumulative": res.cumulative.tolist(),
        "energy": ds.energy_axis.tolist(),
        "eigenspectra": res.eigenspectra[:, :k_show].T.tolist(),
        "score_maps": maps,
    }
    if res.denoised_cube is not None:
        out["denoised"] = _register_cube(
            res.denoised_cube, "SVD denoised", ds, req.image_id
        ).model_dump()
    return out


class EelsAlignRequest(BaseModel):
    image_id: str
    window: tuple[float, float] = (-20.0, 20.0)
    reference: str = "mean"                    # | "max"


@router.post("/eels/align-zlp")
def eels_align_zlp(req: EelsAlignRequest) -> dict:
    """Integer-channel ZLP alignment (eelsAlignZLP.m). Registers the
    aligned cube as a derived spectrum-image."""
    ds = _cube(req.image_id)
    try:
        aligned, shifts = align_zlp(ds.data, ds.energy_axis,
                                    req.window, req.reference)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    meta = _register_cube(aligned, "ZLP aligned", ds, req.image_id)
    return {
        "aligned": meta.model_dump(),
        "max_shift": int(np.abs(shifts).max()),
        "shifted_fraction": float((shifts != 0).mean()),
    }


# ── EDS ──────────────────────────────────────────────────────────────

class EdsQuantifyRequest(BaseModel):
    image_id: str
    elements: list[str]
    method: str = "cliff-lorimer"            # | "zaf"
    half_window_kev: float = 0.085
    thickness_nm: float = 100
    take_off_angle_deg: float = 20


@router.post("/eds/quantify")
def eds_quantify(req: EdsQuantifyRequest) -> dict:
    ds = _cube(req.image_id)
    entries = extract_element_maps(ds.data, ds.energy_axis, req.elements,
                                   half_window=req.half_window_kev)
    if not entries:
        raise HTTPException(422, "no usable element lines in the energy range")
    maps = [e.map for e in entries]
    syms = [e.symbol for e in entries]
    res: ClResult | ZafResult
    if req.method == "zaf":
        res = zaf_correction(maps, syms, thickness_nm=req.thickness_nm,
                             take_off_angle_deg=req.take_off_angle_deg)
    else:
        res = cliff_lorimer(maps, syms)
    map_meta = [
        _register_map(m, f"{sym} at%", ds, req.image_id).model_dump()
        for sym, m in zip(syms, res.atomic_pct_maps, strict=True)
    ]
    return {
        "elements": syms,
        "lines": [e.line for e in entries],
        "mean_atomic_pct": res.mean_atomic_pct.tolist(),
        "mean_weight_pct": res.mean_weight_pct.tolist(),
        "k_factors": res.k_factors.tolist(),
        "maps": map_meta,
    }


# ── Diffraction ──────────────────────────────────────────────────────

class DetectRequest(BaseModel):
    image_id: str
    min_radius: float = 10
    threshold: float = 0.05
    min_separation: float = 8
    max_spots: int = 50


@router.post("/diffraction/detect")
def diffraction_detect(req: DetectRequest) -> dict:
    ds = _get(req.image_id)
    if ds.kind is not DataKind.IMAGE:
        raise HTTPException(400, "spot detection needs a 2D image")
    spots = diff.find_spots(ds.data, req.min_radius, req.threshold,
                            req.min_separation, req.max_spots)
    return {"spots": spots.tolist(), "n": int(spots.shape[0])}


class IndexRequest(BaseModel):
    image_id: str
    spots: list[tuple[float, float]]          # 1-based (row, col)
    pixel_size_mm: float = 1.0
    camera_length_mm: float | None = None
    acc_voltage_kv: float = 200
    tolerance: float = 0.05
    top_n: int = 5


@router.post("/diffraction/index")
def diffraction_index(req: IndexRequest) -> dict:
    ds = _get(req.image_id)
    cands = diff.index_spots(
        np.asarray(req.spots, dtype=np.float64),
        (int(ds.data.shape[0]), int(ds.data.shape[1])),
        pixel_size=req.pixel_size_mm,
        camera_length=req.camera_length_mm
        if req.camera_length_mm is not None else float("nan"),
        acc_voltage=req.acc_voltage_kv,
        tolerance=req.tolerance,
        top_n=req.top_n,
    )
    return {
        "candidates": [
            {
                "phase": c.phase_name,
                "formula": c.formula,
                "score": c.score,
                "n_matched": c.n_matched,
                "matched_hkl": c.matched_hkl.tolist(),
                "zone_axis": list(c.zone_axis),
            }
            for c in cands
        ]
    }
