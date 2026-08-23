"""Grain-report numerics — the derived statistics behind
POST /analyze/grains' payload, lifted out of `routes/structure_grains.py`
(wave A, ADR 0005 §1) so the registered `grains` op and the HTTP route
compute the SAME report instead of the op re-deriving the mean-diameter /
ASTM number arithmetic that used to live in the route's `_grains_payload`.

Session-free by construction: the route keeps naming and registering the
label map (`_register`, `store.name`); this module only turns a label
image into numbers. Lives in its own module because `calc/grains.py`
already sits near the 500-line module ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.grains import astm_grain_size_number, grain_stats

__all__ = ["GrainReport", "grain_report"]


@dataclass(frozen=True)
class GrainReport:
    """The numeric grain report. Calibrated fields are NaN (never None)
    when the source image carries no spatial calibration — presentation
    layers decide how to render missing values."""

    n_grains: int
    #: renumbered compact 1..n label map (background 0), from `grain_stats`
    labels: np.ndarray
    boundary_network_px: float
    boundary_network_calibrated: float
    n_boundary_segments: int
    n_triple_junctions: int
    mean_diameter_px: float
    astm_grain_size: float
    area_px: np.ndarray
    perimeter_crofton_px: np.ndarray
    eccentricity: np.ndarray
    equiv_diameter_px: np.ndarray
    diameter_calibrated: np.ndarray
    unit: str


def grain_report(
    labels: np.ndarray,
    raster: np.ndarray,
    *,
    pixel_size: float = float("nan"),
    unit: str = "px",
) -> GrainReport:
    """Stats + derived aggregates for a grain-label image over its raster."""
    stats = grain_stats(labels, raster, pixel_size=pixel_size)
    diam_cal = stats.diameter_calibrated
    mean_diam_cal = float(np.nanmean(diam_cal)) if diam_cal.size else float("nan")
    return GrainReport(
        n_grains=stats.n_grains,
        labels=stats.labels,
        boundary_network_px=stats.boundary_network_px,
        boundary_network_calibrated=stats.boundary_network_calibrated,
        n_boundary_segments=stats.n_boundary_segments,
        n_triple_junctions=stats.n_triple_junctions,
        mean_diameter_px=(
            float(stats.equiv_diameter_px.mean()) if stats.equiv_diameter_px.size else 0.0
        ),
        astm_grain_size=astm_grain_size_number(mean_diam_cal, unit),
        area_px=stats.area_px,
        perimeter_crofton_px=stats.perimeter_crofton_px,
        eccentricity=stats.eccentricity,
        equiv_diameter_px=stats.equiv_diameter_px,
        diameter_calibrated=stats.diameter_calibrated,
        unit=unit,
    )
