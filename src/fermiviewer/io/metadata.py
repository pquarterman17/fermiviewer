"""Metadata accessors — ports of getGrayscale / getStageTilt (plan B).

Small heuristics over parser metadata; pure functions, no I/O.

**Stage tilt is normalized at parse time.** Every parser that can find a
tilt writes it to ``metadata["stage_tilt_deg"]`` in degrees, because only
the parser knows its format's convention: Gatan DM stores degrees, Thermo
Fisher (FEI TIFF, Velox EMD) stores radians, Zeiss and Bruker store
degrees. The guess-from-magnitude rule below stays as a fallback for
metadata that arrives without a known provenance, but it is a salvage
path, not the mechanism — it silently turns a genuine 2° stage tilt into
114°, so no parser should rely on it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from fermiviewer.calc.raster import rgb_luma

__all__ = [
    "databar_content_rows",
    "databar_stripped_metadata",
    "get_stage_tilt",
    "stage_tilt_from_image_tags",
    "to_grayscale",
]

# keys searched, in priority order; (key, assume_radians_if_small)
_TILT_KEYS = (
    ("stage_tilt_deg", False),  # parser-normalized — always degrees
    # Bruker Esprit's key as the MATLAB port spelled it. io/bcf.py writes
    # the snake_case form above, which is why this alone never matched a
    # real .bcf: the two spellings had drifted apart.
    ("stageTilt_deg", False),
    ("StageT", True),  # FEI/Thermo — radians or degrees, heuristic
    ("StageTa", True),
    ("Tilt", True),
)

# Dotted `image_tags` leaves, matched case-insensitively against the END of
# a key: (suffix, value_is_radians). dm.py / dm5.py / emd.py all flatten
# their vendor trees into the same dotted-key shape, so one table serves
# all three.
_IMAGE_TAG_TILT: tuple[tuple[str, bool], ...] = (
    ("stage position.stage alpha", False),  # Gatan DM3/DM4/DM5 — degrees
    ("stage.alphatilt", True),  # Velox EMD (Thermo Fisher) — radians
)


def _positive_int(value: Any) -> int | None:
    """A strictly-positive row count, or None. Vendor tags arrive as floats
    (io.tiff_vendor stores them through `positive()`) and occasionally as
    strings, so coerce rather than isinstance-check."""
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def databar_content_rows(metadata: Mapping[str, Any], n_rows: int) -> int | None:
    """Rows of real image sitting above a vendor-baked databar, or None.

    Thermo Fisher (FEI) SEM/FIB TIFFs burn an info bar — magnification, HV,
    working distance and the vendor's OWN scale bar — into the bottom of the
    pixel array, so the file is taller than the scanned raster. Parsers
    record both halves of that geometry and deliberately never crop (a
    golden checksum pins the array); this collapses the pair into the one
    number callers actually need.

    ``[Image] ResolutionY`` (recorded as ``image_rows``) is authoritative
    when present, because it IS the scanned raster height; the recorded
    ``databar_height`` is the fallback for files that omit it.

    Returns None when the whole array is image — true for every format that
    doesn't bake a bar in — which callers read as "no databar to avoid".
    """
    rows = _positive_int(metadata.get("image_rows"))
    if rows is not None and rows < n_rows:
        return rows
    bar = _positive_int(metadata.get("databar_height"))
    if bar is not None and bar < n_rows:
        return n_rows - bar
    return None


def databar_stripped_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Metadata to carry onto a databar-cropped derivative of this image.

    The carry-forward rule of POST /strip-databar, lifted out of
    ``routes/filter.py`` (wave D, ADR 0005 §1) to sit beside
    :func:`databar_content_rows`, whose geometry it undoes. The acquisition
    provenance is kept — the databar was *displaying* exactly that
    information (beam kV, instrument, stage tilt), and dropping it would
    leave a figure-ready image that can no longer say how it was taken.
    Only the two keys describing the geometry just removed
    (``databar_height`` / ``image_rows``) are dropped, so a second
    strip call — :func:`databar_content_rows` on the derivative —
    correctly reports "no databar". Load-bearing: keep the dropped-key
    set in lockstep with what :func:`databar_content_rows` reads.
    """
    return {k: v for k, v in metadata.items() if k not in ("databar_height", "image_rows")}


def to_grayscale(pixels: np.ndarray) -> np.ndarray:
    """RGB(A) → grayscale via BT.601 luma; passthrough for 2-D input.

    The luma weights live once in `calc.raster.rgb_luma` (the raster
    boundary, ADR 0003) — this wrapper keeps the passthrough/validation
    contract its callers rely on.
    """
    arr = np.asarray(pixels, dtype=np.float64)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3 and arr.shape[2] >= 3:
        return rgb_luma(arr)
    raise ValueError(f"unsupported pixel array shape {arr.shape}")


def _search(node: Any, key: str) -> Any:
    """Depth-first search for `key` in nested dicts."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            found = _search(v, key)
            if found is not None:
                return found
    return None


def stage_tilt_from_image_tags(image_tags: Mapping[str, Any]) -> float:
    """Stage tilt in DEGREES from a flattened dotted `image_tags` map.

    Returns NaN when the map carries no recognised tilt tag. Parsers call
    this to fill ``metadata["stage_tilt_deg"]``; the per-format radian/degree
    convention is baked into the table, never guessed from the value.
    """
    for suffix, is_radians in _IMAGE_TAG_TILT:
        for key, value in image_tags.items():
            if not str(key).lower().endswith(suffix):
                continue
            try:
                tilt = float(value)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(tilt):
                continue
            return float(np.degrees(tilt)) if is_radians else tilt
    return float("nan")


def get_stage_tilt(metadata: dict[str, Any]) -> tuple[float, str]:
    """Stage tilt in DEGREES from parser metadata, with the source key.

    Prefers the parser-normalized ``stage_tilt_deg``. Falls back to raw
    vendor keys, where the ported FEI heuristic applies: values with
    |v| < π are assumed radians and converted, larger values are taken as
    degrees. Returns (nan, "") when no tilt key is present.
    """
    for key, maybe_radians in _TILT_KEYS:
        val = _search(metadata, key)
        if val is None:
            continue
        try:
            tilt = float(val)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(tilt):
            continue
        if maybe_radians and abs(tilt) < np.pi:
            tilt = float(np.degrees(tilt))
        return tilt, key
    return float("nan"), ""
