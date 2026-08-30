"""The one 2D-raster boundary for every consumer of library pixels.

Every endpoint and op that needs "the 2D scalar view" of a stored dataset
resolves it here: an image as-is, a spectrum-image summed over its energy
(last) axis. 1D spectra have no raster and raise :class:`NoRasterError`;
routes translate that to their own HTTP 400 message so each endpoint keeps
its site-specific wording.

This logic used to exist as 13 near-verbatim copies across routes/, ops/,
calc/ and api/ (ADR 0003 records the survey). Consolidating them is what
makes teaching the app a new DataKind a one-site change here instead of
thirteen independent edits.

The SI sum accumulates directly into float64 (``np.sum(..., dtype=...)``)
rather than casting the whole cube first — identical result, but the cast
transiently duplicates multi-gigabyte cubes (see the allocation-delta guard
in tests/test_ops_registry.py).
"""

from __future__ import annotations

import numpy as np

from fermiviewer.datastruct import DataKind, DataStruct

__all__ = [
    "NoRasterError", "masked_sum_spectrum", "raster_from", "raster_of",
    "region_sum_spectrum", "rgb_luma",
]

#: BT.601 luma weights — the app's one RGB→scalar rule. io/metadata.py's
#: `to_grayscale` delegates here; io/images.py's load-time channel MEAN is
#: deliberately different (a verbatim MATLAB port, see its docstring).
_LUMA = (0.299, 0.587, 0.114)


class NoRasterError(ValueError):
    """The dataset kind has no 2D raster (a 1D spectrum)."""


def rgb_luma(arr: np.ndarray) -> np.ndarray:
    """BT.601 luma of an [H, W, 3+] colour array (extra channels ignored),
    as float64."""
    a = np.asarray(arr, dtype=np.float64)
    return _LUMA[0] * a[..., 0] + _LUMA[1] * a[..., 1] + _LUMA[2] * a[..., 2]


def raster_from(
    data: np.ndarray, kind: DataKind, *, native: bool = False
) -> np.ndarray:
    """2D raster for a bare array + kind (the pre-DataStruct form).

    ``native=True`` returns an image's array as-is (possibly a read-only
    integer buffer — the render/measure paths encode from the native dtype);
    the default promotes to a writeable float64 copy, which is what every
    analysis consumer historically received.
    """
    if kind is DataKind.IMAGE:
        if native:
            return data
        img: np.ndarray = np.asarray(data, dtype=np.float64)
        return img
    if kind is DataKind.SPECTRUM_IMAGE:
        summed: np.ndarray = np.asarray(np.sum(data, axis=2, dtype=np.float64))
        return summed
    if kind is DataKind.RGB_IMAGE:
        # every analysis consumer sees a defensible scalar (ADR 0003 §3);
        # the display path never comes through here — it serves the colour
        # pixels directly
        return rgb_luma(data)
    raise NoRasterError(f"{kind.value} data has no 2D raster")


def raster_of(ds: DataStruct, *, native: bool = False) -> np.ndarray:
    """2D raster of a dataset — see :func:`raster_from`."""
    return raster_from(ds.data, ds.kind, native=native)


def region_sum_spectrum(
    cube: np.ndarray, row0: int, col0: int, row1: int, col1: int
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Region-summed spectrum of an SI cube — the clamp → slice → sum behind
    GET /image/{id}/spectrum's rect path, lifted out of `routes/images.py`
    (wave D, ADR 0005 §1) so the registered op and the HTTP route share it.

    Corners are 1-based inclusive, in either order; they are sorted and
    clamped to the cube. Returns ``(counts, (r0, c0, r1, c1))`` — the float64
    spectrum summed over the spatial axes plus the clamped rect actually
    summed. A region empty after clamping raises ValueError (the route maps
    it to 422). The whole-cube case stays with the caller
    (``DataStruct.sum_spectrum``).

    The slice happens before converting/accumulating so a one-pixel probe
    never materializes a float64 copy of the entire spectrum image.
    """
    cube = np.asarray(cube)
    h, w = int(cube.shape[0]), int(cube.shape[1])
    r0, r1 = sorted((int(row0), int(row1)))
    c0, c1 = sorted((int(col0), int(col1)))
    r0, c0 = max(r0, 1), max(c0, 1)
    r1, c1 = min(r1, h), min(c1, w)
    if r0 > r1 or c0 > c1:
        raise ValueError("region is empty after clamping")
    rect = (r0, c0, r1, c1)
    return masked_sum_spectrum(cube, rect), rect


def masked_sum_spectrum(
    cube: np.ndarray,
    rect: tuple[int, int, int, int],
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Sum an SI cube over a rectangle, optionally narrowed by an exact mask.

    The 4C-1 summation, shared by `GET /image/{id}/spectrum` and the
    `sum_spectrum` op so the two cannot drift (ADR 0005 §1). `rect` is
    1-based inclusive and ALREADY CLAMPED — the clamping lives with
    whoever resolved the region (`region_resolve`, or the sort-and-clamp
    in `region_sum_spectrum` above), not here.

    `mask` is a FULL-IMAGE ``[H, W]`` boolean array or ``None``, matching
    `region_resolve.ResolvedRegion.mask`, and ``None`` means every pixel
    of `rect` is selected. That is not merely an optimization: the
    no-mask branch is the pre-4C expression verbatim, so a rectangle
    keeps summing bit for bit as it always did.

    Its shape is checked against the WHOLE cube, not against the window
    it slices to. Checking only the window lets a crop-local mask through
    whenever the rect starts at the top-left — a ``(4, 4)`` mask paired
    with rect ``(1, 1, 4, 4)`` on an ``[8, 8, C]`` cube slices to the
    right shape while meaning something entirely different — and this
    helper is public, so the mask it advertises is the one it must
    require. dtype is checked too: an integer array is not a mask to
    NumPy but an index list, and indexing with one returns a 4-D block
    rather than a spectrum.

    **Memory.** Neither branch materializes the selected data.
    ``block[window]`` would: advanced indexing builds a dense
    ``(selected, channels)`` copy, which on the multi-gigabyte cubes this
    exists to serve is gigabytes of its own for a broad mask. The
    ``where=`` reduction accumulates in place instead — same answer,
    bounded memory (guarded in tests/test_spectrum_regions.py) — and the
    slice happens before accumulating so a one-pixel probe never touches
    the rest of the cube.
    """
    r0, c0, r1, c1 = rect
    block = cube[r0 - 1:r1, c0 - 1:c1, :]
    if mask is None:
        return np.asarray(np.sum(block, axis=(0, 1), dtype=np.float64))
    mask = np.asarray(mask)
    if mask.dtype != bool:
        raise ValueError(f"mask must be boolean, got dtype {mask.dtype}")
    if mask.shape != cube.shape[:2]:
        raise ValueError(
            f"mask must be a full-image {cube.shape[:2]} array, got {mask.shape}"
        )
    window = mask[r0 - 1:r1, c0 - 1:c1]
    return np.asarray(
        np.sum(block, axis=(0, 1), where=window[..., None], dtype=np.float64)
    )
