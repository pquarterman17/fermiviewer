"""Analysis wire-up endpoints: A3 Back Project, A4 Composition Profile,
A5 ELNES, A8 Simulate + phase list.

These were split out of routes/analysis.py to stay under the 500-line
god-module ceiling. All helpers (_get, _spectral, _register_map) are
imported from that module.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc import diffraction as diff
from fermiviewer.calc.crystal import PHASES
from fermiviewer.calc.eds import assign_elements, detect_peaks
from fermiviewer.calc.eds_maps import composition_profile
from fermiviewer.calc.eels_quant import elnes
from fermiviewer.calc.tomo import back_project
from fermiviewer.datastruct import DataKind
from fermiviewer.models import ImageMeta
from fermiviewer.routes.analysis import _get, _register_map, _spectral

router = APIRouter(prefix="/api")


# ── A3 Back Project (FBP) ─────────────────────────────────────────────

class BackProjectRequest(BaseModel):
    image_id: str
    filter: str = "ramp"         # ramp | shepp-logan | hamming | none
    output_size: int = 0         # 0 → projection width


@router.post("/analyze/back-project")
def analyze_back_project(req: BackProjectRequest) -> ImageMeta:
    """Filtered back-projection reconstruction (A3 — tomo.back_project).

    Expects the active image to be a sinogram: rows=angles, cols=width.
    Registers the square reconstruction as a derived image.
    """
    ds = _get(req.image_id)
    if ds.kind is not DataKind.IMAGE:
        raise HTTPException(400, "back-project requires a 2D sinogram image")
    sino = ds.data.astype(np.float64)
    if sino.ndim != 2:
        raise HTTPException(400, "back-project requires a 2D sinogram image")
    try:
        result = back_project(sino, filter_name=req.filter,
                              output_size=req.output_size)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    name = f"FBP [{req.filter}]"
    return _register_map(result.reconstruction, name, ds, req.image_id)


# ── A4 Composition Profile (EDS SI) ──────────────────────────────────

class CompositionProfileRequest(BaseModel):
    image_id: str            # unused by the handler; kept for API symmetry
    map_ids: list[str]       # derived at% map image IDs (from /eds/quantify)
    elements: list[str]      # element symbols, same order as map_ids
    x1: float                # 1-based pixel coords
    y1: float
    x2: float
    y2: float
    n_points: int = 200
    width: float = 1.0       # averaging width (px)


@router.post("/analyze/composition-profile")
def analyze_composition_profile(req: CompositionProfileRequest) -> dict:
    """Width-averaged element-fraction line profile (A4).

    map_ids must point to at% maps (derived from /eds/quantify or
    /eels/quantify-map) with the same spatial extent. Returns (distance,
    atomic_pct) arrays — one series per element — ready for uPlot.
    """
    if len(req.map_ids) != len(req.elements):
        raise HTTPException(422, "map_ids and elements must have equal length")
    maps = []
    ps = float("nan")
    ref_shape: tuple[int, int] | None = None
    for mid in req.map_ids:
        ds = _get(mid)
        if ds.kind is not DataKind.IMAGE:
            raise HTTPException(422, f"image {mid} is not a 2D map")
        if ref_shape is None:
            ref_shape = (int(ds.data.shape[0]), int(ds.data.shape[1]))
            if ds.pixel_cal.calibrated:
                ps = ds.pixel_cal.scale
        maps.append(ds.data.astype(np.float64))
    if not maps:
        raise HTTPException(422, "at least one map_id is required")
    try:
        dist, pct = composition_profile(
            maps, req.elements,
            req.x1, req.y1, req.x2, req.y2,
            n_points=req.n_points,
            pixel_size=ps if np.isfinite(ps) else 1.0,
            width=req.width,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    unit = "nm" if np.isfinite(ps) else "px"
    return {
        "distance": dist.tolist(),
        "atomic_pct": pct.T.tolist(),   # [n_elements, n_points]
        "elements": req.elements,
        "unit": unit,
    }


# ── A5 ELNES fingerprint ──────────────────────────────────────────────

class ElnesRequest(BaseModel):
    image_id: str
    edge_onset: float                             # eV
    fit_window: tuple[float, float]               # pre-edge bg window (eV)
    elnes_window: tuple[float, float] = (0.0, 30.0)   # relative to onset
    method: str = "powerlaw"
    normalize: bool = True
    reference_id: str | None = None              # optional ref spectrum id


@router.post("/analyze/elnes")
def analyze_elnes(req: ElnesRequest) -> dict:
    """Near-edge fine-structure extraction (A5 — eelsELNES.m port).

    Returns (relative_energy, intensity) for the requested spectrum.
    When reference_id is given, a second set of arrays is returned for
    overlay comparison of reference vs measured ELNES.
    """
    ds = _spectral(req.image_id)
    energy = ds.energy_axis
    spec = ds.sum_spectrum()
    try:
        res = elnes(energy, spec, req.edge_onset, req.fit_window,
                    req.elnes_window, req.method, req.normalize)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    out: dict = {
        "relative_energy": res.relative_energy.tolist(),
        "intensity": res.intensity.tolist(),
        "edge_jump": res.edge_jump,
        "edge_onset": res.edge_onset,
        "background_params": res.background_params,
    }

    if req.reference_id is not None:
        ref_ds = _spectral(req.reference_id)
        ref_energy = ref_ds.energy_axis
        ref_spec = ref_ds.sum_spectrum()
        try:
            ref_res = elnes(
                ref_energy, ref_spec, req.edge_onset, req.fit_window,
                req.elnes_window, req.method, req.normalize,
            )
        except ValueError as e:
            raise HTTPException(422, f"reference: {e}") from None
        out["reference_energy"] = ref_res.relative_energy.tolist()
        out["reference_intensity"] = ref_res.intensity.tolist()

    return out


# ── A8 Kinematic diffraction simulation ──────────────────────────────

class SimulateRequest(BaseModel):
    phase_name: str
    zone_axis: tuple[int, int, int] = (0, 0, 1)
    acc_voltage: float = 200.0
    camera_length: float = 200.0
    pixel_size: float = 0.05
    image_size: tuple[int, int] = (512, 512)
    max_hkl: int = 5
    min_intensity: float = 0.01
    spot_sigma: float = 3.0
    parent_image_id: str | None = None        # register as derived of this DP


@router.get("/diffraction/phases")
def diffraction_phases() -> dict:
    """Return the list of phases in the built-in database (A8 UI)."""
    return {
        "phases": [
            {"name": p.name, "formula": p.formula, "category": p.category}
            for p in PHASES
        ]
    }


@router.post("/analyze/simulate")
def analyze_simulate(req: SimulateRequest) -> dict:
    """Kinematic zone-axis pattern simulation (A8 — simulateDiffraction.m).

    Returns the rendered image (registered as a derived image when
    parent_image_id is given) plus the spot list for overlay rendering.
    """
    try:
        result = diff.simulate(
            req.phase_name,
            zone_axis=req.zone_axis,
            acc_voltage=req.acc_voltage,
            camera_length=req.camera_length,
            pixel_size=req.pixel_size,
            image_size=req.image_size,
            max_hkl=req.max_hkl,
            min_intensity=req.min_intensity,
            spot_sigma=req.spot_sigma,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(422, str(e)) from None

    img_meta: dict | None = None
    if req.parent_image_id is not None:
        parent_ds = _get(req.parent_image_id)
        za = req.zone_axis
        label = f"Sim {req.phase_name} [{za[0]}{za[1]}{za[2]}]"
        meta = _register_map(result.image, label, parent_ds, req.parent_image_id)
        img_meta = meta.model_dump()

    return {
        "phase": result.phase_name,
        "formula": result.formula,
        "zone_axis": list(result.zone_axis),
        "lam_angstrom": result.lam,
        "spots": [
            {
                "hkl": list(s.hkl),
                "d_spacing": (
                    s.d_spacing if np.isfinite(s.d_spacing) else None
                ),
                "intensity": s.intensity,
                "row": s.pixel_row,
                "col": s.pixel_col,
            }
            for s in result.spots
        ],
        "image": img_meta,
    }


# ── D10 / #44 EDS auto-assign elements ───────────────────────────────

class EdsAutoAssignRequest(BaseModel):
    image_id: str
    tolerance_kev: float = 0.15      # match window half-width (keV)
    threshold: float = 0.05          # peak detection floor (fraction of max)


@router.post("/eds/auto-assign")
def eds_auto_assign(req: EdsAutoAssignRequest) -> dict:
    """Peak-detection + line-matching for EDS element auto-assign (#44).

    Detects local maxima in the sum spectrum above threshold * max, then
    matches each peak to known K/L/M lines within tolerance_kev. Returns
    candidate element assignments sorted by |delta| for each peak.
    The caller populates the element-symbols input and the user can edit.
    """
    ds = _spectral(req.image_id)
    energy = ds.energy_axis            # keV (EDS axis)
    counts = ds.sum_spectrum()
    try:
        peak_kev = detect_peaks(energy, counts, threshold=req.threshold)
        assignments = assign_elements(peak_kev, tolerance_kev=req.tolerance_kev)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {
        "peaks_kev": peak_kev.tolist(),
        "assignments": [
            {
                "peak_kev": pa.peak_kev,
                "candidates": [
                    {
                        "symbol": ca.symbol,
                        "line": ca.line,
                        "energy_kev": ca.energy_kev,
                        "delta_kev": ca.delta_kev,
                    }
                    for ca in pa.candidates
                ],
            }
            for pa in assignments
        ],
    }
