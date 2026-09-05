"""Diffraction operation catalogue — wave C (roadmap 3D): batch/scripting
reach for spot detection, ring calibration, and kinematic pattern
simulation. New module because no existing catalogue has the headroom
(the ``catalogue_analysis.py`` precedent); `radial_profile` stays in
``catalogue_spectral.py`` — §2 migrates a grandfathered op only when its
domain's wave touches its code, and this wave does not.

The `diffraction` category does NOT imply a value result, so every op
here sets ``produces_value=True`` explicitly (ADR 0005 §3; the
`radial_profile` precedent).

Every op calls the SAME calc composition its route calls; the crop →
detect → offset-shift and detect → fit → un-distort compositions were
lifted to ``calc/diffraction.find_spots_roi`` /
``calc/diffraction_calib.calibrate_rings`` for exactly that (§1), and the
standard-phase d-spacing anchor to ``calc/phase_registry
.standard_d_spacing``. `diffraction_simulate` is a no-subject op on the
`distribution_fit`/`interface_width` precedent (every input is a flat
scalar, one calc composition, `ds` deliberately unused); its rendered
pattern inlines as a `map` envelope per the wave-B standing rule.

The detect/index `_Roi` model flattens to a ``roi_kind`` choices
discriminator plus two NaN-sentinel groups — a fixed-arity scalar-only
union, spelled with only already-blessed vocabulary. One deliberate
tightening over the route: a `roi_kind` without its coordinate group is
an error here, never a silent whole-image analysis (the strict
`parse_roi_param` rationale); the route's `_Roi` zero-defaults would
silently no-op instead. NOTE this rect is the frontend's 0-based
HALF-OPEN {r0,c0,r1,c1} (calc/diffraction.apply_roi), not the 1-based
inclusive ``"r1,c1,r2,c2"`` string other ops use — do not confuse them.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from fermiviewer.calc.calibration import spacing_at_column_scale
from fermiviewer.calc.diffraction import find_spots_roi, roi_selects_pixels, simulate
from fermiviewer.calc.diffraction_calib import calibrate_rings, camera_constant
from fermiviewer.calc.diffraction_index import index_spots_roi
from fermiviewer.calc.phase_registry import registry, standard_d_spacing
from fermiviewer.calc.raster import raster_of
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.ops._envelopes import nan_none, output, scalar
from fermiviewer.ops._parsing import int_group as _int_group
from fermiviewer.ops._parsing import sentinel_group
from fermiviewer.ops.base import OpParam, OpResult, OpSpec, RowSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []

#: shared by detect and index
_ROI_PARAMS = {
    "roi_kind": OpParam(
        str,
        "",
        choices=("", "rect", "circle"),
        doc="analysis ROI shape; empty = whole image. 'rect' "
        "needs roi_r0/c0/r1/c1 (0-based half-open, the "
        "frontend convention), 'circle' needs "
        "roi_cr/cc/radius",
    ),
    "roi_r0": OpParam(float, float("nan"), doc="rect top row, 0-based"),
    "roi_c0": OpParam(float, float("nan"), doc="rect left col, 0-based"),
    "roi_r1": OpParam(float, float("nan"), doc="rect bottom row, half-open"),
    "roi_c1": OpParam(float, float("nan"), doc="rect right col, half-open"),
    "roi_cr": OpParam(float, float("nan"), doc="circle centre row, 0-based"),
    "roi_cc": OpParam(float, float("nan"), doc="circle centre col, 0-based"),
    "roi_radius": OpParam(float, float("nan"), doc="circle radius (px)"),
}



def _roi_from_params(params: dict[str, Any]) -> dict | None:
    """The `_Roi` dict `calc.diffraction.apply_roi` speaks, from the
    flattened discriminator + sentinel groups."""
    kind = params["roi_kind"]
    if kind == "":
        return None
    if kind == "rect":
        rect = sentinel_group(params, ("roi_r0", "roi_c0", "roi_r1", "roi_c1"))
        if rect is None:
            raise ValueError("roi_kind 'rect' needs roi_r0/roi_c0/roi_r1/roi_c1")
        r0, c0, r1, c1 = _int_group(rect, "roi_r0/roi_c0/roi_r1/roi_c1")
        return {"kind": "rect", "r0": r0, "c0": c0, "r1": r1, "c1": c1}
    circle = sentinel_group(params, ("roi_cr", "roi_cc", "roi_radius"))
    if circle is None:
        raise ValueError("roi_kind 'circle' needs roi_cr/roi_cc/roi_radius")
    cr, cc, radius = _int_group(circle, "roi_cr/roi_cc/roi_radius")
    return {"kind": "circle", "cr": cr, "cc": cc, "radius": radius}


# ── spot detection ────────────────────────────────────────────────────


def _detect(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    # the route's 400 guard: raster_of would silently SUM a spectrum-image
    # cube, a scientific divergence, so mirror the explicit kind check
    if ds.kind is not DataKind.IMAGE:
        raise ValueError("spot detection needs a 2D image")
    roi = _roi_from_params(params)
    # apply_roi silently falls back to the whole image for a degenerate or
    # fully out-of-bounds ROI (the route inherits that); this op's contract
    # is stricter — an ROI that selects no pixels is an error (self-review)
    if roi is not None and not roi_selects_pixels(ds.data.shape, roi):
        raise ValueError("ROI selects no pixels (0-based half-open, clamped to the image)")
    spots = find_spots_roi(
        ds.data,
        roi,
        min_radius=params["min_radius"],
        threshold=params["threshold"],
        min_separation=params["min_separation"],
        max_spots=params["max_spots"],
    )
    rows = spots.tolist()
    outputs = [
        scalar("n_spots", int(spots.shape[0])),
        output(
            "table",
            "spots",
            {
                "columns": ["row", "col"],
                "units": ["px", "px"],
                "position_convention": "(row, col), 1-based",
                "rows": rows,
            },
        ),
        output(
            "overlay",
            "spot_positions",
            {
                "points": rows,
                "convention": "(row, col), 1-based",
            },
        ),
    ]
    return OpResult(
        op="diffraction_detect",
        params=params,
        label="diffraction spot detection",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="diffraction_detect",
        category="diffraction",
        produces_value=True,
        summary="Bright-spot detection on a diffraction pattern, optionally "
        "scoped to a rect/circle analysis ROI "
        "(calc/diffraction.find_spots_roi)",
        params={
            "min_radius": OpParam(
                float, 10.0, doc="ignore spots closer than this to the centre (px)"
            ),
            "threshold": OpParam(float, 0.05, doc="relative intensity threshold"),
            "min_separation": OpParam(float, 8.0, doc="minimum spot separation (px)"),
            "max_spots": OpParam(int, 50, doc="cap on returned spots"),
            **_ROI_PARAMS,
        },
        fn=_detect,
    )
)


# ── ring calibration ──────────────────────────────────────────────────


def _calibrate(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    r_max = params["r_max"] if math.isfinite(params["r_max"]) else None
    cal = calibrate_rings(
        raster,
        r_min=params["r_min"],
        r_max=r_max,
        n_angles=params["n_angles"],
    )
    ellipse = cal.ellipse

    # resolve the anchor d-spacing: explicit, or from a standard phase +
    # hkl. hkl is only inspected when it can matter — an explicit
    # d_known_ang with stray hkl params succeeds, like the route, which
    # never reads hkl once d_known is set (self-review)
    d_known = params["d_known_ang"] if math.isfinite(params["d_known_ang"]) else None
    if d_known is None and params["standard_phase"]:
        hkl = sentinel_group(params, ("hkl_h", "hkl_k", "hkl_l"))
        if hkl is not None:
            h, k, ll = _int_group(hkl, "hkl_h/hkl_k/hkl_l")
            d_known = standard_d_spacing(params["standard_phase"], (h, k, ll))
            if d_known is None:
                raise ValueError(f"unknown standard phase '{params['standard_phase']}'")
    cam_const = camera_constant(d_known, ellipse.mean_radius) if d_known and d_known > 0 else None

    outputs = [
        output(
            "fit",
            "ellipse",
            {
                "model": "ellipse (direct least-squares)",
                "coefficients": {
                    "center_row": ellipse.center_row,
                    "center_col": ellipse.center_col,
                    "a": ellipse.a,
                    "b": ellipse.b,
                    "theta_deg": math.degrees(ellipse.theta),
                    "eccentricity": ellipse.eccentricity,
                    "mean_radius": ellipse.mean_radius,
                },
                "n_points": cal.n_points,
                "rms_residual_px": cal.rms_residual_px,
                "unit": "px",
            },
        ),
    ]
    # absent — not null — when no anchor d-spacing resolves (route says null)
    if d_known is not None:
        outputs.append(scalar("d_known_ang", d_known, unit="A"))
    if cam_const is not None:
        outputs.append(scalar("camera_constant_px_ang", cam_const, unit="px*A"))
    return OpResult(
        op="diffraction_calibrate",
        params=params,
        label="ring distortion calibration",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="diffraction_calibrate",
        category="diffraction",
        produces_value=True,
        summary="Elliptical-distortion + camera-constant calibration from the "
        "dominant ring (calc/diffraction_calib.calibrate_rings); anchor "
        "d via d_known_ang, or standard_phase + hkl_h/k/l "
        "(calc/phase_registry.standard_d_spacing)",
        params={
            "d_known_ang": OpParam(
                float,
                float("nan"),
                doc="known ring d-spacing (Å); leave unset (NaN) "
                "to derive from standard_phase + hkl",
            ),
            "standard_phase": OpParam(
                str, "", doc="standard phase name, e.g. 'Gold'; empty = no phase anchor"
            ),
            "hkl_h": OpParam(
                float, float("nan"), doc="anchored reflection h; give all three hkl_*"
            ),
            "hkl_k": OpParam(float, float("nan")),
            "hkl_l": OpParam(float, float("nan")),
            "r_min": OpParam(float, 5.0, doc="ring search inner radius (px)"),
            "r_max": OpParam(float, float("nan"), doc="ring search outer radius (px); NaN = auto"),
            "n_angles": OpParam(int, 180, doc="radial profiles around the ring"),
        },
        fn=_calibrate,
    )
)


# ── kinematic pattern simulation ──────────────────────────────────────


def _simulate(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    # ds is unused: the subject is a crystal phase, not any loaded image —
    # the distribution_fit/interface_width no-subject precedent (every
    # input is a flat scalar, one calc composition).
    del ds
    dwb = params["debye_waller_B"]
    result = simulate(
        params["phase_name"],
        zone_axis=(params["zone_u"], params["zone_v"], params["zone_w"]),
        acc_voltage=params["acc_voltage"],
        camera_length=params["camera_length"],
        pixel_size=params["pixel_size"],
        image_size=(params["image_rows"], params["image_cols"]),
        max_hkl=params["max_hkl"],
        min_intensity=params["min_intensity"],
        spot_sigma=params["spot_sigma"],
        scattering_model=params["scattering_model"],
        debye_waller_B=(dwb if math.isfinite(dwb) else None),
        # resolve against the registry so imported/custom phases simulate
        # too — the route does the same
        phase=registry.find(params["phase_name"]),
    )
    outputs = [
        output(
            "map",
            "pattern",
            {
                "values": result.image.tolist(),
                "quantity": "intensity",
            },
        ),
        output(
            "table",
            "spots",
            {
                "columns": ["h", "k", "l", "d_spacing", "intensity", "row", "col"],
                "units": ["", "", "", "A", "", "px", "px"],
                "phase": result.phase_name,
                "formula": result.formula,
                "zone_axis": list(result.zone_axis),
                # spots[0] is the direct beam; d_spacing inf -> None, like the route
                "rows": [
                    [
                        s.hkl[0],
                        s.hkl[1],
                        s.hkl[2],
                        nan_none(s.d_spacing),
                        s.intensity,
                        s.pixel_row,
                        s.pixel_col,
                    ]
                    for s in result.spots
                ],
            },
        ),
        scalar("lam_angstrom", result.lam, unit="A"),
    ]
    return OpResult(
        op="diffraction_simulate",
        params=params,
        label=f"kinematic pattern ({result.phase_name})",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="diffraction_simulate",
        category="diffraction",
        produces_value=True,
        summary="Kinematic zone-axis pattern simulation "
        "(calc/diffraction.simulate) — like distribution_fit, the input "
        "image is unused: the subject is the named crystal phase. The "
        "rendered pattern inlines as a `map` envelope (the route "
        "registers it as a session image only when parented); at the "
        "default 512x512 that is ~260k floats per run, so batch scripts "
        "that only need the spot table should shrink "
        "image_rows/image_cols",
        params={
            "phase_name": OpParam(
                str,
                required=True,
                doc="phase to simulate, e.g. 'Gold' (built-in database + imported/custom phases)",
            ),
            "zone_u": OpParam(int, 0, doc="zone axis u"),
            "zone_v": OpParam(int, 0, doc="zone axis v"),
            "zone_w": OpParam(int, 1, doc="zone axis w"),
            "acc_voltage": OpParam(float, 200.0, doc="beam voltage (kV)"),
            "camera_length": OpParam(float, 200.0, doc="camera length (mm)"),
            "pixel_size": OpParam(float, 0.05, doc="detector pixel size (mm)"),
            "image_rows": OpParam(int, 512, doc="rendered pattern height (px)"),
            "image_cols": OpParam(int, 512, doc="rendered pattern width (px)"),
            "max_hkl": OpParam(int, 5, doc="reflection index cap"),
            "min_intensity": OpParam(float, 0.01, doc="relative intensity floor"),
            "spot_sigma": OpParam(float, 3.0, doc="rendered spot width (px)"),
            "scattering_model": OpParam(
                str,
                "fe",
                choices=("fe", "z"),
                doc="Doyle-Turner form factors or "
                "atomic-number proxy (the calc's own "
                "closed set — the route leaves it "
                "unconstrained and lets calc reject)",
            ),
            "debye_waller_B": OpParam(
                float,
                float("nan"),
                doc="isotropic Debye-Waller B (Å²); -1 = "
                "per-element defaults; leave unset "
                "(NaN) = off",
            ),
        },
        fn=_simulate,
    )
)


# ── index (analysis over picked spots) ────────────────────────────────


def _index(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    # the route has no kind check, so raster_of would silently SUM a
    # spectrum-image cube here; `detect` already refuses that and index
    # reads the same geometry, so refuse it the same way
    if ds.kind is not DataKind.IMAGE:
        raise ValueError("spot indexing needs a 2D image")
    pattern = index_spots_roi(
        ds.data.shape,
        np.asarray(params["spots"], dtype=np.float64),
        _roi_from_params(params),
        pixel_size=params["pixel_size_mm"],
        camera_length=params["camera_length_mm"],
        acc_voltage=params["acc_voltage_kv"],
        tolerance=params["tolerance"],
        top_n=params["top_n"],
        # route parity: the column scale typed, rows from the pattern's ratio
        spacing=spacing_at_column_scale(params["pixel_size_mm"], ds.pixel_spacing),
        # the CIF-import registry is module-level mutable state; the route
        # passes it too, and an op that skipped it would index against a
        # smaller phase set than the GUI for the same picture
        extra_phases=list(registry.custom),
    )
    outputs: list[dict[str, Any]] = [
        output(
            "table",
            "candidates",
            {
                "columns": ["phase", "formula", "score", "n_matched", "zone_axis"],
                "rows": [
                    [c.phase_name, c.formula, c.score, c.n_matched, list(c.zone_axis)]
                    for c in pattern.candidates
                ],
            },
        ),
        output(
            "table",
            "measured_radii",
            {
                "columns": ["spot", "r_px"],
                "rows": [
                    [i, nan_none(r)] for i, r in enumerate(pattern.measured_r)
                ],
            },
        ),
        scalar("center_row", pattern.center[0], unit="px"),
        scalar("center_col", pattern.center[1], unit="px"),
        scalar("n_candidates", len(pattern.candidates)),
    ]
    return OpResult(
        op="diffraction_index",
        params=params,
        label=f"indexed {len(pattern.candidates)} candidate phase(s)",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="diffraction_index",
        category="diffraction",
        produces_value=True,
        summary="Match picked diffraction spots to database phases "
        "(calc/diffraction_index.index_spots_roi); centre and measured "
        "radii come back in the FULL-image frame even when an ROI scopes "
        "the indexing, because they drive the whole-image ring overlay",
        params={
            "spots": OpParam(
                list,
                required=True,
                row=RowSpec(width=2, columns=("row", "col"), min_rows=1),
                doc="picked spots, 1-based (row, col) in the FULL image — "
                "note (row, col), unlike atoms_strain's (x, y)",
            ),
            "pixel_size_mm": OpParam(float, 1.0, doc="detector pixel size (mm)"),
            "camera_length_mm": OpParam(
                float,
                float("nan"),
                doc="camera length (mm); absent selects the FFT branch, where "
                "d comes from the reciprocal vector over the effective (H, W) frame",
            ),
            "acc_voltage_kv": OpParam(float, 200.0, doc="beam voltage (kV)"),
            "tolerance": OpParam(float, 0.05, doc="relative d-spacing tolerance"),
            "top_n": OpParam(int, 5, doc="how many candidate phases to return"),
            **_ROI_PARAMS,
        },
        fn=_index,
    )
)
