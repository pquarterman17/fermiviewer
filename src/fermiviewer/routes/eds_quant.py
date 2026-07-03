"""Window-integration EDS quantification endpoint (with uncertainty).

Split out of routes/analysis.py (which sits at the 500-line god-module
ceiling) when PLAN_SPECTRAL_QUANT #6 added counting-statistics error bars.
This is the *window-integration* Cliff-Lorimer / ZAF quant over an SI cube —
the model-based EDS peak-deconvolution counterpart lives in
routes/eds_advanced.py. The `_cube` / `_register_map` helpers are duplicated
here (the same small pattern several route modules already keep locally)
rather than imported across route boundaries.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.eds import ClResult, ZafResult, cliff_lorimer, zaf_correction
from fermiviewer.calc.eds_maps import extract_element_maps
from fermiviewer.calc.uncertainty import (
    cliff_lorimer_uncertainty,
    integral_variance,
)
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _cube(img_id: str) -> DataStruct:
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
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


def _map_is_blank(arr: np.ndarray) -> bool:
    """True for an at% map with no coherent signal — an element that isn't
    really present. Skipped so absent elements don't clutter the library
    (email 2026-07-02).

    Coverage, not peak value, is the discriminator. Because Cliff-Lorimer
    normalizes at% per pixel, an ABSENT element still spikes to ~100 at% in
    stray noise/vacuum pixels (validated on real Bruker SEM data: Au/Pb/W hit
    100 at% yet cover <1% of the field, while present Cu/Al/O cover 2-12%).
    So a map is blank when <1% of pixels rise above 1 at%. This also catches
    the all-zero / all-NaN cases, and keeps a present-everywhere element (a
    single-element quant sits at ~100 at% across the whole field → 100%
    coverage). NaN pixels never satisfy `> 1.0`, so they don't count."""
    a = np.asarray(arr, dtype=np.float64)
    if a.size == 0:
        return True
    return int(np.count_nonzero(a > 1.0)) < 0.01 * a.size


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
    # Blank (solid-black) maps mean the element isn't really present — skip
    # registering them so they don't clutter the library. `maps` stays aligned
    # with `elements` (null placeholder) so the table still lists every element.
    map_meta = [
        None if _map_is_blank(m)
        else _register_map(m, f"{sym} at%", ds, req.image_id).model_dump()
        for sym, m in zip(syms, res.atomic_pct_maps, strict=True)
    ]
    # Aggregate counting-statistics 1σ on the field composition: the net
    # intensity per element is the field total; its Poisson variance comes
    # from the gross counts in the line window of the field-summed spectrum.
    field_sum = ds.data.reshape(-1, ds.data.shape[-1]).sum(axis=0)
    energy = ds.energy_axis
    var_i = []
    for e in entries:
        mask = (energy >= e.window[0]) & (energy <= e.window[1])
        var_i.append(
            integral_variance(field_sum[mask], energy[mask])
            if mask.sum() >= 2 else float("nan")
        )
    unc = cliff_lorimer_uncertainty(
        [e.total for e in entries], var_i, syms, res.k_factors,
    )
    return {
        "elements": syms,
        "lines": [e.line for e in entries],
        "mean_atomic_pct": res.mean_atomic_pct.tolist(),
        "mean_weight_pct": res.mean_weight_pct.tolist(),
        "mean_atomic_pct_error": unc.atomic_pct_sigma.tolist(),
        "mean_weight_pct_error": unc.weight_pct_sigma.tolist(),
        "k_factors": res.k_factors.tolist(),
        "maps": map_meta,
    }
