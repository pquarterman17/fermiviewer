"""Surface roughness (calc.roughness) — guard/edge-case + NaN-policy tests.

The golden path (surface_roughness vs frozen MATLAB reference) lives in
test_imaging.py::test_surface_roughness. This file covers the untested
guards (bad level, empty mask, degenerate flat/1xN images) and the
NaN-robustness extension: non-finite pixels are dropped from the active
mask (same convention as calc.trace_roughness / the 2026-06 grain
hardening) instead of silently poisoning every ISO metric through a NaN
mean or a NaN-corrupted plane_level lstsq fit.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.roughness import surface_roughness

pytestmark = pytest.mark.imaging


# ── pre-existing guards ───────────────────────────────────────────────


def test_empty_mask_raises() -> None:
    img = np.ones((5, 5))
    with pytest.raises(ValueError, match="no true pixels"):
        surface_roughness(img, mask=np.zeros((5, 5), dtype=bool))


def test_mask_shape_mismatch_raises() -> None:
    img = np.ones((5, 5))
    with pytest.raises(ValueError, match="mask must match"):
        surface_roughness(img, mask=np.ones((4, 4), dtype=bool))


def test_bad_level_raises() -> None:
    img = np.ones((5, 5))
    with pytest.raises(ValueError, match="level must be"):
        surface_roughness(img, level="bogus")


def test_flat_image_rsk_rku_zero_division_fallback() -> None:
    # a perfectly flat image has rq == 0 -> the rsk/rku "/ rq**3" would
    # divide by zero without the explicit fallback branch.
    img = np.full((10, 10), 3.0)
    res = surface_roughness(img, level="none")
    assert res.rq == 0.0
    assert res.rsk == 0.0
    assert res.rku == 0.0
    assert res.ra == 0.0


def test_one_by_n_image_does_not_crash() -> None:
    rng = np.random.default_rng(0)
    img = (np.arange(20.0) + rng.normal(0.0, 0.01, 20)).reshape(1, 20)
    res = surface_roughness(img, level="plane")
    assert np.isfinite(res.ra)
    assert np.isfinite(res.rq)
    # degenerate: zero interior grid cells -> SAR falls back to 1.0
    assert res.sar == 1.0


# ── NaN policy (deliberate extension beyond the MATLAB reference) ──────


def test_nan_pixels_are_dropped_not_poisoning() -> None:
    """A NaN-valued pixel must match explicitly masking that same pixel out
    — i.e. non-finite values are excluded from the active mask, not left to
    NaN the mean/lstsq for the whole image."""
    rng = np.random.default_rng(0)
    base = 5.0 + 0.01 * np.add.outer(np.arange(30), np.zeros(30))
    base += rng.normal(0.0, 0.05, (30, 30))

    with_nan = base.copy()
    with_nan[5, 5] = np.nan
    with_nan[10, 20] = np.nan

    mask = np.ones((30, 30), dtype=bool)
    mask[5, 5] = False
    mask[10, 20] = False

    r_nan = surface_roughness(with_nan, level="plane")
    r_masked = surface_roughness(base, level="plane", mask=mask)

    assert np.isfinite(r_nan.ra)
    assert np.isfinite(r_nan.rq)
    assert r_nan.ra == pytest.approx(r_masked.ra, rel=1e-9)
    assert r_nan.rq == pytest.approx(r_masked.rq, rel=1e-9)
    assert r_nan.rz == pytest.approx(r_masked.rz, rel=1e-9)
    assert r_nan.n_pixels == r_masked.n_pixels == 30 * 30 - 2


def test_nan_pixels_dropped_at_none_level_too() -> None:
    img = np.full((10, 10), 2.0)
    img[3, 3] = np.nan
    res = surface_roughness(img, level="none")
    assert res.ra == 0.0     # the remaining 99 pixels are all == 2.0
    assert res.n_pixels == 99


def test_too_few_valid_pixels_returns_nan_result() -> None:
    # 'plane' leveling needs >= 3 finite points; only 2 survive here.
    img = np.full((5, 5), np.nan)
    img[0, 0] = 1.0
    img[1, 1] = 2.0
    res = surface_roughness(img, level="plane")
    assert np.isnan(res.ra)
    assert np.isnan(res.rq)
    assert np.isnan(res.rz)
    assert np.isnan(res.rsk)
    assert np.isnan(res.rku)
    assert np.isnan(res.sar)
    assert res.bearing_heights.size == 0
    assert res.bearing_fraction.size == 0
    assert res.n_pixels == 2


def test_too_few_valid_pixels_quadratic_needs_six() -> None:
    img = np.full((6, 6), np.nan)
    # 5 finite points: enough for 'plane' (needs 3) but not 'quadratic' (needs 6)
    for i in range(5):
        img[i, i] = float(i)
    plane_res = surface_roughness(img, level="plane")
    quad_res = surface_roughness(img, level="quadratic")
    assert np.isfinite(plane_res.ra)
    assert np.isnan(quad_res.ra)


def test_all_nan_image_returns_nan_result() -> None:
    img = np.full((8, 8), np.nan)
    res = surface_roughness(img, level="none")
    assert np.isnan(res.ra)
    assert res.n_pixels == 0
    assert res.bearing_heights.size == 0


def test_sar_finite_with_isolated_nan_pixel() -> None:
    # SAR is computed over the FULL image (not the mask); a single NaN pixel
    # must only exclude the triangles touching it, not NaN the whole ratio.
    img = np.zeros((10, 10))
    img[5, 5] = np.nan
    res = surface_roughness(img, level="none")
    assert np.isfinite(res.sar)
    assert res.sar == pytest.approx(1.0, rel=1e-9)   # flat elsewhere -> SAR ~ 1


def test_nan_and_user_mask_combine() -> None:
    img = np.full((10, 10), 4.0)
    img[2, 2] = np.nan
    mask = np.ones((10, 10), dtype=bool)
    mask[7, 7] = False        # a second pixel excluded via the mask, not NaN
    res = surface_roughness(img, level="none", mask=mask)
    assert res.n_pixels == 10 * 10 - 2
    assert res.ra == 0.0
