"""Particle-analysis endpoint (threshold + label + morphometrics) with 1C
result capture. Split out of routes/structure.py — the capture additions
pushed it past the 500-line ceiling, the same treatment grain segmentation
already received (routes/structure_grains.py). The small `_raster` /
`_register` / `_nan_none` helpers are duplicated here on the established
route-module convention rather than imported across route boundaries."""

from __future__ import annotations

import dataclasses

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.particles import particle_analysis
from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.calc.shape_metrics import (
    ClassThresholds,
    classify_shapes,
    shape_descriptors,
)
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.routes._arrays import value_error_as_422
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _raster(img_id: str) -> tuple[DataStruct, np.ndarray]:
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    try:
        return ds, raster_of(ds)
    except NoRasterError:
        raise HTTPException(400, "1D spectra have no raster") from None


def _register(arr: np.ndarray, name: str, parent: DataStruct, parent_id: str) -> dict:
    derived = DataStruct(
        data=np.ascontiguousarray(arr),
        kind=DataKind.IMAGE,
        axes=(parent.axes[0], parent.axes[1]),
        metadata={"source": name, "parser": "derived"},
    )
    new_id = store.add_derived(derived, name, parent_id)
    return ImageMeta.from_datastruct(new_id, name, derived).model_dump()


def _nan_none(v: float) -> float | None:
    return None if not np.isfinite(v) else float(v)


# ── particle analysis ─────────────────────────────────────────────────


class ShapeClassThresholds(BaseModel):
    """Caller-tunable overrides for `classify_shapes`. Every field is
    None-defaulted: an omitted field means "use the calc-layer default",
    resolved via `dataclasses.replace` at call time so
    `calc.shape_metrics.ClassThresholds` stays the ONLY place a default
    value exists. This model briefly duplicated the literals and the two
    copies drifted on the first correction (sphere cutoff 0.85→0.92
    landed in calc only, so any partial override here silently reverted
    it) — do not reintroduce literal defaults here."""

    aggregate_max_solidity: float | None = None
    rod_min_aspect: float | None = None
    sphere_max_aspect: float | None = None
    sphere_min_circularity: float | None = None


class ParticleRequest(BaseModel):
    image_id: str
    threshold: float | None = None
    polarity: str = "bright"
    min_area: int = Field(default=1, ge=0)
    use_watershed: bool = False
    min_marker_distance: float = 3.0
    class_thresholds: ShapeClassThresholds | None = None
    #: Capture this run as a persisted ResultRecord (1C). Default off until
    #: the client grows its capture affordance.
    record: bool = False


@router.post("/analyze/particles")
def analyze_particles(req: ParticleRequest) -> dict:
    ds, raster = _raster(req.image_id)
    # Input resolution is done; from here a failure is a COMPUTATION
    # failure, which a requested capture must record rather than lose
    # (the 1B contract's failed-state requirement).
    try:
        return _analyze_particles(req, ds, raster)
    except (HTTPException, ValueError) as exc:
        if req.record:
            from fermiviewer.result_capture import capture_result

            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            capture_result(
                analysis="structure.particles",
                label=f"Particle analysis of {store.name(req.image_id)}",
                source_ids=[req.image_id],
                params=_resolved_particle_params(req, req.threshold),
                status="failed",
                error=str(detail),
            )
        raise


def _analyze_particles(req: ParticleRequest, ds, raster) -> dict:
    with value_error_as_422():
        res = particle_analysis(
            raster,
            threshold=req.threshold,
            polarity=req.polarity,
            min_area=req.min_area,
            pixel_area=ds.pixel_area,
            use_watershed=req.use_watershed,
            min_marker_distance=req.min_marker_distance,
        )
    name = store.name(req.image_id)
    # per-particle shape descriptors — SHAPE_ANALYSIS_PLAN Wave 1 #1/#2.
    # `res.labels` is the filtered/renumbered compact 1..n label image
    # `region_stats` already produced, so `desc`'s rows line up 1:1 with
    # `res.particles` by position (ascending label), same guarantee
    # `grains.grain_stats` relies on for its own regionprops_table call.
    desc = shape_descriptors(res.labels, ds.pixel_spacing)
    thresholds = (
        dataclasses.replace(ClassThresholds(), **req.class_thresholds.model_dump(exclude_none=True))
        if req.class_thresholds is not None
        else None
    )
    shape_classes = classify_shapes(desc.aspect_ratio, desc.circularity, desc.solidity, thresholds)
    feret_calibrated = desc.feret_max_calibrated
    labels_meta = _register(
        res.labels.astype(np.float64),
        f"particles({name})",
        ds,
        req.image_id,
    )
    body = {
        "n_particles": res.n_particles,
        "threshold": res.threshold,
        "labels": labels_meta,
        "particles": [
            {
                "id": p.id,
                "area": p.area,
                "centroid": list(p.centroid),
                "equiv_diameter": p.equiv_diameter,
                "mean_intensity": p.mean_intensity,
                "area_calibrated": _nan_none(p.area_calibrated),
                "diameter_calibrated": _nan_none(p.diameter_calibrated),
                "circularity": float(desc.circularity[i]),
                "aspect_ratio": _nan_none(float(desc.aspect_ratio[i])),
                "eccentricity": float(desc.eccentricity[i]),
                "orientation_rad": float(desc.orientation_rad[i]),
                "solidity": float(desc.solidity[i]),
                "feret_max": float(desc.feret_max_px[i]),
                "feret_max_calibrated": _nan_none(float(feret_calibrated[i])),
                "shape_class": shape_classes[i],
            }
            for i, p in enumerate(res.particles)
        ],
        "unit": ds.pixel_unit or "px",
    }
    if req.record:
        body["result"] = _capture_particles(req, body, labels_meta)
    return body


#: The particle table's numeric columns, in member-array column order.
#: centroid follows the wire convention: (row, col), 1-based (MATLAB
#: heritage, `calc/particles.py`) — persisted so a reopened table row can
#: be located in its source image (1C review).
_PARTICLE_COLUMNS = (
    ("id", ""),
    ("centroid_row", "px"),
    ("centroid_col", "px"),
    ("area", "px^2"),
    ("equiv_diameter", "px"),
    ("mean_intensity", ""),
    ("area_calibrated", None),
    ("diameter_calibrated", None),
    ("circularity", ""),
    ("aspect_ratio", ""),
    ("eccentricity", ""),
    ("orientation_rad", "rad"),
    ("solidity", ""),
    ("feret_max", "px"),
    ("feret_max_calibrated", None),
)


def _resolved_particle_params(req: ParticleRequest, threshold: float | None) -> dict:
    """The reproduction key, defaults filled: `threshold` is the value the
    computation actually used (auto-thresholding may have picked it), and
    `class_thresholds` is the FULLY resolved classifier cutoffs — storing
    None or a partial override would let a future default change silently
    reclassify a rerun of this saved record (1C review)."""
    resolved_thresholds = (
        dataclasses.replace(ClassThresholds(), **req.class_thresholds.model_dump(exclude_none=True))
        if req.class_thresholds is not None
        else ClassThresholds()
    )
    return {
        **req.model_dump(exclude={"record"}),
        "threshold": threshold,
        "class_thresholds": dataclasses.asdict(resolved_thresholds),
    }


def _capture_particles(req: ParticleRequest, body: dict, labels_meta: dict) -> dict:
    """This run as a persisted ResultRecord (ADR 0004): particle counts as
    scalars, the numeric morphometrics as a member-backed table (thousands
    of rows must never inline into manifest.json), shape classes inline,
    and the registered label map as a derived id."""
    from fermiviewer.io.project_results import ResultOutput
    from fermiviewer.result_capture import capture_result

    unit = body["unit"]
    columns = [name for name, _ in _PARTICLE_COLUMNS]
    units = [
        (u if u is not None else (f"{unit}^2" if name.startswith("area") else unit))
        for name, u in _PARTICLE_COLUMNS
    ]
    particles = [
        {**p, "centroid_row": p["centroid"][0], "centroid_col": p["centroid"][1]}
        for p in body["particles"]
    ]
    rows = np.array(
        [[np.nan if p[name] is None else float(p[name]) for name in columns] for p in particles],
        dtype=np.float64,
    ).reshape(len(particles), len(columns))
    outputs = [
        ResultOutput(
            kind="scalar",
            name="n_particles",
            data={"value": body["n_particles"], "unit": ""},
        ),
        ResultOutput(
            kind="scalar",
            name="threshold",
            data={"value": body["threshold"], "unit": ""},
        ),
        ResultOutput(
            kind="table",
            name="particles",
            data={
                "columns": columns,
                "units": units,
                # (row, col), 1-based — the wire/table coordinate convention
                "centroid_convention": "(row, col), 1-based",
                "shape_class": [p["shape_class"] for p in body["particles"]],
            },
            array=rows,
        ),
    ]
    record = capture_result(
        analysis="structure.particles",
        label=f"Particle analysis of {store.name(req.image_id)}",
        source_ids=[req.image_id],
        params=_resolved_particle_params(req, body["threshold"]),
        outputs=outputs,
        derived_ids=[labels_meta["id"]],
    )
    return {"id": record.id, "created_at": record.created_at}
