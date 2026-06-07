"""DM4 format-contract tests via synthetic fixtures.

Port of fermi-viewer's tests/parser/test_dm_si_contract.m: voxel values
encode their own (x, y, E) position so any transposition changes values,
not just shapes. v(x, y, e) = x + 10·y + 100·e.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.dm import load_dm
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.parser


def encode(x: int, y: int, e: int) -> int:
    return x + 10 * y + 100 * e


def file_order_cube(dims: list[int], dim_roles: dict[str, int]) -> np.ndarray:
    """Flat file-order array (dims[0] fastest) with position-encoded voxels."""
    flat = np.zeros(int(np.prod(dims)), dtype=np.int64)
    idx = 0
    for i2 in range(dims[2]):
        for i1 in range(dims[1]):
            for i0 in range(dims[0]):
                pos = {0: i0, 1: i1, 2: i2}
                flat[idx] = encode(
                    pos[dim_roles["x"]], pos[dim_roles["y"]], pos[dim_roles["e"]]
                )
                idx += 1
    return flat


def expected_cube(nx: int, ny: int, ne: int) -> np.ndarray:
    out = np.zeros((ny, nx, ne), dtype=np.int64)
    for e in range(ne):
        for y in range(ny):
            for x in range(nx):
                out[y, x, e] = encode(x, y, e)
    return out


def test_energy_last_gms_layout(tmp_path) -> None:
    nx, ny, ne = 4, 3, 5
    f = write_mini_dm4(
        tmp_path / "elast.dm4",
        dims=[nx, ny, ne],
        data=file_order_cube([nx, ny, ne], {"x": 0, "y": 1, "e": 2}),
        cal=[
            {"scale": 0.5, "origin": 0, "units": "nm"},
            {"scale": 0.5, "origin": 0, "units": "nm"},
            {"scale": 0.05, "origin": 40, "units": "eV"},
        ],
    )
    ds = load_dm(f)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (ny, nx, ne)
    np.testing.assert_array_equal(ds.data, expected_cube(nx, ny, ne))
    assert ds.energy_axis[0] == pytest.approx(-2.0)       # (0 − 40) × 0.05
    assert ds.energy_cal.units == "eV"
    assert ds.pixel_size == pytest.approx(0.5)
    assert ds.pixel_unit == "nm"


def test_energy_first_legacy_layout(tmp_path) -> None:
    nx, ny, ne = 4, 3, 5
    f = write_mini_dm4(
        tmp_path / "efirst.dm4",
        dims=[ne, nx, ny],
        data=file_order_cube([ne, nx, ny], {"e": 0, "x": 1, "y": 2}),
        data_type=2,                                       # float32 path
        cal=[
            {"scale": 0.05, "origin": 40, "units": "eV"},
            {"scale": 0.5, "origin": 0, "units": "nm"},
            {"scale": 0.5, "origin": 0, "units": "nm"},
        ],
    )
    ds = load_dm(f)
    assert ds.data.shape == (ny, nx, ne)
    np.testing.assert_array_equal(ds.data, expected_cube(nx, ny, ne))
    assert ds.energy_axis[0] == pytest.approx(-2.0)


def test_no_units_falls_back_to_energy_last(tmp_path) -> None:
    nx, ny, ne = 4, 3, 5
    f = write_mini_dm4(
        tmp_path / "nounits.dm4",
        dims=[nx, ny, ne],
        data=file_order_cube([nx, ny, ne], {"x": 0, "y": 1, "e": 2}),
        cal=[
            {"scale": 0.5, "origin": 0, "units": "nm"},
            {"scale": 0.5, "origin": 0, "units": "nm"},
            {"scale": 1.0, "origin": 0, "units": ""},
        ],
    )
    ds = load_dm(f)
    assert ds.n_channels == ne
    assert ds.data[1, 2, 3] == encode(2, 1, 3)


def test_1d_spectrum_nonzero_origin(tmp_path) -> None:
    n, zlp_ch = 64, 20
    counts = np.round(1000 * np.exp(-((np.arange(n) - zlp_ch) ** 2) / 8)) + 1
    f = write_mini_dm4(
        tmp_path / "spec.dm4",
        dims=[n],
        data=counts,
        cal=[{"scale": 0.05, "origin": zlp_ch, "units": "eV"}],
    )
    ds = load_dm(f)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.energy_axis[0] == pytest.approx(-zlp_ch * 0.05)
    assert ds.energy_axis[int(np.argmax(ds.data))] == pytest.approx(0.0)


def test_offset_record_large_array_path(tmp_path) -> None:
    nx, ny, ne = 9, 8, 16                                  # 1152 > threshold
    f = write_mini_dm4(
        tmp_path / "big.dm4",
        dims=[nx, ny, ne],
        data=file_order_cube([nx, ny, ne], {"x": 0, "y": 1, "e": 2}),
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 0.1, "origin": 0, "units": "eV"},
        ],
    )
    ds = load_dm(f)
    assert ds.data.shape == (ny, nx, ne)
    assert ds.data[7, 8, 15] == encode(8, 7, 15)
    assert ds.data[0, 0, 0] == encode(0, 0, 0)
    np.testing.assert_array_equal(
        ds.sum_spectrum(), ds.data.astype(np.float64).sum(axis=(0, 1))
    )


def test_2d_image_orientation(tmp_path) -> None:
    w, h = 6, 4
    flat = np.array([encode(x, y, 0) for y in range(h) for x in range(w)])
    # file order: d0 (=x) fastest → row y blocks — matches the flat above
    f = write_mini_dm4(
        tmp_path / "img.dm4",
        dims=[w, h],
        data=flat,
        cal=[
            {"scale": 0.2, "origin": 0, "units": "nm"},
            {"scale": 0.2, "origin": 0, "units": "nm"},
        ],
    )
    ds = load_dm(f)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (h, w)
    assert ds.data[2, 4] == encode(4, 2, 0)
    assert ds.pixel_size == pytest.approx(0.2)
