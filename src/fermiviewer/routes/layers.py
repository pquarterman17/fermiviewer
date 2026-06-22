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

from fermiviewer.calc.layers import analyze_layers
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


class LayersRequest(BaseModel):
    image_id: str
    roi: tuple[int, int, int, int] | None = None   # 1-based (r1, c1, r2, c2)
    axis: str = "auto"                              # "auto" | "y" | "x"
    sensitivity: float = 0.3
    n_layers: int = 0
    reduce: str = "mean"
    fit_window: int = 15
    waviness: bool = False
    trace_window: int = 10
    modality: str = "haadf"          # "haadf" | "eels" | "bf" | "df"


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
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

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
            }
            for i in res.interfaces
        ],
        "layers": [
            {
                "index": lyr.index,
                "top": lyr.top,
                "bottom": lyr.bottom,
                "thickness": lyr.thickness,
                "thickness_std": _nan_none(lyr.thickness_std),
            }
            for lyr in res.layers
        ],
    }
