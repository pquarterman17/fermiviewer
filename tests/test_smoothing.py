"""calc/smoothing.py — Savitzky-Golay smoothing + derivative (was audit R5,
ANALYSIS_PRESENTATION_PLAN.md #5).

Pins the two properties that distinguish a real Savitzky-Golay filter from a
hand-rolled or mis-wired one: exact polynomial reproduction, and a
derivative that actually uses ``delta`` (a filter that silently used
delta=1.0 would still "look smooth" but be wrong by a scale factor,
undetectable without a non-unit-delta test)."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.smoothing import savgol_derivative, savgol_smooth

# ── polynomial reproduction (the defining Savitzky-Golay property) ────

def test_savgol_smooth_reproduces_a_cubic_exactly_in_the_interior() -> None:
    x = np.linspace(-5.0, 5.0, 101)
    y = 2.0 * x**3 - 1.5 * x**2 + 0.5 * x - 3.0  # degree-3 polynomial
    smoothed = savgol_smooth(y, window=11, polyorder=3)
    interior = slice(10, -10)  # avoid any edge-mode ambiguity
    np.testing.assert_allclose(smoothed[interior], y[interior], atol=1e-8)


def test_savgol_smooth_does_not_reproduce_a_quartic_with_polyorder_3() -> None:
    """Sanity check on the property test above: a degree-4 polynomial is
    NOT exactly reproduced by a degree-3 fit, so the interior residual must
    be nonzero — otherwise the "exact reproduction" test could pass for a
    filter that just copies its input."""
    x = np.linspace(-5.0, 5.0, 101)
    y = x**4
    smoothed = savgol_smooth(y, window=11, polyorder=3)
    interior = slice(10, -10)
    assert not np.allclose(smoothed[interior], y[interior], atol=1e-6)


# ── derivative exactness (proves delta handling) ───────────────────────

def test_savgol_derivative_matches_the_analytic_derivative_with_nonunit_delta() -> None:
    """y = a*x^2 + b*x + c sampled on a non-unit-spacing axis (delta=0.5);
    dy/dx = 2a*x + b analytically. A filter that used delta=1.0 regardless
    of the supplied value would be off by exactly the delta factor here."""
    a, b, c = 2.0, 3.0, -1.0
    delta = 0.5
    n = 101
    x = np.arange(n) * delta
    y = a * x**2 + b * x + c
    deriv = savgol_derivative(y, window=11, polyorder=3, order=1, delta=delta)
    analytic = 2 * a * x + b
    interior = slice(10, -10)
    np.testing.assert_allclose(deriv[interior], analytic[interior], atol=1e-8)


def test_savgol_derivative_default_delta_is_per_channel() -> None:
    """delta defaults to 1.0 -> derivative is per-sample-index, not per some
    other implicit unit."""
    x = np.arange(101, dtype=np.float64)  # unit spacing
    y = 3.0 * x**2 + 2.0 * x
    deriv = savgol_derivative(y, window=11, polyorder=3, order=1)
    analytic = 6.0 * x + 2.0
    interior = slice(10, -10)
    np.testing.assert_allclose(deriv[interior], analytic[interior], atol=1e-8)


def test_savgol_second_derivative_of_a_quadratic_is_the_constant_2a() -> None:
    a = 4.0
    x = np.linspace(0.0, 10.0, 101)
    y = a * x**2
    deriv2 = savgol_derivative(y, window=15, polyorder=3, order=2, delta=x[1] - x[0])
    interior = slice(15, -15)
    np.testing.assert_allclose(deriv2[interior], 2 * a, atol=1e-6)


# ── noise reduction ─────────────────────────────────────────────────────

def test_savgol_smooth_reduces_noise_relative_to_truth() -> None:
    rng = np.random.default_rng(42)
    x = np.linspace(0.0, 4 * np.pi, 300)
    truth = np.sin(x)
    noisy = truth + rng.normal(scale=0.2, size=x.size)
    smoothed = savgol_smooth(noisy, window=15, polyorder=3)
    std_before = float(np.std(noisy - truth))
    std_after = float(np.std(smoothed - truth))
    assert std_after < std_before


# ── output dtype ─────────────────────────────────────────────────────────

def test_savgol_smooth_output_is_float64_for_any_input_dtype() -> None:
    y = np.ones(20, dtype=np.float32)
    out = savgol_smooth(y, window=5, polyorder=2)
    assert out.dtype == np.float64


def test_savgol_derivative_output_is_float64_for_any_input_dtype() -> None:
    y = np.arange(20, dtype=np.int32)
    out = savgol_derivative(y, window=5, polyorder=2, order=1)
    assert out.dtype == np.float64


# ── validation ───────────────────────────────────────────────────────────

def test_savgol_smooth_rejects_a_non_1d_array() -> None:
    with pytest.raises(ValueError, match="1-D array"):
        savgol_smooth(np.ones((5, 5)), window=3, polyorder=1)


def test_savgol_smooth_rejects_an_even_window() -> None:
    with pytest.raises(ValueError, match="window must be odd"):
        savgol_smooth(np.ones(20), window=10, polyorder=3)


def test_savgol_smooth_rejects_window_not_greater_than_polyorder() -> None:
    with pytest.raises(ValueError, match=r"must be > polyorder"):
        savgol_smooth(np.ones(20), window=5, polyorder=5)


def test_savgol_smooth_rejects_window_larger_than_the_trace() -> None:
    with pytest.raises(ValueError, match=r"must be <= len\(y\)"):
        savgol_smooth(np.ones(5), window=7, polyorder=3)


def test_savgol_derivative_rejects_order_above_polyorder() -> None:
    with pytest.raises(ValueError, match=r"1 <= order <= polyorder"):
        savgol_derivative(np.ones(20), window=11, polyorder=3, order=4)


def test_savgol_derivative_rejects_order_below_one() -> None:
    with pytest.raises(ValueError, match=r"1 <= order <= polyorder"):
        savgol_derivative(np.ones(20), window=11, polyorder=3, order=0)


@pytest.mark.parametrize("bad_delta", [0.0, float("nan"), float("inf")])
def test_savgol_derivative_rejects_a_non_finite_or_zero_delta(bad_delta: float) -> None:
    with pytest.raises(ValueError, match="delta must be finite and nonzero"):
        savgol_derivative(np.ones(20), window=11, polyorder=3, order=1, delta=bad_delta)
