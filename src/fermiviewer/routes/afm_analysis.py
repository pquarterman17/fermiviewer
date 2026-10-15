"""AFM/SPM surface analysis: ISO 25178 parameters with their spectra and
histograms, 2-D PSD / autocorrelation maps, and step height.

Heights are pixel values in the image's ``value_unit``; lateral distances
use the pixel spacing in ``pixel_unit``. Parameters that mix the two
(slopes, developed area) are reported only when both are known lengths.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc import afm_surface as surf
from fermiviewer.calc.afm_features import step_height_evidence
from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.calc.roi import extract_rect_roi
from fermiviewer.datastruct import DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.ops.catalogue_afm import (
    areal_values,
    lateral_scale,
    level_for_analysis,
    z_to_lateral,
)
from fermiviewer.ops.catalogue_afm import (
    surface_map as build_surface_map,
)
from fermiviewer.session import UnknownImageError, store

__all__ = ["router"]

router = APIRouter(prefix="/api/afm")

Roi = tuple[int, int, int, int]          # 1-based, inclusive (r1, c1, r2, c2)
_MAX_CURVE = 512                          # points per returned curve


def _load(image_id: str, roi: Roi | None, level: str) -> tuple[DataStruct, np.ndarray]:
    try:
        ds = store.get(image_id)
        z = raster_of(ds)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {image_id}") from None
    except NoRasterError:
        raise HTTPException(400, "1D spectra have no raster") from None
    try:
        return ds, level_for_analysis(extract_rect_roi(z, roi), level)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


def _thin(x: np.ndarray, y: np.ndarray) -> tuple[list[float], list[float]]:
    if x.size > _MAX_CURVE:
        idx = np.linspace(0, x.size - 1, _MAX_CURVE).round().astype(int)
        x, y = x[idx], y[idx]
    return x.tolist(), y.tolist()


def _num(v: float) -> float | None:
    return float(v) if np.isfinite(v) else None


_PARAMS = ("Sa", "Sq", "Ssk", "Sku", "Sp", "Sv", "Sz", "Sdq", "Sdr", "Sal", "Str", "Std",
           "Sk", "Spk", "Svk", "Smr1", "Smr2", "Vmp", "Vmc", "Vvc", "Vvv")


class SurfaceRequest(BaseModel):
    roi: Roi | None = None
    level: Literal["none", "plane", "quadratic"] = "plane"


@router.post("/{image_id}/surface")
def surface(image_id: str, req: SurfaceRequest) -> dict:
    """ISO 25178 field parameters, radial PSD, height and slope histograms."""
    ds, z = _load(image_id, req.roi, req.level)
    dy, dx, lat = lateral_scale(ds)
    k = z_to_lateral(ds)
    try:
        values = areal_values(ds, z)
        psd, fy, fx = surf.psd_2d(z, dy, dx)
        hx, hy = surf.height_histogram(z)
        sx, sy = surf.slope_histogram(z, dy, dx, k)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    f, power = surf.radial_psd(psd, fy, fx)
    zu = values["unit"] or "a.u."
    params = {key: values[key] for key in _PARAMS}
    units = {**{key: zu for key in ("Sa", "Sq", "Sp", "Sv", "Sz")},
             "Ssk": "", "Sku": "", "Sdq": "", "Sdr": "%", "Sal": lat, "Str": "", "Std": "°",
             # volumes per unit area carry the height unit (nm³/nm² = nm)
             **{key: zu for key in ("Sk", "Spk", "Svk", "Vmp", "Vmc", "Vvc", "Vvv")},
             "Smr1": "%", "Smr2": "%"}
    return {
        "params": {key: _num(v) for key, v in params.items()},
        "units": units,
        "z_unit": zu,
        "lateral_unit": lat,
        "n_pixels": values["n_pixels"],
        "level": req.level,
        "roi": list(req.roi) if req.roi is not None else None,
        "slopes_calibrated": bool(np.isfinite(k)),
        "psd": dict(zip(("frequency", "power"), _thin(f, power), strict=True)),
        "height_hist": dict(zip(("height", "percent"), _thin(hx, hy), strict=True)),
        "slope_hist": dict(zip(("angle", "percent"), _thin(sx, sy), strict=True)),
    }


class MapRequest(BaseModel):
    kind: Literal["psd", "acf"]
    roi: Roi | None = None
    level: Literal["none", "plane", "quadratic"] = "plane"


@router.post("/{image_id}/map")
def surface_map(image_id: str, req: MapRequest) -> ImageMeta:
    """The 2-D PSD (log10) or autocorrelation as a new image, with
    frequency or lag axes centred on zero."""
    ds, z = _load(image_id, req.roi, req.level)
    try:
        derived = build_surface_map(ds, z, req.kind)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    label = derived.metadata["source"]
    name = f"{label}({store.name(image_id)})"
    new_id = store.add_derived(derived, name, image_id)
    return ImageMeta.from_datastruct(new_id, name, derived)


class StepRequest(BaseModel):
    roi: Roi | None = None
    edge: int = 2
    split_axis: Literal["x", "y"] | None = None
    split_fraction: float | None = None


def _sample_curve(values: np.ndarray, limit: int = 256) -> list[float | None]:
    idx = np.linspace(0, max(values.size - 1, 0), min(values.size, limit), dtype=int)
    return [float(v) if np.isfinite(v) else None for v in values[idx]]


def _sample_mask(values: np.ndarray, limit: int = 64) -> list[list[int]]:
    rows = np.linspace(0, values.shape[0] - 1, min(values.shape[0], limit), dtype=int)
    cols = np.linspace(0, values.shape[1] - 1, min(values.shape[1], limit), dtype=int)
    sampled = values[np.ix_(rows, cols)]
    return [[int(value) for value in row] for row in sampled]


@router.post("/{image_id}/step-height")
def measure_step(image_id: str, req: StepRequest) -> dict:
    """Step between two terraces inside the ROI (draw it across the edge)."""
    if not 0 <= req.edge <= 20:
        raise HTTPException(422, "edge exclusion must be 0–20 pixels")
    if (req.split_axis is None) != (req.split_fraction is None):
        raise HTTPException(422, "manual split requires both an axis and a position")
    if req.split_fraction is not None and not 0.05 <= req.split_fraction <= 0.95:
        raise HTTPException(422, "manual split position must be 5–95%")
    ds, z = _load(image_id, req.roi, "none")
    initial_upper: np.ndarray | None = None
    if req.split_axis is not None and req.split_fraction is not None:
        split = int(round(req.split_fraction * z.shape[1 if req.split_axis == "x" else 0]))
        yy, xx = np.indices(z.shape)
        initial_upper = np.asarray(
            (xx >= split) if req.split_axis == "x" else (yy >= split), dtype=bool,
        )
    try:
        evidence = step_height_evidence(
            z, edge=req.edge, n_iter=1 if initial_upper is not None else 6,
            initial_upper=initial_upper,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    s = evidence.result
    return {
        "height": s.height, "lower_std": s.lower_std, "upper_std": s.upper_std,
        "n_lower": s.n_lower, "n_upper": s.n_upper, "upper_fraction": s.upper_fraction,
        "unit": str(ds.metadata.get("value_unit") or "") or "a.u.",
        "roi": list(req.roi) if req.roi is not None else None,
        "signed_height": evidence.signed_height, "profile_axis": evidence.axis,
        "profile_position": _sample_curve(evidence.position),
        "profile_measured": _sample_curve(evidence.measured),
        "profile_fitted": _sample_curve(evidence.fitted),
        "profile_residual": _sample_curve(evidence.residual),
        "profile_upper_fraction": _sample_curve(evidence.upper_fraction_profile),
        "terrace_mask": _sample_mask(evidence.terraces),
        "slope_x": evidence.slope_x, "slope_y": evidence.slope_y,
        "fit_rms": evidence.fit_rms,
        "split_axis": req.split_axis, "split_fraction": req.split_fraction,
    }
