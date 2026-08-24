"""Whole-image read operations — the second half of wave D's measurement
set (roadmap 3E), split out of ``catalogue_measure.py`` to respect the
500-line module ceiling (the ``catalogue_grains_layers.py`` split
precedent): the region-summed spectrum and intensity histogram GET
endpoints plus scale-bar auto-detection. `sum_spectrum` is category
``spectral`` with an explicit ``produces_value=True`` (spectral ops need
spectral fixtures and the registry smoke sweep's category filter must
keep skipping it); the other two are ``analysis`` (category implies the
value result — ``produces_value`` deliberately UNSET).

Conventions, divergences and their audit annotations are documented in
``catalogue_measure.py``'s module docstring, which covers both halves of
the split; the sum_spectrum region params here speak MATLAB-style
1-based inclusive corners, and a region given for a non-cube spectral
input errors where the route silently ignores it (strict-ROI
discipline).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.raster import raster_of, region_sum_spectrum
from fermiviewer.calc.render import histogram
from fermiviewer.calc.scalebar_detect import detect_scale_bar
from fermiviewer.datastruct import SPECTRAL_KINDS, DataKind, DataStruct
from fermiviewer.ops._envelopes import output
from fermiviewer.ops._parsing import int_group, sentinel_group
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


# ── sum_spectrum ──────────────────────────────────────────────────────

_REGION_NAMES = ("region_row0", "region_col0", "region_row1", "region_col1")


def _sum_spectrum(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    # the route's spectral-kind guard, verbatim message
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError("2D images have no spectral axis")
    region = sentinel_group(params, _REGION_NAMES)
    rect: tuple[int, int, int, int] | None = None
    if region is not None:
        # STRICTER than the route, which silently ignores a region on a 1D
        # spectrum and returns the whole spectrum — the strict-ROI
        # discipline: never silently analyze more than the caller scoped
        if ds.kind is not DataKind.SPECTRUM_IMAGE:
            raise ValueError(
                "region_row0/region_col0/region_row1/region_col1 need a "
                "spectrum-image cube (a 1D spectrum has no spatial region)"
            )
        r0, c0, r1, c1 = int_group(region, "/".join(_REGION_NAMES))
        counts, rect = region_sum_spectrum(ds.data, r0, c0, r1, c1)
    else:
        counts = ds.sum_spectrum()
    energy = ds.energy_axis
    outputs = [
        output(
            "curve",
            "counts",
            {
                "x_name": "energy",
                "x_unit": ds.energy_cal.units,
                "y_name": "counts",
                "y_unit": "",
                "x": energy.tolist(),
                "y": np.asarray(counts, dtype=np.float64).tolist(),
            },
        ),
    ]
    # absent — not null — when no region was given (whole-cube sum)
    if rect is not None:
        outputs.append(
            output(
                "table",
                "region",
                {
                    "columns": ["row0", "col0", "row1", "col1"],
                    "units": ["px", "px", "px", "px"],
                    "position_convention": "1-based, inclusive, clamped",
                    "rows": [list(rect)],
                },
            )
        )
    return OpResult(
        op="sum_spectrum", params=params, label="sum spectrum", value={"outputs": outputs}
    )


register(
    OpSpec(
        name="sum_spectrum",
        category="spectral",
        produces_value=True,
        summary="Sum spectrum of an SI cube (or a 1D spectrum as-is), "
        "optionally region-scoped via region_row0/col0/row1/col1 "
        "(1-based inclusive; calc/raster.region_sum_spectrum). Spectral "
        "category (sweep-skipped), so the explicit flag is required",
        params={
            "region_row0": OpParam(
                float,
                float("nan"),
                doc="region corner row, 1-based inclusive; all four region_* or none",
            ),
            "region_col0": OpParam(float, float("nan"), doc="region corner col"),
            "region_row1": OpParam(float, float("nan"), doc="region opposite row"),
            "region_col1": OpParam(float, float("nan"), doc="region opposite col"),
        },
        fn=_sum_spectrum,
    )
)


# ── intensity_histogram ───────────────────────────────────────────────


def _intensity_histogram(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    # the route returns bin CENTERS (calc/render.histogram's contract),
    # not edges — mirrored here
    centers, counts = histogram(raster_of(ds, native=True), params["bins"])
    outputs = [
        output(
            "curve",
            "histogram",
            {
                "x_name": "intensity",
                "x_unit": "",
                "y_name": "counts",
                "y_unit": "",
                "x": centers.tolist(),
                "y": counts.tolist(),
                "x_convention": "bin centers",
            },
        ),
    ]
    return OpResult(
        op="intensity_histogram",
        params=params,
        label="intensity histogram",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="intensity_histogram",
        category="analysis",
        summary="Intensity histogram over the finite raster range "
        "(calc/render.histogram); x values are bin centers",
        params={
            "bins": OpParam(int, 256, minimum=2, maximum=4096, doc="histogram bin count"),
        },
        fn=_intensity_histogram,
    )
)


# ── scalebar_detect ───────────────────────────────────────────────────


def _scalebar_detect(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    # mirror the ROUTE's local reduction (routes/calibration.py), which is
    # NOT raster_of: the route sums SI cubes itself and passes everything
    # else through as float64. Its rgb_image pass-through hands a 3-D
    # array to detect_scale_bar — an unhandled 500 — so there is no
    # working route behavior to mirror and the op raises cleanly instead
    if ds.kind is DataKind.SPECTRUM:
        raise ValueError("1D spectra have no scale bar")
    if ds.kind is DataKind.RGB_IMAGE:
        raise ValueError(
            "rgb_image has no scale-bar detection path (the route has no working RGB path)"
        )
    pixels = (
        np.asarray(np.sum(ds.data, axis=2, dtype=np.float64))
        if ds.kind is DataKind.SPECTRUM_IMAGE
        else np.asarray(ds.data, dtype=np.float64)
    )
    r = detect_scale_bar(pixels)
    # one single-row table, not scalars: `msg` is a string and a scalar
    # envelope's data.value is numeric (the ADR 0005 §5 shaping decision
    # recorded in the wave-D recon). found=False is a valid result.
    outputs = [
        output(
            "table",
            "detection",
            {
                "columns": ["found", "bar_len", "bar_x1", "bar_x2", "bar_y", "msg"],
                "units": ["", "px", "px", "px", "px", ""],
                "position_convention": "1-based, inclusive",
                "rows": [[r.found, r.bar_len, r.bar_x1, r.bar_x2, r.bar_y, r.msg]],
            },
        ),
    ]
    return OpResult(
        op="scalebar_detect",
        params=params,
        label="scale-bar detection",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="scalebar_detect",
        category="analysis",
        summary="Auto-detect a burned-in scale bar in the bottom 15% strip "
        "(calc/scalebar_detect.detect_scale_bar). No params: the "
        "route reads only image_id from its reused request model, and "
        "dead request fields are not mirrored (the efd_similarity "
        "precedent). found=False is a valid result, not an error",
        params={},
        fn=_scalebar_detect,
    )
)
