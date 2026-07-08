"""Intensity normalization helpers (calc.normalize) — direct unit tests.

Net-new shared utility (grain-finding-robustness wave, 2026-06-23) that was
never imported by any test until now: ``sanitize``/``normalize01``/
``robust_normalize01`` are exercised directly here rather than only
incidentally through the grain-finding pipeline that consumes them.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.normalize import normalize01, robust_normalize01, sanitize

pytestmark = pytest.mark.imaging


# ── sanitize ─────────────────────────────────────────────────────────


def test_sanitize_clean_array_is_unchanged() -> None:
    a = np.array([1.0, 2.0, 3.0])
    out = sanitize(a)
    np.testing.assert_array_equal(out, a)


def test_sanitize_fills_nan_and_inf_with_finite_median() -> None:
    a = np.array([1.0, np.nan, 3.0, np.inf])
    out = sanitize(a)
    # median of the finite values [1, 3] is 2.0
    np.testing.assert_array_equal(out, [1.0, 2.0, 3.0, 2.0])


def test_sanitize_all_non_finite_fills_zero() -> None:
    a = np.array([np.nan, np.inf, -np.inf])
    out = sanitize(a)
    np.testing.assert_array_equal(out, [0.0, 0.0, 0.0])


# ── normalize01 ──────────────────────────────────────────────────────


def test_normalize01_basic_stretch() -> None:
    a = np.array([0.0, 5.0, 10.0])
    out = normalize01(a)
    np.testing.assert_allclose(out, [0.0, 0.5, 1.0])


def test_normalize01_constant_image_is_zeros() -> None:
    out = normalize01(np.full((3, 3), 7.0))
    np.testing.assert_array_equal(out, np.zeros((3, 3)))


def test_normalize01_is_nan_inf_safe() -> None:
    img = np.array([[1.0, 2.0, np.nan], [3.0, 100.0, -np.inf]])
    out = normalize01(img)
    assert np.all(np.isfinite(out))
    assert out.min() >= 0.0 and out.max() <= 1.0
    assert out[1, 1] == pytest.approx(1.0)   # the true max (100) still maps to 1


# ── robust_normalize01 ───────────────────────────────────────────────


def test_robust_normalize01_clips_outliers() -> None:
    # a single hot pixel (100) among a tight cluster near 1-2.5 — plain
    # min/max compresses the cluster into a sliver; the robust stretch
    # (percentile-clipped) spreads it over more of the [0, 1] range.
    a = np.array([1.0, 1.5, 2.0, 2.5, 100.0])
    out_plain = normalize01(a)
    out_robust = robust_normalize01(a, clip_percentile=10)
    assert out_robust[:4].std() > out_plain[:4].std()
    assert out_robust.max() == pytest.approx(1.0)


def test_robust_normalize01_zero_percentile_matches_plain() -> None:
    a = np.array([2.0, 4.0, 6.0, 8.0])
    np.testing.assert_allclose(
        robust_normalize01(a, clip_percentile=0), normalize01(a)
    )


def test_robust_normalize01_constant_image_is_zeros() -> None:
    out = robust_normalize01(np.full((4, 4), 3.0))
    np.testing.assert_array_equal(out, np.zeros((4, 4)))


def test_robust_normalize01_collapsed_percentiles_widen_to_minmax() -> None:
    # >50% of values identical at the low end: the [p, 100-p] percentile
    # range collapses (lo == hi) and must widen back to true min/max.
    a = np.concatenate([np.zeros(90), np.linspace(1.0, 10.0, 10)])
    out = robust_normalize01(a, clip_percentile=25)
    assert np.all(np.isfinite(out))
    assert out.max() == pytest.approx(1.0)
    assert out.min() == pytest.approx(0.0)


def test_robust_normalize01_is_nan_inf_safe() -> None:
    img = np.array([[1.0, 2.0, np.nan], [3.0, 100.0, -np.inf]])
    out = robust_normalize01(img, clip_percentile=10)
    assert np.all(np.isfinite(out))
    assert out.min() >= 0.0 and out.max() <= 1.0
