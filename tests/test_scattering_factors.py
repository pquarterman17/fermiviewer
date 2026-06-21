"""Electron scattering factor + Debye--Waller validation.

Not a MATLAB golden: these assertions check the Doyle--Turner f_e(s)
against physics reference values (monotonicity, Z-ordering, published
kinematic intensity ratios) and confirm the Debye--Waller factor damps
high-s reflections. The legacy Z-proxy model is exercised side-by-side
to show it gets the ratios visibly wrong.

References for the intensity ratios:
  - Silicon electron diffraction relative intensities (I(111)=100):
    (111)=100, (220)~64, (311)~35. See e.g. M. De Graef & M. McHenry,
    "Structure of Materials" (2007), Si kinematic table; consistent with
    powder/electron-diffraction tabulations. The key qualitative fact:
    I(220) < I(111) because f_e(s) falls with s and the (220) reflection
    sits at higher s. The Z-proxy instead gives I(220)/I(111) = 2.0.
  - Gold (FCC) I(200) < I(111): with a real f_e(s) the higher-angle
    (200) is weaker than (111); the Z-proxy gives exactly 1.0 (the FCC
    structure factor is 4Z for every allowed reflection, s-independent).
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.crystal import d_spacing, find_phase
from fermiviewer.calc.elements import atomic_number
from fermiviewer.calc.scattering_factors import (
    debye_waller,
    default_debye_waller_B,
    electron_scattering_factor,
    has_scattering_factor,
    scattering_weight,
)

pytestmark = pytest.mark.diffraction


# ── f_e basic shape / physics ────────────────────────────────────────

def test_fe_monotonically_decreasing_in_s() -> None:
    s = np.linspace(0.0, 1.5, 30)
    for el in ("Si", "O", "Au", "Cu", "Ga", "As"):
        fe = electron_scattering_factor(el, s)
        assert np.all(np.diff(fe) < 0), f"{el}: f_e not strictly decreasing"
        assert np.all(fe > 0), f"{el}: f_e went non-positive"


def test_fe_scalar_returns_scalar_like() -> None:
    val = electron_scattering_factor("Si", 0.0)
    assert np.ndim(val) == 0
    # f_e(0) = sum of the a_i coefficients
    assert float(val) == pytest.approx(2.129 + 2.533 + 0.835 + 0.322, rel=1e-9)


def test_fe_heavier_scatters_more_at_s0() -> None:
    # Forward-scattering amplitude grows with Z (heavier atoms scatter
    # electrons more strongly). Not equal to Z, but ordered with it.
    order = ["O", "Si", "Ge", "Au"]
    f0 = [float(electron_scattering_factor(e, 0.0)) for e in order]
    assert f0 == sorted(f0), f"f_e(0) not Z-ordered: {dict(zip(order, f0, strict=True))}"
    # and the heaviest clearly dominates the lightest
    assert f0[-1] > 4 * f0[0]


def test_fe_not_equal_to_atomic_number() -> None:
    # The whole point: f_e(0) is NOT the atomic number.
    for el in ("Si", "Cu", "Au"):
        assert float(electron_scattering_factor(el, 0.0)) != float(atomic_number(el))


def test_fe_unknown_element_raises() -> None:
    with pytest.raises(KeyError, match="no Doyle-Turner"):
        electron_scattering_factor("Xx", 0.1)


def test_has_scattering_factor() -> None:
    assert has_scattering_factor("Si")
    assert has_scattering_factor("Au")
    assert not has_scattering_factor("Xx")


def test_covers_builtin_phase_elements() -> None:
    # Every element appearing in a built-in phase basis must be covered,
    # otherwise simulate(scattering_model="fe") would raise for that phase.
    from fermiviewer.calc.crystal import PHASES

    missing: set[str] = set()
    for p in PHASES:
        for sym, *_ in p.basis:
            if not has_scattering_factor(sym):
                missing.add(sym)
    assert not missing, f"phase-basis elements lack a Doyle-Turner fit: {missing}"


# ── kinematic intensity ratios (the Z-proxy gets these wrong) ─────────

def _structure_intensity(phase_name: str, hkl: tuple[int, int, int], model: str) -> float:
    p = find_phase(phase_name)
    h, k, l = hkl  # noqa: E741
    d = d_spacing(p.a, h, k, l, b=p.b, c=p.c,
                  alpha=p.alpha, beta=p.beta, gamma=p.gamma)
    s = 1.0 / (2.0 * d)
    f = 0j
    for sym, x, y, z in p.basis:
        ph = 2 * np.pi * (h * x + k * y + l * z)
        w = float(scattering_weight(sym, s, model))
        f += w * np.exp(1j * ph)
    return float((f * np.conj(f)).real)


def test_si_220_over_111_ratio() -> None:
    """Si I(220)/I(111): f_e gives ~0.66 (220 weaker, the textbook
    truth — De Graef & McHenry put it near 0.64); the Z-proxy gives the
    physically wrong 2.0 (220 twice as strong as 111)."""
    i111_fe = _structure_intensity("Silicon", (1, 1, 1), "fe")
    i220_fe = _structure_intensity("Silicon", (2, 2, 0), "fe")
    ratio_fe = i220_fe / i111_fe
    assert ratio_fe == pytest.approx(0.66, abs=0.08)   # 220 weaker than 111
    assert ratio_fe < 1.0

    i111_z = _structure_intensity("Silicon", (1, 1, 1), "z")
    i220_z = _structure_intensity("Silicon", (2, 2, 0), "z")
    ratio_z = i220_z / i111_z
    assert ratio_z == pytest.approx(2.0, rel=1e-6)     # Z-proxy: 220 stronger (wrong)
    assert ratio_z > 1.0


def test_au_200_over_111_ratio() -> None:
    """Au I(200)/I(111): f_e correctly puts (200) below (111) (higher s),
    while the Z-proxy gives exactly 1.0 — the FCC structure factor is 4Z
    for every allowed reflection, with no angular falloff."""
    i111_fe = _structure_intensity("Gold", (1, 1, 1), "fe")
    i200_fe = _structure_intensity("Gold", (2, 0, 0), "fe")
    ratio_fe = i200_fe / i111_fe
    assert ratio_fe < 1.0                              # 200 weaker than 111
    assert ratio_fe == pytest.approx(0.82, abs=0.06)

    i111_z = _structure_intensity("Gold", (1, 1, 1), "z")
    i200_z = _structure_intensity("Gold", (2, 0, 0), "z")
    assert i200_z / i111_z == pytest.approx(1.0, rel=1e-9)  # Z-proxy: flat (wrong)


def test_intensity_decreases_with_order_for_au() -> None:
    # With real f_e the FCC family intensities monotonically decrease with
    # scattering angle: 111 > 200 > 220 > 311. The Z-proxy makes them all
    # equal (flat), so this distinction only exists for "fe".
    fams = [(1, 1, 1), (2, 0, 0), (2, 2, 0), (3, 1, 1)]
    inten = [_structure_intensity("Gold", h, "fe") for h in fams]
    assert inten == sorted(inten, reverse=True)


# ── Debye--Waller factor ─────────────────────────────────────────────

def test_debye_waller_unity_at_s0() -> None:
    assert float(debye_waller(0.0, 0.5)) == pytest.approx(1.0)
    # B = 0 disables damping everywhere
    s = np.linspace(0, 1, 11)
    np.testing.assert_allclose(debye_waller(s, 0.0), np.ones_like(s))


def test_debye_waller_decreasing_in_s() -> None:
    s = np.linspace(0.0, 1.0, 25)
    dw = debye_waller(s, 0.6)
    assert np.all(np.diff(dw) < 0)
    assert np.all((dw > 0) & (dw <= 1.0))


def test_debye_waller_suppresses_high_s_more() -> None:
    """A high-s (small-d) reflection is damped much more than a low-s one."""
    b = 0.5
    s_low, s_high = 0.15, 0.45            # Si (111)-ish vs (400)-ish
    dw_low = float(debye_waller(s_low, b))
    dw_high = float(debye_waller(s_high, b))
    assert dw_high < dw_low
    # the *fractional* suppression is far larger at high s
    assert (1 - dw_high) > 3 * (1 - dw_low)


def test_debye_waller_array_b_per_atom() -> None:
    # scalar s, per-atom B array → one factor per atom
    s = 0.3
    b = np.array([0.2, 0.5, 1.0])
    dw = debye_waller(s, b)
    assert dw.shape == (3,)
    assert dw[0] > dw[1] > dw[2]          # larger B → stronger damping


def test_default_b_table_and_fallback() -> None:
    assert default_debye_waller_B("Si") == pytest.approx(0.46)
    assert default_debye_waller_B("Au") == pytest.approx(0.58)
    # un-tabulated element → generic fallback, not a crash
    assert default_debye_waller_B("Xx") == pytest.approx(0.50)


# ── scattering_weight dispatch ───────────────────────────────────────

def test_scattering_weight_z_is_atomic_number() -> None:
    assert float(scattering_weight("Si", 0.3, "z")) == float(atomic_number("Si"))
    # Z-proxy is s-independent
    assert float(scattering_weight("Si", 0.0, "z")) == float(
        scattering_weight("Si", 1.0, "z")
    )


def test_scattering_weight_fe_matches_factor() -> None:
    s = 0.25
    assert float(scattering_weight("Au", s, "fe")) == pytest.approx(
        float(electron_scattering_factor("Au", s))
    )


def test_scattering_weight_unknown_model_raises() -> None:
    with pytest.raises(ValueError, match="unknown scattering_model"):
        scattering_weight("Si", 0.1, "bogus")


# ── simulate integration: extinctions hold under BOTH models ──────────

@pytest.mark.parametrize("model", ["fe", "z"])
def test_simulate_diamond_extinctions_both_models(model: str) -> None:
    """Diamond (200)-type absent, (220)-type present under either model —
    extinctions are a phase-sum property, independent of the per-atom
    weight. Confirms wiring scattering_model in did not perturb them."""
    from fermiviewer.calc.diffraction import simulate

    sim = simulate("Silicon", zone_axis=(0, 0, 1), scattering_model=model)
    hkls = {s.hkl for s in sim.spots[1:]}
    assert (2, 2, 0) in hkls
    assert (2, 0, 0) not in hkls
    # all reflections lie in the [001] zone
    assert all(s.hkl[2] == 0 for s in sim.spots[1:])


def test_simulate_debye_waller_damps_high_order() -> None:
    """With Debye--Waller on, the high-order (440) reflection loses more
    relative intensity than the low-order (220) compared to no damping."""
    from fermiviewer.calc.diffraction import simulate

    def family_intensity(sim, fam_abs):
        vals = [s.intensity for s in sim.spots[1:]
                if sorted(map(abs, s.hkl)) == fam_abs]
        return max(vals) if vals else 0.0

    base = simulate("Silicon", zone_axis=(0, 0, 1), min_intensity=0.0,
                    scattering_model="fe")
    damped = simulate("Silicon", zone_axis=(0, 0, 1), min_intensity=0.0,
                      scattering_model="fe", debye_waller_B=0.5)

    # intensities are peak-normalised within each call; compare the ratio
    # of a high-order family to a low-order one, which must shrink under DW.
    lo_b = family_intensity(base, [0, 2, 2])     # (220)
    hi_b = family_intensity(base, [0, 4, 4])     # (440), higher s
    lo_d = family_intensity(damped, [0, 2, 2])
    hi_d = family_intensity(damped, [0, 4, 4])
    assert hi_b > 0 and lo_b > 0 and hi_d > 0 and lo_d > 0
    assert (hi_d / lo_d) < (hi_b / lo_b)
