"""Standards, derived factors and QC, pure layer (roadmap 5b).

The load-bearing test here is the ROUND TRIP: a factor derived from a
known composition, fed back into the quantification this repo already
ships, must return the composition it was derived from. That checks the
derivation against an independent implementation of the same physics
rather than against my own arithmetic restated, which is the failure mode
a derivation test is most prone to.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eds import cliff_lorimer
from fermiviewer.calc.eds_factors import (
    derive_k_factors,
    derive_zeta_factors,
    transfer_zeta,
    weight_fractions,
)
from fermiviewer.calc.eds_qc import (
    check_absorption,
    check_counting_statistics,
    check_detection_limit,
    check_factor_conditions,
    check_fit_quality,
    check_peak_interference,
    check_resolved_parameters,
    findings_to_json,
)
from fermiviewer.calc.eds_zeta import zeta_quantify
from fermiviewer.io.standards_model import (
    StandardError,
    composition_from,
    normalized_fractions,
    standard_from_json,
    standard_to_json,
)

# ── the composition record ────────────────────────────────────────────


def test_composition_requires_a_stated_basis() -> None:
    """wt% and at% are not interchangeable, and guessing costs the whole
    point of using a standard."""
    with pytest.raises(StandardError, match="basis"):
        composition_from("percent", {"Fe": 70.0})


def test_composition_rejects_a_zero_element() -> None:
    """An element at 0% is one the standard does not contain; listing it
    would put a zero into a ratio."""
    with pytest.raises(StandardError, match="> 0"):
        composition_from("wt", {"Fe": 70.0, "Cr": 0.0})


def test_composition_rejects_more_than_the_whole_material() -> None:
    with pytest.raises(StandardError, match="more than the whole"):
        composition_from("wt", {"Fe": 70.0, "Cr": 45.0})


def test_a_partial_certificate_normalizes() -> None:
    """A certificate often lists only the majors. The ratios a derivation
    uses must not depend on whether the balance was quoted."""
    _, comp = composition_from("wt", {"Fe": 60.0, "Cr": 20.0})
    fr = normalized_fractions(comp)
    assert fr["Fe"] == pytest.approx(0.75)
    assert fr["Cr"] == pytest.approx(0.25)


def test_standard_round_trips_through_json_keeping_unknown_keys() -> None:
    body = {
        "id": "s1",
        "name": "NIST-ish",
        "version": 2,
        "created_at": "2026-09-07T00:00:00Z",
        "updated_at": "2026-09-07T00:00:00Z",
        "basis": "wt",
        "composition": {"Fe": {"value": 70.0, "unit": "%", "sigma": 0.5}, "Cr": 30.0},
        "mass_thickness": {"value": 3e-5, "unit": "kg/m2"},
        "lab_only_key": {"kept": True},
    }
    std = standard_from_json(body)
    assert std.composition["Fe"].sigma == 0.5
    assert std.composition["Cr"].unit == "%"      # a bare number takes the canonical unit
    assert std.mass_thickness is not None
    out = standard_to_json(std)
    assert out["lab_only_key"] == {"kept": True}  # unknown keys ride through


def test_a_reference_region_cannot_name_two_scopes() -> None:
    body = {
        "id": "s1",
        "name": "s",
        "version": 1,
        "created_at": "t",
        "updated_at": "t",
        "basis": "wt",
        "composition": {"Fe": 100.0},
        "regions": [{"label": "matrix", "region": "set/a", "roi": "1,1,4,4"}],
    }
    with pytest.raises(StandardError, match="give one"):
        standard_from_json(body)


# ── weight/atomic conversion ──────────────────────────────────────────


def test_atomic_percent_converts_to_weight() -> None:
    """Treating at% as wt% is an error of tens of percent for a pair with
    dissimilar masses -- the size of effect a standard exists to pin."""
    fr, _ = weight_fractions({"Fe": 50.0, "O": 50.0}, "at")
    # Fe 55.845, O 15.999 -> w_Fe = 55.845 / 71.844
    assert fr["Fe"] == pytest.approx(55.845 / (55.845 + 15.999), rel=1e-3)
    assert fr["Fe"] + fr["O"] == pytest.approx(1.0)


def test_weight_basis_is_only_renormalized() -> None:
    fr, _ = weight_fractions({"Fe": 60.0, "Cr": 20.0}, "wt")
    assert fr["Fe"] == pytest.approx(0.75)


# ── the round trip ────────────────────────────────────────────────────


def test_derived_zeta_recovers_the_standard_through_zeta_quantify() -> None:
    """Derive ζ from a known composition, then quantify with it. The
    composition and the mass-thickness must both come back.

    Checked against `zeta_quantify`, which was written independently of
    the derivation, rather than against the derivation's own arithmetic.
    """
    wf, _ = weight_fractions({"Fe": 70.0, "Cr": 30.0}, "wt")
    net = [21000.0, 6000.0]
    rho_t, dose = 3e-5, 1e12
    z = derive_zeta_factors(
        ["Fe", "Cr"], net, wf, mass_thickness_kg_m2=rho_t, dose_electrons=dose
    )
    back = zeta_quantify(
        [np.array([[net[0]]]), np.array([[net[1]]])],
        ["Fe", "Cr"],
        [f.value for f in z],
        dose,
        absorption=False,
    )
    assert [float(v) for v in back.mean_weight_pct] == pytest.approx([70.0, 30.0])
    assert back.mean_mass_thickness == pytest.approx(rho_t)


def test_derived_k_recovers_the_standard_through_cliff_lorimer() -> None:
    wf, _ = weight_fractions({"Fe": 70.0, "Cr": 30.0}, "wt")
    net = [21000.0, 6000.0]
    ks, ref = derive_k_factors(["Fe", "Cr"], net, wf)
    back = cliff_lorimer(
        [np.array([[net[0]]]), np.array([[net[1]]])],
        ["Fe", "Cr"],
        np.array([f.value for f in ks]),
    )
    assert [float(v) for v in back.mean_weight_pct] == pytest.approx([70.0, 30.0])
    assert ref == "Fe"  # no Si present -> the major element


def test_k_reference_defaults_to_silicon_when_present() -> None:
    """So a derived set is directly comparable with the built-in table,
    which quotes everything relative to Si."""
    wf, _ = weight_fractions({"Si": 40.0, "Fe": 60.0}, "wt")
    ks, ref = derive_k_factors(["Si", "Fe"], [4000.0, 6000.0], wf)
    assert ref == "Si"
    assert next(f.value for f in ks if f.element == "Si") == pytest.approx(1.0)


def test_the_reference_factor_has_no_uncertainty() -> None:
    """k_ref is a definition, not a measurement."""
    wf, _ = weight_fractions({"Si": 40.0, "Fe": 60.0}, "wt")
    ks, _ = derive_k_factors(
        ["Si", "Fe"], [4000.0, 6000.0], wf, intensity_sigma=[63.0, 77.0]
    )
    by = {f.element: f for f in ks}
    assert by["Si"].sigma == 0.0
    assert by["Fe"].sigma > 0.0


def test_zeta_refuses_without_a_certified_mass_thickness() -> None:
    """There is no way to guess ρt that does not invent the answer."""
    wf, _ = weight_fractions({"Fe": 100.0}, "wt")
    with pytest.raises(ValueError, match="mass-thickness"):
        derive_zeta_factors(
            ["Fe"], [1000.0], wf, mass_thickness_kg_m2=0.0, dose_electrons=1e12
        )


def test_a_factor_cannot_be_derived_from_no_signal() -> None:
    wf, _ = weight_fractions({"Fe": 70.0, "Cr": 30.0}, "wt")
    with pytest.raises(ValueError, match="no measurable intensity"):
        derive_k_factors(["Fe", "Cr"], [21000.0, 0.0], wf)


def test_uncertainty_adds_the_reference_in_quadrature() -> None:
    """A 10% error on this element and 10% on the reference is not 10%."""
    wf, _ = weight_fractions({"Si": 50.0, "Fe": 50.0}, "wt")
    ks, _ = derive_k_factors(
        ["Si", "Fe"], [1000.0, 1000.0], wf, intensity_sigma=[100.0, 100.0]
    )
    fe = next(f for f in ks if f.element == "Fe")
    assert fe.sigma / fe.value == pytest.approx(np.hypot(0.1, 0.1))


def test_transfer_scales_zeta_by_the_collected_signal() -> None:
    """ζ ∝ 1/(Ω·ε): halve the solid angle and ζ doubles."""
    wf, _ = weight_fractions({"Fe": 100.0}, "wt")
    z = derive_zeta_factors(
        ["Fe"], [1000.0], wf, mass_thickness_kg_m2=1e-5, dose_electrons=1e12
    )
    moved = transfer_zeta(z, from_solid_angle_sr=0.2, to_solid_angle_sr=0.1)
    assert moved[0].value == pytest.approx(2.0 * z[0].value)
    # and the σ is widened for the flat-efficiency-ratio assumption
    assert moved[0].sigma > z[0].sigma * 2.0


# ── QC ────────────────────────────────────────────────────────────────


def test_counting_statistics_grade_by_relative_error() -> None:
    findings = check_counting_statistics(
        ["Fe", "Cr", "Ni"], [10000.0, 100.0, 9.0], [100.0, 15.0, 3.0]
    )
    codes = {f.code: f for f in findings}
    assert "counts_low" in codes and codes["counts_low"].elements == ("Cr",)
    assert "counts_too_low" in codes and codes["counts_too_low"].elements == ("Ni",)


def test_an_element_below_its_background_is_not_detected() -> None:
    findings = check_detection_limit(["Fe", "Cr"], [1000.0, 20.0], [400.0, 400.0])
    assert [f.code for f in findings] == ["below_detection_limit"]
    assert findings[0].elements == ("Cr",)


@pytest.mark.parametrize(
    "pair",
    [
        ("Ba", "Ti"),  # Ba Lα 4.466 / Ti Kα 4.511
        ("As", "Pb"),  # As Kα 10.544 / Pb Lα 10.551 — the classic
        ("Fe", "Dy"),
    ],
)
def test_overlapping_principal_lines_are_reported(pair) -> None:
    findings = check_peak_interference(list(pair))
    assert findings and findings[0].code == "peak_interference"
    assert set(findings[0].elements) == set(pair)


def test_well_separated_lines_are_not_reported() -> None:
    assert check_peak_interference(["C", "Au"]) == []


def test_the_check_sees_principal_lines_only() -> None:
    """A documented limit, pinned so it is not mistaken for coverage.

    Ti Kβ (4.93) sits under V Kα (4.95), a real and well-known
    interference — but `line_energy` returns each element's PRINCIPAL
    line, so a Kβ/Kα clash is invisible here. Ti Kα and V Kα are 0.44 keV
    apart and correctly read as resolved.
    """
    assert check_peak_interference(["Ti", "V"]) == []


def test_a_structured_residual_is_an_error() -> None:
    assert [f.code for f in check_fit_quality(reduced_chi2=9.0)] == [
        "fit_residual_structured"
    ]
    assert [f.code for f in check_fit_quality(reduced_chi2=1.1)] == []


def test_a_large_absorption_correction_is_reported() -> None:
    findings = check_absorption(["Fe", "O"], [1.02, 247.0])
    assert [f.code for f in findings] == ["absorption_severe"]
    assert findings[0].elements == ("O",)


def test_using_the_200kv_table_at_80kv_is_an_extrapolation() -> None:
    """The standing example: the built-in table records no voltage where
    it is used, so the error is invisible in the answer."""
    findings = check_factor_conditions(beam_kv=80.0, factor_kv=200.0, source="built-in")
    assert [f.code for f in findings] == ["factors_extrapolated"]
    assert findings[0].severity == "error"  # 60% away
    assert check_factor_conditions(beam_kv=200.0, factor_kv=200.0, source="b") == []


def test_unstated_factor_conditions_are_themselves_a_finding() -> None:
    findings = check_factor_conditions(beam_kv=80.0, factor_kv=None, source="built-in")
    assert [f.code for f in findings] == ["factors_unstated_conditions"]


def test_a_defaulted_parameter_is_reported() -> None:
    """A composition computed on a placeholder takeoff angle should not
    look measured."""
    findings = check_resolved_parameters(
        {
            "take_off_angle_deg": {"value": 20.0, "unit": "deg", "origin": "default"},
            "beam_kv": {"value": 80.0, "unit": "kV", "origin": "profile"},
        }
    )
    assert [f.code for f in findings] == ["parameters_defaulted"]
    assert "take_off_angle_deg" in findings[0].message
    assert "beam_kv" not in findings[0].message


def test_findings_are_ordered_most_severe_first() -> None:
    out = findings_to_json(
        [
            *check_fit_quality(r_squared=0.5),          # warn
            *check_counting_statistics(["Ni"], [9.0], [3.0]),  # error
        ]
    )
    assert [f["severity"] for f in out] == ["error", "warn"]


# ── the registered op ─────────────────────────────────────────────────


def test_the_derivation_op_takes_its_composition_inline() -> None:
    """A recipe step naming a per-user standard id would replay only on
    the machine holding that standard, so the op takes the numbers."""
    import fermiviewer.ops  # noqa: F401  (registers the catalogues)
    from fermiviewer.ops.registry import get_spec

    spec = get_spec("eds_derive_factors")
    assert "composition" in spec.params
    assert "standard_id" not in spec.params
    assert spec.produces_value is True


def test_the_op_rejects_a_composition_missing_a_measured_element() -> None:
    """Otherwise the element is silently dropped from the derived set."""
    import fermiviewer.ops  # noqa: F401
    from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
    from fermiviewer.ops.registry import get_spec

    spec = get_spec("eds_derive_factors")
    ds = DataStruct(
        data=np.ones((64,), dtype=np.float64),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(scale=0.02, origin=0.0, units="keV"),),
        metadata={},
    )
    with pytest.raises(ValueError, match=r"states nothing for \['Cr'\]"):
        spec.fn(ds, {**{k: v.default for k, v in spec.params.items()},
                     "elements": "Fe,Cr", "composition": "Fe:70", "basis": "wt"})
