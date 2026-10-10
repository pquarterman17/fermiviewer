"""Force-curve analysis (calc/afm_force.py) on synthetic curves with
known contact mechanics."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import brentq

from fermiviewer.calc.afm_force import Tip, analyze_curve, contact_force, find_contact


def _indent(z: np.ndarray, zc: float, e_r: float, k: float, tip: Tip) -> np.ndarray:
    """Deflection (nm) balancing the cantilever against the contact model."""
    d = np.zeros_like(z)
    for i, zi in enumerate(z):
        if zi <= zc:
            continue
        travel = zi - zc
        d[i] = brentq(lambda x, t=travel: k * x - contact_force(np.array([t - x]), e_r, tip)[0],
                      0.0, travel)
    return d


def _curve(tip: Tip, e_r: float = 0.002, k: float = 0.1, zc: float = 300.0,
           noise: float = 0.0, tilt: float = 0.0, adhesion: float = 0.0, seed: int = 0):
    z = np.linspace(0.0, 400.0, 2000)
    d = _indent(z, zc, e_r, k, tip)
    rng = np.random.default_rng(seed)
    off = 5.0 + tilt * z
    d_app = d + off + rng.normal(0, noise, z.size)
    zr = z[::-1]
    d_ret = _indent(zr, zc, e_r, k, tip)
    # a pull-off well just after leaving contact
    well = -adhesion / k * np.exp(-((zr - (zc - 5.0)) / 3.0) ** 2)
    d_ret = d_ret + well + 5.0 + tilt * zr + rng.normal(0, noise, z.size)
    return z, d_app, zr, d_ret


@pytest.mark.parametrize("tip", [Tip("sphere", radius_nm=20), Tip("cone", half_angle_deg=20),
                                 Tip("pyramid", half_angle_deg=35), Tip("flat", radius_nm=50)])
def test_modulus_and_contact_are_recovered(tip: Tip) -> None:
    z, da, zr, dr = _curve(tip, noise=0.02, tilt=0.002)
    r = analyze_curve(z, da, zr, dr, k=0.1, tip=tip, poisson=0.5)
    assert r.e_r == pytest.approx(0.002, rel=0.05)
    assert r.youngs_modulus == pytest.approx(0.002 * 0.75 * 1e9, rel=0.05)
    assert r.contact_z == pytest.approx(300.0, abs=2.0)
    assert r.fit_r2 > 0.99 and r.baseline[0] == pytest.approx(0.002, abs=2e-4)


def test_fit_window_limits_the_indentation() -> None:
    tip = Tip("sphere", radius_nm=20)
    z, da, zr, dr = _curve(tip)
    full = analyze_curve(z, da, zr, dr, k=0.1, tip=tip)
    part = analyze_curve(z, da, zr, dr, k=0.1, tip=tip, max_indent=20.0)
    assert part.fit_points < full.fit_points
    assert part.e_r == pytest.approx(0.002, rel=0.02)


def test_adhesion_and_work() -> None:
    tip = Tip("sphere", radius_nm=20)
    z, da, zr, dr = _curve(tip, adhesion=2.0)
    r = analyze_curve(z, da, zr, dr, k=0.1, tip=tip)
    assert r.adhesion == pytest.approx(2.0, rel=0.05)
    # a Gaussian well of depth 2 nN and width 3 nm: area √π·3·2 ≈ 10.6 aJ
    assert r.adhesion_energy == pytest.approx(np.sqrt(np.pi) * 3 * 2, rel=0.15)
    no_ret = analyze_curve(z, da, None, None, k=0.1, tip=tip)
    assert np.isnan(no_ret.adhesion)


def test_contact_slope_is_one_on_a_rigid_sample() -> None:
    z = np.linspace(0, 100, 500)
    d = np.clip(z - 80, 0, None)                 # no indentation: d follows Z
    r = analyze_curve(z, d, None, None, k=40.0, tip=Tip(), fit=False)
    assert r.contact_slope == pytest.approx(1.0, rel=1e-3)
    assert r.contact_z == pytest.approx(80.0, abs=0.3)
    assert r.max_indentation == pytest.approx(0.0, abs=0.3)


def test_find_contact_interpolates_the_crossing() -> None:
    z = np.arange(10.0)
    d = np.array([0, -1, 0.5, -0.5, -1, 1, 3, 5, 7, 9], dtype=float)
    assert find_contact(z, d) == pytest.approx(4.5)


def test_bad_inputs() -> None:
    z = np.linspace(0, 1, 50)
    with pytest.raises(ValueError):
        analyze_curve(z, z, None, None, k=0.0, tip=Tip())
    with pytest.raises(ValueError):
        analyze_curve(z[:2], z[:2], None, None, k=1.0, tip=Tip())


def test_batch_parallel_matches_serial_and_marks_failures() -> None:
    from fermiviewer.calc.afm_force_batch import analyze_curves

    tip = Tip("sphere", radius_nm=20)
    good = [_curve(tip, zc=280.0 + 5 * i, noise=0.02, seed=i) for i in range(6)]
    bad = (np.linspace(0, 1, 2), np.zeros(2), None, None)     # too short to analyse
    curves = [*good[:3], bad, *good[3:]]
    serial = analyze_curves(curves, parallel=False, k=0.1, tip=tip)
    parallel = analyze_curves(curves, parallel=True, k=0.1, tip=tip)
    assert serial[3] is None and parallel[3] is None
    for a, b in zip(serial, parallel, strict=True):
        if a is not None:
            assert b is not None and a.youngs_modulus == b.youngs_modulus
            assert a.contact_z == b.contact_z
    assert [round(r.contact_z) for r in serial if r] == [280, 285, 290, 295, 300, 305]
