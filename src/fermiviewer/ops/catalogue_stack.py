"""Multi-image operation catalogue — the first ops to declare auxiliary
``DataStruct`` inputs (ADR 0005 §8, the gap-1 half of the contract
re-opening).

Every op here needs MORE than the single subject ``ops.run`` has always
taken: image math needs a second image, stack alignment and MIP need the
rest of the stack. The rule that kept them unregisterable was never
"multi-image analysis doesn't belong in the vocabulary" — it was that
smuggling a session id through a string param would make ``ops/`` read the
session store, and the pure layer cannot. §8 resolves it the other way: the
caller resolves ids to ``DataStruct``s and hands them over by name, so the
op still never sees an id.

Each op keeps exactly ONE primary subject — the ``ds`` positional, which
stays the recipe chain's spine and the provenance root. For the stack ops
the subject is the FIRST frame (the alignment reference, as in the route)
and ``others`` carries the rest.

``align_stack`` produces N−1 aligned rasters, more than ``OpResult.derived``
can hold, so it follows the wave-B standing rule: inline ``map`` envelopes
in ``value`` while the route registers session images.

``stitch`` closes the last of this module's wave-C bounces. The montage
pair (``montage``, ``montage_compare``) needs the same auxiliary-input
machinery but would have pushed this file past the repo's 500-line ratchet,
so it lives in ``catalogue_montage`` and imports the helpers from here —
the ``catalogue_analysis``/``catalogue_spectral`` precedent (ADR 0005 §2:
never grow an existing catalogue past the ratchet).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.raster import raster_of
from fermiviewer.calc.stack import align_stack, image_math, mip
from fermiviewer.calc.stitch import stitch_images
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.ops._envelopes import output
from fermiviewer.ops.base import OpInput, OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []

#: Every op here takes rasters, so each auxiliary input accepts the kinds
#: ``raster_of`` can reduce (a spectrum image sums to its raster).
_RASTER_KINDS = (DataKind.IMAGE, DataKind.RGB_IMAGE, DataKind.SPECTRUM_IMAGE)


def _derived_image(
    arr: np.ndarray,
    parent: DataStruct,
    source: str,
    extra: dict[str, Any] | None = None,
) -> DataStruct:
    """A derived raster carrying the subject's spatial calibration — the
    routes' ``_register`` behaviour, minus the session name (the pure layer
    composes no display names; wave B's static-``source`` convention).

    ``extra`` rides ``metadata`` alongside it, for the image producers whose
    route ALSO returns non-image evidence (stitch's offsets/layout, a
    montage's baked labels) — an ``OpResult`` carries a derived image or a
    value, not both, and wave D's standing rule puts a derived struct's
    diagnostics in its metadata."""
    return DataStruct(
        data=np.ascontiguousarray(arr),
        kind=DataKind.IMAGE,
        axes=(parent.axes[0], parent.axes[1]),
        metadata={"parser": "derived", "source": source, **(extra or {})},
    )


# ── image_math (derived image; one auxiliary input) ───────────────────


def _image_math(
    ds: DataStruct, params: dict[str, Any], inputs: dict[str, Any]
) -> OpResult:
    out = image_math(raster_of(ds), raster_of(inputs["other"]), params["op"])
    return OpResult(
        op="image_math",
        params=params,
        label=f"image math ({params['op']})",
        derived=_derived_image(out, ds, "image_math"),
    )


register(
    OpSpec(
        name="image_math",
        category="filter",
        summary="Arithmetic between the subject and a second image, cropped "
        "to their common top-left region (calc/stack.image_math)",
        params={
            "op": OpParam(
                str,
                "subtract",
                choices=("subtract", "divide", "ratio", "add"),
                doc="divide and ratio clamp their denominators at 1 "
                "(count-data convention)",
            ),
        },
        inputs={
            "other": OpInput(
                doc="the second operand; the subject is the left-hand one "
                "(the route's a_id)",
                kinds=_RASTER_KINDS,
            ),
        },
        fn=_image_math,
    )
)


# ── align_stack (value + inline maps; variadic input) ─────────────────


def _align_stack(
    ds: DataStruct, params: dict[str, Any], inputs: dict[str, Any]
) -> OpResult:
    frames = [ds, *inputs["others"]]
    aligned, shifts = align_stack([raster_of(f) for f in frames])
    outputs = [
        output(
            "map",
            f"aligned_{i}",
            {"values": aligned[i].tolist(), "unit": ""},
        )
        for i in range(1, len(aligned))
    ]
    outputs.append(
        output(
            "table",
            "shifts",
            {
                "columns": ["frame", "dy", "dx"],
                "rows": [
                    [i, int(dy), int(dx)] for i, (dy, dx) in enumerate(shifts.tolist())
                ],
            },
        )
    )
    return OpResult(
        op="align_stack",
        params=params,
        label=f"drift-aligned stack ({len(frames)} frames)",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="align_stack",
        category="analysis",
        summary="FFT cross-correlation drift correction across a stack; the "
        "subject is the reference frame and the movers come back as "
        "inline aligned maps plus their integer shifts "
        "(calc/stack.align_stack)",
        inputs={
            "others": OpInput(
                doc="the remaining frames, in order; the subject is frame 0 "
                "(the alignment reference, kept as-is)",
                variadic=True,
                min_count=1,
                kinds=_RASTER_KINDS,
            ),
        },
        fn=_align_stack,
    )
)


# ── mip (derived image; variadic input) ───────────────────────────────


def _mip(ds: DataStruct, params: dict[str, Any], inputs: dict[str, Any]) -> OpResult:
    frames = [ds, *inputs["others"]]
    out = mip([raster_of(f) for f in frames])
    return OpResult(
        op="mip",
        params=params,
        label=f"maximum intensity projection ({len(frames)} frames)",
        derived=_derived_image(out, ds, "mip"),
    )


register(
    OpSpec(
        name="mip",
        category="filter",
        summary="Maximum intensity projection across the subject and the "
        "remaining frames (calc/stack.mip)",
        inputs={
            "others": OpInput(
                doc="the remaining frames of the stack",
                variadic=True,
                min_count=1,
                kinds=_RASTER_KINDS,
            ),
        },
        fn=_mip,
    )
)


# ── stitch (derived mosaic; variadic input) ───────────────────────────


def _stitch(ds: DataStruct, params: dict[str, Any], inputs: dict[str, Any]) -> OpResult:
    frames = [ds, *inputs["others"]]
    rasters = [raster_of(f) for f in frames]
    shapes = {r.shape for r in rasters}
    if len(shapes) != 1:
        # the route's own precondition (routes/structure.py's 422), kept
        # route-side there and reproduced here: `stitch_images` blends onto a
        # canvas sized from the FIRST tile, so unequal tiles would silently
        # crop rather than fail.
        raise ValueError(
            f"stitch requires equal-size tiles (got {sorted(shapes)})"
        )
    res = stitch_images(
        rasters,
        layout=params["layout"],
        overlap_frac=params["overlap_frac"],
        blend_width=params["blend_width"],
    )
    return OpResult(
        op="stitch",
        params=params,
        label=f"mosaic ({len(rasters)} tiles, {res.layout})",
        derived=_derived_image(
            res.mosaic,
            ds,
            "stitch",
            {
                # The route returns `offsets` and the RESOLVED `layout`
                # ('auto' -> the orientation the first-pair peak chose)
                # alongside its registered mosaic. They ride the derived
                # struct's metadata rather than a parallel `value`: an
                # OpResult carries EITHER a derived image or a value, and a
                # value set beside a derived image is dropped by both
                # headless consumers (`run_recipe` collects values only from
                # non-image steps; `Image.run` records `value` only when
                # nothing was derived). `layout` could not be a `scalar`
                # envelope anyway — that envelope's `value` is numeric and
                # this one is a word. Wave D's derived-diagnostics rule
                # (`eds_recalibrate`, `savgol_derivative`).
                "layout": res.layout,
                "offsets": res.offsets.tolist(),  # cumulative [dy, dx] per tile
                "n_images": res.n_images,
            },
        ),
    )


register(
    OpSpec(
        name="stitch",
        category="filter",
        summary="Panoramic stitch of equal-size tiles: pairwise FFT "
        "cross-correlation offsets, ramp-blended onto one mosaic "
        "(calc/stitch.stitch_images). The subject is tile 1 (the offset "
        "origin); the resolved layout and the per-tile offsets ride the "
        "mosaic's metadata",
        params={
            "layout": OpParam(
                str,
                "horizontal",
                choices=("horizontal", "vertical", "auto"),
                doc="'auto' picks the orientation whose first-pair "
                "correlation peak is stronger",
            ),
            "overlap_frac": OpParam(
                float,
                0.2,
                minimum=0.0,
                maximum=0.5,
                doc="fraction of each tile searched for the seam",
            ),
            "blend_width": OpParam(
                float, 50.0, doc="linear seam ramp width, in pixels"
            ),
        },
        inputs={
            "others": OpInput(
                doc="the remaining tiles, in sequence order; the subject is "
                "tile 1. Every tile must have the SAME shape (the route's "
                "422)",
                variadic=True,
                min_count=1,
                kinds=_RASTER_KINDS,
            ),
        },
        fn=_stitch,
    )
)


# ── the montage half of the wave-C multi-image cluster ────────────────
