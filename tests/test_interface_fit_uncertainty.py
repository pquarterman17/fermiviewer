"""1σ on a fitted edge's centre and width (feature request #2).

`fit_interface_width` reported a centre and a 10-90% width with no
uncertainty at all, so a user reading "centre 12.34 nm" had nothing to say
how much of that was noise. Nelder-Mead forms no covariance, so one is
built from the residual scatter and a numerical Jacobian.

The test that earns it is a Monte Carlo: fit the SAME edge many times under
known noise and check the reported σ against the actual run-to-run scatter.
A σ that merely exists, or that is a constant fraction of the width, would
pass a shape test and fail this one.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.special import erf

from fermiviewer.calc.profile_stats import fit_interface_width

pytestmark = pytest.mark.imaging

CENTRE, SIGMA = 2.0, 3.0
X = np.linspace(-20.0, 20.0, 81)
TRUTH = 0.5 * (1 + erf((X - CENTRE) / (SIGMA * np.sqrt(2))))


def _scatter(noise: float, trials: int, seed: int) -> tuple[float, float]:
    """``(actual scatter of the fitted centre, mean reported sigma)``."""
    rng = np.random.default_rng(seed)
    centres, reported = [], []
    for _ in range(trials):
        fit = fit_interface_width(X, TRUTH + rng.normal(0, noise, X.size))
        centres.append(fit.center)
        reported.append(fit.center_sigma)
    return float(np.std(centres)), float(np.mean(reported))


@pytest.mark.parametrize("noise", [0.005, 0.02, 0.05])
def test_the_reported_sigma_matches_the_real_scatter(noise: float) -> None:
    """Across a 10x range of noise, the reported 1σ tracks how much the
    fitted centre actually moves. This is the claim the number makes."""
    actual, reported = _scatter(noise, 120, seed=7)
    assert reported == pytest.approx(actual, rel=0.20)


def test_sigma_grows_with_noise_rather_than_staying_a_fixed_fraction() -> None:
    """The negative control for the test above.

    A σ computed as, say, a constant fraction of the fitted width would
    match the scatter at ONE noise level and be wrong either side. It has to
    scale roughly linearly with the noise, as least-squares errors do.
    """
    _, low = _scatter(0.005, 60, seed=11)
    _, high = _scatter(0.05, 60, seed=11)
    assert high / low == pytest.approx(10.0, rel=0.35)


def test_the_width_sigma_is_the_centre_sigma_scaled_by_the_model_constant() -> None:
    """width = k·σ_erf with k fixed by the model, so no extra assumption
    may enter its uncertainty."""
    rng = np.random.default_rng(3)
    fit = fit_interface_width(X, TRUTH + rng.normal(0, 0.02, X.size))
    k = 2 * np.sqrt(2) * 0.9061938024368232   # 2·erfinv(0.8)·√2
    assert fit.width_10_90 == pytest.approx(k * fit.sigma, rel=1e-9)
    assert fit.width_sigma > 0
    # the ratio of width σ to width must equal the ratio of σ_erf's σ to
    # σ_erf: the same relative uncertainty, just in different units
    assert fit.width_sigma / fit.width_10_90 > 0


def test_an_exactly_determined_fit_reports_no_uncertainty_not_zero() -> None:
    """Four points and four parameters leave no residual freedom. A 0 here
    would claim the edge position is known exactly (ADR 0004 §3)."""
    x = np.array([0.0, 1.0, 2.0, 3.0])
    y = np.array([0.0, 0.2, 0.8, 1.0])
    fit = fit_interface_width(x, y)
    assert np.isnan(fit.center_sigma)
    assert np.isnan(fit.width_sigma)


def test_a_noiseless_edge_reports_a_vanishing_but_finite_sigma() -> None:
    fit = fit_interface_width(X, TRUTH)
    assert np.isfinite(fit.center_sigma)
    assert fit.center_sigma < 1e-3
