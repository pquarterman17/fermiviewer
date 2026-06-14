"""Structural-analysis endpoints: particles, grains, atom columns,
template matching, stitching (plan item 28 — adapters over W3/W4 calc)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.atoms import (
    assign_sublattice,
    detect_columns,
    find_lattice_vectors,
    fit_gaussian_2d,
    peak_pair_strain,
)
from fermiviewer.calc.grains import (
    GrainSegmentation,
    WatershedSegmentation,
    astm_grain_size_number,
    enforce_connected_grains,
    grain_stats,
    segment_auto,
    segment_watershed,
    split_grain,
)
from fermiviewer.calc.particles import particle_analysis
from fermiviewer.calc.stack import align_stack, image_math, mip
from fermiviewer.calc.stitch import stitch_images
from fermiviewer.calc.texture import template_match
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.jobs import jobs
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _raster(img_id: str) -> tuple[DataStruct, np.ndarray]:
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    if ds.kind is DataKind.IMAGE:
        return ds, np.asarray(ds.data, dtype=np.float64)
    if ds.kind is DataKind.SPECTRUM_IMAGE:
        summed: np.ndarray = np.asarray(ds.data, dtype=np.float64).sum(axis=2)
        return ds, summed
    raise HTTPException(400, "1D spectra have no raster")


def _register(
    arr: np.ndarray, name: str, parent: DataStruct, parent_id: str,
    keep_axes: bool = True, extra_meta: dict | None = None,
) -> dict:
    axes = (
        (parent.axes[0], parent.axes[1])
        if keep_axes
        else (AxisCal(), AxisCal())
    )
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


class ParticleRequest(BaseModel):
    image_id: str
    threshold: float | None = None
    polarity: str = "bright"
    min_area: int = Field(default=1, ge=0)
    use_watershed: bool = False
    min_marker_distance: float = 3.0


@router.post("/analyze/particles")
def analyze_particles(req: ParticleRequest) -> dict:
    ds, raster = _raster(req.image_id)
    px = ds.pixel_size if np.isfinite(ds.pixel_size) else float("nan")
    try:
        res = particle_analysis(
            raster,
            threshold=req.threshold,
            polarity=req.polarity,
            min_area=req.min_area,
            pixel_size=px,
            use_watershed=req.use_watershed,
            min_marker_distance=req.min_marker_distance,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    name = store.name(req.image_id)
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
            }
            for p in res.particles
        ],
        "unit": ds.pixel_unit or "px",
    }


def _nan_none(v: float) -> float | None:
    return None if not np.isfinite(v) else float(v)


# ── grain segmentation ───────────────────────────────────────────────


class GrainRequest(BaseModel):
    image_id: str
    # "kmeans" is the ported MATLAB texture-clustering path (kept for parity);
    # the others are scikit-image methods chosen per EM image type
    method: Literal["kmeans", "gradient", "rag", "orientation"] = "gradient"
    # k-means params
    k: int = Field(default=4, ge=2, le=10)
    seed: int = 0
    replicates: int = 3
    # gradient / orientation watershed params
    granularity: float = Field(default=0.05, ge=0.0, le=1.0)
    compactness: float = Field(default=0.001, ge=0.0, le=1.0)
    orientation_sigma: float = Field(default=2.0, ge=0.5, le=8.0)
    # superpixel-RAG params
    n_superpixels: int = Field(default=400, ge=50, le=4000)
    merge_threshold: float = Field(default=0.08, ge=0.0, le=1.0)
    # shared
    min_area: int = 25
    run_async: bool = False


def _grains_payload(
    labels: np.ndarray, method: str, ds: DataStruct, raster: np.ndarray,
    source_id: str,
) -> dict:
    """Build the grain-analysis response (shared by initial segmentation and
    interactive merge/split). Registers the renumbered label map tagged so
    the stage can recognize and further edit it."""
    px = ds.pixel_size if np.isfinite(ds.pixel_size) else float("nan")
    stats = grain_stats(labels, raster, pixel_size=px)
    name = store.name(source_id)
    unit = ds.pixel_unit or "px"
    diam_cal = stats.diameter_calibrated
    mean_diam_cal = float(np.nanmean(diam_cal)) if diam_cal.size else float("nan")
    return {
        "n_grains": stats.n_grains,
        "method": method,
        "labels": _register(
            stats.labels.astype(np.float64), f"grains({name})", ds, source_id,
            extra_meta={
                "grain_labels": True,
                "grain_source": source_id,
                "grain_method": method,
            },
        ),
        # legacy pixel-count kept; boundary_network is the true (border-
        # excluding) inter-grain network length
        "boundary_length_px": stats.boundary_length_px,
        "boundary_network_px": stats.boundary_network_px,
        "boundary_length_calibrated": _nan_none(stats.boundary_network_calibrated),
        "n_boundary_segments": stats.n_boundary_segments,
        "n_triple_junctions": stats.n_triple_junctions,
        "mean_diameter_px": (
            float(stats.equiv_diameter_px.mean())
            if stats.equiv_diameter_px.size
            else 0.0
        ),
        "astm_grain_size": _nan_none(astm_grain_size_number(mean_diam_cal, unit)),
        "areas_px": stats.area_px.tolist(),
        "perimeters_px": stats.perimeter_crofton_px.tolist(),
        "eccentricity": stats.eccentricity.tolist(),
        "unit": unit,
    }


def _run_grains(
    req: GrainRequest,
    progress: Callable[[float, str], None] | None = None,
) -> dict:
    ds, raster = _raster(req.image_id)
    seg: GrainSegmentation | WatershedSegmentation
    if req.method == "kmeans":
        seg = segment_auto(
            raster, k=req.k, min_area=req.min_area,
            seed=req.seed, replicates=req.replicates, progress=progress,
        )
    else:
        seg = segment_watershed(
            raster, method=req.method, granularity=req.granularity,
            compactness=req.compactness, min_area=req.min_area,
            n_superpixels=req.n_superpixels, merge_threshold=req.merge_threshold,
            orientation_sigma=req.orientation_sigma, progress=progress,
        )
    return _grains_payload(seg.labels, req.method, ds, raster, req.image_id)


class GrainEditRequest(BaseModel):
    labels_id: str  # a grain-label map produced by /analyze/grains
    op: Literal["merge", "split"]
    # image-pixel clicks (x, y), 0-based; merge needs ≥2 on distinct grains,
    # split takes the first point's grain
    points: list[tuple[float, float]]
    granularity: float = Field(default=0.03, ge=0.0, le=1.0)


@router.post("/grains/edit")
def grains_edit(req: GrainEditRequest) -> dict:
    try:
        labels_ds = store.get(req.labels_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {req.labels_id}") from None
    source_id = labels_ds.metadata.get("grain_source")
    if not isinstance(source_id, str):
        raise HTTPException(422, "not an editable grain-label map")
    source_ds, raster = _raster(source_id)
    labels = np.asarray(labels_ds.data, dtype=np.int64).copy()
    h, w = labels.shape

    pts = [
        (int(round(y)), int(round(x)))
        for x, y in req.points
        if 0 <= int(round(y)) < h and 0 <= int(round(x)) < w
    ]
    if not pts:
        raise HTTPException(422, "no points inside the image")

    base = str(labels_ds.metadata.get("grain_method", "edited"))
    if req.op == "merge":
        ids = {int(labels[r, c]) for r, c in pts if labels[r, c] > 0}
        if len(ids) < 2:
            raise HTTPException(422, "merge needs ≥2 distinct grains")
        keep = min(ids)
        for i in ids:
            labels[labels == i] = keep
        method = f"{base}+merge"
    else:  # split
        gid = int(labels[pts[0]])
        if gid <= 0:
            raise HTTPException(422, "click is not on a grain")
        labels = split_grain(labels, raster, gid, granularity=req.granularity)
        method = f"{base}+split"

    # guarantee every grain is one connected region (a merge of non-adjacent
    # grains, or a split, must not leave a label spanning disconnected pieces)
    labels = enforce_connected_grains(labels)
    return _grains_payload(labels, method, source_ds, raster, source_id)


@router.post("/analyze/grains")
def analyze_grains(req: GrainRequest) -> dict:
    if req.run_async:
        # validate the image id up front so the 404 is synchronous
        _raster(req.image_id)
        return {"job_id": jobs.submit(lambda p: _run_grains(req, p))}
    try:
        return _run_grains(req)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


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
    try:
        det = detect_columns(
            raster, sigma=req.sigma, threshold=req.threshold,
            min_separation=req.min_separation, polarity=req.polarity,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    positions = det.positions
    amplitude = det.intensities
    converged = None
    if req.refine and positions.shape[0] > 0:
        fit = fit_gaussian_2d(
            raster, positions, win_radius=req.win_radius,
            polarity=req.polarity,
        )
        positions = fit.positions
        amplitude = fit.amplitude
        converged = fit.converged.tolist()

    out: dict = {
        "n_columns": int(positions.shape[0]),
        "positions": positions.tolist(),  # (x, y), 1-based
        "amplitude": np.asarray(amplitude).tolist(),
        "converged": converged,
    }

    lv = find_lattice_vectors(positions)
    out["lattice"] = {
        "valid": bool(lv.valid),
        "a1": None if not lv.valid else lv.a1.tolist(),
        "a2": None if not lv.valid else lv.a2.tolist(),
        "spacing": _nan_none(lv.spacing),
    }

    if req.sublattices > 1 and positions.shape[0] > 0:
        out["sublattice"] = assign_sublattice(
            np.asarray(amplitude), req.sublattices
        ).tolist()

    if req.strain:
        st = peak_pair_strain(positions)
        out["strain"] = {
            "valid": bool(st.valid),
            "exx_mean": _nan_none(float(np.nanmean(st.exx))),
            "eyy_mean": _nan_none(float(np.nanmean(st.eyy))),
            "exy_mean": _nan_none(float(np.nanmean(st.exy))),
            "exx": [_nan_none(v) for v in st.exx],
            "eyy": [_nan_none(v) for v in st.eyy],
        }
    return out


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
    try:
        res = template_match(
            raster, template, threshold=req.threshold,
            max_matches=req.max_matches,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
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
    try:
        res = stitch_images(
            rasters, layout=req.layout,
            overlap_frac=req.overlap_frac, blend_width=req.blend_width,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
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
    try:
        out = image_math(a, b, req.op)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
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
    try:
        aligned, shifts = align_stack([r for _, r in pairs])
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
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
