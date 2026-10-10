"""ISO 25178-2 functional parameters (calc/afm_functional.py)."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.afm_functional import functional_parameters, material_ratio_curve


def test_uniform_heights_match_the_analytic_values() -> None:
    # Heights uniform on [0, 1]: the material ratio curve is the straight line
    # h = 1 − mr/100, so the core is everything (Sk = 1, no peaks or valleys)
    # and Vm(p) = p²/2, Vv(q) = (1 − q)²/2 with p, q as fractions.
    z = np.linspace(0.0, 1.0, 200 * 200).reshape(200, 200)
    f = functional_parameters(z)
    assert f.sk == pytest.approx(1.0, abs=0.01)
    assert f.spk == pytest.approx(0.0, abs=0.01) and f.svk == pytest.approx(0.0, abs=0.01)
    assert f.vmp == pytest.approx(0.1**2 / 2, rel=0.02)
    assert f.vmc == pytest.approx(0.8**2 / 2 - 0.1**2 / 2, rel=0.02)
    assert f.vvv == pytest.approx(0.2**2 / 2, rel=0.02)
    assert f.vvc == pytest.approx(0.9**2 / 2 - 0.2**2 / 2, rel=0.02)


def test_gaussian_core_and_symmetry() -> None:
    z = np.random.default_rng(0).normal(0.0, 1.0, (256, 256))
    f = functional_parameters(z)
    assert 2.3 < f.sk < 2.9                       # ~2.6σ for a Gaussian
    assert f.spk == pytest.approx(f.svk, rel=0.15)
    assert 0 < f.smr1 < 20 and 80 < f.smr2 < 100


def test_deep_valleys_raise_svk_not_spk() -> None:
    rng = np.random.default_rng(1)
    z = rng.normal(0.0, 0.1, (200, 200))
    z[rng.random(z.shape) < 0.05] -= 3.0          # a plateau with 5 % pits
    f = functional_parameters(z)
    assert f.svk > 5 * f.spk and f.vvv > f.vmp


def test_scale_and_offset() -> None:
    z = np.random.default_rng(2).normal(0.0, 1.0, (128, 128))
    a, b = functional_parameters(z), functional_parameters(3.0 * z + 7.0)
    for key in ("sk", "spk", "svk", "vmp", "vmc", "vvc", "vvv"):
        assert getattr(b, key) == pytest.approx(3.0 * getattr(a, key), rel=1e-6)
    assert b.smr1 == pytest.approx(a.smr1) and b.smr2 == pytest.approx(a.smr2)


def test_nan_pixels_are_ignored_and_too_few_refused() -> None:
    z = np.linspace(0.0, 1.0, 10000).reshape(100, 100)
    z[:10] = np.nan
    mr, h = material_ratio_curve(z)
    assert np.isfinite(h).all() and h[0] > h[-1]
    with pytest.raises(ValueError):
        functional_parameters(np.array([np.nan, 1.0]))


def test_equivalent_line_is_the_regression_not_the_secant() -> None:
    # a curve h(mr) = 1 − mr/100 + 0.05·sin(π·mr/40): the flattest 40 % window
    # holds one full bump, so its endpoint secant and its regression differ
    mr_true = np.linspace(0.0, 100.0, 200_000)
    h_true = 1 - mr_true / 100 + 0.05 * np.sin(np.pi * mr_true / 40)
    f = functional_parameters(h_true)
    mr, h = material_ratio_curve(h_true)
    w = int(round(40.0 / (mr[1] - mr[0])))
    i = int(np.argmin(h[:-w] - h[w:]))
    slope, hu = np.polyfit(mr[i:i + w + 1], h[i:i + w + 1], 1)
    secant_sk = -(h[i + w] - h[i]) / 40.0 * 100.0
    assert f.sk == pytest.approx(-slope * 100.0, rel=1e-9)
    assert abs(f.sk - secant_sk) > 0.01
