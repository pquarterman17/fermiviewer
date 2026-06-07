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
from fermiviewer.calc.eels import background, extract_map
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
