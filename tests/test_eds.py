"""EDS quant tests: synthetic oracles + golden table/reference comparisons."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eds import (
    K_FACTORS_200KV,
    cliff_lorimer,
    line_energy,
    mass_absorption_coeff,
    zaf_correction,
)
from fermiviewer.calc.elements import atomic_mass

pytestmark = pytest.mark.eds


# ── synthetic oracles ────────────────────────────────────────────────

def test_cliff_lorimer_equal_split() -> None:
    ones = np.ones((4, 4))
    res = cliff_lorimer([ones, ones], ["Fe", "O"], k_factors=np.array([1.0, 1.0]))
    # equal k·I → 50/50 weight; atomic fractions follow w/M
    np.testing.assert_allclose(res.mean_weight_pct, [50, 50], rtol=1e-12)
    m_fe, m_o = atomic_mass("Fe"), atomic_mass("O")
    at_fe = (0.5 / m_fe) / (0.5 / m_fe + 0.5 / m_o) * 100
    np.testing.assert_allclose(res.mean_atomic_pct, [at_fe, 100 - at_fe], rtol=1e-12)
    assert res.mask.all()


def test_cliff_lorimer_mask_threshold() -> None:
    a = np.zeros((2, 2))
    a[0, 0] = 10
    res = cliff_lorimer([a, a], ["Fe", "O"], mask_threshold=1.0)
    assert res.mask.sum() == 1
    assert np.isnan(res.atomic_pct_maps[0][1, 1])


def test_line_energy_selection() -> None:
    e, used = line_energy("Fe")                      # beam ∞ → K wins
    assert (e, used) == (6.404, "K")
    e, used = line_energy("Pb")                      # no K in table → L
    assert (e, used) == (10.551, "L")
    e, used = line_energy("Fe", beam_kv=8.0)         # U_K = 8/(6.404/.9) ≈ 1.12 < 1.5
    assert used == "L"                               # → falls through to L
    e, used = line_energy("W", line="M")
    assert (e, used) == (1.775, "M")
    e, used = line_energy("H")                       # nowhere in any table
    assert np.isnan(e) and used == ""


def test_mac_formula() -> None:
    lam = (12.398 / 0.525) * 1e-8                    # O Kα
    expected = 1.0e22 * 26.0**4 * lam**3 / atomic_mass("Fe")
    assert mass_absorption_coeff("O", "Fe") == pytest.approx(expected, rel=1e-12)


def test_cliff_lorimer_clips_negative_counts() -> None:
    # MATLAB's cliffLorimer.m does NOT clip negative counts; this is a
    # deliberate, small divergence (see calc/eds.py docstring) that aligns
    # with calc.eds_zeta.zeta_quantify's existing clamp. A stray negative
    # count (e.g. a background-over-subtraction artifact upstream) must not
    # flip signs in the weight/atomic fractions.
    fe = np.array([[-5.0, 20.0]])
    o = np.array([[10.0, 20.0]])
    res = cliff_lorimer([fe, o], ["Fe", "O"], k_factors=np.array([1.0, 1.0]))
    assert res.weight_pct_maps[0][0, 0] == pytest.approx(0.0)
    assert res.weight_pct_maps[1][0, 0] == pytest.approx(100.0)
    assert res.mask[0, 0]                              # still a valid pixel


def test_zaf_reduces_to_cl_at_zero_absorption() -> None:
    ones = np.ones((3, 3))
    res = zaf_correction(
        [ones, ones], ["Fe", "Fe"], k_factors=np.array([1.0, 1.0]),
        thickness_nm=1e-6,                           # vanishing thickness
    )
    # identical element & no thickness → Z≈1, A≈1, result ≈ CL
    np.testing.assert_allclose(res.z_factors, 1.0, atol=1e-6)
    np.testing.assert_allclose(res.a_factors, 1.0, atol=1e-4)
    np.testing.assert_allclose(res.mean_weight_pct, res.uncorrected.mean_weight_pct,
                               rtol=1e-6)


# ── golden (vs frozen MATLAB outputs) ────────────────────────────────

@pytest.mark.golden
class TestGolden:
    def test_k_factor_table(self, golden) -> None:
        g = golden("eds_tables")["kFactorTable"]
        gold = {e["element"]: e["k"] for e in g}
        assert gold == K_FACTORS_200KV

    def test_line_energies(self, golden) -> None:
        for e in golden("eds_tables")["lineEnergies"]:
            kev, used = line_energy(e["symbol"])
            assert kev == pytest.approx(e["keV"], rel=1e-12), e["symbol"]
            assert used == e["line"], e["symbol"]

    def test_mass_absorption(self, golden) -> None:
        for e in golden("eds_tables")["massAbsorption"]:
            mac = mass_absorption_coeff(e["emitter"], e["absorber"])
            assert mac == pytest.approx(e["mu_rho"], rel=1e-12), e

    @staticmethod
    def _reference_maps() -> tuple[np.ndarray, np.ndarray]:
        # MATLAB ndgrid(0:7, 0:7): xg varies down rows, yg across cols
        xg = np.arange(8, dtype=np.float64)[:, None]
        yg = np.arange(8, dtype=np.float64)[None, :]
        return 100 + xg + 10 * yg, 50 + 2 * xg + yg

    def test_cliff_lorimer_reference(self, golden) -> None:
        g = golden("eds_tables")["cliffLorimer_FeO"]
        map_fe, map_o = self._reference_maps()
        res = cliff_lorimer([map_fe, map_o], ["Fe", "O"])
        np.testing.assert_allclose(res.mean_atomic_pct, g["meanAtomicPct"], rtol=1e-12)
        np.testing.assert_allclose(res.mean_weight_pct, g["meanWeightPct"], rtol=1e-12)
        np.testing.assert_allclose(res.k_factors, g["kFactors"], rtol=1e-12)
        np.testing.assert_allclose(
            res.atomic_pct_maps[0], np.array(g["atomicPctMaps"][0]), rtol=1e-12
        )
        np.testing.assert_allclose(
            res.weight_pct_maps[1], np.array(g["weightPctMaps"][1]), rtol=1e-12
        )

    def test_zaf_reference(self, golden) -> None:
        g = golden("eds_tables")["zaf_FeO"]
        map_fe, map_o = self._reference_maps()
        res = zaf_correction([map_fe, map_o], ["Fe", "O"])
        np.testing.assert_allclose(res.mean_atomic_pct, g["meanAtomicPct"], rtol=1e-9)
        np.testing.assert_allclose(res.mean_weight_pct, g["meanWeightPct"], rtol=1e-9)
        np.testing.assert_allclose(res.z_factors, g["zafFactors"]["Z"], rtol=1e-9)
        np.testing.assert_allclose(res.a_factors, g["zafFactors"]["A"], rtol=1e-9)
        np.testing.assert_allclose(
            res.atomic_pct_maps[0], np.array(g["atomicPctMaps"][0]), rtol=1e-9
        )
