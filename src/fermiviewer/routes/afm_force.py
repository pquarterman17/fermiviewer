"""AFM force curves: the opened files (session_force.py), one curve with
its analysis (calc/afm_force.py), and force-map images.

Calibration: the file's spring constant and InvOLS are used unless the
request overrides them. A new InvOLS rescales a deflection the file gives
in nm (by new / file InvOLS) and converts one given in V.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.afm_force import ForceAnalysis, Tip, analyze_curve, contact_force
from fermiviewer.calc.afm_force_batch import CurveArrays, analyze_curves
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.force_common import ForceCurve, ForceFile
from fermiviewer.models import ForceMeta, ImageMeta
from fermiviewer.session import store
from fermiviewer.session_force import UnknownForceError, force_store

__all__ = ["router"]

router = APIRouter(prefix="/api/afm/force")

_MAX_POINTS = 4096          # per returned segment


def _file(force_id: str) -> ForceFile:
    try:
        return force_store.get(force_id)
    except UnknownForceError:
        raise HTTPException(404, f"unknown force file: {force_id}") from None


def _curve(f: ForceFile, index: int) -> ForceCurve:
    if not 0 <= index < len(f.curves):
        raise HTTPException(404, f"curve {index} out of range (0–{len(f.curves) - 1})")
    return f.curves[index]


def _thin(*arrays: np.ndarray) -> list[list[float]]:
    n = arrays[0].size
    idx = np.linspace(0, n - 1, _MAX_POINTS).round().astype(int) if n > _MAX_POINTS else slice(None)
    return [np.round(a[idx], 6).tolist() for a in arrays]


def _num(v: float) -> float | None:
    return float(v) if math.isfinite(v) else None


@router.get("")
def list_force() -> list[ForceMeta]:
    return [ForceMeta.from_file(i, force_store.name(i), force_store.get(i))
            for i in force_store.ids()]


@router.get("/{force_id}")
def force_meta(force_id: str) -> ForceMeta:
    f = _file(force_id)
    return ForceMeta.from_file(force_id, force_store.name(force_id), f)


@router.delete("/{force_id}")
def close_force(force_id: str) -> None:
    try:
        force_store.close(force_id)
    except UnknownForceError:
        raise HTTPException(404, f"unknown force file: {force_id}") from None


@router.get("/{force_id}/curve/{index}")
def curve_data(force_id: str, index: int) -> dict:
    """Raw segments (Z in nm, deflection in the file's unit), time order."""
    f = _file(force_id)
    c = _curve(f, index)
    return {
        "label": c.label,
        "position_nm": list(c.position_nm) if c.position_nm else None,
        "deflection_unit": f.deflection_unit,
        "segments": [dict(zip(("z", "deflection"), _thin(s.z, s.deflection), strict=True),
                          kind=s.kind) for s in c.segments],
    }


class ForceSettings(BaseModel):
    spring_constant: float | None = Field(None, gt=0)    # N/m; None = the file's
    invols: float | None = Field(None, gt=0)             # nm/V; None = the file's
    tip: Literal["sphere", "cone", "pyramid", "flat"] = "sphere"
    radius_nm: float = Field(20.0, gt=0)
    half_angle_deg: float = Field(20.0, gt=0, lt=90)
    poisson: float = Field(0.5, ge=0, le=0.5)
    baseline_from: float = Field(0.0, ge=0, lt=1)       # fraction of the approach Z range
    baseline_to: float = Field(0.5, gt=0, le=1)
    max_indent_nm: float | None = Field(None, gt=0)
    max_force_nn: float | None = Field(None, gt=0)
    fit: bool = True


def _calibration(f: ForceFile, s: ForceSettings) -> tuple[float, float, float]:
    """(spring constant, InvOLS used, factor taking the deflection to nm)."""
    k = s.spring_constant or f.spring_constant
    if not math.isfinite(k) or k <= 0:
        raise HTTPException(422, "the file has no spring constant — enter one")
    invols = s.invols or f.invols
    if f.deflection_unit == "V":
        if not math.isfinite(invols):
            raise HTTPException(422, "deflection is in volts — enter the InvOLS (nm/V)")
        return k, invols, invols
    if s.invols is None:
        return k, invols, 1.0
    if not math.isfinite(f.invols):
        raise HTTPException(422, "the file gives deflection in nm without its InvOLS, "
                                 "so a new InvOLS cannot be applied")
    return k, invols, s.invols / f.invols


def _options(s: ForceSettings, k: float) -> dict:
    if s.baseline_to <= s.baseline_from:
        raise HTTPException(422, "the baseline window is empty")
    return dict(k=k, tip=Tip(s.tip, s.radius_nm, s.half_angle_deg), poisson=s.poisson,
                baseline=(s.baseline_from, s.baseline_to), max_indent=s.max_indent_nm,
                max_force=s.max_force_nn, fit=s.fit)


def _arrays(c: ForceCurve, scale: float) -> CurveArrays:
    a, r = c.approach, c.retract
    assert a is not None
    return (a.z, a.deflection * scale, r.z if r else None,
            r.deflection * scale if r else None)


def _analyze(c: ForceCurve, s: ForceSettings, k: float, scale: float) -> ForceAnalysis:
    return analyze_curve(*_arrays(c, scale), **_options(s, k))


_UNITS = {"youngs_modulus": "Pa", "e_r": "GPa", "contact_z": "nm", "max_force": "nN",
          "snap_in": "nN", "adhesion": "nN", "adhesion_z": "nm", "adhesion_energy": "aJ",
          "max_indentation": "nm", "noise_nm": "nm", "fit_rms": "nN", "fit_r2": "",
          "fit_points": "", "contact_slope": ""}


@router.post("/{force_id}/curve/{index}/analyze")
def analyze(force_id: str, index: int, s: ForceSettings) -> dict:
    """One curve: values, and force vs Z / separation for plotting."""
    f = _file(force_id)
    c = _curve(f, index)
    k, invols, scale = _calibration(f, s)
    try:
        res = _analyze(c, s, k, scale)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    slope, offset = res.baseline
    zc = res.contact_z
    plot = {}
    for seg in c.segments:
        d = seg.deflection * scale - (slope * seg.z + offset)
        z, force, sep = _thin(seg.z, k * d, (zc - seg.z) + d)
        plot[seg.kind] = {"z": z, "force": force, "separation": sep}
    fit = None
    if math.isfinite(res.e_r):
        a = c.approach
        assert a is not None
        d = a.deflection * scale - (slope * a.z + offset)
        in_contact = (a.z >= zc) & (k * d <= (s.max_force_nn or np.inf))
        if s.max_indent_nm is not None:
            in_contact &= (a.z - zc) - d <= s.max_indent_nm
        tip = Tip(s.tip, s.radius_nm, s.half_angle_deg)
        model = contact_force((a.z - zc) - d, res.e_r, tip)
        z, force, sep = _thin(a.z[in_contact], model[in_contact], ((zc - a.z) + d)[in_contact])
        fit = {"z": z, "force": force, "separation": sep}
    values = {key: _num(float(getattr(res, key))) for key in _UNITS}
    return {
        "values": values, "units": _UNITS, "plot": plot, "fit": fit,
        "spring_constant": k, "invols": _num(invols),
        "baseline": {"slope": slope, "offset_nm": offset},
    }


_MOD_UNITS = (("GPa", 1e9), ("MPa", 1e6), ("kPa", 1e3), ("Pa", 1.0))


def _modulus_unit(values: np.ndarray) -> tuple[str, float]:
    finite = values[np.isfinite(values)]
    med = float(np.median(np.abs(finite))) if finite.size else 1.0
    return next(((u, f) for u, f in _MOD_UNITS if med >= f), ("Pa", 1.0))


@router.post("/{force_id}/maps")
def force_maps(force_id: str, s: ForceSettings) -> dict:
    """Every curve analysed; a force map also becomes modulus, adhesion and
    contact-height images (registered in the session)."""
    f = _file(force_id)
    k, _, scale = _calibration(f, s)
    results = analyze_curves([_arrays(c, scale) for c in f.curves], **_options(s, k))
    failed = sum(r is None for r in results)
    rows = [(r.youngs_modulus, r.adhesion, r.contact_z, r.max_force, r.fit_r2)
            if r is not None else (math.nan,) * 5 for r in results]
    cols = np.array(rows, dtype=np.float64).T
    table = {name: [_num(v) for v in col] for name, col in
             zip(("youngs_modulus", "adhesion", "contact_z", "max_force", "fit_r2"), cols,
                 strict=True)}
    images: list[ImageMeta] = []
    if f.grid is not None:
        mod_unit, mod_div = _modulus_unit(cols[0])
        height = -cols[2]
        height = height - np.nanmin(height) if np.isfinite(height).any() else height
        for label, data, unit in (("Young's modulus", cols[0] / mod_div, mod_unit),
                                  ("Adhesion", cols[1], "nN"), ("Contact height", height, "nm")):
            images.append(_register(f, force_id, label, data.reshape(f.grid), unit))
    return {"n": len(f.curves), "failed": failed, "table": table,
            "units": {"youngs_modulus": "Pa", "adhesion": "nN", "contact_z": "nm",
                      "max_force": "nN", "fit_r2": ""},
            "images": [m.model_dump() for m in images]}


def _register(f: ForceFile, force_id: str, label: str, data: np.ndarray, unit: str) -> ImageMeta:
    dy, dx = f.map_pitch_nm or (math.nan, math.nan)
    axes = (AxisCal(dy, 0.0, "nm") if math.isfinite(dy) else AxisCal(1.0, 0.0, ""),
            AxisCal(dx, 0.0, "nm") if math.isfinite(dx) else AxisCal(1.0, 0.0, ""))
    ds = DataStruct(data=np.ascontiguousarray(data, dtype=np.float64), kind=DataKind.IMAGE,
                    axes=axes, metadata={"source": label, "parser": "derived",
                                         "value_unit": unit, "force_map": force_id})
    name = f"{label}({force_store.name(force_id)})"
    img_id = store.add_parsed(ds, name)
    return ImageMeta.from_datastruct(img_id, name, ds)
