"""Montage catalogue — the tiling half of the wave-C multi-image cluster
(ADR 0005 §8 auxiliary inputs + §9 record params).

``montage`` and ``montage_compare`` were bounced twice: gap 1 (N images by
session id) for both, and gap 2 for montage-compare, whose tiles are nested
models carrying a ``float|str|bool|None`` field no scalar encoding covered.
The re-opened contract answers both — the caller resolves ids and hands over
``DataStruct``s by name, and the per-tile metadata that has no dataset
channel travels as a ``RecordSpec`` list — so these are now
pattern-following registrations rather than contract work.

Its own module, not an addition to ``catalogue_stack``: that file is the
multi-input home but would have gone past the repo's 500-line ratchet
(ADR 0005 §2, the ``catalogue_analysis`` precedent). The shared helpers
(``_RASTER_KINDS``, ``_derived_image``) are imported from there rather than
copied; the import runs one way only.

ONE DELIBERATE DIVERGENCE from the routes, ADR 0005 §8's last bullet: the
routes letter their tiles with ``store.name(image_id)``, and a pure op has
no session store and never resolves an id, so each tile is labelled from its
own ``metadata['source']`` instead (falling back to its position). The baked
pixels therefore differ from the GUI's for the same images — it is the one
thing about these ops a caller must know, and it is why `labels` is spelled
out in both summaries.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.montage import montage
from fermiviewer.calc.montage_physical import (
    montage_physical_scale,
    order_by_param_value,
)
from fermiviewer.calc.raster import raster_of
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops._parsing import int_group, sentinel_group
from fermiviewer.ops.base import (
    ANY_SCALAR,
    OpInput,
    OpParam,
    OpResult,
    OpSpec,
    RecordSpec,
)
from fermiviewer.ops.catalogue_stack import _RASTER_KINDS, _derived_image
from fermiviewer.ops.registry import register

__all__: list[str] = []


def _tile_label(ds: DataStruct, index: int) -> str:
    """The per-tile caption baked into the pixels.

    The module docstring's divergence, in one place: ``metadata['source']``
    (wave B's static-name convention, which ADR 0005 §8 names for exactly
    this op) instead of the route's session name. A struct with no
    ``source`` falls back to its position, so a caption is never blank.
    """
    source = ds.metadata.get("source")
    return str(source) if source else f"tile {index + 1}"


def _cols(params: dict[str, Any]) -> int | None:
    """The routes' ``cols: int | None`` as the blessed NaN sentinel.

    NaN (the default) IS the route's ``null`` — ``montage`` then picks
    ceil(sqrt(n)). Chosen over "0 means auto" because a magic zero is a
    per-op encoding invention (§4) while the NaN sentinel is existing
    vocabulary (``_parsing.sentinel_group``), and over a plain ``int``
    because ``int`` has no spare value for "unset". ``int_group`` keeps the
    route's pydantic ``int`` strictness — 2.5 is refused, not truncated —
    and ``cols < 1`` is left to calc, so the op raises the route's own
    message rather than a second spelling of the same rule.
    """
    group = sentinel_group(params, ("cols",))
    return None if group is None else int_group(group, "cols")[0]


_COLS_PARAM = OpParam(
    float,
    float("nan"),
    doc="grid columns; NaN (the default) is the route's null -> ceil(sqrt(n))",
)


# ── montage (derived image; variadic input) ───────────────────────────


def _montage(
    ds: DataStruct, params: dict[str, Any], inputs: dict[str, Any]
) -> OpResult:
    frames = [ds, *inputs["others"]]
    labels = (
        [_tile_label(f, i) for i, f in enumerate(frames)] if params["labels"] else None
    )
    out = montage(
        [raster_of(f) for f in frames],
        cols=_cols(params),
        labels=labels,
        gap=params["gap"],
        bg=params["bg"],
        overlap=params["overlap"],
        font_size=params["font_size"],
    )
    return OpResult(
        op="montage",
        params=params,
        label=f"montage ({len(frames)} tiles)",
        derived=_derived_image(
            out,
            ds,
            "montage",
            # what was baked, for a caller who cannot read the pixels back
            {"n_tiles": len(frames), "tile_labels": labels or []},
        ),
    )


register(
    OpSpec(
        name="montage",
        category="filter",
        summary="Contact-sheet montage of the subject and the remaining "
        "frames, tiled pixel-for-pixel (calc/montage.montage). Labels "
        "DIVERGE from the route: the pure layer has no session store, so a "
        "tile is captioned from its own metadata['source'], not its library "
        "name (ADR 0005 §8)",
        params={
            "cols": _COLS_PARAM,
            "labels": OpParam(
                bool,
                True,
                doc="bake a per-tile caption (metadata['source'], NOT the "
                "route's session name) into the pixels",
            ),
            "gap": OpParam(
                int,
                4,
                minimum=0,
                maximum=64,
                doc="px between tiles; ignored when overlap > 0",
            ),
            "bg": OpParam(float, 0.0, doc="background fill value"),
            "overlap": OpParam(
                float,
                0.0,
                minimum=0.0,
                exclusive_maximum=1.0,
                doc="fractional tile overlap [0, 1) — the route's "
                "Field(ge=0.0, lt=1.0)",
            ),
            "font_size": OpParam(int, 14, minimum=6, maximum=48),
        },
        inputs={
            "others": OpInput(
                doc="the remaining frames, in tile order; the subject is "
                "tile 1. Optional — the route montages a single image too",
                variadic=True,
                required=False,
                min_count=0,
                kinds=_RASTER_KINDS,
            ),
        },
        fn=_montage,
    )
)


# ── montage_compare (derived image; variadic input + record param) ────


def _montage_compare(
    ds: DataStruct, params: dict[str, Any], inputs: dict[str, Any]
) -> OpResult:
    tiles = [ds, *inputs["tiles"]]
    meta: list[dict[str, Any]] = params["tile_meta"]
    if meta and len(meta) != len(tiles):
        raise ValueError(
            f"montage_compare: tile_meta has {len(meta)} record(s) for "
            f"{len(tiles)} tile(s) — pass one record per tile, in "
            f"[subject, *tiles] order (or none at all)"
        )
    values = [m["param_value"] for m in meta] if meta else [None] * len(tiles)

    frames: list[np.ndarray] = []
    pixel_sizes: list[float] = []
    pixel_units: list[str] = []
    labels: list[str] = []
    for i in order_by_param_value(values):
        tile = tiles[i]
        if not tile.pixel_cal.calibrated:
            # the route's 422, which names the offending image; the pure
            # layer names its position and static source instead
            raise ValueError(
                f"montage_compare: tile {i} ('{_tile_label(tile, i)}') has no "
                f"pixel calibration — a common physical scale is undefined "
                f"for this panel"
            )
        frames.append(raster_of(tile))
        pixel_sizes.append(tile.pixel_size)
        pixel_units.append(tile.pixel_unit)
        caption = str(meta[i]["label"]) if meta else ""
        labels.append(caption or _tile_label(tile, i))

    res = montage_physical_scale(
        frames,
        pixel_sizes,
        pixel_units,
        labels=labels,
        cols=_cols(params),
        gap=params["gap"],
        bg=params["bg"],
        font_size=params["font_size"],
        bar_color=params["bar_color"],
    )
    bar = res.scale_bar
    cal = AxisCal(scale=res.pixel_size, origin=0.0, units=res.pixel_unit)
    derived = DataStruct(
        data=np.ascontiguousarray(res.canvas),
        kind=DataKind.IMAGE,
        # NOT the subject's calibration (so not `_derived_image`): every tile
        # was resampled to the coarsest common scale, which is what the
        # canvas measures in — the calibration the route registers too.
        axes=(cal, cal),
        metadata={
            "parser": "derived",
            "source": "montage-compare",
            "tile_labels": labels,
            "n_tiles": len(tiles),
            # the route's second payload key: the panel's ONE shared bar.
            # Metadata, not a parallel `value` — an OpResult carries a
            # derived image or a value, and a value set beside a derived
            # image is dropped by both headless consumers (`run_recipe`
            # collects values from non-image steps only; `Image.run` records
            # `value` only when nothing was derived).
            "scale_bar": {
                "x": bar.x,
                "y": bar.y,
                "width": bar.width,
                "height": bar.height,
                "label": bar.label,
                "color": bar.color,
            },
        },
    )
    return OpResult(
        op="montage_compare",
        params=params,
        label=f"comparison montage ({len(tiles)} tiles)",
        derived=derived,
    )


register(
    OpSpec(
        name="montage_compare",
        category="filter",
        summary="Comparison montage: every tile resampled to ONE common "
        "physical scale (the coarsest input's) with ONE shared scale bar "
        "baked in (calc/montage_physical.montage_physical_scale). Tiles are "
        "ordered by tile_meta[].param_value first; an uncalibrated tile is "
        "refused, as in the route. The bar geometry rides the derived "
        "image's metadata",
        params={
            "tile_meta": OpParam(
                list,
                record=RecordSpec(
                    fields={
                        "label": OpParam(
                            str,
                            "",
                            doc="baked tile caption; blank falls back to the "
                            "dataset's metadata['source'] (where the route "
                            "falls back to its session name)",
                        ),
                        "param_value": OpParam(
                            ANY_SCALAR,
                            None,
                            doc="the compared parameter's value. ANY_SCALAR "
                            "because only a real int/float orders the panel: "
                            "a numeric-LOOKING string ('300') and a bool are "
                            "categorical and keep request order at the back "
                            "(calc order_by_param_value). A float or str "
                            "ptype here would coerce that distinction away "
                            "and silently re-order the panel",
                        ),
                    },
                    min_rows=0,
                ),
                doc="the route's per-tile fields minus image_id (the caller "
                "resolves that into the `tiles` input): one record per tile "
                "in [subject, *tiles] order, or none at all for request "
                "order with metadata captions",
            ),
            "cols": _COLS_PARAM,
            "gap": OpParam(int, 4, minimum=0, maximum=64),
            "bg": OpParam(float, 0.0, doc="background fill value"),
            "font_size": OpParam(int, 14, minimum=6, maximum=48),
            "bar_color": OpParam(
                str,
                "#ffffff",
                doc="baked as an intensity — the canvas is single-channel",
            ),
        },
        inputs={
            "tiles": OpInput(
                doc="the remaining tiles; the subject is tile 1 (the panel's "
                "provenance root, and the route's parent image). Optional — "
                "the route panels a single tile too",
                variadic=True,
                required=False,
                min_count=0,
                kinds=_RASTER_KINDS,
            ),
        },
        fn=_montage_compare,
    )
)
