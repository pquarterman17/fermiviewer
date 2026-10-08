"""The memory-bounded big-cube paths must agree with the reference paths.

Forced on small cubes by shrinking the size threshold and the per-block
budget, so the chunked code runs through many blocks."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc import eels_advanced, eels_bigcube
from fermiviewer.calc.eels import thickness_map


def _si(dtype=np.uint16, shape=(9, 11, 64), seed=0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    ny, nx, ne = shape
    energy = np.linspace(-10, 53, ne)
    zlp = np.exp(-((energy[None, None, :] - rng.integers(-3, 4, (ny, nx, 1))) ** 2) / 4)
    cube = 1000 * zlp + rng.poisson(20, (ny, nx, ne))
    return cube.astype(dtype), energy


def _run(fn, *a, big: bool, monkeypatch, **kw):
    with monkeypatch.context() as m:
        if big:
            m.setattr(eels_bigcube, "BIG_CUBE_BYTES", 0)
            m.setattr(eels_bigcube, "_BLOCK_BYTES", 4096)  # many blocks
        return fn(*a, **kw)


@pytest.mark.parametrize("reference", ["mean", "max"])
@pytest.mark.parametrize("subpixel", [False, True])
def test_align_zlp_chunked_matches(monkeypatch, reference, subpixel) -> None:
    cube, energy = _si()
    args = (cube, energy, (-8.0, 8.0), reference, subpixel)
    ref_out, ref_s = _run(eels_advanced.align_zlp, *args, big=False, monkeypatch=monkeypatch)
    calls = []
    real = eels_advanced.align_zlp_chunked
    monkeypatch.setattr(eels_advanced, "align_zlp_chunked",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    out, s = _run(eels_advanced.align_zlp, *args, big=True, monkeypatch=monkeypatch)
    assert calls, "chunked path did not run"
    np.testing.assert_allclose(s, ref_s)
    assert out.dtype == ref_out.dtype
    np.testing.assert_allclose(out.astype(float), ref_out.astype(float), atol=1)


@pytest.mark.parametrize("denoise", [False, True])
def test_svd_chunked_matches(monkeypatch, denoise) -> None:
    cube, energy = _si(dtype=np.float64)
    ref = _run(eels_advanced.svd, cube, energy, 5, denoise, big=False, monkeypatch=monkeypatch)
    got = _run(eels_advanced.svd, cube, energy, 5, denoise, big=True, monkeypatch=monkeypatch)
    np.testing.assert_allclose(got.singular_values, ref.singular_values, rtol=1e-6)
    np.testing.assert_allclose(got.explained, ref.explained, rtol=1e-6, atol=1e-9)
    np.testing.assert_allclose(got.mean_spectrum, ref.mean_spectrum, rtol=1e-12)
    # leading components are well separated → same vectors (sign fixed)
    np.testing.assert_allclose(got.eigenspectra[:, :2], ref.eigenspectra[:, :2], atol=1e-6)
    np.testing.assert_allclose(got.score_maps[..., :2], ref.score_maps[..., :2],
                               rtol=1e-5, atol=1e-6 * np.abs(ref.score_maps).max())
    if denoise:
        assert got.denoised_cube is not None and ref.denoised_cube is not None
        assert got.denoised_cube.dtype == np.float32
        np.testing.assert_allclose(got.denoised_cube, ref.denoised_cube,
                                   rtol=1e-4, atol=1e-3)


def test_thickness_native_dtype_matches_float64() -> None:
    cube, energy = _si()
    t_native, v_native = thickness_map(cube, energy)
    t_f64, v_f64 = thickness_map(cube.astype(np.float64), energy)
    np.testing.assert_array_equal(v_native, v_f64)
    np.testing.assert_array_equal(t_native, t_f64)
