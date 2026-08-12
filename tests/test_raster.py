"""calc/raster.py — the one 2D-raster boundary (ADR 0003).

The 13 former per-site copies are covered by their endpoints' own suites;
this file pins the shared helper's contract directly.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.raster import NoRasterError, raster_from, raster_of
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct


def _image(dtype: str = "uint16") -> DataStruct:
    return DataStruct(
        data=np.arange(12, dtype=dtype).reshape(3, 4),
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )


def _cube() -> DataStruct:
    return DataStruct(
        data=np.arange(24, dtype=np.uint16).reshape(2, 3, 4),
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(), AxisCal(), AxisCal(scale=1.0, units="eV")),
    )


def test_image_default_is_writeable_float64_copy() -> None:
    ds = _image()
    r = raster_of(ds)
    assert r.dtype == np.float64
    assert r.flags.writeable  # analysis consumers historically got a copy
    np.testing.assert_array_equal(r, ds.data)


def test_image_native_returns_the_frozen_buffer_as_is() -> None:
    ds = _image()
    r = raster_of(ds, native=True)
    assert r is ds.data  # no copy, native dtype — the render/measure path
    assert r.dtype == np.uint16
    assert not r.flags.writeable


def test_spectrum_image_sums_energy_axis_in_float64() -> None:
    ds = _cube()
    r = raster_of(ds)
    assert r.shape == (2, 3)
    assert r.dtype == np.float64
    np.testing.assert_array_equal(r, ds.data.astype(np.float64).sum(axis=2))


def test_spectrum_image_ignores_native_flag() -> None:
    # native only affects the image branch; a summed cube is always a fresh
    # float64 array
    ds = _cube()
    np.testing.assert_array_equal(
        raster_of(ds, native=True), raster_of(ds, native=False)
    )


def test_spectrum_raises_no_raster_error() -> None:
    ds = DataStruct(
        data=np.arange(8, dtype=np.float64),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(scale=0.01, units="keV"),),
    )
    with pytest.raises(NoRasterError):
        raster_of(ds)
    # routes translate via `except NoRasterError`; ops callers historically
    # caught ValueError — the subclass keeps both working
    assert issubclass(NoRasterError, ValueError)


def test_raster_from_matches_raster_of() -> None:
    ds = _cube()
    np.testing.assert_array_equal(
        raster_from(ds.data, ds.kind), raster_of(ds)
    )


def test_si_sum_accumulates_without_casting_the_cube() -> None:
    """The sum must not materialize a float64 copy of the whole cube.

    Mirrors tests/test_ops_registry.py's allocation-delta guard at the
    boundary itself: for a (64, 64, 512) uint16 cube (4 MiB raw), a
    whole-cube float64 cast would allocate 16 MiB transiently; direct
    accumulation allocates only the (64, 64) output.
    """
    import tracemalloc

    cube = np.zeros((64, 64, 512), dtype=np.uint16)
    ds = DataStruct(
        data=cube,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(), AxisCal(), AxisCal(scale=1.0, units="eV")),
    )
    tracemalloc.start()
    before, _ = tracemalloc.get_traced_memory()
    raster_of(ds)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    # output is 64*64*8 = 32 KiB; the failed (cast-first) variant peaks at
    # ~16 MiB. 4 MiB is a generous middle that only the cast can exceed.
    assert peak - before < 4 * 1024 * 1024
