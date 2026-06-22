"""EDS bremsstrahlung continuum tests: synthetic continuum + peak masking."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eds_calib import fano_sigma_kev
from fermiviewer.calc.eds_continuum import (
    bremsstrahlung_component,
    fit_continuum,
    kramers_continuum,
    subtract_continuum,
)

pytestmark = pytest.mark.eds


def _axis() -> np.ndarray:
    return np.linspace(0.1, 20.0, 1991)  # 0.1..20 keV, ~10 eV/channel


def test_kramers_shape_zero_above_e0() -> None:
    e = _axis()
    cont = kramers_continuum(e, e0_kev=15.0, amp=100.0)
    assert np.all(cont[e >= 15.0] == 0.0)
    assert np.all(cont[(e > 0.1) & (e < 15.0)] > 0.0)


def test_kramers_diverges_low_e_without_absorption() -> None:
    e = np.array([0.5, 1.0, 5.0])
    cont = kramers_continuum(e, e0_kev=20.0, amp=1.0)
    # (E0-E)/E is monotonically decreasing in E ⇒ low-E is largest
    assert cont[0] > cont[1] > cont[2]


def test_absorption_suppresses_low_energy() -> None:
    e = _axis()
    bare = kramers_continuum(e, 20.0, amp=1.0, absorption=0.0)
    shaped = kramers_continuum(e, 20.0, amp=1.0, absorption=2.0)
    lo = e < 2.0
    assert np.all(shaped[lo] <= bare[lo] + 1e-12)
    assert shaped[lo].sum() < bare[lo].sum()


def test_fit_recovers_known_amplitude() -> None:
    e = _axis()
    truth = kramers_continuum(e, e0_kev=18.0, amp=500.0, absorption=0.0)
    fit = fit_continuum(e, truth, e0_kev=18.0, fit_absorption=False, weights=None)
    assert fit.amp == pytest.approx(500.0, rel=1e-3)
    np.testing.assert_allclose(fit.continuum, truth, rtol=1e-3, atol=1e-6)


def test_fit_recovers_amplitude_under_peaks() -> None:
    # continuum + two characteristic peaks; masking should still recover amp
    e = _axis()
    cont_true = kramers_continuum(e, e0_kev=18.0, amp=400.0, absorption=0.0)
    counts = cont_true.copy()
    for center, amp in ((6.404, 8000.0), (8.048, 6000.0)):  # Fe, Cu Kα
        sigma = fano_sigma_kev(center)
        counts = counts + amp * np.exp(-0.5 * ((e - center) / sigma) ** 2)
    fit = fit_continuum(
        e, counts, e0_kev=18.0,
        exclude_lines=["Fe", "Cu"], fit_absorption=False, weights=None,
    )
    # without masking the peaks would inflate amp badly; with it we recover ~400
    assert fit.amp == pytest.approx(400.0, rel=0.05)
    # the masked channels under the peaks are excluded from the keep-mask
    assert not fit.keep_mask[np.argmin(np.abs(e - 6.404))]


def test_exclude_windows_mask_channels() -> None:
    e = _axis()
    counts = kramers_continuum(e, 18.0, amp=300.0)
    fit = fit_continuum(
        e, counts, e0_kev=18.0, exclude_windows=[(6.0, 7.0)], weights=None,
    )
    assert not fit.keep_mask[(e >= 6.0) & (e <= 7.0)].any()


def test_subtract_continuum_clips_to_nonnegative() -> None:
    e = _axis()
    counts = kramers_continuum(e, 18.0, amp=200.0)
    net, fit = subtract_continuum(e, counts, e0_kev=18.0, fit_absorption=False, weights=None)
    assert np.all(net >= 0.0)
    # subtracting the (well-fit) continuum from itself leaves ~zero
    assert float(np.abs(net).max()) < 1.0


def test_component_param_count_toggles_with_fit_absorption() -> None:
    two = bremsstrahlung_component(15.0, fit_absorption=True)
    one = bremsstrahlung_component(15.0, fit_absorption=False)
    assert two.param_names == ("amp", "absorption")
    assert one.param_names == ("amp",)


def test_fit_too_few_channels_raises() -> None:
    e = _axis()
    counts = kramers_continuum(e, 18.0, amp=100.0)
    with pytest.raises(ValueError, match="2 channels"):
        fit_continuum(e, counts, e0_kev=18.0, exclude_windows=[(0.0, 25.0)], weights=None)


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="equal length"):
        fit_continuum(np.arange(5.0), np.arange(4.0), e0_kev=15.0)
