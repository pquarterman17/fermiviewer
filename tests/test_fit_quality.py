"""Tests for calc/fit_quality.r_squared (#2 / audit R4)."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.fit_quality import r_squared


def test_perfect_fit_is_one() -> None:
    actual = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert r_squared(actual, actual) == pytest.approx(1.0)


def test_known_value() -> None:
    actual = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    predicted = np.array([1.0, 2.0, 3.0, 4.0, 6.0])
    # mean=3, ss_tot=4+1+0+1+4=10; ss_res=(5-6)^2=1; R²=1-1/10=0.9
    assert r_squared(actual, predicted) == pytest.approx(0.9)


def test_worse_than_the_mean_is_negative() -> None:
    actual = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    predicted = np.array([10.0, -8.0, 20.0, -5.0, 15.0])
    assert r_squared(actual, predicted) < 0.0


def test_degenerate_ss_tot_returns_zero_not_nan() -> None:
    # a constant "actual" window has zero variance to explain
    actual = np.full(5, 7.0)
    predicted = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    got = r_squared(actual, predicted)
    assert got == 0.0
    assert np.isfinite(got)


def test_mismatched_lengths_raise() -> None:
    with pytest.raises(ValueError):
        r_squared(np.array([1.0, 2.0]), np.array([1.0]))
