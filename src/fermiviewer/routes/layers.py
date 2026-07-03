"""Cross-section layer analysis endpoint (PLAN_CROSS_SECTION_LAYERS #2).

Thin adapter over calc/layers.analyze_layers — auto-orient, collapse to a
depth profile, detect + erf-refine interfaces, report layer thicknesses
and σ_erf. Uses the image's pixel calibration; the result is metadata the
frontend renders as a stage overlay (no derived image registered).
"""

from __future__ import annotations

import math

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.layers import LayerResult, analyze_layers, recompute_layers
from fermiviewer.calc.trace_roughness import analyze_trace, conformality, sigma_chem
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _get(img_id: str) -> DataStruct:
    try:
        return store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None


def _nan_none(x: float) -> float | None:
    return None if not math.isfinite(x) else float(x)


def _roughness_blocks(
    res: LayerResult,
) -> tuple[list[dict | None], list[float | None]]:
    """Per-interface roughness reports + per-layer conformality (items #9-12).

    Runs the full trace metrology (detrend/robust/noise-corrected sigma with a
    block-bootstrap CI, PSD, self-affine xi/H, quality) on every traced
    interface, plus the sigma_chem quadrature decomposition and the adjacent-
    trace conformality r for each layer. Interfaces without a trace (waviness
    off) report None.
    """
    reports: list[dict | None] = []
    resids: list[np.ndarray | None] = []
    for i in res.interfaces:
        if i.trace is None:
            reports.append(None)
            resids.append(None)
            continue
        r = analyze_trace(i.trace, res.pixel_size)
        resids.append(r.detrended)
        lo, hi = r.sigma_ci
        reports.append({
            "sigma_ci": [lo, hi] if math.isfinite(lo) and math.isfinite(hi) else None,
            "sigma_raw": _nan_none(r.sigma_raw),
            "noise_floor": _nan_none(r.noise_floor),
            "quality": r.quality,
            "xi": _nan_none(r.xi),
            "hurst": _nan_none(r.hurst),
            "sigma_chem": _nan_none(sigma_chem(i.sigma_erf, r.sigma_w)),
            "psd_wavelength": r.psd_wavelength.tolist(),
            "psd_power": r.psd_power.tolist(),
        })
    conf: list[float | None] = []
    for k in range(max(0, len(res.interfaces) - 1)):
        a, b = resids[k], resids[k + 1]
        conf.append(
            _nan_none(conformality(a, b)) if a is not None and b is not None else None
        )
    return reports, conf


def _result_to_dict(res: LayerResult) -> dict:
    rough, conf = _roughness_blocks(res)
    return {
        "axis": res.axis,
        "layers_horizontal": res.layers_horizontal,
        "tilt_deg": _nan_none(res.tilt_deg),
        "coherence": _nan_none(res.coherence),
        "pixel_size": res.pixel_size,
        "unit": res.unit,
        "depth_pos": res.depth_pos.tolist(),
        "depth_profile": res.depth_profile.tolist(),
        "interfaces": [
            {
                "position": i.position,
                "sigma_erf": _nan_none(i.sigma_erf),
                "r_squared": i.r_squared,
                "sigma_w": _nan_none(i.sigma_w),
                "trace": i.trace.tolist() if i.trace is not None else None,
                "roughness": rough[k],
            }
            for k, i in enumerate(res.interfaces)
        ],
        "layers": [
            {
                "index": lyr.index,
                "top": lyr.top,
                "bottom": lyr.bottom,
                "thickness": lyr.thickness,
                "thickness_std": _nan_none(lyr.thickness_std),
                "conformality": conf[lyr.index] if lyr.index < len(conf) else None,
            }
            for lyr in res.layers
        ],
    }


class LayersRequest(BaseModel):
    image_id: str
    roi: tuple[int, int, int, int] | None = None   # 1-based (r1, c1, r2, c2)
    axis: str = "auto"                              # "auto" | "y" | "x"
    sensitivity: float = 0.3
    n_layers: int = 0
    reduce: str = "mean"             # "mean" | "sum" | "median" (robust to streaks)
    fit_window: int = 15
    waviness: bool = False
    trace_window: int = 10
    modality: str = "haadf"          # "haadf" | "eels" | "bf" | "df"
    destripe: bool = False           # FFT notch out FIB curtaining first


@router.post("/analyze/layers")
def analyze_layers_route(req: LayersRequest) -> dict:
    """Identify layers + measure thickness and interface sharpness (σ_erf)."""
    ds = _get(req.image_id)
    if ds.kind is not DataKind.IMAGE:
        raise HTTPException(
            400, "layer analysis needs a 2-D image — derive a map from a cube first"
        )

    px = ds.pixel_size
    unit = ds.pixel_unit
    if not np.isfinite(px) or px <= 0:
        px, unit = 1.0, "px"

    try:
        res = analyze_layers(
            ds.data, roi=req.roi, axis=req.axis, sensitivity=req.sensitivity,
            n_layers=req.n_layers, reduce=req.reduce, pixel_size=px, unit=unit,
            fit_window=req.fit_window, waviness=req.waviness,
            trace_window=req.trace_window, modality=req.modality,
            destripe_fib=req.destripe,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    return _result_to_dict(res)


class LayersEditRequest(BaseModel):
    image_id: str
    positions: list[float]            # interface depths (profile pixels)
    axis: str = "y"                   # explicit — editing assumes a known axis
    roi: tuple[int, int, int, int] | None = None
    reduce: str = "mean"             # "mean" | "sum" | "median"
    fit_window: int = 15
    waviness: bool = False
    trace_window: int = 10
    destripe: bool = False


@router.post("/analyze/layers/edit")
def edit_layers_route(req: LayersEditRequest) -> dict:
    """Re-measure layers from a user-edited interface list (no detection)."""
    ds = _get(req.image_id)
    if ds.kind is not DataKind.IMAGE:
        raise HTTPException(400, "layer analysis needs a 2-D image")
    px = ds.pixel_size
    unit = ds.pixel_unit
    if not np.isfinite(px) or px <= 0:
        px, unit = 1.0, "px"
    try:
        res = recompute_layers(
            ds.data, list(req.positions), axis=req.axis, roi=req.roi,
            reduce=req.reduce, pixel_size=px, unit=unit, fit_window=req.fit_window,
            waviness=req.waviness, trace_window=req.trace_window,
            destripe_fib=req.destripe,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _result_to_dict(res)


class LayersMultiRequest(BaseModel):
    image_ids: list[str]              # element/score maps to compare
    reference: int = 0               # which map's detection defines the interfaces
    axis: str = "auto"
    sensitivity: float = 0.3
    n_layers: int = 0
    modality: str = "haadf"
    waviness: bool = True            # σ_w is the point of a per-element comparison


@router.post("/analyze/layers/multi")
def multi_layers_route(req: LayersMultiRequest) -> dict:
    """Per-element interface roughness across several maps (EELS/EDS · #7).

    Detects interfaces on the reference map, then re-measures those same
    interfaces on every map → per-element σ_erf / σ_w (chemical interface
    sharpness vs geometric roughness). All maps must share a shape.
    """
    if not req.image_ids:
        raise HTTPException(422, "give at least one image_id")
    ref_idx = max(0, min(req.reference, len(req.image_ids) - 1))

    structs = []
    for img_id in req.image_ids:
        ds = _get(img_id)
        if ds.kind is not DataKind.IMAGE:
            raise HTTPException(400, f"{img_id} is not a 2-D image map")
        structs.append(ds)
    shape0 = structs[0].data.shape
    if any(s.data.shape != shape0 for s in structs):
        raise HTTPException(422, "all maps must share the same shape")

    ref = structs[ref_idx]
    px = ref.pixel_size if np.isfinite(ref.pixel_size) and ref.pixel_size > 0 else 1.0
    unit = ref.pixel_unit if ref.pixel_unit else "px"
    try:
        ref_res = analyze_layers(
            ref.data, axis=req.axis, sensitivity=req.sensitivity,
            n_layers=req.n_layers, modality=req.modality, waviness=req.waviness,
            pixel_size=px, unit=unit,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    positions = [i.position for i in ref_res.interfaces]
    use_axis = ref_res.axis

    maps = []
    for img_id, ds in zip(req.image_ids, structs, strict=True):
        m_px = ds.pixel_size if np.isfinite(ds.pixel_size) and ds.pixel_size > 0 else px
        m_unit = ds.pixel_unit if ds.pixel_unit else unit
        res = recompute_layers(
            ds.data, positions, axis=use_axis, pixel_size=m_px, unit=m_unit,
            waviness=req.waviness,
        )
        maps.append({
            "image_id": img_id,
            "name": store.name(img_id),
            "interfaces": [
                {"position": i.position, "sigma_erf": _nan_none(i.sigma_erf),
                 "sigma_w": _nan_none(i.sigma_w)}
                for i in res.interfaces
            ],
            "layers": [
                {"index": lyr.index, "thickness": lyr.thickness,
                 "thickness_std": _nan_none(lyr.thickness_std)}
                for lyr in res.layers
            ],
        })

    return {"axis": use_axis, "unit": unit, "reference_positions": positions, "maps": maps}
