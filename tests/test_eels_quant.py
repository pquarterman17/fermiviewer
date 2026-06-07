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
