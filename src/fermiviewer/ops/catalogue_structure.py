"""Structure operation catalogue — wave A of the parity waves (roadmap 3B):
batch/scripting reach for particle, shape-similarity and region-proposal
analysis. The wave's grain + cross-section layer ops live in
``catalogue_grains_layers.py`` (same category, split for the 500-line
module ceiling).

Same rule as every catalogue: each op calls the SAME pure ``calc/``
function(s) its FastAPI route calls — wiring + schema only, no
reimplemented physics. The wave-A lifts (`calc/efd_rank.py`,
`calc/region_propose.py`, `calc/grain_report.py`) exist precisely so the
compositions that used to live in `routes/` are shared, not duplicated.

`structure` is this wave's one new category (ADR 0005 §2); it is not
"analysis", so every value op here sets ``produces_value=True``
explicitly (ADR 0005 §3's predicate reads it).

Per ADR 0005 §5 every op returns ``value = {"outputs": [...]}`` with
ADR 0004 envelopes (see ``ops/_envelopes.py``); arrays inline as lists.
Optional compound params follow the established flattenings: NaN-sentinel
floats for optional tuples/overrides (`eels_fit`'s ``fit_range_lo/hi``
precedent) and the ``"r1,c1,r2,c2"`` ROI string `calc.roi.parse_rect_roi`
already speaks. The classifier cutoffs deliberately carry NO literal
defaults here — `calc.shape_metrics.ClassThresholds` is the ONLY home of
those values (see `routes/structure_particles.py`'s drift-bug note); NaN
means "use the calc default", resolved via ``dataclasses.replace``.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import numpy as np

from fermiviewer.calc.efd_rank import rank_by_efd
from fermiviewer.calc.particles import particle_analysis
from fermiviewer.calc.raster import raster_of
from fermiviewer.calc.region_propose import propose_region
from fermiviewer.calc.region_segment import place_labels, region_values
from fermiviewer.calc.roi import roi_slices
from fermiviewer.calc.segment import multi_otsu
from fermiviewer.calc.shape_metrics import (
    ClassThresholds,
    classify_shapes,
    shape_descriptors,
)
from fermiviewer.datastruct import DataStruct
from fermiviewer.ops._envelopes import nan_none as _nn
from fermiviewer.ops._envelopes import output, scalar
from fermiviewer.ops._parsing import pixel_cal as _px_cal
from fermiviewer.ops._parsing import sentinel_group as _pair
from fermiviewer.ops._region_param import (
    LABEL_CONTEXT_EXACT,
    REGION_PARAM,
    ScopedRegion,
    region_output,
    scope_from_params,
)
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


# ── particles ─────────────────────────────────────────────────────────

#: The particle table's numeric columns, in row order — the route capture's
#: `_PARTICLE_COLUMNS` (duplicated, never imported: `ops/` may not import a
#: `routes/*` module — the `_dist_payload` precedent). centroid follows the
#: wire convention: (row, col), 1-based.
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

_CLASS_THRESHOLD_KEYS = (
    "aggregate_max_solidity",
    "rod_min_aspect",
    "sphere_max_aspect",
    "sphere_min_circularity",
)


def _scoped_particle_input(
    raster: np.ndarray,
    scoped: ScopedRegion | None,
    threshold: float | None,
    polarity: str,
) -> tuple[np.ndarray, float | None]:
    """The crop `particle_analysis` should see, and the threshold to use.

    Out-of-region pixels are filled with the infinity that CANNOT pass the
    polarity test (`-inf` for bright, `+inf` for dark), so thresholding
    excludes them and every later stage — watershed, `min_area` filtering,
    the per-particle table, the label numbering — is consistent with the
    label map by construction. Clipping labels afterwards instead would
    leave `res.particles` describing the unclipped shapes.

    An auto threshold is then computed from the SELECTED values, not from
    the crop: a bright feature the user drew around must not set the level
    for the pixels they kept. With a rectangular region the two are the
    same pixels, which is why that path is left exactly as it was.
    """
    if scoped is None:
        return raster, threshold
    rows, cols = roi_slices(raster.shape, scoped.rect)
    block = raster[rows, cols]
    if scoped.mask is None:
        return block, threshold
    if threshold is None:
        threshold = float(
            multi_otsu(region_values(raster, scoped.rect, scoped.mask), n_classes=2)
            .thresholds[0]
        )
    outside = -np.inf if polarity == "bright" else np.inf
    filled = np.where(scoped.mask[rows, cols], block, outside)
    return np.asarray(filled, dtype=np.float64), threshold


def _particles(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    px, unit = _px_cal(ds)
    has_cal = np.isfinite(px) and px > 0
    threshold = params["threshold"] if math.isfinite(params["threshold"]) else None
    scoped = scope_from_params(params, raster.shape)
    analysis_raster, threshold = _scoped_particle_input(
        raster, scoped, threshold, params["polarity"]
    )
    res = particle_analysis(
        analysis_raster,
        threshold=threshold,
        polarity=params["polarity"],
        min_area=params["min_area"],
        pixel_size=px,
        use_watershed=params["use_watershed"],
        min_marker_distance=params["min_marker_distance"],
    )
    desc = shape_descriptors(res.labels)
    overrides = {k: params[k] for k in _CLASS_THRESHOLD_KEYS if math.isfinite(params[k])}
    thresholds = dataclasses.replace(ClassThresholds(), **overrides) if overrides else None
    shape_classes = classify_shapes(desc.aspect_ratio, desc.circularity, desc.solidity, thresholds)
    feret_calibrated = (
        desc.feret_max_px * px if has_cal else np.full_like(desc.feret_max_px, np.nan)
    )
    # `particle_analysis` measured the CROP, so its centroids are
    # crop-local while the map above is full-image. Before 4C-3 this op had
    # no ROI at all and the two frames were the same, which is exactly why
    # cropping it silently split them. Everything else in the row —
    # area, circularity, orientation, Feret — is translation-invariant, so
    # the origin is the whole of the difference.
    row_offset, col_offset = (
        (scoped.rect[0] - 1, scoped.rect[1] - 1) if scoped is not None else (0, 0)
    )
    rows = [
        [
            p.id,
            p.centroid[0] + row_offset,
            p.centroid[1] + col_offset,
            p.area,
            p.equiv_diameter,
            p.mean_intensity,
            _nn(p.area_calibrated),
            _nn(p.diameter_calibrated),
            float(desc.circularity[i]),
            _nn(float(desc.aspect_ratio[i])),
            float(desc.eccentricity[i]),
            float(desc.orientation_rad[i]),
            float(desc.solidity[i]),
            float(desc.feret_max_px[i]),
            _nn(float(feret_calibrated[i])),
        ]
        for i, p in enumerate(res.particles)
    ]
    labels = (
        place_labels(res.labels, raster.shape, scoped.rect)[0]
        if scoped is not None
        else res.labels
    )
    columns = [name for name, _ in _PARTICLE_COLUMNS]
    units = [
        (u if u is not None else (f"{unit}^2" if name.startswith("area") else unit))
        for name, u in _PARTICLE_COLUMNS
    ]
    outputs = [
        scalar("n_particles", res.n_particles),
        scalar("threshold", res.threshold),
        output(
            "table",
            "particles",
            {
                "columns": columns,
                "units": units,
                # (row, col), 1-based — the wire/table coordinate convention
                "centroid_convention": "(row, col), 1-based",
                "shape_class": list(shape_classes),
                "rows": rows,
            },
        ),
        output(
            "map",
            "labels",
            {
                "values": labels.tolist(),
                "convention": "0 = background; values are particle ids (table rows)",
            },
        ),
    ]
    if scoped is not None:
        # exact for every scope: the polarity fill clips the labels before
        # thresholding, so a hole in the region is a hole in the analysis
        outputs.append(region_output(scoped, label_context=LABEL_CONTEXT_EXACT))
    return OpResult(
        op="particles", params=params, label="particle analysis", value={"outputs": outputs}
    )


register(
    OpSpec(
        name="particles",
        category="structure",
        produces_value=True,
        summary="Threshold + label + per-particle morphometrics and shape classes "
        "(calc/particles.particle_analysis, calc/shape_metrics)",
        params={
            "threshold": OpParam(
                float,
                float("nan"),
                doc="intensity threshold; leave unset (NaN) for auto multi-Otsu",
            ),
            "polarity": OpParam(
                str,
                "bright",
                choices=("bright", "dark"),
                doc="particles brighter or darker than background",
            ),
            "min_area": OpParam(int, 1, minimum=0, doc="drop regions smaller than this (px)"),
            "region": REGION_PARAM,
            "use_watershed": OpParam(bool, False, doc="split touching particles by watershed"),
            "min_marker_distance": OpParam(float, 3.0, doc="watershed marker separation (px)"),
            "aggregate_max_solidity": OpParam(
                float,
                float("nan"),
                doc="classify_shapes override; leave unset (NaN) for the calc-layer default",
            ),
            "rod_min_aspect": OpParam(
                float, float("nan"), doc="classify_shapes override; NaN = calc default"
            ),
            "sphere_max_aspect": OpParam(
                float, float("nan"), doc="classify_shapes override; NaN = calc default"
            ),
            "sphere_min_circularity": OpParam(
                float, float("nan"), doc="classify_shapes override; NaN = calc default"
            ),
        },
        fn=_particles,
    )
)


# ── EFD similarity ────────────────────────────────────────────────────


def _efd_similarity(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    threshold = params["threshold"] if math.isfinite(params["threshold"]) else None
    # Same segmentation as `particles`, so the same scoping: one helper
    # rather than a second interpretation of what a region means here.
    scoped = scope_from_params(params, raster.shape)
    analysis_raster, threshold = _scoped_particle_input(
        raster, scoped, threshold, params["polarity"]
    )
    # No pixel_size: similarity ranks by SHAPE, calibration never enters —
    # mirrors the route, which also omits it here.
    res = particle_analysis(
        analysis_raster,
        threshold=threshold,
        polarity=params["polarity"],
        min_area=params["min_area"],
        use_watershed=params["use_watershed"],
        min_marker_distance=params["min_marker_distance"],
    )
    ranking = rank_by_efd(
        res.labels,
        [p.id for p in res.particles],
        params["ref_id"],
        n_harmonics=params["n_harmonics"],
    )
    outputs = [
        output(
            "table",
            "ranked",
            {
                "columns": ["id", "distance"],
                "units": ["", ""],
                "rows": [[r["id"], r["distance"]] for r in ranking.ranked],
            },
        ),
        output(
            "table",
            "skipped",
            {
                "columns": ["id", "reason"],
                "units": ["", ""],
                "rows": [[s["id"], s["reason"]] for s in ranking.skipped],
            },
        ),
        scalar("n_harmonics", params["n_harmonics"]),
    ]
    if scoped is not None:
        outputs.append(region_output(scoped, label_context=LABEL_CONTEXT_EXACT))
    return OpResult(
        op="efd_similarity",
        params=params,
        label="EFD shape-similarity ranking",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="efd_similarity",
        category="structure",
        produces_value=True,
        summary="Segment particles, then rank every region by elliptic-Fourier "
        "shape distance to a reference region (calc/efd_rank.rank_by_efd). "
        "Note: the route's dead `class_thresholds` field is deliberately "
        "not mirrored — classification never enters similarity",
        params={
            "region": REGION_PARAM,
            "ref_id": OpParam(
                int,
                required=True,
                doc="particle id (from this run's segmentation) every "
                "other region is ranked against",
            ),
            "threshold": OpParam(
                float,
                float("nan"),
                doc="intensity threshold; leave unset (NaN) for auto multi-Otsu",
            ),
            "polarity": OpParam(str, "bright", choices=("bright", "dark")),
            "min_area": OpParam(int, 1, minimum=0),
            "use_watershed": OpParam(bool, False),
            "min_marker_distance": OpParam(float, 3.0),
            "n_harmonics": OpParam(
                int, 10, minimum=1, doc="EFD harmonic count (calc/efd.DEFAULT_N_HARMONICS)"
            ),
        },
        fn=_efd_similarity,
    )
)


# ── region proposal ───────────────────────────────────────────────────



def _propose_region(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    seed = _pair(params, ("seed_x", "seed_y"))
    rect = _pair(params, ("rect_x0", "rect_y0", "rect_x1", "rect_y1"))
    px, unit = _px_cal(ds)
    proposal = propose_region(
        raster,
        seed=seed,  # type: ignore[arg-type]
        rect=rect,  # type: ignore[arg-type]
        n_classes=params["n_classes"],
        morph_radius=params["morph_radius"],
        tolerance=params["tolerance"],
        pixel_size=px,
        unit=unit,
    )
    outputs = [
        output(
            "overlay",
            "proposal",
            {
                "points": [list(p) for p in proposal.points],
                "closed": False,
                "convention": "normalized (x, y) in [0, 1] — a polygon measure's pts",
            },
        ),
        scalar("area_px", proposal.area_px, unit="px^2"),
    ]
    if proposal.area_calibrated is not None:
        outputs.append(scalar("area_calibrated", proposal.area_calibrated, unit=f"{unit}^2"))
    return OpResult(
        op="propose_region",
        params=params,
        label="region proposal from seed",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="propose_region",
        category="structure",
        produces_value=True,
        summary="Propose one region's polygon outline from a click/box seed "
        "(calc/region_propose.propose_region: multi-Otsu + morphology + "
        "connected components + contour trace). Give seed_x/seed_y, or "
        "rect_x0..y1, or both",
        params={
            "seed_x": OpParam(
                float, float("nan"), doc="normalized click x in [0, 1]; give with seed_y"
            ),
            "seed_y": OpParam(float, float("nan"), doc="normalized click y in [0, 1]"),
            "rect_x0": OpParam(
                float, float("nan"), doc="normalized box seed corner; give all four rect_*"
            ),
            "rect_y0": OpParam(float, float("nan")),
            "rect_x1": OpParam(float, float("nan")),
            "rect_y1": OpParam(float, float("nan")),
            "n_classes": OpParam(int, 3, minimum=2, maximum=5, doc="multi-Otsu classes"),
            "morph_radius": OpParam(int, 1, doc="closing radius (px) cleaning the mask"),
            "tolerance": OpParam(float, 2.0, doc="contour simplification tolerance (px)"),
        },
        fn=_propose_region,
    )
)
