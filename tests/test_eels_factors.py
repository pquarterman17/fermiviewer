"""EELS cross-section derivation from a known standard (roadmap 5b).

The oracle throughout is a hand-worked Fe2O3: 40 at% Fe / 60 at% O, which
the same certificate states as 69.94 wt% Fe / 30.06 wt% O. Planting edge
intensities of 4000 and 3000 makes the arithmetic exact --

    σ_Fe = σ_O · (4000/0.4) / (3000/0.6) = 2 σ_O

-- so a test can assert the number rather than a property of it, and the
weight/atomic mix-up this module exists to prevent lands in a DIFFERENT
place (it makes Fe the reference, which moves the anchor as well as the
ratios, and O comes out 2.44x too large) rather than shifting everything
by one factor the assertions would absorb.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.composition import atomic_fractions, weight_fractions
from fermiviewer.calc.eels_factors import derive_cross_sections
from fermiviewer.calc.eels_quant import ElementEdge, cross_section, quantify

pytestmark = pytest.mark.eels

#: Fe2O3, atomic basis, and the same material on the weight basis
AT_PCT = {"Fe": 40.0, "O": 60.0}
WT_PCT = {"Fe": 69.9427, "O": 30.0573}

ELEMENTS = ["Fe", "O"]
INTENSITY = [4000.0, 3000.0]
#: stand-in model values; only the reference's is used as the anchor
MODEL = [7.0e-25, 5.0e-25]


def _derive(**kw):
    af, _ = atomic_fractions(AT_PCT, "at")
    return derive_cross_sections(ELEMENTS, INTENSITY, MODEL, af, **kw)


def test_the_certificate_states_one_material_on_two_bases() -> None:
    """The fixture's own premise: WT_PCT and AT_PCT are the same solid."""
    af, _ = atomic_fractions(WT_PCT, "wt")
    assert af["Fe"] == pytest.approx(0.40, abs=5e-5)
    assert af["O"] == pytest.approx(0.60, abs=5e-5)
    wf, _ = weight_fractions(AT_PCT, "at")
    assert wf["Fe"] == pytest.approx(0.699427, abs=5e-6)


def test_reference_defaults_to_the_major_element_and_takes_the_anchor() -> None:
    derived, ref = _derive()
    assert ref == "O"                       # 0.6 > 0.4 on the ATOMIC basis
    by_sym = {f.element: f for f in derived}
    # the anchor is the model's own value, asserted rather than measured
    assert by_sym["O"].value == pytest.approx(MODEL[1])
    assert by_sym["O"].sigma == 0.0
    # σ_Fe = σ_O · (I_Fe/a_Fe)/(I_O/a_O) = 2 σ_O -- worked by hand above
    assert by_sym["Fe"].value == pytest.approx(2.0 * MODEL[1])


def test_derived_set_reproduces_the_certified_composition() -> None:
    """The closure that makes a derived set worth having.

    `eels_quant.quantify` computes at% as the normalised I/σ. Feeding the
    DERIVED σ back through that same arithmetic must return the
    certificate -- if it does not, the set does not quantify its own
    standard correctly and cannot be trusted on an unknown.
    """
    derived, _ = _derive()
    ratio = np.array([f.intensity / f.value for f in derived])
    at_pct = 100.0 * ratio / ratio.sum()
    np.testing.assert_allclose(at_pct, [40.0, 60.0], rtol=1e-9)


def test_the_model_set_does_not_reproduce_it() -> None:
    """The negative control for the test above: the MODEL values are not
    already the answer, so that closure is a real constraint."""
    ratio = np.array(
        [i / s for i, s in zip(INTENSITY, MODEL, strict=True)]
    )
    at_pct = 100.0 * ratio / ratio.sum()
    assert at_pct[0] != pytest.approx(40.0, abs=1.0)


def test_reading_the_certificate_on_the_wrong_basis_moves_the_answer() -> None:
    """Why `calc.composition` holds both conversions in one place.

    EELS quantifies on the ATOMIC basis; Cliff-Lorimer on the WEIGHT
    basis. Handing this derivation weight fractions does not merely
    rescale the set -- it changes which element is the reference, so the
    anchor moves (5e-25 -> 7e-25) on top of the 1.745 shift in the
    measured ratio, and O lands 2.44x too large. A test that only checked
    "σ came back positive" would pass either way.
    """
    right, ref_right = _derive()
    wf, _ = weight_fractions(WT_PCT, "wt")
    wrong, ref_wrong = derive_cross_sections(ELEMENTS, INTENSITY, MODEL, wf)
    assert ref_right == "O" and ref_wrong == "Fe"
    o_right = next(f.value for f in right if f.element == "O")
    o_wrong = next(f.value for f in wrong if f.element == "O")
    assert o_wrong / o_right == pytest.approx(1.745 * 7.0 / 5.0, rel=0.001)


def test_an_independent_anchor_rescales_the_whole_set() -> None:
    """Only ratios are measurable, so replacing the anchor must move every
    entry by the same factor and none of them relative to each other."""
    base, _ = _derive()
    scaled, _ = _derive(reference_value_m2=2.0 * MODEL[1])
    for a, b in zip(base, scaled, strict=True):
        assert b.value == pytest.approx(2.0 * a.value)
    assert [f.model_value for f in scaled] == MODEL  # the comparison is unchanged


def test_anchor_uncertainty_reaches_every_entry_including_the_reference() -> None:
    plain, _ = _derive()
    with_sig, _ = _derive(reference_value_m2=MODEL[1], reference_value_sigma=0.1 * MODEL[1])
    by_sym = {f.element: f for f in with_sig}
    # the reference's σ is the anchor's alone: the measured terms cancel
    assert by_sym["O"].sigma / by_sym["O"].value == pytest.approx(0.1)
    assert all(f.sigma == 0.0 for f in plain)
    assert by_sym["Fe"].sigma / by_sym["Fe"].value == pytest.approx(0.1)


def test_measurement_uncertainty_propagates_but_not_onto_the_anchor() -> None:
    derived, _ = _derive(
        intensity_sigma=[0.03 * 4000.0, 0.04 * 3000.0],
        atomic_fraction_sigma={"Fe": 0.01 * 0.4},
    )
    by_sym = {f.element: f for f in derived}
    # the reference is a definition here (anchor σ = 0), not a measurement
    assert by_sym["O"].sigma == 0.0
    expected = np.sqrt(0.03**2 + 0.01**2 + 0.04**2)
    assert by_sym["Fe"].sigma / by_sym["Fe"].value == pytest.approx(expected)


def test_model_ratio_reports_how_far_the_model_was_off() -> None:
    derived, _ = _derive()
    by_sym = {f.element: f for f in derived}
    assert by_sym["O"].model_ratio == pytest.approx(1.0)     # it IS the anchor
    assert by_sym["Fe"].model_ratio == pytest.approx(2.0 * MODEL[1] / MODEL[0])


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"reference": "Cu"}, "not among the measured elements"),
        ({"reference_value_m2": 0.0}, "must be positive"),
        ({"reference_value_sigma": -1.0}, "must be >= 0"),
        ({"intensity_sigma": [1.0]}, "must match elements length"),
    ],
)
def test_refusals(kw, match) -> None:
    with pytest.raises(ValueError, match=match):
        _derive(**kw)


def test_a_zero_anchor_from_the_model_is_refused_not_defaulted() -> None:
    """A model σ of 0 for the reference cannot be scaled from. Refusing
    beats substituting a 1.0 that would silently make the whole set
    dimensionless."""
    af, _ = atomic_fractions(AT_PCT, "at")
    with pytest.raises(ValueError, match="must be positive"):
        derive_cross_sections(ELEMENTS, INTENSITY, [7e-25, 0.0], af)


def test_an_unmeasured_element_is_refused() -> None:
    af, _ = atomic_fractions(AT_PCT, "at")
    with pytest.raises(ValueError, match="no measurable edge intensity"):
        derive_cross_sections(ELEMENTS, [4000.0, 0.0], MODEL, af)
    with pytest.raises(ValueError, match="states no composition"):
        derive_cross_sections(["Fe", "Cu"], INTENSITY, MODEL, af)


def test_end_to_end_against_a_synthetic_spectrum() -> None:
    """The one test that goes through `quantify` rather than around it.

    A power-law background with two rectangular edges of known area; the
    derivation reuses quantify's own intensities and model σ, so the
    closure holds on real fitted numbers rather than planted ones.
    """
    e = np.linspace(300.0, 900.0, 2400)
    spec = 2e7 * e**-2.6
    spec = spec + np.where((e > 540) & (e < 600), 90.0, 0.0)      # O K
    spec = spec + np.where((e > 715) & (e < 775), 40.0, 0.0)      # Fe L23
    edges = [
        ElementEdge("O", "K", 8, 532.0, (540.0, 600.0), (450.0, 525.0)),
        ElementEdge("Fe", "L", 26, 708.0, (715.0, 775.0), (630.0, 700.0)),
    ]
    res = quantify(e, spec, edges, e0_kv=200, beta_mrad=10)
    af, _ = atomic_fractions(AT_PCT, "at")
    derived, ref = derive_cross_sections(
        ["O", "Fe"], res.intensity.tolist(), res.sigma.tolist(), af
    )
    assert ref == "O"
    # the anchor really is the hydrogenic model for the O K edge over the
    # window that was integrated -- not some rounded stand-in
    assert derived[0].value == pytest.approx(
        cross_section(8, "K", 200, 10, 60.0, 532.0)
    )
    ratio = np.array([f.intensity / f.value for f in derived])
    np.testing.assert_allclose(100 * ratio / ratio.sum(), [60.0, 40.0], rtol=1e-9)
