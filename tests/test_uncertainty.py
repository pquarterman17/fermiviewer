"""Uncertainty-propagation tests (PLAN_SPECTRAL_QUANT #6).

Two kinds of check:
- **Analytic** — hand-computed values for the Poisson + delta-method
  primitives (small cases verifiable by hand).
- **Monte-Carlo coverage** — the gold standard for error propagation: draw
  noisy realisations, run the real quant pipeline on each, and confirm the
  empirical scatter of the composition matches the predicted 1σ. Seeded for
  determinism; tolerances are loose because the delta method is first-order.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eds import cliff_lorimer
from fermiviewer.calc.eels_quant import ElementEdge, quantify
from fermiviewer.calc.uncertainty import (
    atomic_fraction_sigma,
    cliff_lorimer_uncertainty,
    default_k_factors,
    eels_atomic_sigma,
    fraction_variance,
    integral_variance,
    poisson_sigma,
    trapezoid_weights,
)

# ── primitives ───────────────────────────────────────────────────────


def test_poisson_sigma_root_n_and_clamp() -> None:
    s = poisson_sigma([100.0, 0.0, -5.0, 25.0])
    assert s == pytest.approx([10.0, 0.0, 0.0, 5.0])


def test_poisson_sigma_nan_counts_propagate_nan() -> None:
    # PINNED behaviour: poisson_sigma has no explicit NaN policy — a NaN
    # count survives np.maximum(nan, 0.0) == nan and sqrt(nan) == nan,
    # rather than clamping to 0 like a genuinely negative count does.
    s = poisson_sigma([np.nan, 25.0])
    assert np.isnan(s[0])
    assert s[1] == pytest.approx(5.0)


def test_trapezoid_weights_reproduce_integral() -> None:
    x = np.array([0.0, 1.0, 2.5, 3.0, 7.0])
    y = np.array([2.0, 5.0, 1.0, 4.0, 0.5])
    w = trapezoid_weights(x)
    assert float(np.sum(w * y)) == pytest.approx(float(np.trapezoid(y, x)))
    # weights of a unit-height integrand sum to the axis span
    assert float(w.sum()) == pytest.approx(x[-1] - x[0])


def test_integral_variance_hand_computed() -> None:
    # x=[0,1,2] → weights [0.5, 1.0, 0.5]; var = Σ w² N = .25·10 + 1·10 + .25·10
    assert integral_variance([10.0, 10.0, 10.0], [0.0, 1.0, 2.0]) == pytest.approx(15.0)


def test_integral_variance_clamps_negative_counts() -> None:
    v = integral_variance([10.0, -10.0, 10.0], [0.0, 1.0, 2.0])
    assert v == pytest.approx(0.25 * 10 + 1.0 * 0.0 + 0.25 * 10)  # 5.0


def test_integral_variance_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="equal length"):
        integral_variance([1.0, 2.0, 3.0], [0.0, 1.0])


def test_trapezoid_weights_needs_at_least_two_samples() -> None:
    with pytest.raises(ValueError, match="at least 2 samples"):
        trapezoid_weights([1.0])
    with pytest.raises(ValueError, match="at least 2 samples"):
        trapezoid_weights([])


def test_fraction_variance_single_element_is_zero() -> None:
    # one element is identically 100 % — no compositional freedom
    assert fraction_variance([42.0], [9.0]) == pytest.approx([0.0])


def test_fraction_variance_two_element_closed_form() -> None:
    # var(frac0) = (b²·va + a²·vb) / s⁴ ; a=b=1, va=vb=1, s=2 → 2/16 = 0.125
    v = fraction_variance([1.0, 1.0], [1.0, 1.0])
    assert v == pytest.approx([0.125, 0.125])


def test_fraction_variance_vector_equals_diag_matrix() -> None:
    q = [3.0, 1.0, 6.0]
    var = [0.4, 0.1, 0.9]
    a = fraction_variance(q, var)
    b = fraction_variance(q, np.diag(var))
    assert a == pytest.approx(b)


def test_fraction_variance_common_mode_cancels() -> None:
    # perfectly-correlated equal-variance inputs: a common scale shift leaves
    # the ratio unchanged ⇒ zero fraction variance
    cov = np.array([[1.0, 1.0], [1.0, 1.0]])
    assert fraction_variance([1.0, 1.0], cov) == pytest.approx([0.0, 0.0], abs=1e-12)


def test_fraction_variance_nonpositive_total_is_nan() -> None:
    v = fraction_variance([0.0, 0.0], [1.0, 1.0])
    assert np.all(np.isnan(v))


def test_fraction_variance_non_finite_total_is_nan() -> None:
    v = fraction_variance([np.inf, 1.0], [1.0, 1.0])
    assert np.all(np.isnan(v))


def test_fraction_variance_empty_input_is_empty() -> None:
    v = fraction_variance([], [])
    assert v.shape == (0,)


def test_atomic_fraction_sigma_matches_primitive() -> None:
    q = np.array([4.0, 6.0])
    qs = np.array([0.5, 0.7])
    got = atomic_fraction_sigma(q, qs)
    want = 100.0 * np.sqrt(fraction_variance(q, qs**2))
    assert got == pytest.approx(want)


def test_fraction_variance_bad_shape_raises() -> None:
    with pytest.raises(ValueError):
        fraction_variance([1.0, 2.0], [1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        fraction_variance([1.0, 2.0], np.ones((3, 3)))


# ── EDS Cliff-Lorimer propagation ────────────────────────────────────


@pytest.mark.eds
def test_cliff_lorimer_uncertainty_symmetry() -> None:
    # identical elements/intensities/variances ⇒ identical at%/wt% sigma
    k = default_k_factors(["Fe", "Fe"])
    u = cliff_lorimer_uncertainty([1000.0, 1000.0], [1000.0, 1000.0], ["Fe", "Fe"], k)
    assert u.atomic_pct_sigma[0] == pytest.approx(u.atomic_pct_sigma[1])
    assert u.weight_pct_sigma[0] == pytest.approx(u.weight_pct_sigma[1])
    assert u.atomic_pct_sigma[0] > 0


@pytest.mark.eds
def test_cliff_lorimer_uncertainty_regime_agnostic() -> None:
    # the same call shape serves Poisson (var=N) and fit-error² inputs
    k = default_k_factors(["Si", "O"])
    poisson = cliff_lorimer_uncertainty([5000.0, 9000.0], [5000.0, 9000.0], ["Si", "O"], k)
    fiterr = cliff_lorimer_uncertainty([5000.0, 9000.0], [70.0**2, 95.0**2], ["Si", "O"], k)
    assert poisson.atomic_pct_sigma[0] > 0
    assert fiterr.atomic_pct_sigma[0] > 0
    # different variances → different sigmas (sanity that var_intensity is used)
    assert poisson.atomic_pct_sigma[0] != pytest.approx(fiterr.atomic_pct_sigma[0])


@pytest.mark.eds
def test_cliff_lorimer_uncertainty_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        cliff_lorimer_uncertainty([1.0, 2.0], [1.0, 2.0], ["Fe"], [1.0, 2.0])


@pytest.mark.eds
def test_cliff_lorimer_uncertainty_unknown_element_mass_fallback() -> None:
    # an element missing from calc.elements.ELEMENTS falls back to mass=1.0
    # (matching calc.eds.cliff_lorimer's own fallback) rather than raising.
    k = default_k_factors(["Fe", "Zzunobtainium"])
    u = cliff_lorimer_uncertainty(
        [1000.0, 1000.0], [1000.0, 1000.0], ["Fe", "Zzunobtainium"], k
    )
    assert np.all(np.isfinite(u.atomic_pct_sigma))
    assert np.all(np.isfinite(u.weight_pct_sigma))
    assert u.atomic_pct_sigma[0] > 0


@pytest.mark.eds
def test_cliff_lorimer_monte_carlo_coverage() -> None:
    """Predicted at% 1σ matches the scatter of Poisson-resampled quant."""
    rng = np.random.default_rng(0)
    syms = ["Si", "Fe", "O"]
    true_i = np.array([8000.0, 5000.0, 12000.0])
    k = cliff_lorimer(
        [np.array([[v]]) for v in true_i], syms
    ).k_factors  # the k-factors the quant actually used

    pred = cliff_lorimer_uncertainty(true_i, true_i, syms, k)  # var = N (Poisson)

    trials = 3000
    at = np.empty((trials, len(syms)))
    for t in range(trials):
        samp = rng.poisson(true_i).astype(float)
        cl = cliff_lorimer([np.array([[v]]) for v in samp], syms)
        at[t] = cl.mean_atomic_pct
    emp = at.std(axis=0)

    # first-order delta method vs empirical scatter — agree to ~15 %
    assert pred.atomic_pct_sigma == pytest.approx(emp, rel=0.15)


# ── EELS Poisson propagation ─────────────────────────────────────────


def _synthetic_eels() -> tuple[np.ndarray, np.ndarray, list[ElementEdge]]:
    """Power-law background + two box 'edges' with high counts.

    The edges are simple steps in their signal windows; the quant's power-law
    background fit extrapolates and subtracts, leaving the step as net signal.
    Counts are large so Poisson noise is well into the Gaussian regime.
    """
    energy = np.linspace(200.0, 900.0, 701)  # 1 eV/channel
    bg = 4000.0 * (energy / 200.0) ** -2.0   # smooth, hundreds–thousands of counts
    spectrum = bg.copy()
    # edge A onset 532 eV (O-K-like), edge B onset 708 eV (Fe-L-like)
    spectrum[(energy >= 535) & (energy <= 580)] += 900.0
    spectrum[(energy >= 712) & (energy <= 757)] += 1400.0
    edges = [
        ElementEdge("O", "K", 8, 532.0, (535.0, 580.0), (460.0, 525.0)),
        ElementEdge("Fe", "L", 26, 708.0, (712.0, 757.0), (640.0, 705.0)),
    ]
    return energy, spectrum, edges


@pytest.mark.eels
def test_eels_atomic_sigma_is_positive_and_finite() -> None:
    energy, spectrum, edges = _synthetic_eels()
    res = quantify(energy, spectrum, edges, e0_kv=200, beta_mrad=10)
    sig = eels_atomic_sigma(
        energy, spectrum,
        [e.signal_window for e in edges],
        res.areal_ratio, res.sigma,
    )
    assert sig.shape == (2,)
    assert np.all(np.isfinite(sig))
    assert np.all(sig > 0)
    # two-element system: the two at% sigmas are equal (frac0+frac1=1 ⇒ δ are ±)
    assert sig[0] == pytest.approx(sig[1], rel=1e-9)


@pytest.mark.eels
def test_eels_atomic_sigma_monte_carlo_coverage() -> None:
    """Predicted EELS at% 1σ tracks Poisson-resampled quant scatter."""
    energy, spectrum, edges = _synthetic_eels()
    res = quantify(energy, spectrum, edges, e0_kv=200, beta_mrad=10)
    pred = eels_atomic_sigma(
        energy, spectrum, [e.signal_window for e in edges],
        res.areal_ratio, res.sigma,
    )

    rng = np.random.default_rng(1)
    trials = 400
    at = np.empty((trials, 2))
    for t in range(trials):
        samp = rng.poisson(spectrum).astype(float)
        q = quantify(energy, samp, edges, e0_kv=200, beta_mrad=10)
        at[t] = q.atomic_percent
    emp = at.std(axis=0)

    # the background-fit fluctuation (a documented 2nd-order term we omit) makes
    # the empirical scatter a touch larger; predicted should be the same order
    # and not wildly off — within a factor of ~1.8 either way.
    ratio = pred / emp
    assert np.all(ratio > 0.55)
    assert np.all(ratio < 1.8)


@pytest.mark.eels
def test_eels_atomic_sigma_zero_cross_section_is_nan() -> None:
    # var(r) = var(I)/sigma^2 is undefined for sigma == 0 (:202); NaN
    # propagates through fraction_variance's covariance to ALL elements,
    # not just the zero-cross-section one (cov is not block-diagonal once
    # any entry is NaN) — pinning that as the current behaviour.
    energy, spectrum, edges = _synthetic_eels()
    res = quantify(energy, spectrum, edges, e0_kv=200, beta_mrad=10)
    sig = eels_atomic_sigma(
        energy, spectrum,
        [e.signal_window for e in edges],
        res.areal_ratio, np.array([0.0, res.sigma[1]]),
    )
    assert np.all(np.isnan(sig))


@pytest.mark.eels
def test_eels_atomic_sigma_narrow_window_is_nan() -> None:
    # a signal window selecting < 2 channels -> var_i[k] = NaN (:196-197)
    energy, spectrum, edges = _synthetic_eels()
    res = quantify(energy, spectrum, edges, e0_kv=200, beta_mrad=10)
    lo = edges[0].signal_window[0]
    narrow_windows = [(lo, lo + 0.05), edges[1].signal_window]
    sig = eels_atomic_sigma(
        energy, spectrum, narrow_windows, res.areal_ratio, res.sigma,
    )
    assert np.all(np.isnan(sig))


@pytest.mark.eels
def test_eels_atomic_sigma_shrinks_with_more_counts() -> None:
    """More counts → smaller relative composition error (√N scaling)."""
    energy, spectrum, edges = _synthetic_eels()
    res1 = quantify(energy, spectrum, edges, e0_kv=200, beta_mrad=10)
    s1 = eels_atomic_sigma(
        energy, spectrum, [e.signal_window for e in edges],
        res1.areal_ratio, res1.sigma,
    )
    big = spectrum * 100.0
    res2 = quantify(energy, big, edges, e0_kv=200, beta_mrad=10)
    s2 = eels_atomic_sigma(
        energy, big, [e.signal_window for e in edges],
        res2.areal_ratio, res2.sigma,
    )
    # 100× counts → ~10× smaller sigma (at% itself is unchanged)
    assert np.all(s2 < s1)
    assert s2[0] == pytest.approx(s1[0] / 10.0, rel=0.05)
