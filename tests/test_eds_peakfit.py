"""EDS peak-deconvolution tests: overlap separation with known ratios."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.special import voigt_profile

from fermiviewer.calc.eds import line_energy
from fermiviewer.calc.eds_calib import fano_sigma_kev
from fermiviewer.calc.eds_peakfit import element_peak_component, fit_peaks, quantify_peaks
from fermiviewer.calc.spectral_fit import linear_background

pytestmark = pytest.mark.eds

_SQRT_2PI = np.sqrt(2.0 * np.pi)


def _axis() -> np.ndarray:
    return np.linspace(0.0, 20.0, 4001)  # 5 eV/channel


def _gauss(energy: np.ndarray, area: float, center: float) -> np.ndarray:
    sigma = fano_sigma_kev(center)
    amp = area / (sigma * _SQRT_2PI)
    return amp * np.exp(-0.5 * ((energy - center) / sigma) ** 2)


def _voigt(energy: np.ndarray, area: float, center: float, gamma: float) -> np.ndarray:
    """Synthesize a Voigt-shaped peak of known net AREA (not amp)."""
    sigma = fano_sigma_kev(center)
    norm = voigt_profile(0.0, sigma, gamma)
    amp = area * norm  # so that amp / norm (voigt_area's inverse) == area
    return amp * voigt_profile(energy - center, sigma, gamma) / norm


def test_single_peak_net_area_recovered() -> None:
    e = _axis()
    counts = _gauss(e, area=5000.0, center=6.404)  # Fe Kα
    pf = fit_peaks(e, counts, ["Fe"], weights=None)
    assert pf.net_areas["Fe"] == pytest.approx(5000.0, rel=1e-3)


def test_two_well_separated_peaks() -> None:
    e = _axis()
    counts = _gauss(e, 4000.0, 6.404) + _gauss(e, 6000.0, 8.048)  # Fe, Cu
    pf = fit_peaks(e, counts, ["Fe", "Cu"], weights=None)
    assert pf.net_areas["Fe"] == pytest.approx(4000.0, rel=2e-3)
    assert pf.net_areas["Cu"] == pytest.approx(6000.0, rel=2e-3)


def test_overlapping_triplet_s_mo_pb() -> None:
    # S-Kα 2.307, Mo-Lα 2.293, Pb-Mα 2.342 — the classic ~50 eV overlap
    e = _axis()
    e_s, _ = line_energy("S", beam_kv=200.0)
    e_mo, _ = line_energy("Mo", beam_kv=200.0)
    e_pb, _ = line_energy("Pb", beam_kv=200.0)
    areas = {"S": 3000.0, "Mo": 5000.0, "Pb": 2000.0}
    counts = (
        _gauss(e, areas["S"], e_s)
        + _gauss(e, areas["Mo"], e_mo)
        + _gauss(e, areas["Pb"], e_pb)
    )
    pf = fit_peaks(e, counts, ["S", "Mo", "Pb"], weights=None)
    # constrained fixed-position fit separates the blended triplet
    for sym, area in areas.items():
        assert pf.net_areas[sym] == pytest.approx(area, rel=0.05)


def test_joint_fit_with_linear_background() -> None:
    e = _axis()
    counts = 50.0 + 2.0 * e + _gauss(e, 4000.0, 6.404)
    bg = linear_background("bg", intercept=40.0, slope=1.0)
    pf = fit_peaks(e, counts, ["Fe"], background=bg, weights=None)
    assert pf.net_areas["Fe"] == pytest.approx(4000.0, rel=5e-3)


def test_net_area_error_is_finite_and_positive() -> None:
    rng = np.random.default_rng(0)
    e = _axis()
    clean = _gauss(e, 8000.0, 6.404)
    counts = clean + rng.normal(0.0, 5.0, size=e.shape)
    pf = fit_peaks(e, counts, ["Fe"], weights=None)
    assert np.isfinite(pf.net_area_errors["Fe"]) and pf.net_area_errors["Fe"] > 0.0


def test_quantify_peaks_equal_areas_to_composition() -> None:
    e = _axis()
    # equal net areas with k=1 → 50/50 weight; matches the cliff_lorimer oracle
    counts = _gauss(e, 5000.0, line_energy("Fe", beam_kv=200.0)[0]) + _gauss(
        e, 5000.0, line_energy("O", beam_kv=200.0)[0]
    )
    pf, cl = quantify_peaks(e, counts, ["Fe", "O"], k_factors=np.array([1.0, 1.0]), weights=None)
    np.testing.assert_allclose(cl.mean_weight_pct, [50, 50], rtol=2e-2)


def test_unknown_line_warns_and_nans() -> None:
    e = _axis()
    counts = _gauss(e, 3000.0, 6.404)
    with pytest.warns(UserWarning, match="no characteristic line"):
        pf = fit_peaks(e, counts, ["Fe", "Xx"], weights=None)
    assert np.isnan(pf.net_areas["Xx"])
    assert pf.net_areas["Fe"] == pytest.approx(3000.0, rel=1e-2)


def test_center_tolerance_absorbs_small_shift() -> None:
    e = _axis()
    center = line_energy("Cu", beam_kv=200.0)[0]
    counts = _gauss(e, 5000.0, center + 0.03)  # 30 eV miscalibration
    pf = fit_peaks(e, counts, ["Cu"], center_tol_kev=0.05, weights=None)
    assert pf.net_areas["Cu"] == pytest.approx(5000.0, rel=1e-2)


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="equal length"):
        fit_peaks(np.arange(5.0), np.arange(4.0), ["Fe"])


def test_empty_elements_raises() -> None:
    e = _axis()
    with pytest.raises(ValueError, match="at least one element"):
        fit_peaks(e, np.zeros_like(e), [])


def test_all_unknown_lines_raises() -> None:
    e = _axis()
    counts = np.ones_like(e)
    with pytest.warns(UserWarning, match="no characteristic line"):
        with pytest.raises(ValueError, match="no fittable element lines"):
            fit_peaks(e, counts, ["Xx", "Yy"], weights=None)


# ── opt-in Voigt path (lorentzian_hwhm_kev) ─────────────────────────────


def test_lorentzian_hwhm_zero_is_byte_identical_to_omitted() -> None:
    # The default (0.0) must be EXACTLY the original Gaussian-only path —
    # not just close. Compare the component curve directly, not just the
    # fitted result, so a stray branch difference can't hide behind the
    # optimizer converging to the same place.
    center, sigma, amp0 = 6.404, fano_sigma_kev(6.404), 123.0
    default = element_peak_component("Fe", center, sigma, amp0)
    explicit_zero = element_peak_component(
        "Fe", center, sigma, amp0, lorentzian_hwhm_kev=0.0
    )
    e = _axis()
    np.testing.assert_array_equal(
        default.func(e, np.array([amp0])), explicit_zero.func(e, np.array([amp0]))
    )

    e = _axis()
    counts = _gauss(e, 5000.0, 6.404)
    pf_default = fit_peaks(e, counts, ["Fe"], weights=None)
    pf_explicit = fit_peaks(e, counts, ["Fe"], weights=None, lorentzian_hwhm_kev=0.0)
    assert pf_default.net_areas["Fe"] == pf_explicit.net_areas["Fe"]
    assert pf_default.net_area_errors["Fe"] == pf_explicit.net_area_errors["Fe"]
    # and pinned against the pre-existing Gaussian-path expectation
    assert pf_default.net_areas["Fe"] == pytest.approx(5000.0, rel=1e-3)


def test_voigt_path_recovers_single_peak_net_area() -> None:
    e = _axis()
    gamma = 0.002  # a realistic natural-linewidth HWHM, keV
    counts = _voigt(e, area=5000.0, center=6.404, gamma=gamma)
    pf = fit_peaks(e, counts, ["Fe"], weights=None, lorentzian_hwhm_kev=gamma)
    assert pf.net_areas["Fe"] == pytest.approx(5000.0, rel=1e-3)


def test_voigt_path_separates_overlapping_two_element_synthetic() -> None:
    # S-K / Mo-L: the classic ~14 eV overlap that window integration
    # mis-assigns (only appears at lower beam energy — at 200 kV Mo picks
    # its K line instead, ~17 keV away).
    e = _axis()
    beam_kv = 15.0
    gamma = 0.002
    e_s, fam_s = line_energy("S", beam_kv=beam_kv)
    e_mo, fam_mo = line_energy("Mo", beam_kv=beam_kv)
    assert fam_s == "K" and fam_mo == "L"  # sanity: this IS the overlap case
    areas = {"S": 3000.0, "Mo": 5000.0}
    counts = _voigt(e, areas["S"], e_s, gamma) + _voigt(e, areas["Mo"], e_mo, gamma)
    pf = fit_peaks(
        e, counts, ["S", "Mo"], beam_kv=beam_kv, weights=None,
        lorentzian_hwhm_kev=gamma,
    )
    assert pf.fit.success
    for sym, area in areas.items():
        assert pf.net_areas[sym] == pytest.approx(area, rel=0.05)

    # quantify_peaks forwards the kwarg through and yields a sensible
    # (nonzero, ordered) composition for the deconvolved areas.
    pf2, cl = quantify_peaks(
        e, counts, ["S", "Mo"], beam_kv=beam_kv, weights=None,
        lorentzian_hwhm_kev=gamma, k_factors=np.array([1.0, 1.0]),
    )
    assert cl.mean_weight_pct[1] > cl.mean_weight_pct[0]  # Mo (5000) > S (3000)
    assert np.isclose(np.sum(cl.mean_weight_pct), 100.0)
