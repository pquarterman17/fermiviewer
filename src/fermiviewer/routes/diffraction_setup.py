"""Diffraction setup endpoints — elliptical-distortion calibration + custom
phase import (Diffraction #1/#2 wiring).

Thin adapters over calc/diffraction_calib.py and calc/cif.py +
calc/phase_registry.py. Kept in their own module because routes/analysis.py is
at the 500-line ceiling.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc import diffraction_calib as dcal
from fermiviewer.calc.cif import CIFParseError, parse_cif
from fermiviewer.calc.crystal import PHASES
from fermiviewer.calc.phase_registry import registry, standard_d_spacing
from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _raster(image_id: str) -> np.ndarray:
    try:
        ds = store.get(image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {image_id}") from None
    try:
        return raster_of(ds)
    except NoRasterError:
        raise HTTPException(400, "calibration needs a 2D diffraction image") from None


# ── elliptical-distortion + camera-constant calibration ──────────────

class CalibrateRequest(BaseModel):
    image_id: str
    # the standard ring's known d-spacing (Å) to anchor the camera constant;
    # if omitted but a standard phase + hkl are given, it is computed
    d_known_ang: float | None = None
    standard_phase: str | None = None      # e.g. "Gold"
    hkl: tuple[int, int, int] | None = None  # the anchored ring's reflection
    r_min: float = 5.0
    r_max: float | None = None
    n_angles: int = 180


@router.post("/diffraction/calibrate")
def diffraction_calibrate(req: CalibrateRequest) -> dict:
    """Fit an ellipse to the dominant ring, un-distort it, and (if a standard
    d is supplied/derivable) anchor the camera constant C = R·d.

    Returns the ellipse (centre, semi-axes, angle, eccentricity), the RMS
    radial residual of the un-distorted ring, and the camera constant."""
    raster = _raster(req.image_id)
    # detect -> fit -> un-distort lives in calc (wave C, ADR 0005 §1 —
    # shared with the registered `diffraction_calibrate` op)
    try:
        cal = dcal.calibrate_rings(
            raster, r_min=req.r_min, r_max=req.r_max, n_angles=req.n_angles
        )
    except ValueError as e:  # too few ring points, bad n_angles, degenerate fit
        raise HTTPException(422, str(e)) from None
    ellipse = cal.ellipse

    # resolve the anchor d-spacing: explicit, or from a standard phase + hkl
    d_known = req.d_known_ang
    if d_known is None and req.standard_phase and req.hkl:
        try:
            d_known = standard_d_spacing(req.standard_phase, req.hkl)
        except ValueError as e:  # hkl (0,0,0) — previously a latent 500 (inf)
            raise HTTPException(422, str(e)) from None
        if d_known is None:
            raise HTTPException(422, f"unknown standard phase '{req.standard_phase}'")

    cam_const = (
        dcal.camera_constant(d_known, ellipse.mean_radius)
        if d_known and d_known > 0
        else None
    )
    return {
        "ellipse": {
            "center_row": ellipse.center_row,
            "center_col": ellipse.center_col,
            "a": ellipse.a,
            "b": ellipse.b,
            "theta_deg": float(np.degrees(ellipse.theta)),
            "eccentricity": ellipse.eccentricity,
            "mean_radius": ellipse.mean_radius,
        },
        "n_points": cal.n_points,
        "rms_residual_px": cal.rms_residual_px,
        "d_known_ang": d_known,
        "camera_constant_px_ang": cam_const,
    }


# ── custom phase import (CIF / delete) ───────────────────────────────

class CifImportRequest(BaseModel):
    cif_text: str
    name: str = ""  # optional display-name override


@router.post("/diffraction/phases/import")
def import_phase(req: CifImportRequest) -> dict:
    """Parse CIF text into a Phase, register it, and return its summary."""
    try:
        phase = parse_cif(req.cif_text, name=req.name)
    except CIFParseError as e:
        raise HTTPException(422, f"CIF parse error: {e}") from None
    registry.add(phase)
    return {
        "name": phase.name,
        "formula": phase.formula,
        "centering": phase.centering,
        "system": phase.system,
        "a": phase.a,
        "b": phase.b,
        "c": phase.c,
        "n_sites": len(phase.basis),
        "custom": True,
    }


@router.delete("/diffraction/phases/{name}")
def delete_phase(name: str) -> dict:
    """Remove a custom phase by name (built-in phases are never removed)."""
    if name in {p.name for p in PHASES}:
        raise HTTPException(422, f"'{name}' is a built-in phase — cannot delete")
    if not registry.remove(name):
        raise HTTPException(404, f"no custom phase '{name}'")
    return {"removed": name}
