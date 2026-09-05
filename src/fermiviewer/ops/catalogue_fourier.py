"""Fourier-domain operation catalogue — the imaging half of wave B
(roadmap 3C): batch/scripting reach for the FFT display transform, the
virtual dark field, GPA strain mapping, lattice measurement from FFT spot
picks, and CTF defocus estimation. New module because no existing
catalogue has ~400 lines of headroom (the ``catalogue_analysis.py``
precedent).

No new category (ADR 0005 §2's allowance stays unspent — wave B is
FFT-domain measurement of ordinary images, not a new domain): the two
image producers ride ``filter``; the value ops ride ``analysis``, whose
category already implies a value result, so none of them sets
``produces_value`` (ADR 0005 §3).

Every op calls the SAME calc composition its route calls; the window
arithmetic behind the local FFT and the GPA field means were lifted to
``calc/fourier.local_fft_region`` / ``calc/gpa.gpa_mean_strain`` for
exactly that (§1). Optional/compound params use the frozen flattenings:
NaN-sentinel float groups for optional tuples (``sentinel_group``) and
required tuples as named scalars (`composition_profile`'s x1/y1
precedent). Value ops emit ADR 0005 §5 typed envelopes; GPA's four strain
maps — which the route registers as FOUR session images — inline as
``map`` envelopes on the wave-A `grains` precedent (`OpResult.derived`
carries at most one image; see the ADR's wave-B addendum).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from fermiviewer.calc.calibration import spacing_at_column_scale
from fermiviewer.calc.ctf import estimate_ctf
from fermiviewer.calc.eds_maps import virtual_dark_field
from fermiviewer.calc.fourier import compute_fft, fft_mask_inverse, local_fft_region
from fermiviewer.calc.gpa import geometric_phase_analysis, gpa_mean_strain
from fermiviewer.calc.lattice import lattice_measure
from fermiviewer.calc.raster import raster_of
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops._envelopes import output, scalar
from fermiviewer.ops._parsing import sentinel_group
from fermiviewer.ops.base import OpParam, OpResult, OpSpec, RowSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


# ── fft (derived image) ───────────────────────────────────────────────


def _fft(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    rect = sentinel_group(params, ("rect_r1", "rect_c1", "rect_r2", "rect_c2"))
    if rect is not None:
        raster = local_fft_region(raster, rect)  # type: ignore[arg-type]
    mag, _ = compute_fft(raster)
    # FFT space is not real space: drop the parent axes (the route does
    # the same), unlike the filter ops which carry calibration through.
    derived = DataStruct(
        data=np.ascontiguousarray(mag),
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata={"parser": "derived", "filter_kind": "fft", "source": "fft"},
    )
    return OpResult(op="fft", params=params, label="log-magnitude FFT", derived=derived)


register(
    OpSpec(
        name="fft",
        category="filter",
        summary="Log-magnitude centred 2D FFT as a derived image "
        "(calc/fourier.compute_fft); the optional rect computes the "
        "LOCAL FFT of that region only (calc/fourier.local_fft_region)",
        params={
            "rect_r1": OpParam(
                float,
                float("nan"),
                doc="local-FFT region corner row, 1-based inclusive; give all four rect_* or none",
            ),
            "rect_c1": OpParam(float, float("nan"), doc="region corner col"),
            "rect_r2": OpParam(float, float("nan"), doc="opposite corner row"),
            "rect_c2": OpParam(float, float("nan"), doc="opposite corner col"),
        },
        fn=_fft,
    )
)


# ── vdf (derived image) ───────────────────────────────────────────────


def _vdf(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    out = virtual_dark_field(
        raster,
        (params["center_row"], params["center_col"]),
        mask_radius=params["radius"],
        mask_shape=params["shape"],
        inner_radius=params["inner_radius"],
    )
    derived = DataStruct(
        data=np.ascontiguousarray(out),
        kind=DataKind.IMAGE,
        axes=(ds.axes[0], ds.axes[1]),
        metadata={"parser": "derived", "filter_kind": "vdf", "source": "vdf"},
    )
    return OpResult(op="vdf", params=params, label="virtual dark field", derived=derived)


register(
    OpSpec(
        name="vdf",
        category="filter",
        summary="Virtual dark-field image via FFT aperture masking "
        "(calc/eds_maps.virtual_dark_field)",
        params={
            "center_row": OpParam(
                float, required=True, doc="aperture centre row, 1-based, on the fftshifted FFT"
            ),
            "center_col": OpParam(float, required=True, doc="aperture centre col, 1-based"),
            "radius": OpParam(float, 10.0, doc="aperture radius (FFT px)"),
            "shape": OpParam(str, "circle", choices=("circle", "annulus")),
            "inner_radius": OpParam(float, 0.0, minimum=0.0, doc="annulus inner radius (FFT px)"),
        },
        fn=_vdf,
    )
)


# ── gpa (value: 4 strain maps + field means) ──────────────────────────


def _gpa(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    res = geometric_phase_analysis(
        raster,
        (params["g1x"], params["g1y"]),
        (params["g2x"], params["g2y"]),
        mask_radius=params["mask_radius"],
        mask_order=params["mask_order"],
        pixel_size=params["pixel_size"],
    )
    maps = {"exx": res.exx, "eyy": res.eyy, "exy": res.exy, "rotation": res.rotation}
    means = gpa_mean_strain(res)
    outputs = [
        output(
            "map",
            key,
            {
                "values": m.tolist(),
                "quantity": "strain" if key != "rotation" else "rotation (rad)",
            },
        )
        for key, m in maps.items()
    ]
    # field means: absent — not null — when the field is all-NaN
    for key in maps:
        if math.isfinite(means[key]):
            outputs.append(
                scalar(
                    f"{key}_mean",
                    means[key],
                    unit="" if key != "rotation" else "rad",
                )
            )
    return OpResult(
        op="gpa", params=params, label="geometric phase analysis", value={"outputs": outputs}
    )


register(
    OpSpec(
        name="gpa",
        category="analysis",
        summary="Geometric phase analysis strain/rotation maps + field means "
        "(calc/gpa.geometric_phase_analysis + gpa_mean_strain). The four "
        "maps inline as `map` envelopes — the route registers them as "
        "session images instead (grains precedent, ADR 0005 wave-B "
        "addendum)",
        params={
            "g1x": OpParam(
                float, required=True, doc="1st reciprocal vector x (FFT-pixel offset from centre)"
            ),
            "g1y": OpParam(float, required=True, doc="1st reciprocal vector y"),
            "g2x": OpParam(float, required=True, doc="2nd reciprocal vector x"),
            "g2y": OpParam(float, required=True, doc="2nd reciprocal vector y"),
            "mask_radius": OpParam(
                float,
                0.0,
                minimum=0.0,
                doc="Gaussian mask radius (FFT px); 0 = auto "
                "(min(|g1|,|g2|)/3, the calc's own sentinel)",
            ),
            "mask_order": OpParam(float, 2.0, doc="Gaussian mask order"),
            "pixel_size": OpParam(
                float,
                1.0,
                doc="real-space calibration (unit/px); the route "
                "takes it from the request, not the image — "
                "mirrored",
            ),
        },
        fn=_gpa,
    )
)


# ── lattice (value: scalar set) ───────────────────────────────────────


def _lattice(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    px = params["pixel_size"]
    if not math.isfinite(px):
        px = ds.pixel_size if np.isfinite(ds.pixel_size) else 1.0
    res = lattice_measure(
        (params["spot1_row"], params["spot1_col"]),
        (params["spot2_row"], params["spot2_col"]),
        (raster.shape[0], raster.shape[1]),
        pixel_size=px,
        # route parity: `px` is the column scale, rows follow the image's ratio
        spacing=spacing_at_column_scale(px, ds.pixel_spacing),
    )
    unit = ds.pixel_unit or "px"
    outputs = [
        scalar("a", res.a, unit=unit),
        scalar("b", res.b, unit=unit),
        scalar("gamma_deg", res.gamma_deg, unit="deg"),
        scalar("d_spacing1", res.d_spacing1, unit=unit),
        scalar("d_spacing2", res.d_spacing2, unit=unit),
        scalar("unit_cell_area", res.unit_cell_area, unit=f"{unit}^2"),
    ]
    return OpResult(
        op="lattice",
        params=params,
        label="lattice measure from FFT spots",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="lattice",
        category="analysis",
        summary="Real-space lattice parameters from two reciprocal-space spot "
        "picks on the fftshifted FFT (calc/lattice.lattice_measure)",
        params={
            "spot1_row": OpParam(float, required=True, doc="1st FFT spot row, 1-based, fftshifted"),
            "spot1_col": OpParam(float, required=True, doc="1st FFT spot col, 1-based"),
            "spot2_row": OpParam(float, required=True, doc="2nd FFT spot row, 1-based"),
            "spot2_col": OpParam(float, required=True, doc="2nd FFT spot col, 1-based"),
            "pixel_size": OpParam(
                float,
                float("nan"),
                doc="real-space calibration (unit/px); leave unset "
                "(NaN) to use the image's own, falling back "
                "to 1.0",
            ),
        },
        fn=_lattice,
    )
)


# ── ctf (value: fit + curves) ─────────────────────────────────────────


def _ctf(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    # OpParam has no exclusive minimum, so the route's Field(gt=0) is
    # enforced here (ADR 0005 wave-B addendum notes the vocabulary gap).
    # `not (x > 0)` so NaN is also rejected, matching the route's
    # Field(gt=0) exactly (self-review finding)
    if not (params["pixel_size_a"] > 0):
        raise ValueError("pixel_size_a must be > 0")
    res = estimate_ctf(
        raster,
        voltage_kv=params["voltage_kv"],
        cs_mm=params["cs_mm"],
        pixel_size=params["pixel_size_a"],
        spacing=spacing_at_column_scale(params["pixel_size_a"], ds.pixel_spacing),
    )
    outputs = [
        output(
            "fit",
            "ctf",
            {
                "model": "thon-rings",
                "coefficients": {
                    "defocus_a": res.defocus,
                    "defocus_nm": res.defocus_nm,
                    "lambda_a": res.lambda_a,
                },
                "r_squared": res.r_squared,
                "x_name": "spatial_freq",
                "x_unit": "1/A",
                "y_name": "|CTF|^2",
                "y_unit": "",
                "x_fit": res.radial_freq.tolist(),
                "y_fit": res.ctf_fit.tolist(),
            },
        ),
        output(
            "curve",
            "radial_power",
            {
                "x_name": "spatial_freq",
                "x_unit": "1/A",
                "y_name": "power",
                "y_unit": "",
                "x": res.radial_freq.tolist(),
                "y": res.radial_power.tolist(),
            },
        ),
    ]
    return OpResult(
        op="ctf", params=params, label="CTF defocus estimate", value={"outputs": outputs}
    )


register(
    OpSpec(
        name="ctf",
        category="analysis",
        summary="Defocus estimate from Thon rings: radial power spectrum + "
        "fitted |CTF|² (calc/ctf.estimate_ctf)",
        params={
            "voltage_kv": OpParam(float, 200.0, doc="beam voltage (kV)"),
            "cs_mm": OpParam(float, 1.2, doc="spherical aberration (mm)"),
            "pixel_size_a": OpParam(
                float,
                1.0,
                exclusive_minimum=0.0,
                doc="pixel size (Å/px), must be > 0",
            ),
        },
        fn=_ctf,
    )
)


# ── fft_mask (derived image) ──────────────────────────────────────────


def _fft_mask(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    masks = [(row, col, radius) for row, col, radius in params["masks"]]
    out = fft_mask_inverse(raster, masks, mode=params["mode"])
    derived = DataStruct(
        data=np.ascontiguousarray(out),
        kind=DataKind.IMAGE,
        axes=(ds.axes[0], ds.axes[1]),
        metadata={"parser": "derived", "filter_kind": "fft_mask", "source": "fft_mask"},
    )
    label = "FFT band-pass" if params["mode"] == "pass" else "FFT band-reject"
    return OpResult(op="fft_mask", params=params, label=label, derived=derived)


register(
    OpSpec(
        name="fft_mask",
        category="filter",
        summary="Inverse FFT through circular spectral masks — periodic-noise "
        "removal ('reject') or lattice isolation ('pass') "
        "(calc/fourier.fft_mask_inverse)",
        params={
            # The first list-shaped param in the catalogue (the contract's
            # gap-2 re-opening): the route takes real (row, col, radius)
            # triples, so the op takes them too, rather than inventing an
            # "r:c:rad,…" string the way a pre-contract flattening would.
            "masks": OpParam(
                list,
                required=True,
                row=RowSpec(
                    width=3,
                    columns=("row", "col", "radius"),
                    min_rows=1,
                ),
                doc="circular masks on the fftshifted spectrum, 1-based; "
                "each radius must be > 0 (calc rejects a flat mask, as for "
                "the route — no OpParam bound, which would also constrain "
                "the row/col columns)",
            ),
            "mode": OpParam(
                str,
                "pass",
                choices=("pass", "reject"),
                doc="'pass' keeps only the masked regions (mirrored through "
                "DC so the result stays real); 'reject' suppresses them",
            ),
        },
        fn=_fft_mask,
    )
)
