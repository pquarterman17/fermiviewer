"""Analysis-fit batch ops: eels_fit, eds_peakfit, eds_element_maps,
composition_profile, distribution_fit (ANALYSIS_PRESENTATION_PLAN.md #8,
audit R7 — batch/scripting reach for spectral fitting).

Parity contract: each op's output must equal a direct call to the SAME
calc/ function the analogous route calls, on the same synthetic input —
never a reimplementation. Onset energies / line energies come from the
app's own tables (calc.eels.EELS_EDGES, calc.eds.line_energy), matching
the fixtures-derive-from-production-tables convention used throughout this
repo and mirrored from tests/test_ops_spectral.py.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import fermiviewer.api as fv
import fermiviewer.ops as ops
from fermiviewer.calc.distributions import fit_all, fit_distribution, histogram_bins, summarize
from fermiviewer.calc.eds import cliff_lorimer, line_energy, zaf_correction
from fermiviewer.calc.eds_maps import (
    composition_profile,
    composition_profile_sigma,
    element_map,
    extract_element_maps,
)
from fermiviewer.calc.eds_peakfit import quantify_peaks
from fermiviewer.calc.eels import EELS_EDGES
from fermiviewer.calc.eels_model import fit_edges
from fermiviewer.calc.eels_quant import ElementEdge
from fermiviewer.calc.energy_units import to_kev
from fermiviewer.calc.uncertainty import atomic_fraction_sigma, default_k_factors
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops.base import ParamError

pytestmark = pytest.mark.parser


def _edge(element: str, edge: str):
    return next(e for e in EELS_EDGES if e.element == element and e.edge == edge)


def _eels_cube(h: int = 3, w: int = 4) -> DataStruct:
    """Synthetic SI cube with two core-loss edges (O K + Fe L23) over a
    power-law background — onsets from the app's own EELS_EDGES table."""
    o_edge = _edge("O", "K")
    fe_edge = _edge("Fe", "L23")
    scale, offset, n = 2.0, 300.0, 400
    energy = offset + scale * np.arange(n)             # 300..1098 eV
    background = 8000.0 * (energy / energy[0]) ** -3.0
    spectrum = (
        background
        + 40.0 * (energy >= o_edge.onset_ev)
        + 25.0 * (energy >= fe_edge.onset_ev)
    )
    cube = np.tile(spectrum, (h, w, 1))
    return DataStruct(
        data=cube, kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "nm"),
            AxisCal(scale, -offset / scale, "eV"),
        ),
        metadata={"source": "synthetic-eels"},
    )


def _eels_edges() -> list[ElementEdge]:
    o_edge = _edge("O", "K")
    fe_edge = _edge("Fe", "L23")
    return [
        ElementEdge("O", "K", 8, o_edge.onset_ev, (532.0, 572.0), (462.0, 522.0)),
        ElementEdge("Fe", "L", 26, fe_edge.onset_ev, (708.0, 748.0), (632.0, 698.0)),
    ]


def _eds_cube(h: int = 4, w: int = 5) -> tuple[DataStruct, float, float]:
    """Synthetic SI cube with Fe Ka + Si Ka peaks — energies from the app's
    own line_energy() table."""
    scale, n = 0.01, 1200
    energy_kev = scale * np.arange(n)                  # 0..11.99 keV
    fe_e, _ = line_energy("Fe", beam_kv=200.0)
    si_e, _ = line_energy("Si", beam_kv=200.0)
    spectrum = np.full(n, 2.0)
    spectrum += 60.0 * np.exp(-((energy_kev - fe_e) ** 2) / (2 * 0.03**2))
    spectrum += 40.0 * np.exp(-((energy_kev - si_e) ** 2) / (2 * 0.03**2))
    cube = np.tile(spectrum, (h, w, 1))
    ds = DataStruct(
        data=cube, kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "nm"),
            AxisCal(scale, 0.0, "keV"),
        ),
        metadata={"source": "synthetic-eds"},
    )
    return ds, float(fe_e), float(si_e)


# ── registration ─────────────────────────────────────────────────────

def test_new_ops_are_registered_with_expected_categories() -> None:
    by_name = {s.name: s for s in ops.list_ops()}
    assert by_name["eels_fit"].category == "eels"
    assert by_name["eds_peakfit"].category == "eds"
    assert by_name["eds_element_maps"].category == "eds"
    assert by_name["composition_profile"].category == "eds"
    assert by_name["distribution_fit"].category == "analysis"
    assert by_name["eels_fit"].produces_value
    assert by_name["eds_peakfit"].produces_value
    assert by_name["eds_element_maps"].produces_value
    assert by_name["composition_profile"].produces_value
    # distribution_fit doesn't set the flag explicitly — category=="analysis"
    # implies it for consumers (routes/batch_ops.py, gen_api_reference.py),
    # so the flag itself staying False here is correct, not an oversight.
    assert not by_name["distribution_fit"].produces_value
    assert by_name["distribution_fit"].category == "analysis"


# ── eels_fit ─────────────────────────────────────────────────────────

def test_eels_fit_op_matches_direct_calc_call() -> None:
    ds = _eels_cube()
    edges = _eels_edges()
    expected = fit_edges(ds.energy_axis, ds.sum_spectrum(), edges, 200.0, 10.0)
    result = ops.run("eels_fit", ds, {
        "elements": "O,Fe", "shells": "K,L", "z": "8,26",
        "onset_ev": f"{edges[0].onset_ev},{edges[1].onset_ev}",
        "signal_windows": "532:572,708:748",
        "bg_windows": "462:522,632:698",
    })
    assert not result.produces_image
    assert result.value["elements"] == expected.elements
    np.testing.assert_allclose(result.value["atomic_percent"], expected.atomic_percent)
    np.testing.assert_allclose(result.value["amplitudes"], expected.amplitudes)
    np.testing.assert_allclose(result.value["amplitude_errors"], expected.amplitude_errors)
    np.testing.assert_allclose(result.value["background"], expected.background)
    np.testing.assert_allclose(result.value["edge_curves"], expected.edge_curves)
    np.testing.assert_allclose(result.value["model"], expected.model)
    assert result.value["reduced_chi2"] == pytest.approx(expected.reduced_chi2)
    assert result.value["r_squared"] == pytest.approx(expected.r_squared)
    assert result.value["success"] == expected.success
    assert result.value["fit_range"] == pytest.approx(list(expected.fit_range))
    expected_err = atomic_fraction_sigma(expected.amplitudes, expected.amplitude_errors)
    np.testing.assert_allclose(result.value["atomic_percent_error"], expected_err)


def test_eels_fit_honours_an_explicit_fit_range() -> None:
    ds = _eels_cube()
    edges = _eels_edges()
    expected = fit_edges(
        ds.energy_axis, ds.sum_spectrum(), edges, 200.0, 10.0, fit_range=(500.0, 1000.0),
    )
    result = ops.run("eels_fit", ds, {
        "elements": "O,Fe", "shells": "K,L", "z": "8,26",
        "onset_ev": f"{edges[0].onset_ev},{edges[1].onset_ev}",
        "signal_windows": "532:572,708:748",
        "bg_windows": "462:522,632:698",
        "fit_range_lo": 500.0, "fit_range_hi": 1000.0,
    })
    assert result.value["fit_range"] == pytest.approx([500.0, 1000.0])
    np.testing.assert_allclose(result.value["atomic_percent"], expected.atomic_percent)


def test_eels_fit_rejects_a_plain_image() -> None:
    img = DataStruct(
        data=np.zeros((4, 4)), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    with pytest.raises(ValueError, match="spectral"):
        ops.run("eels_fit", img, {
            "elements": "O", "shells": "K", "z": "8", "onset_ev": "532",
            "signal_windows": "532:572", "bg_windows": "462:522",
        })


def test_eels_fit_rejects_mismatched_edge_lists() -> None:
    ds = _eels_cube()
    with pytest.raises(ValueError, match="same non-zero number of edges"):
        ops.run("eels_fit", ds, {
            "elements": "O,Fe", "shells": "K", "z": "8,26",
            "onset_ev": "532,708", "signal_windows": "532:572,708:748",
            "bg_windows": "462:522,632:698",
        })


def test_eels_fit_accepts_a_bare_1d_spectrum() -> None:
    ds = _eels_cube()
    edges = _eels_edges()
    spec = DataStruct(
        data=ds.sum_spectrum(), kind=DataKind.SPECTRUM, axes=(ds.axes[-1],),
    )
    result = ops.run("eels_fit", spec, {
        "elements": "O,Fe", "shells": "K,L", "z": "8,26",
        "onset_ev": f"{edges[0].onset_ev},{edges[1].onset_ev}",
        "signal_windows": "532:572,708:748",
        "bg_windows": "462:522,632:698",
    })
    assert result.value["elements"] == ["O", "Fe"]


# ── eds_peakfit ──────────────────────────────────────────────────────

def test_eds_peakfit_op_matches_direct_calc_call() -> None:
    ds, fe_e, si_e = _eds_cube()
    energy_kev = to_kev(ds.energy_axis, ds.energy_cal.units)
    expected_pf, expected_cl = quantify_peaks(
        energy_kev, ds.sum_spectrum(), ["Fe", "Si"],
        beam_kv=200.0, weights="poisson", center_tol_kev=0.0, lorentzian_hwhm_kev=0.0,
    )
    result = ops.run("eds_peakfit", ds, {"elements": "Fe,Si"})
    assert not result.produces_image
    assert result.value["elements"] == ["Fe", "Si"]
    assert result.value["net_areas"] == pytest.approx(
        [expected_pf.net_areas["Fe"], expected_pf.net_areas["Si"]]
    )
    assert result.value["net_area_errors"] == pytest.approx(
        [expected_pf.net_area_errors["Fe"], expected_pf.net_area_errors["Si"]]
    )
    assert result.value["line_energies"] == pytest.approx(
        [expected_pf.line_energies["Fe"], expected_pf.line_energies["Si"]]
    )
    assert result.value["lines"] == [expected_pf.lines["Fe"], expected_pf.lines["Si"]]
    assert result.value["reduced_chi2"] == pytest.approx(expected_pf.fit.reduced_chi2)
    assert result.value["success"] == expected_pf.fit.success
    np.testing.assert_allclose(result.value["mean_atomic_pct"], expected_cl.mean_atomic_pct)
    np.testing.assert_allclose(result.value["mean_weight_pct"], expected_cl.mean_weight_pct)
    np.testing.assert_allclose(result.value["k_factors"], expected_cl.k_factors)


def test_eds_peakfit_uniform_weights_maps_to_none() -> None:
    ds, fe_e, si_e = _eds_cube()
    energy_kev = to_kev(ds.energy_axis, ds.energy_cal.units)
    expected_pf, _ = quantify_peaks(
        energy_kev, ds.sum_spectrum(), ["Fe", "Si"], weights=None,
    )
    result = ops.run("eds_peakfit", ds, {"elements": "Fe,Si", "weights": "uniform"})
    assert result.value["net_areas"] == pytest.approx(
        [expected_pf.net_areas["Fe"], expected_pf.net_areas["Si"]]
    )


def test_eds_peakfit_rejects_a_plain_image() -> None:
    img = DataStruct(
        data=np.zeros((4, 4)), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    with pytest.raises(ValueError, match="spectral"):
        ops.run("eds_peakfit", img, {"elements": "Fe"})


def test_eds_peakfit_requires_at_least_one_element() -> None:
    ds, _, _ = _eds_cube()
    with pytest.raises(ValueError, match="at least one symbol"):
        ops.run("eds_peakfit", ds, {"elements": " , "})


# ── eds_element_maps ─────────────────────────────────────────────────

def test_eds_element_maps_op_matches_direct_calc_call() -> None:
    ds, fe_e, si_e = _eds_cube()
    energy_kev = to_kev(ds.energy_axis, ds.energy_cal.units)
    expected = extract_element_maps(ds.data, energy_kev, ["Fe", "Si"], half_window=0.085)
    result = ops.run("eds_element_maps", ds, {"elements": "Fe,Si"})
    assert not result.produces_image
    assert result.value["elements"] == [e.symbol for e in expected]
    assert result.value["lines"] == [e.line for e in expected]
    np.testing.assert_allclose(result.value["energies_kev"], [e.energy_kev for e in expected])
    np.testing.assert_allclose(result.value["totals"], [e.total for e in expected])
    for got_map, exp in zip(result.value["maps"], expected, strict=True):
        np.testing.assert_allclose(got_map, exp.map)
    assert result.value["shape"] == list(expected[0].map.shape)


def test_eds_element_maps_rejects_a_plain_image() -> None:
    img = DataStruct(
        data=np.zeros((4, 4)), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    with pytest.raises(ValueError, match="spectrum-image"):
        ops.run("eds_element_maps", img, {"elements": "Fe"})


def test_eds_element_maps_rejects_a_1d_spectrum() -> None:
    spec = DataStruct(
        data=np.ones(10), kind=DataKind.SPECTRUM, axes=(AxisCal(1.0, 0.0, "keV"),),
    )
    with pytest.raises(ValueError, match="spectrum-image"):
        ops.run("eds_element_maps", spec, {"elements": "Fe"})


def test_eds_element_maps_requires_at_least_one_element() -> None:
    ds, _, _ = _eds_cube()
    with pytest.raises(ValueError, match="at least one symbol"):
        ops.run("eds_element_maps", ds, {"elements": " , "})


def test_eds_element_maps_unknown_element_only_warns_then_raises() -> None:
    ds, _, _ = _eds_cube()
    with pytest.warns(UserWarning, match="no known line"):
        with pytest.raises(ValueError, match="no usable element lines"):
            ops.run("eds_element_maps", ds, {"elements": "Xx"})


# ── composition_profile ──────────────────────────────────────────────

def test_composition_profile_op_matches_direct_calc_call_cliff_lorimer() -> None:
    ds, fe_e, si_e = _eds_cube()
    energy_kev = to_kev(ds.energy_axis, ds.energy_cal.units)
    entries = extract_element_maps(ds.data, energy_kev, ["Fe", "Si"], half_window=0.085)
    net_maps = [e.map for e in entries]
    syms = [e.symbol for e in entries]
    cl = cliff_lorimer(net_maps, syms)
    expected_dist, expected_pct = composition_profile(
        cl.atomic_pct_maps, syms, 1.0, 1.0, 5.0, 4.0, n_points=10, pixel_size=1.0, width=1.0,
    )
    gross_maps = [
        element_map(ds.data, energy_kev, e.window[0], e.window[1], bg="none")
        for e in entries
    ]
    expected_sigma = composition_profile_sigma(
        net_maps, gross_maps, syms, default_k_factors(syms),
        1.0, 1.0, 5.0, 4.0, n_points=10, width=1.0,
    )

    result = ops.run("composition_profile", ds, {
        "elements": "Fe,Si", "x1": 1.0, "y1": 1.0, "x2": 5.0, "y2": 4.0, "n_points": 10,
    })
    assert not result.produces_image
    assert result.value["elements"] == syms
    np.testing.assert_allclose(result.value["distance"], expected_dist)
    np.testing.assert_allclose(result.value["atomic_pct"], expected_pct.T)
    np.testing.assert_allclose(result.value["atomic_percent_error"], expected_sigma.T)
    assert result.value["unit"] == "nm"  # the synthetic cube's axes are nm-calibrated


def test_composition_profile_zaf_method_has_no_sigma_key() -> None:
    ds, fe_e, si_e = _eds_cube()
    energy_kev = to_kev(ds.energy_axis, ds.energy_cal.units)
    entries = extract_element_maps(ds.data, energy_kev, ["Fe", "Si"], half_window=0.085)
    net_maps = [e.map for e in entries]
    syms = [e.symbol for e in entries]
    zr = zaf_correction(net_maps, syms, thickness_nm=100.0, take_off_angle_deg=20.0)
    expected_dist, expected_pct = composition_profile(
        zr.atomic_pct_maps, syms, 1.0, 1.0, 5.0, 4.0, n_points=10, pixel_size=1.0, width=1.0,
    )
    result = ops.run("composition_profile", ds, {
        "elements": "Fe,Si", "x1": 1.0, "y1": 1.0, "x2": 5.0, "y2": 4.0, "n_points": 10,
        "method": "zaf",
    })
    np.testing.assert_allclose(result.value["distance"], expected_dist)
    np.testing.assert_allclose(result.value["atomic_pct"], expected_pct.T)
    assert "atomic_percent_error" not in result.value


def test_composition_profile_rejects_a_plain_image() -> None:
    img = DataStruct(
        data=np.zeros((4, 4)), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    with pytest.raises(ValueError, match="spectrum-image"):
        ops.run("composition_profile", img, {
            "elements": "Fe", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0,
        })


def test_composition_profile_unknown_element_only_warns_then_raises() -> None:
    ds, _, _ = _eds_cube()
    with pytest.warns(UserWarning, match="no known line"):
        with pytest.raises(ValueError, match="no usable element lines"):
            ops.run("composition_profile", ds, {
                "elements": "Xx", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0,
            })


# ── distribution_fit ─────────────────────────────────────────────────

_POP = "12.1,14.3,9.8,15.2,11.0,13.4,10.7,16.1,12.8,14.9,10.2,13.7"


def test_distribution_fit_op_matches_direct_calc_call_all() -> None:
    values = np.array([float(v) for v in _POP.split(",")])
    expected_summary = summarize(values)
    expected_hist = histogram_bins(values)
    expected_fits = fit_all(values)

    ds, _, _ = _eds_cube()  # arbitrary — the op ignores ds entirely
    result = ops.run("distribution_fit", ds, {"values": _POP})
    assert not result.produces_image
    s = result.value["summary"]
    assert s["n"] == expected_summary.n
    assert s["mean"] == pytest.approx(expected_summary.mean)
    assert s["std"] == pytest.approx(expected_summary.std)
    assert s["median"] == pytest.approx(expected_summary.median)
    np.testing.assert_allclose(result.value["histogram"]["edges"], expected_hist.edges)
    np.testing.assert_allclose(result.value["histogram"]["counts"], expected_hist.counts)
    assert result.value["fits"]["best"] == expected_fits.best
    assert result.value["fits"]["normal"]["aic"] == pytest.approx(expected_fits.normal.aic)
    assert result.value["fits"]["lognormal"]["aic"] == pytest.approx(expected_fits.lognormal.aic)
    assert result.value["fits"]["weibull"]["aic"] == pytest.approx(expected_fits.weibull.aic)


def test_distribution_fit_single_kind() -> None:
    values = np.array([float(v) for v in _POP.split(",")])
    expected = fit_distribution(values, "normal")
    ds, _, _ = _eds_cube()
    result = ops.run("distribution_fit", ds, {"values": _POP, "fit": "normal"})
    assert result.value["fits"]["normal"]["params"] == pytest.approx(expected.params)
    assert result.value["fits"]["lognormal"] is None
    assert result.value["fits"]["best"] is None


def test_distribution_fit_none_omits_fits() -> None:
    ds, _, _ = _eds_cube()
    result = ops.run("distribution_fit", ds, {"values": _POP, "fit": "none"})
    assert result.value["fits"] is None


def test_distribution_fit_requires_at_least_one_value() -> None:
    ds, _, _ = _eds_cube()
    with pytest.raises(ValueError, match="at least one number"):
        ops.run("distribution_fit", ds, {"values": " , "})


def test_distribution_fit_is_indifferent_to_the_input_images_kind() -> None:
    """The op's subject is the VALUES string, not ds — a plain 2D image
    input must work exactly like a spectral one, pinning that the input
    image's data is genuinely unused."""
    img = DataStruct(
        data=np.zeros((4, 4)), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    values = np.array([float(v) for v in _POP.split(",")])
    expected_summary = summarize(values)
    result = ops.run("distribution_fit", img, {"values": _POP, "fit": "none"})
    assert result.value["summary"]["n"] == expected_summary.n


# ── misc ─────────────────────────────────────────────────────────────

def test_unknown_param_still_rejected_for_new_ops() -> None:
    ds, _, _ = _eds_cube()
    with pytest.raises(ParamError, match="unknown param"):
        ops.run("eds_peakfit", ds, {"elements": "Fe", "typo": 1})


# ── scripting surface (fermiviewer.api) ─────────────────────────────

@pytest.fixture()
def eds_msa_path(tmp_path: Path) -> Path:
    """A tiny real EDS spectrum file, loaded through fv.open() like a user
    script would — proving the new op is reachable end-to-end through the
    documented Python surface, not just the ops registry directly."""
    fe_e, _ = line_energy("Fe", beam_kv=200.0)
    n = 400
    scale = 0.02
    energy_kev = scale * np.arange(n)
    spectrum = np.full(n, 2.0) + 50.0 * np.exp(-((energy_kev - fe_e) ** 2) / (2 * 0.03**2))
    lines = [
        "#FORMAT : EMSA/MAS Spectral Data File",
        f"#NPOINTS : {n}",
        f"#XPERCHAN : {scale * 1000}",   # keV -> eV per channel
        "#OFFSET : 0.0",
        "#XUNITS : eV",
        "#SPECTRUM :",
        *(str(v) for v in spectrum),
        "#ENDOFDATA :",
    ]
    p = tmp_path / "fe.msa"
    p.write_text("\n".join(lines), encoding="latin-1")
    return p


def test_new_op_is_reachable_end_to_end_through_the_scripting_api(
    eds_msa_path: Path,
) -> None:
    """A newly-registered op needs no api/ changes: Image.__getattr__
    dispatches any registered op name straight to the registry (see
    fermiviewer/api/__init__.py), so eds_peakfit is callable as
    img.eds_peakfit(**params) the moment catalogue_analysis registers it."""
    img = fv.open(eds_msa_path)
    assert "eds_peakfit" in {o["name"] for o in fv.ops()}
    result = img.eds_peakfit(elements="Fe")
    assert isinstance(result, fv.Result)
    assert result.image is None  # value-producing op
    assert result.value["elements"] == ["Fe"]
    assert result.op == "eds_peakfit"
    # also runnable via the generic .run() dispatch and a recipe pipeline step
    via_run = img.run("eds_peakfit", elements="Fe")
    assert via_run.value["net_areas"] == pytest.approx(result.value["net_areas"])
