"""Crystallography tests: synthetic Bragg oracles + golden comparisons."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.crystal import (
    PHASES,
    d_spacing,
    electron_wavelength,
    find_phase,
    plane_spacings,
)

pytestmark = pytest.mark.diffraction


def test_d_spacing_cubic() -> None:
    a = 5.4309                                       # Si
    assert d_spacing(a, 1, 1, 1) == pytest.approx(a / np.sqrt(3), rel=1e-12)
    assert d_spacing(a, 4, 0, 0) == pytest.approx(a / 4, rel=1e-12)


def test_d_spacing_hexagonal() -> None:
    # 1/d² = 4/3·(h²+hk+k²)/a² + l²/c²
    a, c = 3.1890, 5.1864                            # GaN
    expected = 1 / np.sqrt(4 / 3 * (1 + 1 + 1) / a**2 + 0)
    assert d_spacing(a, 1, 1, 0, c=c, gamma=120) == pytest.approx(expected, rel=1e-9)
    assert d_spacing(a, 0, 0, 2, c=c, gamma=120) == pytest.approx(c / 2, rel=1e-12)


def test_fcc_extinctions() -> None:
    a = 5.4309
    refl = plane_spacings(a, centering="F", max_hkl=3)
    # allowed families present (by d — representative hkl follows MATLAB's
    # sortrows tie-break, e.g. (0,0,2) represents the {200} family)
    assert np.isclose(refl.d, a / np.sqrt(3)).any()        # {111}
    assert np.isclose(refl.d, a / 2).any()                 # {200}
    # mixed-parity families absent
    assert not np.isclose(refl.d, a).any()                 # {100}
    assert not np.isclose(refl.d, a / np.sqrt(2)).any()    # {110}
    assert not np.isclose(refl.d, a / np.sqrt(5)).any()    # {210}


def test_r_centering_obverse_rule() -> None:
    sap = find_phase("Sapphire")
    refl = plane_spacings(sap.a, c=sap.c, gamma=120, centering="R", max_hkl=4)
    hkls = {tuple(h) for h in refl.hkl}
    assert (0, 0, 3) in hkls                          # −0+0+3 = 3 ✓
    assert not any(h[:2] == (0, 0) and h[2] in (1, 2) for h in hkls)
    # obverse (not reverse): (0,1,2) allowed (−0+1+2=3), (1,0,2) forbidden
    flat = [tuple(h) for h in refl.hkl]
    assert (0, 1, 2) in flat


def test_bcc_multiplicity_and_order() -> None:
    refl = plane_spacings(2.8665, centering="I", max_hkl=2)
    assert sorted(abs(v) for v in refl.hkl[0]) == [0, 1, 1]   # {110} first
    assert refl.multiplicity[0] == 12
    assert np.all(np.diff(refl.d) <= 1e-12)


def test_two_theta_bragg_consistency() -> None:
    refl = plane_spacings(4.0495, centering="F", max_hkl=2, lam=1.5406)
    d111 = 4.0495 / np.sqrt(3)
    expected = 2 * np.degrees(np.arcsin(1.5406 / (2 * d111)))
    assert refl.two_theta[0] == pytest.approx(expected, rel=1e-12)


def test_find_phase_contains_match() -> None:
    assert find_phase("silicon").formula == "Si"
    assert find_phase("SrTiO3").a == 3.9050
    with pytest.raises(KeyError):
        find_phase("unobtainium")


# ── golden ───────────────────────────────────────────────────────────

@pytest.mark.golden
class TestGolden:
    def test_wavelengths(self, golden) -> None:
        for e in golden("diffraction")["wavelengths"]:
            assert electron_wavelength(e["kV"]) == pytest.approx(
                e["lambda"], rel=1e-12
            ), e["kV"]

    def test_phase_database_names(self, golden) -> None:
        g = golden("diffraction")
        assert len(PHASES) == g["phaseCount"]
        assert [p.name for p in PHASES] == [e["name"] for e in g["phases"]]

    def test_silicon_d_spacings_match_simulation_golden(self, golden) -> None:
        # the simulated top-spot d-values must be reproducible from our
        # lattice math: every golden dSpacing is a Si reflection d
        g = golden("diffraction")["simulateSilicon001"]
        si = find_phase("Silicon")
        refl = plane_spacings(si.a, centering="F", max_hkl=6, min_d=0.5)
        spots = [s for s in g["topSpots"] if s.get("dSpacing")]  # skip direct beam
        assert spots
        for spot in spots:
            close = np.isclose(refl.d, spot["dSpacing"], rtol=1e-6).any()
            assert close, f"golden spot d={spot['dSpacing']} not in reflection list"
