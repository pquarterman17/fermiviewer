"""Tests for the Lorentzian / pseudo-Voigt / true-Voigt peak shapes.

Same validation style as ``test_spectral_fit.py``: numeric (trapezoid)
integration checked against the analytic area helpers, shape limits
checked pointwise, and a full fit round-trip recovering known synthetic
parameters. Marked ``eels`` since these shapes plug into the same
EELS/EDS spectral engine as :func:`gaussian` (PLAN_SPECTRAL_QUANT /
ANALYSIS_PRESENTATION_PLAN #1).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from fermiviewer.calc.peak_shapes import (
    lorentzian,
    lorentzian_area,
    pseudo_voigt,
    pseudo_voigt_area,
    voigt,
    voigt_area,
)
from fermiviewer.calc.spectral_fit import (
    evaluate,
    fit_spectrum,
    gaussian,
    gaussian_area,
    linear_background,
)

pytestmark = pytest.mark.eels

# FWHM-matching relation used by pseudo_voigt/documented in its docstring:
# FWHM = 2*sqrt(2*ln2)*sigma; matching Lorentzian HWHM = FWHM/2.
_FWHM_TO_GAMMA = math.sqrt(2.0 * math.log(2.0))


def test_gaussian_area_matches_numeric_integral() -> None:
    e = np.linspace(-200.0, 200.0, 400_001)
    g = gaussian("g", amp=7.0, center=0.0, sigma=3.0)
    curve = evaluate([g], e, [7.0, 0.0, 3.0])["g"]
    numeric = np.trapezoid(curve, e)
    analytic = gaussian_area(7.0, 3.0)
    assert numeric == pytest.approx(analytic, rel=5e-3)


def test_lorentzian_area_matches_numeric_integral() -> None:
    # Lorentzian tails are heavy (~1/x^2); needs a wide window to converge.
    e = np.linspace(-2000.0, 2000.0, 400_001)
    lo = lorentzian("l", amp=3.0, center=0.0, gamma=2.0)
    curve = evaluate([lo], e, [3.0, 0.0, 2.0])["l"]
    numeric = np.trapezoid(curve, e)
    analytic = lorentzian_area(3.0, 2.0)
    assert numeric == pytest.approx(analytic, rel=5e-3)


def test_pseudo_voigt_area_matches_numeric_integral() -> None:
    e = np.linspace(-400.0, 400.0, 400_001)
    pv = pseudo_voigt("pv", amp=5.0, center=1.0, sigma=1.5, eta=0.3)
    curve = evaluate([pv], e, [5.0, 1.0, 1.5, 0.3])["pv"]
    numeric = np.trapezoid(curve, e)
    analytic = pseudo_voigt_area(5.0, 1.5, 0.3)
    assert numeric == pytest.approx(analytic, rel=5e-3)


def test_voigt_area_matches_numeric_integral() -> None:
    e = np.linspace(-400.0, 400.0, 400_001)
    v = voigt("v", amp=4.0, center=0.0, sigma=1.0, gamma=0.5)
    curve = evaluate([v], e, [4.0, 0.0, 1.0, 0.5])["v"]
    numeric = np.trapezoid(curve, e)
    analytic = voigt_area(4.0, 1.0, 0.5)
    assert numeric == pytest.approx(analytic, rel=5e-3)


def test_pseudo_voigt_eta_zero_matches_gaussian_pointwise() -> None:
    e = np.linspace(-30.0, 30.0, 601)
    pv = pseudo_voigt("pv", amp=5.0, center=1.0, sigma=1.5, eta=0.0)
    g = gaussian("g", amp=5.0, center=1.0, sigma=1.5)
    cpv = evaluate([pv], e, [5.0, 1.0, 1.5, 0.0])["pv"]
    cg = evaluate([g], e, [5.0, 1.0, 1.5])["g"]
    np.testing.assert_allclose(cpv, cg, atol=1e-10)


def test_pseudo_voigt_eta_one_matches_lorentzian_pointwise() -> None:
    e = np.linspace(-30.0, 30.0, 601)
    sigma = 1.5
    gamma = _FWHM_TO_GAMMA * sigma
    pv = pseudo_voigt("pv", amp=5.0, center=1.0, sigma=sigma, eta=1.0)
    lo = lorentzian("l", amp=5.0, center=1.0, gamma=gamma)
    cpv = evaluate([pv], e, [5.0, 1.0, sigma, 1.0])["pv"]
    cl = evaluate([lo], e, [5.0, 1.0, gamma])["l"]
    np.testing.assert_allclose(cpv, cl, atol=1e-10)


def test_voigt_tiny_gamma_matches_gaussian_pointwise() -> None:
    e = np.linspace(-20.0, 20.0, 4001)
    v = voigt("v", amp=4.0, center=0.0, sigma=1.0, gamma=1e-6)
    g = gaussian("g", amp=4.0, center=0.0, sigma=1.0)
    cv = evaluate([v], e, [4.0, 0.0, 1.0, 1e-6])["v"]
    cg = evaluate([g], e, [4.0, 0.0, 1.0])["g"]
    np.testing.assert_allclose(cv, cg, atol=1e-4)


def test_lorentzian_tail_is_much_heavier_than_gaussian() -> None:
    # Mutation guard: at 5x FWHM the Lorentzian sits many orders of
    # magnitude above the Gaussian (heavy 1/x^2 tail vs exp(-x^2)) — a
    # swapped/typo'd shape implementation collapses this ratio.
    sigma = 1.0
    fwhm = 2.0 * math.sqrt(2.0 * math.log(2.0)) * sigma
    gamma = _FWHM_TO_GAMMA * sigma  # FWHM-matched
    x = np.array([5.0 * fwhm])
    g = gaussian("g", amp=1.0, center=0.0, sigma=sigma)
    lo = lorentzian("l", amp=1.0, center=0.0, gamma=gamma)
    gv = evaluate([g], x, [1.0, 0.0, sigma])["g"][0]
    lv = evaluate([lo], x, [1.0, 0.0, gamma])["l"][0]
    assert lv / gv > 1e10


def test_fit_recovers_known_voigt_plus_linear_background() -> None:
    e = np.linspace(0.0, 100.0, 2000)
    true_amp, true_c, true_s, true_g = 500.0, 50.0, 4.0, 2.0
    truth = (
        evaluate(
            [voigt("v", amp=true_amp, center=true_c, sigma=true_s, gamma=true_g)],
            e, [true_amp, true_c, true_s, true_g],
        )["v"]
        + (10.0 + 0.05 * e)
    )
    comps = [
        linear_background("bg", intercept=8.0, slope=0.02),
        voigt("v", amp=400.0, center=48.0, sigma=3.0, gamma=1.5),
    ]
    r = fit_spectrum(e, truth, comps)
    assert r.success
    assert r.params["v_amp"] == pytest.approx(true_amp, rel=1e-3)
    assert r.params["v_center"] == pytest.approx(true_c, rel=1e-3)
    assert r.params["v_sigma"] == pytest.approx(true_s, rel=1e-3)
    assert r.params["v_gamma"] == pytest.approx(true_g, rel=1e-2)
    assert r.params["bg_intercept"] == pytest.approx(10.0, abs=1e-2)
    assert r.params["bg_slope"] == pytest.approx(0.05, abs=1e-4)


def test_fit_recovers_known_pseudo_voigt() -> None:
    e = np.linspace(0.0, 100.0, 2000)
    true_amp, true_c, true_s, true_eta = 300.0, 55.0, 5.0, 0.4
    truth = evaluate(
        [pseudo_voigt("pv", amp=true_amp, center=true_c, sigma=true_s, eta=true_eta)],
        e, [true_amp, true_c, true_s, true_eta],
    )["pv"] + 3.0
    comps = [
        linear_background("bg", intercept=3.0, slope=0.0),
        pseudo_voigt("pv", amp=250.0, center=53.0, sigma=4.0, eta=0.5),
    ]
    r = fit_spectrum(e, truth, comps)
    assert r.success
    assert r.params["pv_amp"] == pytest.approx(true_amp, rel=1e-3)
    assert r.params["pv_center"] == pytest.approx(true_c, rel=1e-3)
    assert r.params["pv_sigma"] == pytest.approx(true_s, rel=1e-3)
    assert r.params["pv_eta"] == pytest.approx(true_eta, abs=5e-3)


def test_pseudo_voigt_eta_bounds_respected() -> None:
    e = np.linspace(0.0, 100.0, 500)
    # Truth wants eta > 1 (pure Lorentzian would fit better still) but the
    # default eta_bounds=(0,1) must pin the optimum at the upper bound.
    gamma = _FWHM_TO_GAMMA * 4.0
    truth = evaluate(
        [lorentzian("l", amp=200.0, center=50.0, gamma=gamma)],
        e, [200.0, 50.0, gamma],
    )["l"]
    pv = pseudo_voigt("pv", amp=150.0, center=50.0, sigma=4.0, eta=0.5)
    r = fit_spectrum(e, truth, [pv])
    assert r.params["pv_eta"] <= 1.0 + 1e-9
    assert r.params["pv_eta"] == pytest.approx(1.0, abs=1e-3)
