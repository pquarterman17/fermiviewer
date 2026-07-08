"""Tests for the shared least-squares spectral fitting core.

Validation is by recovery of KNOWN synthetic parameters (no MATLAB
goldens — the predecessor has no model-fit path). Marked ``eels`` since
the core is the EELS/EDS model-fit foundation (PLAN_SPECTRAL_QUANT #1).
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.spectral_fit import (
    Component,
    evaluate,
    fit_spectrum,
    gaussian,
    linear_background,
    polynomial_background,
    power_law,
)

pytestmark = pytest.mark.eels


def test_recovers_single_gaussian() -> None:
    e = np.linspace(0.0, 100.0, 500)
    truth = 50.0 * np.exp(-0.5 * ((e - 40.0) / 5.0) ** 2)
    g = gaussian("peak", amp=10.0, center=35.0, sigma=2.0)
    r = fit_spectrum(e, truth, [g])
    assert r.success
    assert r.params["peak_amp"] == pytest.approx(50.0, rel=1e-4)
    assert r.params["peak_center"] == pytest.approx(40.0, rel=1e-4)
    assert r.params["peak_sigma"] == pytest.approx(5.0, rel=1e-4)
    assert r.reduced_chi2 < 1e-6


def test_recovers_two_gaussians_plus_linear_bg() -> None:
    e = np.linspace(0.0, 200.0, 800)
    truth = (
        100.0 * np.exp(-0.5 * ((e - 60.0) / 4.0) ** 2)
        + 70.0 * np.exp(-0.5 * ((e - 120.0) / 8.0) ** 2)
        + (5.0 + 0.1 * e)
    )
    comps = [
        linear_background("bg", intercept=1.0, slope=0.0),
        gaussian("a", amp=50.0, center=58.0, sigma=3.0),
        gaussian("b", amp=50.0, center=118.0, sigma=6.0),
    ]
    r = fit_spectrum(e, truth, comps)
    assert r.success
    assert r.params["a_amp"] == pytest.approx(100.0, rel=1e-3)
    assert r.params["b_amp"] == pytest.approx(70.0, rel=1e-3)
    assert r.params["bg_intercept"] == pytest.approx(5.0, abs=1e-2)
    assert r.params["bg_slope"] == pytest.approx(0.1, abs=1e-4)
    # per-component curves + total are returned over the full axis
    assert set(r.component_curves) == {"bg", "a", "b"}
    np.testing.assert_allclose(
        r.model, sum(r.component_curves.values()), rtol=1e-12
    )


def test_resolves_overlapping_doublet() -> None:
    # Ti-Kβ / V-Kα-style overlap: two close peaks of known area ratio
    e = np.linspace(4.0, 6.0, 400)
    truth = (
        300.0 * np.exp(-0.5 * ((e - 4.93) / 0.06) ** 2)   # Ti-Kβ
        + 500.0 * np.exp(-0.5 * ((e - 4.95) / 0.06) ** 2)  # V-Kα
    )
    comps = [
        gaussian("tikb", amp=200.0, center=4.93, sigma=0.06,
                 center_bounds=(4.90, 4.96)),
        gaussian("vka", amp=200.0, center=4.95, sigma=0.06,
                 center_bounds=(4.92, 4.98)),
    ]
    r = fit_spectrum(e, truth, comps)
    assert r.success
    ratio = r.params["tikb_amp"] / r.params["vka_amp"]
    assert ratio == pytest.approx(300.0 / 500.0, rel=2e-2)


def test_recovers_power_law_background() -> None:
    e = np.linspace(100.0, 300.0, 600)
    truth = 1.0e6 * np.power(e, -3.0)
    r = fit_spectrum(e, truth, [power_law("bg", amp=1.0e5, exponent=2.0)])
    assert r.success
    assert r.params["bg_exponent"] == pytest.approx(3.0, rel=1e-4)
    assert r.params["bg_amp"] == pytest.approx(1.0e6, rel=1e-3)


def test_polynomial_background_and_evaluate() -> None:
    e = np.linspace(-5.0, 5.0, 200)
    truth = 2.0 - 1.0 * e + 0.5 * e**2
    poly = polynomial_background("p", [1.0, 0.0, 0.0])
    r = fit_spectrum(e, truth, [poly])
    assert r.params["p_c0"] == pytest.approx(2.0, abs=1e-6)
    assert r.params["p_c1"] == pytest.approx(-1.0, abs=1e-6)
    assert r.params["p_c2"] == pytest.approx(0.5, abs=1e-6)
    # evaluate() reproduces the fitted curve from the flat param vector
    flat = [r.params[k] for k in r.param_order]
    curve = evaluate([poly], e, flat)["p"]
    np.testing.assert_allclose(curve, r.model, rtol=1e-12)


def test_bounds_are_respected() -> None:
    e = np.linspace(0.0, 100.0, 300)
    truth = 80.0 * np.exp(-0.5 * ((e - 50.0) / 5.0) ** 2)
    # cap amplitude well below the true value → optimum pinned at the bound
    g = gaussian("peak", amp=10.0, center=50.0, sigma=5.0,
                 amp_bounds=(0.0, 40.0))
    r = fit_spectrum(e, truth, [g])
    assert r.params["peak_amp"] <= 40.0 + 1e-9
    assert r.params["peak_amp"] == pytest.approx(40.0, rel=1e-3)


def test_poisson_weighting_and_covariance() -> None:
    rng = np.random.default_rng(0)
    e = np.linspace(0.0, 100.0, 600)
    clean = 200.0 * np.exp(-0.5 * ((e - 50.0) / 6.0) ** 2) + 20.0
    noisy = rng.poisson(clean).astype(float)
    comps = [
        linear_background("bg", intercept=20.0, slope=0.0),
        gaussian("peak", amp=150.0, center=48.0, sigma=4.0),
    ]
    r = fit_spectrum(e, noisy, comps, weights="poisson")
    assert r.success
    # recovered within a few σ of truth
    assert r.params["peak_amp"] == pytest.approx(200.0, rel=0.1)
    assert r.params["peak_center"] == pytest.approx(50.0, abs=0.5)
    # covariance is finite, symmetric, positive on the diagonal
    cov = r.covariance
    assert cov.shape == (5, 5)   # bg(2) + gaussian(3)
    assert np.all(np.isfinite(cov))
    np.testing.assert_allclose(cov, cov.T, rtol=1e-8)
    assert r.errors["peak_amp"] > 0
    # reduced χ² near 1 for correctly-weighted Poisson data
    assert 0.5 < r.reduced_chi2 < 2.0


def test_fit_range_excludes_window() -> None:
    e = np.linspace(0.0, 100.0, 500)
    truth = 5.0 + 0.2 * e
    corrupted = truth.copy()
    corrupted[e < 20.0] += 1000.0          # garbage below 20 (e.g. ZLP)
    r = fit_spectrum(
        e, corrupted, [linear_background("bg")], fit_range=(20.0, 100.0)
    )
    assert r.params["bg_intercept"] == pytest.approx(5.0, abs=1e-6)
    assert r.params["bg_slope"] == pytest.approx(0.2, abs=1e-8)
    # component curve still spans the full input axis
    assert r.model.shape == e.shape


def test_validation_errors() -> None:
    e = np.linspace(0.0, 10.0, 50)
    with pytest.raises(ValueError):
        fit_spectrum(e, e[:-1], [linear_background("bg")])   # length mismatch
    with pytest.raises(ValueError):
        fit_spectrum(e, e, [])                               # no components
    with pytest.raises(ValueError):
        Component("bad", ("a", "b"), lambda x, p: x, (1.0,))  # p0 mismatch


def test_fit_range_too_narrow_raises() -> None:
    e = np.linspace(0.0, 100.0, 500)
    truth = 5.0 + 0.1 * e
    with pytest.raises(ValueError, match="fewer than 2 channels"):
        fit_spectrum(e, truth, [linear_background("bg")], fit_range=(0.0, 0.05))


def test_unknown_weights_scheme_raises() -> None:
    e = np.linspace(0.0, 100.0, 50)
    truth = 5.0 + 0.1 * e
    with pytest.raises(ValueError, match="unknown weights scheme"):
        fit_spectrum(e, truth, [linear_background("bg")], weights="bogus")


def test_single_data_point_clamps_dof_to_one() -> None:
    # n_data - n_param = 1 - 2 = -1 -> dof = max(..., 1) rather than a
    # division by a non-positive number in reduced_chi2.
    e = np.array([5.0])
    y = np.array([10.0])
    r = fit_spectrum(e, y, [linear_background("bg", intercept=10.0, slope=0.0)])
    assert r.success
    assert np.isfinite(r.reduced_chi2)


def test_nan_counts_raise_from_the_optimizer() -> None:
    # PINNED behaviour: fit_spectrum has no explicit NaN policy of its own;
    # scipy.optimize.least_squares rejects a non-finite residual at the
    # initial point outright rather than silently fitting garbage.
    e = np.linspace(0.0, 100.0, 50)
    truth = 5.0 + 0.1 * e
    counts = truth.copy()
    counts[0] = np.nan
    with pytest.raises(ValueError, match="not finite"):
        fit_spectrum(e, counts, [linear_background("bg")])
