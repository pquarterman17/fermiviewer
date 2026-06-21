"""CIF reader + phase registry (Diffraction #2)."""

from __future__ import annotations

import pytest

from fermiviewer.calc.cif import CIFParseError, parse_cif
from fermiviewer.calc.crystal import find_phase
from fermiviewer.calc.phase_registry import PhaseRegistry

pytestmark = pytest.mark.diffraction

# Silicon (Fd-3m, a=5.4309 Å) with the 8 diamond sites listed explicitly so
# the no-symmetry-expansion reader reproduces the built-in basis.
_SI_CIF = """data_Si
_chemical_name_mineral 'Silicon'
_chemical_formula_sum 'Si'
_cell_length_a 5.4309(5)
_cell_length_b 5.4309(5)
_cell_length_c 5.4309(5)
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'F d -3 m'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Si1 Si 0.0 0.0 0.0 1.0
Si2 Si 0.5 0.5 0.0 1.0
Si3 Si 0.5 0.0 0.5 1.0
Si4 Si 0.0 0.5 0.5 1.0
Si5 Si 0.25 0.25 0.25 1.0
Si6 Si 0.75 0.75 0.25 1.0
Si7 Si 0.75 0.25 0.75 1.0
Si8 Si 0.25 0.75 0.75 1.0
"""

# Sapphire (R-centered hexagonal) — checks the centering letter feeds the
# OBVERSE R machinery unchanged.
_SAPPHIRE_CIF = """data_Al2O3
_chemical_formula_sum 'Al2 O3'
_cell_length_a 4.7589
_cell_length_b 4.7589
_cell_length_c 12.9910
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_symmetry_space_group_name_H-M 'R -3 c'
"""


def test_si_cif_reproduces_builtin_cell_and_centering() -> None:
    phase = parse_cif(_SI_CIF)
    builtin = find_phase("Silicon")
    assert phase.a == pytest.approx(builtin.a)  # 5.4309, uncertainty stripped
    assert phase.b == pytest.approx(builtin.b)
    assert phase.c == pytest.approx(builtin.c)
    assert phase.centering == builtin.centering == "F"
    assert phase.system == "cubic"
    assert len(phase.basis) == 8
    assert {site[0] for site in phase.basis} == {"Si"}
    assert phase.formula == "Si"
    assert phase.name == "Silicon"


def test_r_centering_preserved_for_hexagonal() -> None:
    phase = parse_cif(_SAPPHIRE_CIF)
    assert phase.centering == "R"  # feeds the OBVERSE extinction rule
    assert phase.system == "hexagonal"
    assert phase.c == pytest.approx(12.9910)


def test_element_extraction_from_charges_and_labels() -> None:
    cif = """data_x
_cell_length_a 4.0
_cell_length_b 4.0
_cell_length_c 4.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
O2- 0.0 0.0 0.0
Ti4+ 0.5 0.5 0.5
"""
    phase = parse_cif(cif)
    assert [s[0] for s in phase.basis] == ["O", "Ti"]


def test_missing_cell_param_raises() -> None:
    with pytest.raises(CIFParseError, match="cell"):
        parse_cif("data_x\n_cell_length_a 4.0\n")
    with pytest.raises(CIFParseError, match="empty"):
        parse_cif("   \n# only a comment\n")


def test_phase_registry_merges_and_overrides() -> None:
    reg = PhaseRegistry()
    n_builtin = len(reg.all())
    custom = parse_cif(_SI_CIF, name="My Si")
    reg.add(custom)
    assert len(reg.all()) == n_builtin + 1
    assert reg.find("My Si") is not None
    assert reg.find("nonexistent-phase") is None
    # built-in still findable through the registry
    assert reg.find("Gold").name == "Gold"
    assert reg.remove("My Si")
    assert len(reg.all()) == n_builtin


def test_registry_custom_overrides_builtin_name() -> None:
    reg = PhaseRegistry()
    n = len(reg.all())
    fake_gold = parse_cif(_SI_CIF, name="Gold")  # same name as a built-in
    reg.add(fake_gold)
    assert len(reg.all()) == n  # overrides, doesn't add a duplicate
    # the override (Si cell) shadows the real Gold in the merged list
    gold = next(p for p in reg.all() if p.name == "Gold")
    assert gold.a == pytest.approx(5.4309)
