"""EELS quantification tests (cross-section, at%, ELNES) — synthetic oracles."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eels_quant import ElementEdge, cross_section, elnes, quantify

pytestmark = pytest.mark.eels


def test_cross_section_physical_behaviour() -> None:
    s_c = cross_section(6, "K", 200, 10, 50, 284)     # C-K
    s_o = cross_section(8, "K", 200, 10, 50, 532)     # O-K
    assert s_c > 0 and s_o > 0
    assert s_c > s_o                                   # higher onset → smaller σ
    # wider integration window collects more signal
    assert cross_section(8, "K", 200, 10, 100, 532) > s_o
    # L-shell at same onset differs from K (occupancy + falloff).
    # NB: compare as a ratio — pytest.approx's default ABSOLUTE tolerance
    # (1e-12) dwarfs cross-sections of order 1e-26 m².
    ratio = cross_section(26, "L", 200, 10, 50, 708) / cross_section(
        26, "K", 200, 10, 50, 708
    )
    assert ratio != pytest.approx(1.0, rel=1e-6)
    with pytest.raises(ValueError, match="shell"):
        cross_section(8, "M", 200, 10, 50, 532)


def test_quantify_closure_two_elements() -> None:
    # synthetic: power-law bg + two rectangular edges of known area
    e = np.linspace(200, 800, 2400)
    bg = 1e6 * e**-2.2
    edge1 = np.where((e > 290) & (e < 340), 200.0, 0.0)   # "C-K"-like
    edge2 = np.where((e > 540) & (e < 590), 80.0, 0.0)    # "O-K"-like
    spec = bg + edge1 + edge2

    els = [
        ElementEdge("C", "K", 6, 284, (290, 340), (220, 280)),
        ElementEdge("O", "K", 8, 532, (540, 590), (460, 525)),
    ]
    res = quantify(e, spec, els, e0_kv=200, beta_mrad=10)
    assert res.atomic_percent.sum() == pytest.approx(100, rel=1e-12)

    # closure: at% must equal the (I/σ) normalisation computed manually
    manual = res.intensity / res.sigma
    manual = 100 * manual / manual.sum()
    np.testing.assert_allclose(res.atomic_percent, manual, rtol=1e-12)
    # background-subtracted intensities recover the injected edge areas
    assert res.intensity[0] == pytest.approx(200 * 50, rel=0.05)
    assert res.intensity[1] == pytest.approx(80 * 50, rel=0.05)


def test_elnes_normalisation_and_window() -> None:
    e = np.linspace(450, 650, 800)
    bg = 5e5 * e**-2.0
    onset = 532.0
    fine = np.where(e >= onset, 100 * (1 + 0.5 * np.sin((e - onset) / 4)), 0.0)
    res = elnes(e, bg + fine, edge_onset=onset, fit_window=(460, 525))
    assert res.relative_energy[0] >= 0
    assert res.relative_energy[-1] <= 30
    # normalised: mean over the first 5 eV is the jump reference ≈ 1
    first5 = res.intensity[res.relative_energy <= 5]
    assert first5.mean() == pytest.approx(1.0, rel=1e-9)

    with pytest.raises(ValueError, match="below edge_onset"):
        elnes(e, bg, edge_onset=500, fit_window=(460, 525))


# ── quantify_map (port of eelsQuantifyMap.m, upstream PR #25) ────────

def _edges_co():
    from fermiviewer.calc.eels_quant import ElementEdge

    return [
        ElementEdge("C", "K", 6, 284, (284, 384), (230, 280)),
        ElementEdge("O", "K", 8, 532, (532, 632), (470, 525)),
    ]


def _spectrum(energy, c_amp, o_amp):
    bg = 5e5 * energy**-2.2
    return (bg
            + np.where(energy >= 284, c_amp, 0.0)
            + np.where(energy >= 532, o_amp, 0.0))


def test_quantify_map_uniform_cube_matches_scalar() -> None:
    """The MATLAB oracle: a cube whose pixels all hold the same
    spectrum reproduces eelsQuantify on that spectrum to round-off."""
    from fermiviewer.calc.eels_quant import quantify, quantify_map

    energy = np.linspace(200, 700, 600)
    spec = _spectrum(energy, 40.0, 25.0)
    cube = np.broadcast_to(spec, (4, 5, energy.size)).copy()

    scalar = quantify(energy, spec, _edges_co(), 200, 10)
    maps = quantify_map(cube, energy, _edges_co(), 200, 10)

    assert maps.elements == scalar.elements
    np.testing.assert_allclose(maps.sigma, scalar.sigma, rtol=1e-12)
    for k in range(2):
        np.testing.assert_allclose(
            maps.atomic_percent[:, :, k], scalar.atomic_percent[k],
            rtol=1e-9)
        np.testing.assert_allclose(
            maps.intensity[:, :, k], scalar.intensity[k], rtol=1e-9)
    # per-pixel at% sums to 100 where there is signal
    np.testing.assert_allclose(
        maps.atomic_percent.sum(axis=2), 100.0, rtol=1e-9)


def test_quantify_map_two_region_gradient() -> None:
    """Left half carbon-rich, right half oxygen-rich → the maps
    separate the regions (the MATLAB two-region case)."""
    from fermiviewer.calc.eels_quant import quantify_map

    energy = np.linspace(200, 700, 600)
    cube = np.empty((3, 6, energy.size))
    cube[:, :3, :] = _spectrum(energy, 60.0, 5.0)   # C-rich left
    cube[:, 3:, :] = _spectrum(energy, 5.0, 60.0)   # O-rich right

    res = quantify_map(cube, energy, _edges_co(), 200, 10)
    c_map = res.atomic_percent[:, :, 0]
    assert c_map[:, :3].mean() > 60
    assert c_map[:, 3:].mean() < 40
    # spatial ordering preserved (no transpose slip in the reshape)
    assert c_map[0, 0] > c_map[0, 5]


def test_quantify_map_guards() -> None:
    from fermiviewer.calc.eels_quant import quantify_map

    energy = np.linspace(200, 700, 600)
    cube = np.zeros((2, 2, 600))
    with pytest.raises(ValueError, match="energy length"):
        quantify_map(cube, energy[:-5], _edges_co(), 200, 10)
    with pytest.raises(ValueError, match="cube must be"):
        quantify_map(cube[0], energy, _edges_co(), 200, 10)
    bad = _edges_co()
    from fermiviewer.calc.eels_quant import ElementEdge

    bad[0] = ElementEdge("C", "K", 6, 284, (284, 384), (1000, 1001))
    with pytest.raises(ValueError, match="bg window"):
        quantify_map(cube, energy, bad, 200, 10)
    # all-zero cube → defined zeros, not NaN
    res = quantify_map(cube, energy, _edges_co(), 200, 10)
    assert np.all(res.atomic_percent == 0)
