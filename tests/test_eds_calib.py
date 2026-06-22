"""EDS detector-calibration tests: Fano FWHM model + energy recalibration."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eds_calib import (
    MN_KA_FWHM_EV,
    MN_KA_KEV,
    fano_fwhm,
    fano_sigma_kev,
    recalibrate,
)

pytestmark = pytest.mark.eds


# ── Fano FWHM model ──────────────────────────────────────────────────

def test_fano_fwhm_anchors_at_mn_ka() -> None:
    # by construction the curve passes through the Mn-Kα spec point
    assert fano_fwhm(MN_KA_KEV) == pytest.approx(MN_KA_FWHM_EV, abs=1e-9)


def test_fano_fwhm_monotonic_increasing() -> None:
    e = np.array([0.277, 1.487, 5.899, 8.048, 17.479])  # C, Al, Mn, Cu, Mo Kα
    fwhm = fano_fwhm(e)
    assert np.all(np.diff(fwhm) > 0)


def test_fano_fwhm_cu_ka_in_physical_range() -> None:
    # real SDDs sit ~145–152 eV at Cu-Kα when spec'd 130 eV at Mn
    assert 145.0 < float(fano_fwhm(8.048)) < 155.0


def test_fano_fwhm_low_energy_stays_real() -> None:
    # far below the anchor the noise term cannot drive the variance negative
    val = float(fano_fwhm(0.1))
    assert np.isfinite(val) and val >= 0.0


def test_fano_fwhm_scalar_vs_array_shape() -> None:
    assert np.isscalar(fano_fwhm(5.899))
    out = fano_fwhm(np.array([1.0, 2.0, 3.0]))
    assert isinstance(out, np.ndarray) and out.shape == (3,)


def test_fano_sigma_kev_matches_fwhm() -> None:
    # σ_keV = FWHM_eV / 2.3548 / 1000
    factor = 2.0 * np.sqrt(2.0 * np.log(2.0))
    sigma = fano_sigma_kev(8.048)
    assert sigma == pytest.approx(float(fano_fwhm(8.048)) / factor / 1000.0, rel=1e-12)


def test_fano_fwhm_fano_factor_widens() -> None:
    # away from the anchor, a larger Fano factor broadens the line
    narrow = float(fano_fwhm(12.0, fano=0.10))
    wide = float(fano_fwhm(12.0, fano=0.16))
    assert wide > narrow


# ── energy recalibration ─────────────────────────────────────────────

def _spectrum() -> tuple[np.ndarray, np.ndarray]:
    energy = np.linspace(0.0, 10.0, 2001)  # 5 eV/channel
    return energy, np.zeros_like(energy)


def _add_peak(counts: np.ndarray, energy: np.ndarray, center: float, sigma: float = 0.05) -> None:
    counts += np.exp(-0.5 * ((energy - center) / sigma) ** 2)


def test_recalibrate_two_point_recovers_linear_shift() -> None:
    energy, counts = _spectrum()
    # true lines Mn-Kα 5.899, Cu-Kα 8.048 appear shifted by E_obs = 0.98·E + 0.10
    gain_true, off_true = 0.98, 0.10
    for true in (5.899, 8.048):
        _add_peak(counts, energy, gain_true * true + off_true)
    res = recalibrate(energy, counts, [5.899, 8.048], search_kev=0.2)
    # inverse of the distortion: E' = (E - off)/gain ⇒ gain≈1/0.98, off≈-0.10/0.98
    assert res.gain == pytest.approx(1.0 / gain_true, rel=2e-3)
    assert res.offset == pytest.approx(-off_true / gain_true, rel=2e-2)
    # corrected positions land on the true energies
    corrected_mn = res.gain * (gain_true * 5.899 + off_true) + res.offset
    assert corrected_mn == pytest.approx(5.899, abs=2e-3)


def test_recalibrate_explicit_pairs() -> None:
    energy, counts = _spectrum()
    res = recalibrate(energy, counts, [(5.80, 5.899), (7.95, 8.048)])
    assert res.gain == pytest.approx((8.048 - 5.899) / (7.95 - 5.80), rel=1e-9)
    assert len(res.anchors) == 2


def test_recalibrate_single_anchor_is_offset_only() -> None:
    energy, counts = _spectrum()
    _add_peak(counts, energy, 5.80)  # observed Mn slightly low
    res = recalibrate(energy, counts, [5.899], search_kev=0.2)
    assert res.gain == pytest.approx(1.0, abs=1e-12)
    assert res.offset == pytest.approx(0.099, abs=5e-3)


def test_recalibrate_no_anchors_is_identity() -> None:
    energy, counts = _spectrum()
    res = recalibrate(energy, counts, [])
    assert res.gain == 1.0 and res.offset == 0.0
    np.testing.assert_array_equal(res.corrected_energy, energy)


def test_recalibrate_empty_window_falls_back_to_target() -> None:
    energy, counts = _spectrum()  # all zeros → no peak to find
    res = recalibrate(energy, counts, [5.899], search_kev=0.2)
    # observed falls back to the target ⇒ zero shift
    assert res.offset == pytest.approx(0.0, abs=1e-12)


def test_recalibrate_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="equal length"):
        recalibrate(np.arange(5.0), np.arange(4.0), [5.899])
