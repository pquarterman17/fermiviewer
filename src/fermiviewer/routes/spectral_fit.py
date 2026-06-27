"""Model-based spectral-fit endpoints (PLAN_SPECTRAL_QUANT #2).

Thin adapters over calc/eels_model — the simultaneous multi-edge EELS
fit. Kept in its own module because routes/analysis.py is already at the
500-line god-module ceiling. Sum-spectrum fits return the fitted curves
(for an overlay on the spectrum plot); the SI map variant registers the
per-pixel at% maps as derived images, mirroring /eels/quantify-map.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.eels_model import fit_edges, fit_edges_map
from fermiviewer.calc.eels_quant import ElementEdge
from fermiviewer.calc.uncertainty import atomic_fraction_sigma
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _get(img_id: str) -> DataStruct:
    try:
        return store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None


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


class FitEdgeModel(BaseModel):
    element: str
    shell: str                       # 'K' | 'L'
    z: int
    onset_ev: float
    # signal/bg windows are optional for the model fit (it spans the whole
    # range); bg_window[0] still seeds the default fit-window lower bound
    signal_window: tuple[float, float] = (0.0, 0.0)
    bg_window: tuple[float, float] = (0.0, 0.0)


class EelsFitRequest(BaseModel):
    image_id: str
    edges: list[FitEdgeModel]
    e0_kv: float = 200
    beta_mrad: float = 10
    fit_range: tuple[float, float] | None = None


def _edges(req: EelsFitRequest) -> list[ElementEdge]:
    return [
        ElementEdge(e.element, e.shell, e.z, e.onset_ev,
                    e.signal_window, e.bg_window)
        for e in req.edges
    ]


@router.post("/eels/fit")
def eels_fit(req: EelsFitRequest) -> dict:
    """Simultaneous background + multi-edge fit of the summed spectrum.

    Returns at% (from the fitted amplitude ratios), per-amplitude 1σ
    errors, and the fitted curves (model / background / per-edge) for an
    overlay on the spectrum plot.
    """
    ds = _get(req.image_id)
    if ds.kind is DataKind.IMAGE:
        raise HTTPException(400, "image has no spectral axis")
    energy = ds.energy_axis
    spectrum = ds.sum_spectrum()
    try:
        res = fit_edges(
            energy, spectrum, _edges(req), req.e0_kv, req.beta_mrad,
            fit_range=req.fit_range,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    # at% 1σ from the fitted amplitude covariance (delta method through the
    # amplitude-ratio normalisation), in percentage points
    at_err = atomic_fraction_sigma(res.amplitudes, res.amplitude_errors)
    edges_out = [
        {
            "element": el,
            "shell": req.edges[k].shell,
            "atomic_percent": float(res.atomic_percent[k]),
            "atomic_percent_error": float(at_err[k]),
            "amplitude": float(res.amplitudes[k]),
            "amplitude_error": float(res.amplitude_errors[k]),
            "curve": res.edge_curves[k].tolist(),
        }
        for k, el in enumerate(res.elements)
    ]
    return {
        "energy": energy.tolist(),
        "spectrum": spectrum.tolist(),
        "model": res.model.tolist(),
        "background": res.background.tolist(),
        "edges": edges_out,
        "reduced_chi2": res.reduced_chi2,
        "success": res.success,
    }


@router.post("/eels/fit-map")
def eels_fit_map(req: EelsFitRequest) -> dict:
    """Per-pixel model fit over an SI cube; registers at% maps as derived
    images (the background exponent is fixed from the summed-spectrum fit,
    so each pixel is a fast linear solve). Same request shape as
    /eels/fit."""
    ds = _get(req.image_id)
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise HTTPException(400, "requires a spectrum-image cube")
    try:
        res = fit_edges_map(
            ds.data, ds.energy_axis, _edges(req), req.e0_kv, req.beta_mrad,
            fit_range=req.fit_range,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    maps = [
        _register_map(res.atomic_percent[:, :, k], f"{sym} at% (EELS fit)",
                      ds, req.image_id).model_dump()
        for k, sym in enumerate(res.elements)
    ]
    mean_at = [
        float(np.nanmean(res.atomic_percent[:, :, k]))
        for k in range(len(res.elements))
    ]
    return {
        "elements": res.elements,
        "background_exponent": res.background_exponent,
        "mean_atomic_percent": mean_at,
        "maps": maps,
    }
