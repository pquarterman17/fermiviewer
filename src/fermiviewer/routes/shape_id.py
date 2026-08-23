"""Shape-identification endpoints (SHAPE_ANALYSIS_PLAN Tier-2, items #4
and #5): EFD similarity ranking and circle/ellipse fitting. THIN adapters
over `calc/efd.py` and `calc/shape_fit.py` -- no numerics live here.

`POST /analyze/efd-similarity` mirrors `routes/structure.py`'s
`ParticleRequest` by IMPORTING it (`EfdSimilarityRequest(ParticleRequest)`
below), not by redeclaring its fields. Import was chosen over a
hand-copied mirror because it is directly possible without editing
`structure.py` -- `ParticleRequest` is already a plain, importable
`BaseModel` -- and `routes/structure_grains.py` already establishes this
exact cross-route-module pattern (`from fermiviewer.routes.structure
import _nan_none, _raster, _register`), so this is not a new coupling
shape for the codebase. The alternative (hand-copying the six
`ParticleRequest` fields into a new class) would silently drift the moment
A1 changes `structure.py`'s request shape -- inheritance cannot drift.
`_raster` is reused the same way, for the identical image-lookup-plus-404
logic `structure.py` already has right.

Stateless recompute pattern (matches `/analyze/particles`): the request
carries the SAME segmentation parameters as `/analyze/particles`, plus
`ref_id`. Nothing is cached between calls -- segmentation, contour
tracing and EFD are all recomputed from scratch every request, then every
resulting region is ranked by EFD distance to `ref_id`. `ref_id` itself
is checked against the freshly recomputed region ids FIRST (before the
more expensive per-region contour/EFD pass), so an unknown id 404s
promptly rather than after paying for contours nobody asked to see.

PLAN_4DSTEM #10 (Bragg-disk detection) is a documented FUTURE consumer of
`calc/shape_fit.py`'s circle fit, not wired up here -- see that module.

The trace -> describe -> rank loop (including the tolerance-0 tracing
rationale and the skip-and-note semantics) lives in `calc/efd_rank.py` --
lifted there for wave A (ADR 0005 §1) so the registered `efd_similarity`
op and this route run the SAME code.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.efd import DEFAULT_N_HARMONICS
from fermiviewer.calc.efd_rank import rank_by_efd
from fermiviewer.calc.particles import particle_analysis
from fermiviewer.calc.shape_fit import fit_circle, fit_ellipse
from fermiviewer.routes._arrays import value_error_as_422
from fermiviewer.routes.structure import _raster
from fermiviewer.routes.structure_particles import ParticleRequest

router = APIRouter(prefix="/api")


# ── EFD similarity ──────────────────────────────────────────────────


class EfdSimilarityRequest(ParticleRequest):
    """`ParticleRequest`'s segmentation fields (imported, see module
    docstring) plus the two this endpoint adds: `ref_id`, the already-
    segmented region every other region is ranked against, and
    `n_harmonics`, caller-overridable per `calc/efd.py`'s "never a hidden
    magic number" rule (defaults to that module's `DEFAULT_N_HARMONICS`).
    """

    ref_id: int
    n_harmonics: int = Field(default=DEFAULT_N_HARMONICS, ge=1)


@router.post("/analyze/efd-similarity")
def analyze_efd_similarity(req: EfdSimilarityRequest) -> dict:
    _, raster = _raster(req.image_id)
    with value_error_as_422():
        res = particle_analysis(
            raster,
            threshold=req.threshold,
            polarity=req.polarity,
            min_area=req.min_area,
            use_watershed=req.use_watershed,
            min_marker_distance=req.min_marker_distance,
        )

    ids = {p.id for p in res.particles}
    if req.ref_id not in ids:
        raise HTTPException(404, f"unknown ref_id: {req.ref_id}")

    # calc/efd_rank.py raises ValueError only when the REFERENCE region
    # cannot be described (other regions skip-and-note) -- that stays a 422
    # naming the region, same as before the wave-A lift.
    with value_error_as_422():
        ranking = rank_by_efd(
            res.labels,
            [p.id for p in res.particles],
            req.ref_id,
            n_harmonics=req.n_harmonics,
        )
    return {
        "ranked": ranking.ranked,
        "skipped": ranking.skipped,
        "n_harmonics": req.n_harmonics,
    }


# ── circle / ellipse fitting ────────────────────────────────────────


class FitShapeRequest(BaseModel):
    points: list[list[float]]  # [[row, col], ...], px, 1-based, closed ring


@router.post("/analyze/fit-shape")
def analyze_fit_shape(req: FitShapeRequest) -> dict:
    # No route-level point-count pre-checks: `fit_circle`/`fit_ellipse`
    # (calc/shape_fit.py) already enforce their own >= 3 / >= 5 minimums
    # with clear, shape-specific messages -- calling both in order (circle
    # first) naturally gives the "enforce both, per-shape" contract for
    # free (a too-short-for-ellipse-but-long-enough-for-circle input fails
    # on the `fit_ellipse` call, naming "ellipse"; too short for either
    # fails on `fit_circle` first, naming "circle") without a second,
    # route-level copy of the same thresholds to keep in sync.
    with value_error_as_422():
        pts = np.asarray(req.points, dtype=np.float64)
        circle = fit_circle(pts)
        ellipse = fit_ellipse(pts)
    return {
        "circle": {"cy": circle.cy, "cx": circle.cx, "r": circle.r, "rms": circle.rms},
        "ellipse": {
            "cy": ellipse.cy,
            "cx": ellipse.cx,
            "a": ellipse.a,
            "b": ellipse.b,
            "theta_rad": ellipse.theta_rad,
            "rms": ellipse.rms,
        },
    }
