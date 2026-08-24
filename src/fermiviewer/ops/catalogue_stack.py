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
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.raster import raster_of
from fermiviewer.calc.stack import align_stack, image_math, mip
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.ops._envelopes import output
from fermiviewer.ops.base import OpInput, OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []

#: Every op here takes rasters, so each auxiliary input accepts the kinds
#: ``raster_of`` can reduce (a spectrum image sums to its raster).
_RASTER_KINDS = (DataKind.IMAGE, DataKind.RGB_IMAGE, DataKind.SPECTRUM_IMAGE)


def _derived_image(arr: np.ndarray, parent: DataStruct, source: str) -> DataStruct:
    """A derived raster carrying the subject's spatial calibration — the
    routes' ``_register`` behaviour, minus the session name (the pure layer
    composes no display names; wave B's static-``source`` convention)."""
    return DataStruct(
        data=np.ascontiguousarray(arr),
        kind=DataKind.IMAGE,
        axes=(parent.axes[0], parent.axes[1]),
        metadata={"parser": "derived", "source": source},
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
