"""Batch EELS map endpoint (SPECTRAL_WORKSPACE_PLAN #14).

``calc.eels.extract_map`` has always done the single-species job, but its
only caller was ``/eels/map`` — one signal window per request, and the
result comes back as a REGISTERED ``ImageMeta`` a montage/overlay cannot
consume directly (it would need N round trips just to read N rasters back
out of the library). This exposes the batch case directly: N species in
(each with its own signal window, optional background window, and method),
N inline rasters out — decoupled from ``/eels/quantify-map``, which forces
a full composition quantification the user may not want just to see maps.

Mirrors routes/eds_maps.py's shape and per-row error semantics: a species
the user picked by hand (an edge label, a signal window, maybe a background
window) must never vanish unexplained. A row whose window falls off the
cube's energy axis, or whose background-fit window is degenerate, reports
its reason in that row; a wholly-failed list is still HTTP 200.

Its own module because analysis.py (the other EELS routes) and
analysis_wireups.py both sit near the 500-line god-module ceiling — the
``_cube`` / ``_register_map`` helpers are duplicated here rather than
imported across route boundaries, the same small pattern routes/eds_maps.py
and routes/eds_quant.py already keep locally.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.eels import extract_map
from fermiviewer.datastruct import DataKind, DataStruct
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
    derived = DataStruct(
        data=np.ascontiguousarray(arr), kind=DataKind.IMAGE,
        axes=(parent.axes[0], parent.axes[1]),
        metadata={"source": name, "parser": "derived"},
    )
    new_id = store.add_derived(derived, name, parent_id)
    return ImageMeta.from_datastruct(new_id, name, derived)


class EelsWindow(BaseModel):
    lo: float                        # eV
    hi: float                        # eV


class EelsMapSpec(BaseModel):
    """One requested species — a label plus its integration windows.

    ``label`` is free text (an edge label like "Fe-L23", or anything the
    caller's species list uses); unlike the EDS batch endpoint there is no
    line-energy lookup here; the windows are taken as given. ``background``
    is optional — omitting it sums the signal window directly, the same
    "no background subtraction" behaviour ``extract_map`` gives when its own
    ``background_window`` is ``None``.
    """

    label: str
    signal: EelsWindow
    background: EelsWindow | None = None
    method: str = "powerlaw"         # "powerlaw" | "exponential"


class EelsMapsRequest(BaseModel):
    image_id: str
    species: list[EelsMapSpec]
    save_derived: bool = False


def _outside_axis_reason(
    win: EelsWindow, e_min: float, e_max: float, kind: str
) -> str | None:
    lo, hi = sorted((win.lo, win.hi))
    if lo > e_max or hi < e_min:
        return (
            f"{kind} window [{lo:.3f}, {hi:.3f}] eV is outside the energy "
            f"axis [{e_min:.3f}, {e_max:.3f}] eV"
        )
    return None


@router.post("/eels/maps")
def eels_maps(req: EelsMapsRequest) -> dict:
    """N species → N rasters, without going through quantification.

    Every requested species gets an entry, in request order. A species that
    cannot be mapped (its signal or background window falls outside the
    cube's energy axis, or the background-fit window is degenerate — fewer
    than 2 channels) comes back with ``map: null`` and a human-readable
    ``error`` rather than being dropped.

    Response
    --------
    {
      "image_id": str,
      "shape": [H, W],                        # shared by every successful map
      "maps": [
        {"label": str, "signal_window": [lo, hi]|null,
         "background_window": [lo, hi]|null, "method": str,
         "map": [[float, ...], ...]|null, "total_counts": float|null,
         "map_meta": ImageMeta|null, "error": str|null},
        ...
      ]
    }

    All-failed is still 200 with per-row reasons, so the caller renders a
    partly-failed and a wholly-failed list through one path.
    """
    if not req.species:
        raise HTTPException(422, "no species requested")
    ds = _cube(req.image_id)
    energy = ds.energy_axis            # EELS axis is native eV — no conversion
    e_min, e_max = float(energy.min()), float(energy.max())
    h, w = ds.data.shape[:2]

    out: list[dict] = []
    for spec in req.species:
        label = spec.label.strip()
        reason = _outside_axis_reason(spec.signal, e_min, e_max, "signal")
        bg_window: tuple[float, float] | None = None
        if spec.background is not None:
            b_lo, b_hi = sorted((spec.background.lo, spec.background.hi))
            bg_window = (b_lo, b_hi)
            if reason is None:
                reason = _outside_axis_reason(spec.background, e_min, e_max,
                                              "background")

        m: np.ndarray | None = None
        if reason is None:
            sig_lo, sig_hi = sorted((spec.signal.lo, spec.signal.hi))
            try:
                m = extract_map(ds.data, energy, (sig_lo, sig_hi),
                                bg_window, spec.method)
            except ValueError as e:
                reason = str(e)

        if reason is not None:
            out.append({
                "label": label, "signal_window": None,
                "background_window": None, "method": spec.method,
                "map": None, "total_counts": None, "map_meta": None,
                "error": reason,
            })
            continue

        assert m is not None
        map_meta = None
        if req.save_derived:
            meta = _register_map(m, f"{label} map".strip(), ds, req.image_id)
            map_meta = meta.model_dump()
        out.append({
            "label": label,
            "signal_window": [sig_lo, sig_hi],
            "background_window": list(bg_window) if bg_window is not None else None,
            "method": spec.method,
            "map": m.tolist(),
            "total_counts": float(m.sum()),
            "map_meta": map_meta,
            "error": None,
        })

    return {"image_id": req.image_id, "shape": [h, w], "maps": out}
