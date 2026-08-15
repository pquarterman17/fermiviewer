"""Structural-analysis endpoints: particles, atom columns, template
matching, stitching, stack ops (plan item 28 — adapters over W3/W4
calc). Grain segmentation lives in routes/structure_grains.py — split
out to keep both modules comfortably under the 500-line ceiling."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.atoms import (
    PairStrain,
    assign_sublattice,
    detect_columns,
    find_lattice_vectors,
    fit_gaussian_2d,
    peak_pair_strain,
)
from fermiviewer.calc.particles import particle_analysis
from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.calc.shape_metrics import (
    ClassThresholds,
    classify_shapes,
    shape_descriptors,
)
from fermiviewer.calc.stack import align_stack, image_math, mip
from fermiviewer.calc.stitch import stitch_images
from fermiviewer.calc.texture import template_match
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
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


def _register(
    arr: np.ndarray, name: str, parent: DataStruct, parent_id: str,
    keep_axes: bool = True, extra_meta: dict | None = None,
) -> dict:
    axes = (parent.axes[0], parent.axes[1]) if keep_axes else (AxisCal(), AxisCal())
    metadata: dict = {"source": name, "parser": "derived"}
    if extra_meta:
        metadata.update(extra_meta)
    derived = DataStruct(
        data=np.ascontiguousarray(arr),
        kind=DataKind.IMAGE,
        axes=axes,
        metadata=metadata,
    )
    new_id = store.add_derived(derived, name, parent_id)
    return ImageMeta.from_datastruct(new_id, name, derived).model_dump()


# ── particle analysis ─────────────────────────────────────────────────


class ShapeClassThresholds(BaseModel):
    """Caller-tunable overrides for `classify_shapes` — see
    `calc.shape_metrics.ClassThresholds` for the (identical) defaults and
    the aggregate-checked-first precedence rule."""

    aggregate_max_solidity: float = 0.85
    rod_min_aspect: float = 2.5
    sphere_max_aspect: float = 1.3
    sphere_min_circularity: float = 0.85


class ParticleRequest(BaseModel):
    image_id: str
    threshold: float | None = None
    polarity: str = "bright"
    min_area: int = Field(default=1, ge=0)
    use_watershed: bool = False
    min_marker_distance: float = 3.0
    class_thresholds: ShapeClassThresholds | None = None


@router.post("/analyze/particles")
def analyze_particles(req: ParticleRequest) -> dict:
    ds, raster = _raster(req.image_id)
    px = ds.pixel_size if np.isfinite(ds.pixel_size) else float("nan")
    has_cal = np.isfinite(px) and px > 0
    with value_error_as_422():
        res = particle_analysis(
            raster,
            threshold=req.threshold,
            polarity=req.polarity,
            min_area=req.min_area,
            pixel_size=px,
            use_watershed=req.use_watershed,
            min_marker_distance=req.min_marker_distance,
        )
    name = store.name(req.image_id)
    # per-particle shape descriptors — SHAPE_ANALYSIS_PLAN Wave 1 #1/#2.
    # `res.labels` is the filtered/renumbered compact 1..n label image
    # `region_stats` already produced, so `desc`'s rows line up 1:1 with
    # `res.particles` by position (ascending label), same guarantee
    # `grains.grain_stats` relies on for its own regionprops_table call.
    desc = shape_descriptors(res.labels)
    thresholds = (
        ClassThresholds(**req.class_thresholds.model_dump())
        if req.class_thresholds is not None
        else None
    )
    shape_classes = classify_shapes(
        desc.aspect_ratio, desc.circularity, desc.solidity, thresholds
    )
    feret_calibrated = desc.feret_max_px * px if has_cal else np.full_like(
        desc.feret_max_px, np.nan
    )
    return {
        "n_particles": res.n_particles,
        "threshold": res.threshold,
        "labels": _register(
            res.labels.astype(np.float64),
            f"particles({name})", ds, req.image_id,
        ),
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


def _nan_none(v: float) -> float | None:
    return None if not np.isfinite(v) else float(v)


def _nanmean_or_nan(values: np.ndarray) -> float:
    """NaN-aware mean without warning when every sample is missing."""
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0 or np.isnan(array).all():
        return float("nan")
    return float(np.nanmean(array))


# ── atom columns ─────────────────────────────────────────────────────


class AtomsRequest(BaseModel):
    image_id: str
    sigma: float = 2.0
    threshold: float = 0.2
    min_separation: float = 8.0
    polarity: str = "bright"
    refine: bool = True
    win_radius: int = 6
    strain: bool = False
    sublattices: int = Field(default=1, ge=1, le=4)


@router.post("/analyze/atoms")
def analyze_atoms(req: AtomsRequest) -> dict:
    _, raster = _raster(req.image_id)
    with value_error_as_422():
        det = detect_columns(raster, sigma=req.sigma, threshold=req.threshold,
                             min_separation=req.min_separation, polarity=req.polarity)

    positions, amplitude, converged = det.positions, det.intensities, None
    if req.refine and positions.shape[0] > 0:
        fit = fit_gaussian_2d(raster, positions, win_radius=req.win_radius,
                              polarity=req.polarity)
        positions, amplitude, converged = fit.positions, fit.amplitude, fit.converged.tolist()

    out: dict = {
        "n_columns": int(positions.shape[0]),
        "positions": positions.tolist(),  # (x, y), 1-based
        "amplitude": np.asarray(amplitude).tolist(),
        "converged": converged,
    }
    lv = find_lattice_vectors(positions)
    out["lattice"] = {"valid": bool(lv.valid), "spacing": _nan_none(lv.spacing),
                      "a1": None if not lv.valid else lv.a1.tolist(),
                      "a2": None if not lv.valid else lv.a2.tolist()}
    if req.sublattices > 1 and positions.shape[0] > 0:
        out["sublattice"] = assign_sublattice(np.asarray(amplitude),
                                              req.sublattices).tolist()
    if req.strain:
        out["strain"] = _ppa_payload(peak_pair_strain(positions))
    return out


def _ppa_payload(st: PairStrain) -> dict:
    """Serialise a PairStrain to JSON (reused by /atoms/strain)."""
    _s = lambda a: [_nan_none(v) for v in a]  # noqa: E731
    return {
        "valid": bool(st.valid),
        "exx_mean": _nan_none(_nanmean_or_nan(st.exx)),
        "eyy_mean": _nan_none(_nanmean_or_nan(st.eyy)),
        "exy_mean": _nan_none(_nanmean_or_nan(st.exy)),
        "exx": _s(st.exx), "eyy": _s(st.eyy),
        "exy": _s(st.exy), "rotation": _s(st.rotation),
        "displacement": st.displacement.tolist() if st.valid else [],
    }


class AtomsStrainRequest(BaseModel):
    positions: list[list[float]]         # [[x,y], …] 1-based
    ref_vectors: list[list[float]] | None = None  # [[a1x,a1y],[a2x,a2y]]
    origin: list[float] | None = None    # [x0, y0]
    neighbors: int = Field(default=8, ge=3, le=32)


@router.post("/atoms/strain")
def atoms_strain(req: AtomsStrainRequest) -> dict:
    """PPA strain from already-fitted positions (no re-detection needed)."""
    with value_error_as_422():
        pos = np.asarray(req.positions, dtype=np.float64)
        rv = np.asarray(req.ref_vectors, dtype=np.float64) if req.ref_vectors else None
        org = np.asarray(req.origin, dtype=np.float64) if req.origin else None
        return _ppa_payload(peak_pair_strain(pos, ref_vectors=rv, origin=org,
                                             neighbors=req.neighbors))


# ── template match ───────────────────────────────────────────────────


class TemplateRequest(BaseModel):
    image_id: str
    # template cut from the same image: (row, col, height, width), 1-based
    rect: tuple[int, int, int, int]
    threshold: float = Field(default=0.7, ge=0, le=1)
    max_matches: int = 100


@router.post("/analyze/template-match")
def analyze_template(req: TemplateRequest) -> dict:
    _, raster = _raster(req.image_id)
    r0, c0, th, tw = req.rect
    h, w = raster.shape
    if not (1 <= r0 <= h and 1 <= c0 <= w and th > 0 and tw > 0
            and r0 + th - 1 <= h and c0 + tw - 1 <= w):
        raise HTTPException(422, "template rect out of bounds")
    template = raster[r0 - 1 : r0 - 1 + th, c0 - 1 : c0 - 1 + tw]
    with value_error_as_422():
        res = template_match(
            raster, template, threshold=req.threshold,
            max_matches=req.max_matches,
        )
    return {
        "n_matches": res.n_matches,
        "locations": res.locations.tolist(),  # (row, col) centres
        "scores": res.scores.tolist(),
    }


# ── stitching ────────────────────────────────────────────────────────


class StitchRequest(BaseModel):
    image_ids: list[str]
    layout: str = "horizontal"
    overlap_frac: float = Field(default=0.2, ge=0, le=0.5)
    blend_width: float = 50.0


@router.post("/analyze/stitch")
def analyze_stitch(req: StitchRequest) -> dict:
    if len(req.image_ids) < 2:
        raise HTTPException(422, "need at least 2 images to stitch")
    rasters = []
    parent: DataStruct | None = None
    for img_id in req.image_ids:
        ds, raster = _raster(img_id)
        if parent is None:
            parent = ds
        rasters.append(raster)
    shapes = {r.shape for r in rasters}
    if len(shapes) != 1:
        raise HTTPException(422, "stitch requires equal-size tiles")
    with value_error_as_422():
        res = stitch_images(
            rasters, layout=req.layout,
            overlap_frac=req.overlap_frac, blend_width=req.blend_width,
        )
    assert parent is not None
    return {
        "mosaic": _register(
            res.mosaic, f"mosaic({len(rasters)})", parent,
            req.image_ids[0],
        ),
        "offsets": res.offsets.tolist(),
        "layout": res.layout,
    }


# ── stack ops (image math / drift alignment / MIP) ───────────────────


class ImageMathRequest(BaseModel):
    a_id: str
    b_id: str
    op: str = "subtract"  # subtract | divide | ratio | add


@router.post("/analyze/image-math")
def analyze_image_math(req: ImageMathRequest) -> dict:
    ds_a, a = _raster(req.a_id)
    _, b = _raster(req.b_id)
    with value_error_as_422():
        out = image_math(a, b, req.op)
    name = f"{req.op}({store.name(req.a_id)}, {store.name(req.b_id)})"
    return {"image": _register(out, name, ds_a, req.a_id)}


class StackIdsRequest(BaseModel):
    image_ids: list[str]


@router.post("/analyze/align-stack")
def analyze_align_stack(req: StackIdsRequest) -> dict:
    """FFT cross-correlation drift correction; the first image is the
    reference (kept as-is), movers register as aligned derived images."""
    if len(req.image_ids) < 2:
        raise HTTPException(422, "need at least 2 images to align")
    pairs = [_raster(i) for i in req.image_ids]
    with value_error_as_422():
        aligned, shifts = align_stack([r for _, r in pairs])
    images = []
    for i, img_id in enumerate(req.image_ids[1:], start=1):
        ds = pairs[i][0]
        images.append(_register(
            aligned[i], f"aligned({store.name(img_id)})", ds, img_id,
        ))
    return {"images": images, "shifts": shifts.tolist()}


@router.post("/analyze/mip")
def analyze_mip(req: StackIdsRequest) -> dict:
    """Maximum intensity projection across the given images."""
    if len(req.image_ids) < 2:
        raise HTTPException(422, "need at least 2 images for a MIP")
    pairs = [_raster(i) for i in req.image_ids]
    out = mip([r for _, r in pairs])
    name = f"MIP({len(pairs)})"
    return {"image": _register(out, name, pairs[0][0], req.image_ids[0])}
