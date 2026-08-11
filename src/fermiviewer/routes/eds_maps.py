"""Batch EDS element-map endpoint (SPECTRAL_WORKSPACE_PLAN #8).

``extract_element_maps()`` has always done the multi-species job, but its
only caller was ``/eds/quantify`` — so asking for five element maps forced a
Cliff-Lorimer/ZAF quantification the user may not have wanted. This exposes
the batch map directly, with a per-species window override so it can serve
the species list rather than recomputing default windows.

Why its own module: the single-element ``/eds/element-map`` lives in
routes/analysis_wireups.py, which sits at 432/500 — the size ratchet's rule
is that new code goes in a new focused module, not appended to a file near
its ceiling. The ``_cube`` / ``_register_map`` helpers are duplicated here,
the same small pattern routes/eds_quant.py already keeps locally rather than
importing across route boundaries.

Unlike ``/eds/quantify`` (fed by auto-assign, so it suppresses blank maps to
keep absent elements out of the library), every species here was requested
by name — so every requested map is returned, and registered when
``save_derived`` is set. ``total_counts`` is what the caller flags empties
with.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from fermiviewer.calc.eds import line_energy
from fermiviewer.calc.eds_maps import (
    UnusableElementError,
    element_map,
    resolve_element_window,
)
from fermiviewer.calc.energy_units import to_kev
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.routes._arrays import value_error_as_422
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


class ElementSpec(BaseModel):
    """One requested species.

    A bare string is accepted and means "this symbol, default window", so
    the simple ``["Fe", "Si"]`` batch call stays readable. Supplying
    ``e_lo``/``e_hi`` overrides the window — that is how the species list
    sends its user-tuned windows instead of having them recomputed here.
    """

    symbol: str
    e_lo: float | None = None        # keV — window override; needs e_hi too
    e_hi: float | None = None        # keV
    line: str = "auto"               # "auto" | "K" | "L" | "M"

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_symbol(cls, v: object) -> object:
        return {"symbol": v} if isinstance(v, str) else v


class EdsElementMapsRequest(BaseModel):
    image_id: str
    elements: list[ElementSpec]
    half_window_kev: float = 0.085   # used only where no override is given
    bg: str = "linear"               # "linear" | "none" | "bremsstrahlung"
    bg_width: float | None = None    # background window width (keV)
    bg_gap: float = 0.0              # peak↔background gap (keV)
    beam_kv: float | None = None     # None → inf, i.e. the K line unconditionally
    e0_kev: float | None = None      # beam energy; required for bremsstrahlung
    save_derived: bool = False


def _window_for(
    spec: ElementSpec, e_min: float, e_max: float,
    half_window: float, beam_kv: float,
) -> tuple[float, str, tuple[float, float]]:
    """Resolve one species to (line energy, line label, window).

    An explicit override wins; otherwise the shared calc-layer rule picks
    the principal line. An override is still reported alongside whatever
    line the symbol would have used, so the UI can label the row — and an
    override makes an unknown symbol usable rather than fatal, since the
    window no longer depends on the line table.
    """
    if (spec.e_lo is None) != (spec.e_hi is None):
        raise UnusableElementError("a window override needs both e_lo and e_hi")
    if spec.e_lo is None or spec.e_hi is None:
        return resolve_element_window(
            spec.symbol, e_min, e_max,
            half_window=half_window, beam_kv=beam_kv, line=spec.line,
        )
    lo, hi = sorted((spec.e_lo, spec.e_hi))
    if lo > e_max or hi < e_min:
        raise UnusableElementError(
            f"window [{lo:.3f}, {hi:.3f}] keV is outside the energy axis "
            f"[{e_min:.3f}, {e_max:.3f}] keV"
        )
    e, used = line_energy(spec.symbol.strip(), line=spec.line, beam_kv=beam_kv)
    return float(e), used, (lo, hi)


@router.post("/eds/element-maps")
def eds_element_maps(req: EdsElementMapsRequest) -> dict:
    """N species → N rasters, without going through quantification.

    Every requested species gets an entry, in request order. A species that
    cannot be mapped (no known line, or its line/window falls outside the
    cube's energy axis) comes back with ``map: null`` and a human-readable
    ``error`` rather than being dropped — a row the user picked by hand must
    not vanish unexplained, which is the one behaviour this endpoint does
    NOT inherit from ``extract_element_maps``'s warn-and-skip.

    Response
    --------
    {
      "image_id": str,
      "shape": [H, W],                     # shared by every successful map
      "bg": str,
      "maps": [
        {"symbol": str, "line": str|null, "energy_kev": float|null,
         "window": [lo, hi]|null, "map": [[float, ...], ...]|null,
         "total_counts": float|null, "map_meta": ImageMeta|null,
         "error": str|null},
        ...
      ]
    }

    All-failed is still 200 with per-row reasons, so the caller renders a
    partly-failed and a wholly-failed list through one path.
    """
    if not req.elements:
        raise HTTPException(422, "no elements requested")
    ds = _cube(req.image_id)
    # Windows and the line library are keV; the axis may be in eV.
    energy = to_kev(ds.energy_axis, ds.energy_cal.units)
    e_min, e_max = float(energy.min()), float(energy.max())
    beam_kv = float("inf") if req.beam_kv is None else req.beam_kv
    h, w = ds.data.shape[:2]

    out: list[dict] = []
    with value_error_as_422():          # cube-wide shape errors abort the batch
        for spec in req.elements:
            sym = spec.symbol.strip()
            try:
                e_kev, line, win = _window_for(
                    spec, e_min, e_max, req.half_window_kev, beam_kv
                )
            except UnusableElementError as exc:
                out.append({
                    "symbol": sym, "line": None, "energy_kev": None,
                    "window": None, "map": None, "total_counts": None,
                    "map_meta": None, "error": str(exc),
                })
                continue
            m = element_map(
                ds.data, energy, win[0], win[1],
                bg=req.bg,
                bg_width=float("nan") if req.bg_width is None else req.bg_width,
                bg_gap=req.bg_gap,
                e0_kev=float("nan") if req.e0_kev is None else req.e0_kev,
            )
            map_meta = None
            if req.save_derived:
                meta = _register_map(m, f"{sym} {line} map".strip(), ds,
                                     req.image_id)
                map_meta = meta.model_dump()
            out.append({
                "symbol": sym,
                "line": line or None,
                "energy_kev": float(e_kev) if np.isfinite(e_kev) else None,
                "window": [win[0], win[1]],
                "map": m.tolist(),
                "total_counts": float(m.sum()),
                "map_meta": map_meta,
                "error": None,
            })

    return {"image_id": req.image_id, "shape": [h, w], "bg": req.bg,
            "maps": out}
