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

__all__ = ["NoRasterError", "raster_from", "raster_of"]


class NoRasterError(ValueError):
    """The dataset kind has no 2D raster (a 1D spectrum)."""


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
    raise NoRasterError(f"{kind.value} data has no 2D raster")


def raster_of(ds: DataStruct, *, native: bool = False) -> np.ndarray:
    """2D raster of a dataset — see :func:`raster_from`."""
    return raster_from(ds.data, ds.kind, native=native)
