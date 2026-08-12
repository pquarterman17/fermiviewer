"""calc/distributions.py — population summary stats + normal/log-normal/
Weibull distribution fitting for measured object populations
(ANALYSIS_PRESENTATION_PLAN.md #6, audit R6).

Pins: summary stats agree with plain numpy; a seeded log-normal sample is
correctly IDENTIFIED as log-normal by AIC and its shape/scale are recovered;
a seeded normal sample is correctly identified as normal; validation paths
(too few values, non-positive values for lognormal/weibull, unknown kind);
histogram bin counts on both a real distribution and degenerate inputs.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.distributions import (
    MIN_FIT_N,
    fit_all,
    fit_distribution,
    histogram_bins,
    summarize,
)

# ── summarize ───────────────────────────────────────────────────────────


def test_summarize_matches_numpy_reference() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    s = summarize(values)
    assert s.n == 10
    assert s.n_dropped == 0
    assert s.mean == pytest.approx(float(np.mean(values)))
    assert s.std == pytest.approx(float(np.std(values, ddof=1)))
    assert s.minimum == 1.0
    assert s.maximum == 10.0
    assert s.median == pytest.approx(float(np.percentile(values, 50)))
    assert s.q1 == pytest.approx(float(np.percentile(values, 25)))
    assert s.q3 == pytest.approx(float(np.percentile(values, 75)))


def test_summarize_drops_non_finite_and_reports_the_count() -> None:
    values = np.array([1.0, 2.0, np.nan, 3.0, np.inf, -np.inf, 4.0])
    s = summarize(values)
    assert s.n == 4
    assert s.n_dropped == 3
    assert s.mean == pytest.approx(2.5)


def test_summarize_single_value_has_nan_std_not_a_crash() -> None:
    s = summarize(np.array([5.0]))
    assert s.n == 1
    assert np.isnan(s.std)
    assert s.mean == s.median == s.q1 == s.q3 == 5.0


def test_summarize_raises_on_all_non_finite() -> None:
    with pytest.raises(ValueError, match="no finite values"):
        summarize(np.array([np.nan, np.inf, -np.inf]))


# ── fit_distribution: validation ────────────────────────────────────────


def test_fit_distribution_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown distribution kind"):
        fit_distribution(np.arange(1.0, 20.0), "gamma")


def test_fit_distribution_rejects_too_few_values() -> None:
    values = np.arange(1.0, float(MIN_FIT_N))  # MIN_FIT_N - 1 values
    assert values.size == MIN_FIT_N - 1
    with pytest.raises(ValueError, match=f"at least {MIN_FIT_N}"):
        fit_distribution(values, "normal")


def test_fit_distribution_accepts_exactly_the_minimum() -> None:
    values = np.arange(1.0, float(MIN_FIT_N) + 1.0)  # exactly MIN_FIT_N
    assert values.size == MIN_FIT_N
    fit_distribution(values, "normal")  # must not raise


def test_fit_distribution_rejects_non_positive_for_lognormal() -> None:
    values = np.array([1.0, 2.0, -1.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    with pytest.raises(ValueError, match="strictly positive"):
        fit_distribution(values, "lognormal")


def test_fit_distribution_rejects_non_positive_for_weibull() -> None:
    values = np.array([0.0, 2.0, 1.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    with pytest.raises(ValueError, match="strictly positive"):
        fit_distribution(values, "weibull")


def test_fit_distribution_normal_allows_negative_values() -> None:
    values = np.array([-5.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    fit_distribution(values, "normal")  # must not raise


def test_fit_distribution_non_finite_values_are_dropped_before_the_count_check() -> None:
    # 7 finite values + 3 non-finite: below MIN_FIT_N once cleaned
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, np.nan, np.inf, -np.inf])
    with pytest.raises(ValueError, match=f"at least {MIN_FIT_N}"):
        fit_distribution(values, "normal")


# ── fit_distribution / fit_all: real recovery ───────────────────────────


def test_lognormal_sample_is_identified_as_lognormal_by_aic() -> None:
    rng = np.random.default_rng(0)
    true_sigma, true_scale = 0.4, np.exp(1.0)
    data = rng.lognormal(mean=1.0, sigma=true_sigma, size=500)

    fits = fit_all(data)

    assert fits.best == "lognormal"
    assert fits.lognormal.aic < fits.normal.aic
    assert fits.lognormal.aic < fits.weibull.aic
    # shape/scale recovered within a generous tolerance for N=500
    assert fits.lognormal.params["s"] == pytest.approx(true_sigma, rel=0.15)
    assert fits.lognormal.params["scale"] == pytest.approx(true_scale, rel=0.15)
    assert fits.lognormal.params["loc"] == 0.0  # floc pinned


def test_normal_sample_is_identified_as_normal_by_aic() -> None:
    rng = np.random.default_rng(0)
    true_loc, true_scale = 10.0, 1.5
    data = rng.normal(loc=true_loc, scale=true_scale, size=500)

    fits = fit_all(data)

    assert fits.best == "normal"
    assert fits.normal.aic < fits.lognormal.aic
    assert fits.normal.aic < fits.weibull.aic
    assert fits.normal.params["loc"] == pytest.approx(true_loc, rel=0.05)
    assert fits.normal.params["scale"] == pytest.approx(true_scale, rel=0.15)


def test_fit_all_raises_when_lognormal_weibull_cannot_fit() -> None:
    # negative values are physically fine for "normal" but not lognormal/weibull
    rng = np.random.default_rng(1)
    data = rng.normal(loc=0.0, scale=1.0, size=100)
    with pytest.raises(ValueError, match="strictly positive"):
        fit_all(data)


def test_ks_and_log_likelihood_are_finite_and_sane() -> None:
    rng = np.random.default_rng(2)
    data = rng.normal(loc=5.0, scale=1.0, size=200)
    f = fit_distribution(data, "normal")
    assert np.isfinite(f.log_likelihood)
    assert np.isfinite(f.aic)
    assert 0.0 <= f.ks_statistic <= 1.0
    assert 0.0 <= f.ks_pvalue <= 1.0


def test_no_scipy_convergence_warning_leaks(recwarn: pytest.WarningsRecorder) -> None:
    # small/near-degenerate sample: worst realistic case for scipy's MLE
    # search to emit a convergence RuntimeWarning/OptimizeWarning; the
    # module must swallow those internally rather than let pytest's
    # filterwarnings=error turn one into a failure elsewhere in the suite.
    values = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0001])
    fit_distribution(values, "weibull")
    assert len(recwarn) == 0


# ── histogram_bins ──────────────────────────────────────────────────────


def test_histogram_bins_cover_every_value() -> None:
    rng = np.random.default_rng(3)
    data = rng.normal(loc=0.0, scale=1.0, size=1000)
    h = histogram_bins(data)
    assert h.counts.sum() == data.size
    assert h.edges.size == h.counts.size + 1
    assert h.edges[0] <= data.min()
    assert h.edges[-1] >= data.max()


def test_histogram_bins_constant_input_is_one_bin() -> None:
    h = histogram_bins(np.full(20, 5.0))
    assert h.counts.tolist() == [20]
    assert h.edges.size == 2
    assert h.edges[0] < 5.0 < h.edges[1]


def test_histogram_bins_constant_zero_input_pads_symmetrically() -> None:
    h = histogram_bins(np.zeros(10))
    assert h.counts.tolist() == [10]
    assert h.edges[0] == pytest.approx(-0.5)
    assert h.edges[1] == pytest.approx(0.5)


def test_histogram_bins_degenerate_iqr_falls_back_to_sqrt_rule() -> None:
    # more than half the mass at one value collapses q1==q3 (IQR=0), but
    # the range is nonzero (min != max) — Freedman-Diaconis's width would
    # be zero/undefined here, so the sqrt-choice rule must kick in instead
    # of raising or returning a single degenerate bin.
    values = np.concatenate([np.full(80, 1.0), np.linspace(1.0, 10.0, 20)])
    h = histogram_bins(values)
    assert h.counts.sum() == values.size
    expected_bins = int(np.ceil(np.sqrt(values.size)))
    assert h.counts.size == expected_bins


def test_histogram_bins_raises_on_all_non_finite() -> None:
    with pytest.raises(ValueError, match="no finite values"):
        histogram_bins(np.array([np.nan, np.inf]))


def test_histogram_bins_bin_count_is_capped() -> None:
    # a huge, near-zero IQR relative to a wide range would otherwise blow
    # n_bins up arbitrarily large — must stay bounded.
    rng = np.random.default_rng(4)
    tight = rng.normal(loc=0.0, scale=1e-9, size=5000)
    wide_outlier = np.array([1e6])
    data = np.concatenate([tight, wide_outlier])
    h = histogram_bins(data)
    assert h.counts.size <= 200
