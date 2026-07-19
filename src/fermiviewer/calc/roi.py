"""Rectangular analysis-ROI helpers shared by pure calculation modules.

Public analysis APIs use MATLAB-style, 1-based inclusive rectangles
``(r1, c1, r2, c2)``. Keeping the clamping and embedding rules here avoids
slightly different ROI conventions in each analysis route.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

RectRoi = tuple[int, int, int, int]


def parse_rect_roi(value: object) -> RectRoi | None:
    """Parse the compact provenance form used in derived-image metadata."""
    if not isinstance(value, str):
        return None
    parts = value.split(",")
    if len(parts) != 4:
        return None
    return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])


def roi_slices(shape: Sequence[int], roi: RectRoi | None) -> tuple[slice, slice]:
    """Return clamped NumPy slices for a 1-based inclusive rectangle."""
    if len(shape) != 2:
        raise ValueError("ROI analysis requires a 2-D image")
    h, w = int(shape[0]), int(shape[1])
    if h < 1 or w < 1:
        raise ValueError("ROI analysis requires a non-empty image")
    r1, c1, r2, c2 = roi if roi is not None else (1, 1, h, w)
    r1, r2 = sorted((int(round(r1)), int(round(r2))))
    c1, c2 = sorted((int(round(c1)), int(round(c2))))
    r1, r2 = max(r1, 1), min(r2, h)
    c1, c2 = max(c1, 1), min(c2, w)
    if r1 > r2 or c1 > c2:
        raise ValueError("ROI does not overlap the image")
    return slice(r1 - 1, r2), slice(c1 - 1, c2)


def extract_rect_roi(array: NDArray, roi: RectRoi | None) -> NDArray:
    """View ``array`` through the clamped ROI (or return the whole image)."""
    rows, cols = roi_slices(array.shape, roi)
    return array[rows, cols]


def embed_rect_roi(
    values: NDArray, shape: Sequence[int], roi: RectRoi | None,
) -> NDArray:
    """Embed ROI-local values in a zero-filled full-image array."""
    rows, cols = roi_slices(shape, roi)
    expected = (rows.stop - rows.start, cols.stop - cols.start)
    if values.shape != expected:
        raise ValueError(f"ROI result shape {values.shape} does not match {expected}")
    if roi is None and tuple(shape) == values.shape:
        return values
    result = np.zeros(tuple(shape), dtype=values.dtype)
    result[rows, cols] = values
    return result
