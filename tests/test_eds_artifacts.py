"""EDS artifact tests: predicted positions, free/blocked partition,
measured areas, and the full remove→re-quant flow (Cu-escape-on-Fe-Kα,
the classic false-ID trap)."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eds import line_energy
from fermiviewer.calc.eds_artifacts import (
    SI_ESCAPE_KEV,
    artifact_curve,
    measure_artifacts,
    partition_artifacts,
    predict_artifacts,
    remove_artifacts,
)
from fermiviewer.calc.eds_peakfit import fit_peaks

pytestmark = pytest.mark.eds

FE = line_energy("Fe", beam_kv=200.0)[0]      # 6.404
CU = line_energy("Cu", beam_kv=200.0)[0]      # 8.048
LINES = {"Fe": FE, "Cu": CU}


def _axis() -> np.ndarray:
    return np.linspace(0.0, 20.0, 4001)       # 5 eV/channel


# ── predict_artifacts ────────────────────────────────────────────────

def test_predicted_positions_reference_values() -> None:
    arts = {a.name: a for a in predict_artifacts(LINES)}
    assert arts["esc_Fe"].energy_kev == pytest.approx(FE - SI_ESCAPE_KEV)   # 4.664
    assert arts["esc_Cu"].energy_kev == pytest.approx(CU - SI_ESCAPE_KEV)   # 6.308
    assert arts["sum_Fe_Fe"].energy_kev == pytest.approx(2 * FE)            # 12.808
    assert arts["sum_Fe_Cu"].energy_kev == pytest.approx(FE + CU)           # 14.452
    assert arts["sum_Cu_Cu"].energy_kev == pytest.approx(2 * CU)            # 16.096
    assert len(arts) == 5
    assert arts["esc_Fe"].kind == "escape" and arts["sum_Fe_Cu"].kind == "sum"


def test_no_escape_below_si_k_edge() -> None:
    o = line_energy("O", beam_kv=200.0)[0]    # 0.525 < 1.839 keV
    arts = predict_artifacts({"O": o})
    assert all(a.kind != "escape" for a in arts)
    assert [a.name for a in arts] == ["sum_O_O"]


def test_range_filter_drops_off_axis_sums() -> None:
    arts = predict_artifacts(LINES, e_max_kev=10.0)
    names = {a.name for a in arts}
    assert "sum_Fe_Fe" not in names and "sum_Cu_Cu" not in names
    assert {"esc_Fe", "esc_Cu"} <= names


def test_family_toggles() -> None:
    assert all(a.kind == "sum"
               for a in predict_artifacts(LINES, include_escape=False))
    assert all(a.kind == "escape"
               for a in predict_artifacts(LINES, include_sum=False))


# ── partition_artifacts ──────────────────────────────────────────────

def test_cu_escape_is_blocked_by_fe_line() -> None:
    arts = predict_artifacts(LINES)
    free, blocked = partition_artifacts(arts, LINES)
    assert [a.name for a in blocked] == ["esc_Cu"]     # 6.308 vs Fe 6.404
    free_names = {a.name for a in free}
    assert {"esc_Fe", "sum_Fe_Fe", "sum_Fe_Cu", "sum_Cu_Cu"} == free_names


# ── artifact_curve / measure_artifacts ───────────────────────────────

def test_artifact_curve_integrates_to_area() -> None:
    e = _axis()
    c = artifact_curve(e, area=250.0, center_kev=6.308)
    assert np.trapezoid(c, e) == pytest.approx(250.0, rel=1e-6)


def test_measured_areas_recovered() -> None:
    e = _axis()
    resid = (artifact_curve(e, 300.0, FE - SI_ESCAPE_KEV)
             + artifact_curve(e, 150.0, 2 * CU))
    arts = predict_artifacts(LINES)
    free, _ = partition_artifacts(arts, LINES)
    m = measure_artifacts(e, resid, free)
    assert m.areas["esc_Fe"] == pytest.approx(300.0, rel=1e-3)
    assert m.areas["sum_Cu_Cu"] == pytest.approx(150.0, rel=1e-3)
    assert m.areas["sum_Fe_Cu"] == pytest.approx(0.0, abs=1.0)


# ── remove_artifacts: the full pre-pass flow ─────────────────────────

FRACTION = 0.01


def _spectrum_with_artifacts(e: np.ndarray) -> np.ndarray:
    """Fe (4000) + Cu (6000) + their escapes at FRACTION + one sum peak."""
    return (
        artifact_curve(e, 4000.0, FE)
        + artifact_curve(e, 6000.0, CU)
        + artifact_curve(e, FRACTION * 4000.0, FE - SI_ESCAPE_KEV)
        + artifact_curve(e, FRACTION * 6000.0, CU - SI_ESCAPE_KEV)
        + artifact_curve(e, 30.0, FE + CU)
    )


def test_remove_then_requant_recovers_truth() -> None:
    e = _axis()
    counts = _spectrum_with_artifacts(e)

    pf0 = fit_peaks(e, counts, ["Fe", "Cu"], weights=None)
    naive_fe = pf0.net_areas["Fe"]
    assert naive_fe > 4010.0       # Cu escape (6.308) inflates Fe-Kα (6.404)

    removal = remove_artifacts(
        e, counts, LINES,
        residual=counts - pf0.fit.model,
        parent_areas=pf0.net_areas,
        escape_fraction=FRACTION,
    )
    # free artifacts measured, blocked Cu escape modeled from its parent
    assert removal.measured["esc_Fe"] == pytest.approx(40.0, rel=0.1)
    assert removal.measured["sum_Fe_Cu"] == pytest.approx(30.0, rel=0.1)
    assert removal.modeled["esc_Cu"] == pytest.approx(60.0, rel=0.05)
    assert removal.skipped == []

    pf1 = fit_peaks(e, removal.corrected, ["Fe", "Cu"], weights=None)
    assert pf1.net_areas["Fe"] == pytest.approx(4000.0, rel=5e-3)
    assert pf1.net_areas["Cu"] == pytest.approx(6000.0, rel=5e-3)
    assert abs(pf1.net_areas["Fe"] - 4000.0) < abs(naive_fe - 4000.0)


def test_blocked_escape_without_parent_area_is_skipped() -> None:
    e = _axis()
    counts = _spectrum_with_artifacts(e)
    removal = remove_artifacts(e, counts, LINES)   # no parent_areas
    assert "esc_Cu" in removal.skipped
    assert "esc_Cu" not in removal.modeled


def test_escape_fraction_validation() -> None:
    e = _axis()
    with pytest.raises(ValueError):
        remove_artifacts(e, np.zeros_like(e), LINES, escape_fraction=1.5)
