"""Wave-D EDS ops (roadmap 3E): eds_continuum, eds_artifacts, eds_zeta
(catalogue_eds_model) + eds_recalibrate, eds_auto_assign
(catalogue_eds_calib). Parity contract (ADR 0005 §1): each op's numbers
must equal a direct call to the SAME calc composition its route calls —
the wave-D lifts (calc/eds_continuum.background_component,
calc/eds_peakfit.fit_summed_peaks, calc/eds_artifacts.artifact_prepass/
artifact_block, calc/eds_zeta.zeta_uncertainty, calc/eds_calib
.resolve_anchors/recalibrated_cal) exist so this is one code path.

Envelope contract (ADR 0005 §5): every value op returns
value = {"outputs": [...]} of ADR 0004 {kind, name, data} envelopes with
unique names; non-finite scalars are absent — not null. eds_recalibrate
is the wave's derived-DataStruct op: produces_value stays UNSET and the
new energy AxisCal + gain/offset/anchors/skipped diagnostics ride the
derived struct (the savgol_derivative metadata precedent).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import fermiviewer.ops as ops

# explicit imports register the wave-D EDS ops (ops/__init__ is wired later)
from fermiviewer.calc.eds import assign_elements, detect_peaks, line_energy
from fermiviewer.calc.eds_artifacts import (
    DEFAULT_ESCAPE_FRACTION,
    artifact_block,
    artifact_prepass,
)
from fermiviewer.calc.eds_calib import (
    fano_sigma_kev,
    recalibrate,
    recalibrated_cal,
    resolve_anchors,
)
from fermiviewer.calc.eds_continuum import background_component, fit_continuum
from fermiviewer.calc.eds_peakfit import fit_peaks, fit_summed_peaks
from fermiviewer.calc.eds_zeta import (
    dose_electrons,
    zeta_quantify,
    zeta_uncertainty,
)
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops import (
    catalogue_eds_calib,  # noqa: F401
    catalogue_eds_model,  # noqa: F401
)
from fermiviewer.ops._envelopes import OUTPUT_KINDS
from fermiviewer.ops.base import ParamError, produces_value_result

pytestmark = pytest.mark.eds

_WAVE_D_EDS = (
    "eds_continuum",
    "eds_artifacts",
    "eds_zeta",
    "eds_recalibrate",
    "eds_auto_assign",
)

_SCALE, _N = 0.01, 1200  # 10 eV/channel, 0..11.99 keV
_FE_AREA, _CU_AREA = 5000.0, 3000.0


def _line_centers() -> tuple[float, float]:
    """Fe Kα + Cu Kα from the app's own line table (the fixtures-derive-
    from-production-tables convention, as in test_ops_spectral.py)."""
    fe_e, _ = line_energy("Fe", beam_kv=200.0)
    cu_e, _ = line_energy("Cu", beam_kv=200.0)
    return float(fe_e), float(cu_e)


def _counts(shift_kev: float = 0.0) -> np.ndarray:
    energy = _SCALE * np.arange(_N)
    fe_e, cu_e = _line_centers()
    counts = np.full(_N, 2.0)
    for center, area in ((fe_e, _FE_AREA), (cu_e, _CU_AREA)):
        sigma = float(fano_sigma_kev(center))
        amp = area / (sigma * math.sqrt(2.0 * math.pi))
        counts += amp * np.exp(-0.5 * ((energy - (center + shift_kev)) / sigma) ** 2)
    return counts


def _eds_ds(shift_kev: float = 0.0) -> DataStruct:
    """Synthetic EDS SPECTRUM with Fe Kα + Cu Kα peaks at Fano widths."""
    return DataStruct(
        data=_counts(shift_kev),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(_SCALE, 0.0, "keV"),),
        metadata={"source": "synthetic-eds"},
    )


def _energy_kev() -> np.ndarray:
    return _SCALE * np.arange(_N, dtype=np.float64)


def _outputs(result) -> dict[str, dict]:
    """{name: envelope} for a wave op's value, validating the §5 contract
    (unique names included — a duplicate would shadow in this map)."""
    assert set(result.value) == {"outputs"}
    by_name = {}
    for env in result.value["outputs"]:
        assert set(env) == {"kind", "name", "data"}
        assert env["kind"] in OUTPUT_KINDS
        assert isinstance(env["data"], dict)
        assert env["name"] not in by_name
        by_name[env["name"]] = env
    return by_name


# ── registration ─────────────────────────────────────────────────────


def test_wave_d_eds_ops_are_registered_with_expected_categories() -> None:
    by_name = {s.name: s for s in ops.list_ops()}
    for name in _WAVE_D_EDS:
        assert by_name[name].category == "eds", name
    # the derived-DataStruct op: produces_value UNSET (False), and the §3
    # predicate must report an image producer
    assert by_name["eds_recalibrate"].produces_value is False
    assert not produces_value_result(by_name["eds_recalibrate"])
    for name in ("eds_continuum", "eds_artifacts", "eds_zeta", "eds_auto_assign"):
        # `eds` does NOT imply a value result — the explicit flag is required
        assert by_name[name].produces_value, name
        assert produces_value_result(by_name[name]), name


def test_unknown_param_is_a_param_error() -> None:
    with pytest.raises(ParamError, match="unknown param"):
        ops.run("eds_continuum", _eds_ds(), {"e0_kev": 15.0, "bogus": 1})
    with pytest.raises(ParamError, match="missing required"):
        ops.run("eds_continuum", _eds_ds())
    # the route's dropped optional `pairs` input is a hard error, never
    # silent divergence (optional-input omission rule)
    with pytest.raises(ParamError, match="unknown param"):
        ops.run("eds_recalibrate", _eds_ds(), {"elements": "Fe", "pairs": "1:2"})


def test_ops_reject_non_spectral_input() -> None:
    img = DataStruct(
        data=np.ones((8, 9)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata={},
    )
    with pytest.raises(ValueError, match="requires spectral input"):
        ops.run("eds_continuum", img, {"e0_kev": 15.0})
    with pytest.raises(ValueError, match="requires spectral input"):
        ops.run("eds_auto_assign", img)


# ── eds_continuum ─────────────────────────────────────────────────────


def test_continuum_op_matches_direct_calc_call() -> None:
    ds = _eds_ds()
    outs = _outputs(ops.run("eds_continuum", ds, {"e0_kev": 15.0, "exclude_lines": "Fe,Cu"}))
    direct = fit_continuum(
        _energy_kev(),
        _counts(),
        15.0,
        exclude_lines=["Fe", "Cu"],
        exclude_windows=[],
        fit_absorption=True,
        weights="poisson",
    )
    fit = outs["continuum"]["data"]
    assert fit["model"] == "kramers"
    assert fit["coefficients"]["amp"] == pytest.approx(direct.amp)
    assert fit["coefficients"]["absorption"] == pytest.approx(direct.absorption)
    assert fit["reduced_chi2"] == pytest.approx(direct.fit.reduced_chi2)
    assert fit["success"] == direct.fit.success
    assert fit["y_fit"] == direct.continuum.tolist()
    assert fit["x_fit"] == _energy_kev().tolist()
    assert outs["spectrum"]["data"]["y"] == _counts().tolist()


def test_continuum_op_windows_and_uniform_weights_match_direct() -> None:
    ds = _eds_ds()
    fe_e, cu_e = _line_centers()
    windows = f"{fe_e - 0.2}:{fe_e + 0.2},{cu_e - 0.2}:{cu_e + 0.2}"
    outs = _outputs(
        ops.run(
            "eds_continuum",
            ds,
            {"e0_kev": 15.0, "exclude_windows": windows, "weights": "uniform"},
        )
    )
    # the "uniform" choice maps to the calc layer's None
    direct = fit_continuum(
        _energy_kev(),
        _counts(),
        15.0,
        exclude_lines=[],
        exclude_windows=[(fe_e - 0.2, fe_e + 0.2), (cu_e - 0.2, cu_e + 0.2)],
        fit_absorption=True,
        weights=None,
    )
    assert outs["continuum"]["data"]["y_fit"] == direct.continuum.tolist()


# ── eds_artifacts ─────────────────────────────────────────────────────


def test_artifacts_op_matches_direct_calc_composition() -> None:
    ds = _eds_ds()
    outs = _outputs(ops.run("eds_artifacts", ds, {"elements": "Fe,Cu"}))
    pf = fit_peaks(
        _energy_kev(),
        _counts(),
        ["Fe", "Cu"],
        beam_kv=200.0,
        background=background_component("linear", None),
        weights="poisson",
    )
    removal = artifact_prepass(_energy_kev(), _counts(), pf, DEFAULT_ESCAPE_FRACTION)
    assert outs["spectrum"]["data"]["y"] == _counts().tolist()
    assert outs["corrected"]["data"]["y"] == removal.corrected.tolist()
    table = outs["artifacts"]["data"]
    assert table["columns"] == [
        "name",
        "label",
        "kind",
        "energy_kev",
        "status",
        "area",
        "area_error",
    ]
    block = artifact_block(removal)
    assert len(block) > 0  # the fixture must actually exercise artifacts
    assert table["rows"] == [
        [b["name"], b["label"], b["kind"], b["energy_kev"], b["status"], b["area"], b["area_error"]]
        for b in block
    ]
    # Cu escape (6.308 keV) sits on Fe Kα (6.404) -> modeled, not measured
    by_name = {r[0]: r for r in table["rows"]}
    assert by_name["esc_Cu"][4] == "modeled"
    assert by_name["esc_Fe"][4] == "measured"


def test_artifacts_op_bremsstrahlung_without_e0_errors() -> None:
    with pytest.raises(ValueError, match="needs e0_kev"):
        ops.run(
            "eds_artifacts",
            _eds_ds(),
            {"elements": "Fe,Cu", "background": "bremsstrahlung"},
        )


# ── eds_zeta ──────────────────────────────────────────────────────────


def _direct_zeta(zeta: np.ndarray, elements: list[str]):
    pf, removal = fit_summed_peaks(
        _energy_kev(),
        _counts(),
        elements,
        beam_kv=200.0,
        background=background_component("linear", None),
        weights="poisson",
        center_tol_kev=0.0,
        strip_artifacts=False,
        escape_fraction=DEFAULT_ESCAPE_FRACTION,
    )
    dose = dose_electrons(1.0, 100.0)
    net = np.array([max(pf.net_areas[s], 0.0) for s in elements])
    zr = zeta_quantify(
        [np.array([[v]]) for v in net],
        elements,
        zeta,
        dose,
        take_off_angle_deg=20.0,
        absorption=True,
        density_g_cm3=None,
    )
    unc, rho_t_sigma = zeta_uncertainty(
        net,
        [pf.net_area_errors[s] for s in elements],
        elements,
        zeta,
        zr.absorption_factors,
        dose,
    )
    assert removal is None
    return pf, dose, zr, unc, rho_t_sigma


def test_zeta_op_matches_direct_calc_composition() -> None:
    elements = ["Fe", "Cu"]
    zeta = np.array([500.0, 800.0])
    outs = _outputs(
        ops.run("eds_zeta", _eds_ds(), {"elements": "Fe,Cu", "zeta_factors": "500,800"})
    )
    pf, dose, zr, unc, rho_t_sigma = _direct_zeta(zeta, elements)

    fit = outs["model"]["data"]
    assert fit["y_fit"] == pf.fit.model.tolist()
    assert fit["reduced_chi2"] == pytest.approx(pf.fit.reduced_chi2)
    assert fit["success"] == pf.fit.success
    # model_sigma rides the fit envelope as y_sigma ONLY when present
    if pf.model_sigma is not None:
        assert fit["y_sigma"] == pf.model_sigma.tolist()
    else:
        assert "y_sigma" not in fit

    assert outs["spectrum"]["data"]["y"] == _counts().tolist()
    assert outs["elements"]["data"]["rows"] == [
        [s, pf.lines[s], pf.line_energies[s], pf.net_areas[s], pf.net_area_errors[s]]
        for s in elements
    ]
    for row, i in zip(outs["quant"]["data"]["rows"], range(2), strict=True):
        assert row[0] == elements[i]
        assert row[1] == pytest.approx(float(zr.mean_atomic_pct[i]))
        assert row[2] == pytest.approx(float(unc.atomic_pct_sigma[i]))
        assert row[3] == pytest.approx(float(zr.mean_weight_pct[i]))
        assert row[4] == pytest.approx(float(unc.weight_pct_sigma[i]))
        assert row[5] == zeta[i]
        assert row[6] == pytest.approx(float(zr.absorption_factors[i]))

    # the §5 sigma-in-envelope scalar: rho*t with its counting-stats 1σ
    rho_t = outs["mass_thickness_kg_m2"]["data"]
    assert rho_t["value"] == pytest.approx(zr.mean_mass_thickness)
    assert rho_t["sigma"] == pytest.approx(rho_t_sigma)
    assert outs["dose_electrons"]["data"]["value"] == pytest.approx(dose)
    # no density given -> thickness is non-finite -> absent, not null
    assert "thickness_nm" not in outs
    # remove_artifacts=False -> no artifacts table
    assert "artifacts" not in outs


def test_zeta_op_density_and_artifact_modes() -> None:
    outs = _outputs(
        ops.run(
            "eds_zeta",
            _eds_ds(),
            {
                "elements": "Fe,Cu",
                "zeta_factors": "500,800",
                "density_g_cm3": 7.0,
                "remove_artifacts": True,
            },
        )
    )
    # with a density the thickness scalar appears...
    rho_t = outs["mass_thickness_kg_m2"]["data"]["value"]
    assert outs["thickness_nm"]["data"]["value"] == pytest.approx(rho_t / 7000.0 * 1e9)
    # ...and the pre-pass appends the artifacts table
    assert outs["artifacts"]["kind"] == "table"
    assert len(outs["artifacts"]["data"]["rows"]) > 0


def test_zeta_op_xor_validation() -> None:
    ds = _eds_ds()
    with pytest.raises(ValueError, match="got both"):
        ops.run(
            "eds_zeta",
            ds,
            {"elements": "Fe,Cu", "zeta_factors": "500,800", "zeta_si": 600.0},
        )
    with pytest.raises(ValueError, match="provide zeta_factors or zeta_si"):
        ops.run("eds_zeta", ds, {"elements": "Fe,Cu"})
    with pytest.raises(ValueError, match="must match elements length"):
        ops.run("eds_zeta", ds, {"elements": "Fe,Cu", "zeta_factors": "500"})


# ── eds_recalibrate (derived) ─────────────────────────────────────────


def test_recalibrate_op_derives_new_axis_cal_and_keeps_pixels() -> None:
    shift = 0.05
    ds = _eds_ds(shift_kev=shift)
    result = ops.run("eds_recalibrate", ds, {"elements": "Fe,Cu,Zz"})
    assert result.produces_image
    assert result.value is None
    derived = result.derived
    assert derived is not None

    # parity: the direct calc composition the route runs
    anchors, skipped = resolve_anchors(["Fe", "Cu", "Zz"], [], 200.0)
    res = recalibrate(_energy_kev(), _counts(shift), anchors, search_kev=0.15)
    new_cal = recalibrated_cal(ds.axes[-1], res.gain, res.offset)

    # pixels unchanged, kind unchanged, spatial axes unchanged
    assert np.array_equal(derived.data, ds.data)
    assert derived.kind is ds.kind
    assert derived.axes[-1] == new_cal
    # the fitted correction actually moved the axis (peaks were shifted)
    assert new_cal != ds.axes[-1]

    # diagnostics ride derived.metadata (the savgol_derivative precedent)
    md = derived.metadata
    assert md["parser"] == "derived"
    assert md["source"] == "eds_recalibrate"
    assert md["gain"] == pytest.approx(res.gain)
    assert md["offset"] == pytest.approx(res.offset)
    assert md["skipped"] == skipped == ["Zz"]
    assert md["anchors"] == [list(p) for p in res.anchors]

    # the correction pulls the observed (shifted) peaks back onto the true
    # line energies: E' = gain*E + offset applied to observed ~ true
    fe_e, _ = _line_centers()
    assert res.gain * (fe_e + shift) + res.offset == pytest.approx(fe_e, abs=5e-3)


def test_recalibrate_op_failure_modes() -> None:
    # no anchors at all (default empty elements) — the route's 422
    with pytest.raises(ValueError, match="no usable anchors"):
        ops.run("eds_recalibrate", _eds_ds())
    # only unknown symbols
    with pytest.raises(ValueError, match="no usable anchors"):
        ops.run("eds_recalibrate", _eds_ds(), {"elements": "Zz,Qq"})


# ── eds_auto_assign ───────────────────────────────────────────────────


def test_auto_assign_op_matches_direct_calc_composition() -> None:
    outs = _outputs(ops.run("eds_auto_assign", _eds_ds()))
    peaks = detect_peaks(_energy_kev(), _counts(), threshold=0.05)
    assignments = assign_elements(peaks, tolerance_kev=0.15)
    assert peaks.size > 0  # the fixture must actually exercise peaks

    assert outs["peaks"]["data"]["rows"] == [[i, float(e)] for i, e in enumerate(peaks)]
    # the ragged peak -> candidates nest flattens to one row per candidate
    expect = [
        [i, pa.peak_kev, ca.symbol, ca.line, ca.energy_kev, ca.delta_kev]
        for i, pa in enumerate(assignments)
        for ca in pa.candidates
    ]
    assert outs["assignments"]["data"]["rows"] == expect
    # closest-first within each peak: Fe and Cu are each some peak's best
    best = {r[0]: r[2] for r in reversed(outs["assignments"]["data"]["rows"])}
    assert set(best.values()) >= {"Fe", "Cu"}


def test_auto_assign_op_ev_axis_converts_to_kev() -> None:
    # same channels, calibrated in eV (the SER/DM path) — to_kev mirrors
    # the route, so the detected peak energies come back in keV
    ds_ev = DataStruct(
        data=_counts(),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(_SCALE * 1000.0, 0.0, "eV"),),
        metadata={},
    )
    outs = _outputs(ops.run("eds_auto_assign", ds_ev))
    peaks = detect_peaks(_energy_kev(), _counts(), threshold=0.05)
    rows = outs["peaks"]["data"]["rows"]
    assert [r[0] for r in rows] == list(range(peaks.size))
    assert [r[1] for r in rows] == pytest.approx([float(e) for e in peaks])


def test_auto_assign_op_empty_result_is_valid() -> None:
    flat = DataStruct(
        data=np.full(64, 3.0),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(_SCALE, 0.0, "keV"),),
        metadata={},
    )
    outs = _outputs(ops.run("eds_auto_assign", flat))
    assert outs["peaks"]["data"]["rows"] == []
    assert outs["assignments"]["data"]["rows"] == []
