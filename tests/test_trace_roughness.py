"""Interface-trace roughness metrology (calc.trace_roughness, items #8-12).

Net-new (no MATLAB golden): verified against synthetic ground truth —
traces with known roughness sigma / correlation length / Hurst exponent,
plus known contaminants (tilt, bow, outlier columns, localisation jitter)
that the raw ``np.std`` conflated with roughness.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.ndimage import gaussian_filter1d

from fermiviewer.calc import trace_roughness as tr
from fermiviewer.calc.layers import analyze_layers

pytestmark = pytest.mark.imaging


def _correlated(n: int, smooth: float, sigma: float, seed: int) -> np.ndarray:
    """Gaussian-correlated roughness: ACF exp(-(r/xi)^2) with xi = 2*smooth."""
    rng = np.random.default_rng(seed)
    r = gaussian_filter1d(rng.normal(0.0, 1.0, n), smooth)
    return r * (sigma / r.std())


def _dirty_trace(n: int = 1024, seed: int = 1) -> tuple[np.ndarray, float]:
    """sigma=2 roughness + tilt + bow + 6 outlier columns + 0.5 px jitter."""
    rng = np.random.default_rng(seed)
    rough = _correlated(n, 12.0, 2.0, seed)
    x = np.arange(n)
    trace = 100.0 + rough + 0.02 * x + 5e-6 * (x - n / 2) ** 2
    trace += rng.normal(0.0, 0.5, n)
    bad = np.array([50, 300, 301, 700, 901, 1000])
    trace[bad] += rng.choice([-1.0, 1.0], bad.size) * rng.uniform(15, 40, bad.size)
    return trace, 2.0


class TestRobustSigmaW:
    def test_recovers_true_sigma_under_contamination(self):
        trace, true_sigma = _dirty_trace()
        # the old estimator: hopelessly inflated by tilt + bow + outliers
        assert float(np.std(trace)) > 3.0 * true_sigma
        s = tr.robust_sigma_w(trace)
        assert s == pytest.approx(true_sigma, rel=0.2)

    def test_flat_noisy_trace_reports_near_zero(self):
        # jitter only — after noise subtraction almost nothing remains
        rng = np.random.default_rng(3)
        s = tr.robust_sigma_w(100.0 + rng.normal(0.0, 0.5, 1024))
        assert s < 0.25

    def test_short_trace_is_nan(self):
        assert np.isnan(tr.robust_sigma_w(np.array([1.0, 2.0, 3.0])))


class TestCleanTrace:
    def test_outliers_rejected_and_flagged(self):
        trace, _ = _dirty_trace()
        resid, keep = tr.clean_trace(trace)
        assert keep.sum() >= trace.size - 8          # only the bad columns go
        assert not keep[300] and not keep[700]
        assert np.isnan(resid[300])

    def test_detrend_removes_tilt_and_bow(self):
        x = np.arange(1024, dtype=np.float64)
        resid, _ = tr.clean_trace(50.0 + 0.05 * x + 1e-5 * (x - 512) ** 2)
        assert tr.robust_sigma(resid) < 1e-6


class TestNoiseFloorAndCI:
    def test_analyze_trace_estimates_noise_floor(self):
        trace, _ = _dirty_trace()
        r = tr.analyze_trace(trace)
        assert r.noise_floor == pytest.approx(0.5, abs=0.15)
        assert 0.98 <= r.quality <= 1.0

    def test_ci_brackets_truth(self):
        trace, true_sigma = _dirty_trace()
        r = tr.analyze_trace(trace)
        lo, hi = r.sigma_ci
        assert lo < true_sigma < hi
        assert lo > 0


class TestSpectrum:
    def test_psd_parseval_scale(self):
        rough = _correlated(1024, 12.0, 2.0, 2)
        wl, p = tr.trace_psd(rough)
        assert wl.size == p.size > 0
        # windowed PSD sum ~ variance (loose: Hann leakage)
        assert float(p.sum()) == pytest.approx(float(rough.var()), rel=0.35)

    def test_hhcf_fit_smooth_gaussian_acf(self):
        # gaussian ACF => self-affine with H=1, xi = 2*smooth
        r = tr.analyze_trace(100.0 + _correlated(1024, 12.0, 2.0, 1))
        assert r.hurst == pytest.approx(1.0, abs=0.15)
        assert r.xi == pytest.approx(24.0, rel=0.35)

    def test_hhcf_fit_survives_contamination(self):
        trace, _ = _dirty_trace()
        r = tr.analyze_trace(trace)
        assert r.hurst == pytest.approx(1.0, abs=0.2)
        assert r.xi == pytest.approx(24.0, rel=0.4)

    def test_hhcf_fit_jagged_ar1(self):
        # AR(1) has exponential ACF => H = 0.5, xi = decay length.
        # A single 1k-px realization scatters H by ~+-0.3; 4k stabilises it.
        rng = np.random.default_rng(5)
        n, phi = 4096, float(np.exp(-1.0 / 15.0))
        ar = np.empty(n)
        ar[0] = 0.0
        w = rng.normal(0.0, 1.0, n)
        for i in range(1, n):
            ar[i] = phi * ar[i - 1] + w[i]
        r = tr.analyze_trace(100.0 + ar * (2.0 / ar.std()))
        assert r.hurst == pytest.approx(0.5, abs=0.2)
        assert r.xi == pytest.approx(15.0, rel=0.5)

    def test_calibration_scales_lengths(self):
        trace, _ = _dirty_trace()
        a = tr.analyze_trace(trace, pixel_size=1.0)
        b = tr.analyze_trace(trace, pixel_size=0.5)
        assert b.sigma_w == pytest.approx(0.5 * a.sigma_w, rel=1e-6)
        assert b.xi == pytest.approx(0.5 * a.xi, rel=1e-6)
        assert b.hurst == pytest.approx(a.hurst, rel=1e-6)  # dimensionless


class TestConformalityAndDecomposition:
    def test_replicated_roughness_correlates(self):
        rough = _correlated(1024, 12.0, 2.0, 7)
        rng = np.random.default_rng(8)
        assert tr.conformality(rough, rough + rng.normal(0, 0.3, 1024)) > 0.9

    def test_independent_roughness_does_not(self):
        a = _correlated(1024, 12.0, 2.0, 9)
        b = _correlated(1024, 12.0, 2.0, 10)
        assert abs(tr.conformality(a, b)) < 0.4

    def test_sigma_chem_quadrature(self):
        assert tr.sigma_chem(5.0, 3.0) == pytest.approx(4.0)

    def test_sigma_chem_roughness_limited_is_nan(self):
        assert np.isnan(tr.sigma_chem(2.0, 3.0))
        assert np.isnan(tr.sigma_chem(float("nan"), 1.0))


def _stack_image(
    n: int = 256, thin_top: int = 118, thin_bot: int = 126, seed: int = 11
) -> np.ndarray:
    """3-layer synthetic: a thin (8 px) bright layer between two strong steps."""
    rng = np.random.default_rng(seed)
    img = np.full((n, n), 100.0)
    img[thin_top:thin_bot, :] = 220.0     # thin bright layer
    img[thin_bot:, :] = 160.0
    img = gaussian_filter1d(img, 1.5, axis=0)
    return img + rng.normal(0.0, 2.0, (n, n))


class TestFitFailureExits:
    """HHCF/bootstrap/PSD fit-failure exits — documented-but-untested NaN/empty
    returns (module docstring items #8-12)."""

    def test_short_trace_hurst_and_xi_are_nan(self):
        # n_valid=20 < 32 required by hhcf_fit -> immediate (nan, nan) exit
        r = tr.analyze_trace(np.arange(20.0))
        assert np.isnan(r.hurst)
        assert np.isnan(r.xi)

    def test_bootstrap_below_sixteen_valid_is_nan_ci(self):
        # a short but CLEAN trace (nothing rejected) has quality 1.0 yet still
        # too few points (< 16) for the block bootstrap to resample
        trace = 50.0 + 0.1 * np.arange(15.0)
        r = tr.analyze_trace(trace, order=1)
        assert r.quality == pytest.approx(1.0)
        lo, hi = r.sigma_ci
        assert np.isnan(lo) and np.isnan(hi)

    def test_psd_below_eight_valid_points_is_empty(self):
        resid = np.array([1.0, 2.0, np.nan, np.nan, np.nan, np.nan, 3.0])
        wl, p = tr.trace_psd(resid)
        assert wl.size == 0 and p.size == 0

    def test_hhcf_fit_nugget_absorbs_pure_jitter_not_roughness(self):
        # a KNOWN correlated roughness component plus PURE iid jitter (no
        # tilt/bow/outliers) isolates the nugget term in _saff/hhcf_fit:
        # without it, the lag-1 jitter jump would bias H down / xi up (see
        # module docstring). The fit must still recover the true xi/H, and
        # the jitter itself must land in noise_floor, not sigma_w.
        rough = _correlated(1024, 12.0, 2.0, seed=20)   # true sigma=2, xi=24
        rng = np.random.default_rng(21)
        jitter = rng.normal(0.0, 1.5, 1024)             # pure delta-correlated noise
        trace = 100.0 + rough + jitter
        r = tr.analyze_trace(trace)
        assert r.hurst == pytest.approx(1.0, abs=0.2)
        assert r.xi == pytest.approx(24.0, rel=0.4)
        assert r.noise_floor == pytest.approx(1.5, rel=0.3)
        assert r.sigma_w == pytest.approx(2.0, rel=0.3)


class TestConformalityEdgeCases:
    def test_length_mismatch_is_nan(self):
        assert np.isnan(tr.conformality(np.zeros(5), np.zeros(6)))

    def test_overlap_below_sixteen_is_nan(self):
        assert np.isnan(tr.conformality(np.arange(10.0), np.arange(10.0)))

    def test_constant_trace_is_nan(self):
        # zero variance in one trace -> denom <= 0
        assert np.isnan(tr.conformality(np.full(20, 5.0), np.arange(20.0)))


class TestEndToEndDegenerateTraces:
    def test_nan_bearing_trace_does_not_poison_the_result(self):
        rng_trace = _correlated(500, 12.0, 2.0, seed=3) + 100.0
        rng_trace[50:55] = np.nan
        r = tr.analyze_trace(rng_trace)
        assert np.isfinite(r.sigma_w)
        assert r.sigma_w == pytest.approx(2.0, rel=0.2)

    def test_empty_trace_returns_nan_and_empty_arrays(self):
        r = tr.analyze_trace(np.array([]))
        assert np.isnan(r.sigma_w)
        assert np.isnan(r.hurst) and np.isnan(r.xi)
        lo, hi = r.sigma_ci
        assert np.isnan(lo) and np.isnan(hi)
        assert r.psd_wavelength.size == 0
        assert r.detrended.size == 0
        assert r.quality == 0.0


class TestAdaptiveTraceWindow:
    def test_thin_layer_trace_does_not_lock_onto_neighbor(self):
        """Item #8 regression: with a fixed +-10 px window both interfaces of
        an 8 px layer see each other's (stronger) gradient and the traces
        collapse together; the adaptive window must keep them apart."""
        img = _stack_image()
        res = analyze_layers(img, axis="y", waviness=True, sensitivity=0.2)
        # find the two interfaces bounding the thin layer
        pos = [i.position for i in res.interfaces]
        top = min(res.interfaces, key=lambda i: abs(i.position - 118))
        bot = min(res.interfaces, key=lambda i: abs(i.position - 126))
        assert abs(top.position - bot.position) > 4, pos
        assert top.trace is not None and bot.trace is not None
        # each trace must stay near its own interface, not migrate to the other
        assert abs(float(np.median(top.trace)) - top.position) < 3.0
        assert abs(float(np.median(bot.trace)) - bot.position) < 3.0

    def test_sigma_w_is_detrended_in_the_pipeline(self):
        """A tilted but smooth stack must not report the tilt as roughness."""
        n = 256
        img = np.full((n, n), 100.0)
        img[n // 2 :, :] = 200.0
        img = gaussian_filter1d(img, 2.0, axis=0)
        # shear: interface depth drifts 12 px across the FOV (a real tilt)
        sheared = np.empty_like(img)
        for c in range(n):
            sheared[:, c] = np.roll(img[:, c], int(round(12.0 * c / n)))
        rng = np.random.default_rng(12)
        sheared = sheared + rng.normal(0.0, 1.0, (n, n))
        res = analyze_layers(sheared, axis="y", waviness=True, n_layers=2)
        ifc = max(res.interfaces, key=lambda i: 0 if i.trace is None else 1)
        assert ifc.trace is not None
        # raw std of the trace sees the 12 px drift; sigma_w must not
        assert float(np.std(ifc.trace)) > 2.0
        assert ifc.sigma_w < 1.0
