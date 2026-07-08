"""ζ-factor quantification tests: hand-checked values + forward-model
self-consistency (inject known composition/ρt, recover both)."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eds import K_FACTORS_200KV, mass_absorption_coeff
from fermiviewer.calc.eds_zeta import (
    detector_solid_angle_sr,
    dose_electrons,
    zeta_from_k_factors,
    zeta_quantify,
)

pytestmark = pytest.mark.eds


# ── dose / geometry helpers ──────────────────────────────────────────

def test_dose_electrons_hand_value() -> None:
    # 1 nA for 100 s → 1e-7 C / e = 6.2415e11 electrons
    assert dose_electrons(1.0, 100.0) == pytest.approx(6.2415091e11, rel=1e-6)


def test_dose_electrons_rejects_nonpositive() -> None:
    with pytest.raises(ValueError):
        dose_electrons(0.0, 10.0)
    with pytest.raises(ValueError):
        dose_electrons(1.0, -1.0)


def test_solid_angle_small_angle_formula() -> None:
    # 30 mm² at 20 mm → 0.075 sr (typical windowless SDD geometry)
    assert detector_solid_angle_sr(30.0, 20.0) == pytest.approx(0.075)
    with pytest.raises(ValueError):
        detector_solid_angle_sr(-1.0, 20.0)


def test_zeta_from_k_factors_scales_the_table() -> None:
    z = zeta_from_k_factors(["Si", "Fe", "Cu"], zeta_si=1000.0)
    assert z[0] == pytest.approx(1000.0)                        # k_Si = 1
    assert z[1] == pytest.approx(1000.0 * K_FACTORS_200KV["Fe"])
    assert z[2] == pytest.approx(1000.0 * K_FACTORS_200KV["Cu"])


# ── zeta_quantify: exact no-absorption arithmetic ────────────────────

def test_hand_checked_two_element_no_absorption() -> None:
    # Σζ·I = 500·2000 + 1000·1000 = 2e6 → w = (0.5, 0.5), ρt = 2e6/1e10
    r = zeta_quantify(
        [np.array([[2000.0]]), np.array([[1000.0]])],
        ["Fe", "O"], [500.0, 1000.0], dose=1e10, absorption=False,
    )
    np.testing.assert_allclose(r.mean_weight_pct, [50.0, 50.0], rtol=1e-12)
    assert r.mean_mass_thickness == pytest.approx(2.0e-4, rel=1e-12)
    assert np.all(r.absorption_factors == 1.0)
    # at%: w/M renormalised — Fe 55.845, O 15.999 → O-rich in atoms
    m_fe, m_o = 55.845, 15.999
    at_fe = (0.5 / m_fe) / (0.5 / m_fe + 0.5 / m_o) * 100
    assert r.mean_atomic_pct[0] == pytest.approx(at_fe, rel=1e-3)


def test_thickness_from_density() -> None:
    r = zeta_quantify(
        [np.array([[2000.0]]), np.array([[1000.0]])],
        ["Fe", "O"], [500.0, 1000.0], dose=1e10,
        absorption=False, density_g_cm3=5.0,
    )
    # t = ρt/ρ = 2e-4 kg/m² / 5000 kg/m³ = 4e-8 m = 40 nm
    assert r.mean_thickness_nm == pytest.approx(40.0, rel=1e-9)
    assert r.thickness_map_nm is not None
    assert r.thickness_map_nm[0, 0] == pytest.approx(40.0, rel=1e-9)


def test_composition_is_dose_independent_but_thickness_is_not() -> None:
    maps = [np.array([[3000.0]]), np.array([[1000.0]])]
    a = zeta_quantify(maps, ["Ni", "O"], [800.0, 1200.0], dose=1e10, absorption=False)
    b = zeta_quantify(maps, ["Ni", "O"], [800.0, 1200.0], dose=2e10, absorption=False)
    np.testing.assert_allclose(a.mean_weight_pct, b.mean_weight_pct, rtol=1e-12)
    assert a.mean_mass_thickness == pytest.approx(2 * b.mean_mass_thickness, rel=1e-12)


# ── forward-model self-consistency with absorption ───────────────────

def _forward_intensities(
    w_true: np.ndarray,
    rho_t: float,
    zeta: np.ndarray,
    dose: float,
    elements: list[str],
    take_off_deg: float,
) -> list[np.ndarray]:
    """I_meas = C·ρt·D/ζ · (1−exp(−χρt))/(χρt) — the model's own physics
    run forward, so the inversion must recover (w_true, ρt) exactly."""
    csc = 1.0 / np.sin(np.deg2rad(take_off_deg))
    n = len(elements)
    mac = np.empty((n, n))
    for i, em in enumerate(elements):
        for j, ab in enumerate(elements):
            mac[i, j] = mass_absorption_coeff(em, ab) * 0.1   # cm²/g → m²/kg
    chi = (mac @ w_true) * csc
    x = chi * rho_t
    f_abs = (1.0 - np.exp(-x)) / x        # thin-film absorption factor ≤ 1
    i_gen = w_true * rho_t * dose / zeta
    return [np.array([[v]]) for v in i_gen * f_abs]


def test_absorption_iteration_recovers_truth() -> None:
    # Fe/Ni K-lines keep χ·ρt in the thin-film regime under the repo's
    # calibrated Z⁴λ³ MAC model (sub-keV lines like O-Kα blow it up).
    elements = ["Fe", "Ni"]
    w_true = np.array([0.5, 0.5])
    rho_t = 2.0e-3                        # kg/m² (~225 nm at 8.9 g/cm³)
    zeta = np.array([900.0, 950.0])
    dose = 5.0e11
    maps = _forward_intensities(w_true, rho_t, zeta, dose, elements, 20.0)

    r = zeta_quantify(maps, elements, zeta, dose, take_off_angle_deg=20.0,
                      absorption=True, iterations=10)
    np.testing.assert_allclose(r.mean_weight_pct, w_true * 100, rtol=2e-3)
    assert r.mean_mass_thickness == pytest.approx(rho_t, rel=2e-3)
    # the softer Fe-Kα is absorbed harder → larger restoring factor
    assert r.absorption_factors[0] > r.absorption_factors[1] > 1.0


def test_ignoring_absorption_biases_the_softer_line() -> None:
    elements = ["Fe", "Ni"]
    w_true = np.array([0.5, 0.5])
    zeta = np.array([900.0, 950.0])
    maps = _forward_intensities(w_true, 2.0e-3, zeta, 5.0e11, elements, 20.0)
    r = zeta_quantify(maps, elements, zeta, 5.0e11, absorption=False)
    # Fe-Kα (6.4 keV) is absorbed harder than Ni-Kα (7.5 keV) →
    # uncorrected Fe reads low, and the whole ρt reads low too
    assert r.mean_weight_pct[0] < 50.0
    assert r.mean_mass_thickness < 2.0e-3


# ── map behaviour / validation ───────────────────────────────────────

def test_blank_pixels_are_masked_nan() -> None:
    fe = np.array([[2000.0, 0.0], [1000.0, 0.0]])
    o = np.array([[1000.0, 0.0], [500.0, 0.0]])
    r = zeta_quantify([fe, o], ["Fe", "O"], [500.0, 1000.0], dose=1e10,
                      absorption=False)
    assert not r.mask[0, 1] and not r.mask[1, 1]
    assert np.isnan(r.weight_pct_maps[0][0, 1])
    assert np.isnan(r.mass_thickness_map[1, 1])
    assert np.isfinite(r.mass_thickness_map[0, 0])


def test_zeta_from_k_factors_rejects_nonpositive_zeta_si() -> None:
    with pytest.raises(ValueError, match="zeta_si must be positive"):
        zeta_from_k_factors(["Fe"], 0.0)
    with pytest.raises(ValueError, match="zeta_si must be positive"):
        zeta_from_k_factors(["Fe"], -1.0)


def test_negative_counts_are_clamped() -> None:
    # a stray negative count (e.g. a background-subtraction artifact) must
    # clamp to 0, not flow through as a negative intensity (:246 np.clip).
    fe = np.array([[-100.0, 200.0]])
    o = np.array([[50.0, 100.0]])
    r = zeta_quantify([fe, o], ["Fe", "O"], [500.0, 1000.0], dose=1e10, absorption=False)
    assert r.weight_pct_maps[0][0, 0] == pytest.approx(0.0)
    assert r.weight_pct_maps[1][0, 0] == pytest.approx(100.0)
    assert r.mask[0, 0]


def test_fully_blank_map_is_all_nan() -> None:
    # every pixel below mask_threshold -> mean_rt (and mean at%/wt%) NaN
    # (:271), not a crash from meaning over an empty valid-pixel selection.
    fe = np.zeros((2, 2))
    o = np.zeros((2, 2))
    r = zeta_quantify([fe, o], ["Fe", "O"], [500.0, 1000.0], dose=1e10, absorption=False)
    assert not r.mask.any()
    assert np.isnan(r.mean_mass_thickness)
    assert np.all(np.isnan(r.mean_weight_pct))
    assert np.all(np.isnan(r.mean_atomic_pct))
    assert np.all(np.isnan(r.weight_pct_maps[0]))


def test_nan_intensity_pixel_is_auto_masked() -> None:
    # PINNED behaviour (no explicit NaN policy in eds_zeta.py): a NaN in the
    # intensity cube makes that pixel's summed intensity NaN, and
    # ``NaN > mask_threshold`` is False in numpy, so the pixel is EXCLUDED
    # from the mask automatically rather than poisoning the composition.
    fe = np.array([[np.nan, 200.0]])
    o = np.array([[50.0, 100.0]])
    r = zeta_quantify([fe, o], ["Fe", "O"], [500.0, 1000.0], dose=1e10, absorption=False)
    assert not r.mask[0, 0]
    assert r.mask[0, 1]
    assert np.isnan(r.weight_pct_maps[0][0, 0])
    assert np.isfinite(r.weight_pct_maps[0][0, 1])
    assert np.isnan(r.mass_thickness_map[0, 0])
    assert np.isfinite(r.mass_thickness_map[0, 1])


def test_input_validation() -> None:
    m = [np.array([[1.0]]), np.array([[1.0]])]
    with pytest.raises(ValueError):
        zeta_quantify(m, ["Fe"], [1.0, 2.0], dose=1e9)          # length mismatch
    with pytest.raises(ValueError):
        zeta_quantify(m, ["Fe", "O"], [1.0], dose=1e9)          # ζ length
    with pytest.raises(ValueError):
        zeta_quantify(m, ["Fe", "O"], [1.0, -2.0], dose=1e9)    # ζ sign
    with pytest.raises(ValueError):
        zeta_quantify(m, ["Fe", "O"], [1.0, 2.0], dose=0.0)     # dose
    with pytest.raises(ValueError):
        zeta_quantify(m, ["Fe", "O"], [1.0, 2.0], dose=1e9,
                      take_off_angle_deg=95.0)                  # take-off
    with pytest.raises(ValueError):
        zeta_quantify(m, ["Fe", "O"], [1.0, 2.0], dose=1e9,
                      density_g_cm3=-1.0)                       # density
