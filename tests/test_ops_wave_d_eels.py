"""Wave-D EELS ops (roadmap 3E): eels_background, elnes, eels_auto_assign
(catalogue_eels_core) and eels_thickness, eels_quantify_map, eels_fit_map,
eels_maps (catalogue_eels_maps). Parity contract (ADR 0005 §1): each op's
numbers must equal a direct call to the SAME calc/ composition its route
calls. Envelope contract (§5): value = {"outputs": [...]} of ADR 0004
{kind, name, data} envelopes; SI rasters inline as `map` envelopes per
the wave-B standing rule, NaN cells as null.

Onset energies come from the app's own calc.eels.EELS_EDGES table
(the fixtures-derive-from-production-tables convention).
"""

from __future__ import annotations

import numpy as np
import pytest

import fermiviewer.ops as ops

# ops/__init__.py is not yet wired to the wave-D catalogues — import them
# explicitly so their register() calls run (the orchestrator wires them in
# after this wave lands)
from fermiviewer.calc.eels import EELS_EDGES, background, thickness_map
from fermiviewer.calc.eels_identify import identify_edges
from fermiviewer.calc.eels_model import fit_edges_map
from fermiviewer.calc.eels_quant import ElementEdge, elnes, quantify_map
from fermiviewer.calc.eels_report import mean_atomic_percent, thickness_summary
from fermiviewer.calc.eels_species_maps import SpeciesSpec, species_maps
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops import (
    catalogue_eels_core,  # noqa: F401  (import registers ops)
    catalogue_eels_maps,  # noqa: F401  (import registers ops)
)
from fermiviewer.ops._envelopes import OUTPUT_KINDS
from fermiviewer.ops.base import ParamError, produces_value_result

pytestmark = pytest.mark.eels

_WAVE_D_EELS = (
    "eels_background",
    "elnes",
    "eels_auto_assign",
    "eels_thickness",
    "eels_quantify_map",
    "eels_fit_map",
    "eels_maps",
)


def _edge(element: str, edge: str):
    return next(e for e in EELS_EDGES if e.element == element and e.edge == edge)


def _eels_cube(h: int = 3, w: int = 4) -> DataStruct:
    """Synthetic SI cube with two core-loss edges (O K + Fe L23) over a
    power-law background — onsets from the app's own EELS_EDGES table."""
    o_edge = _edge("O", "K")
    fe_edge = _edge("Fe", "L23")
    scale, offset, n = 2.0, 300.0, 400
    energy = offset + scale * np.arange(n)  # 300..1098 eV
    bg = 8000.0 * (energy / energy[0]) ** -3.0
    spectrum = bg + 40.0 * (energy >= o_edge.onset_ev) + 25.0 * (energy >= fe_edge.onset_ev)
    cube = np.tile(spectrum, (h, w, 1))
    return DataStruct(
        data=cube,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(1.0, 0.0, "nm"),
            AxisCal(1.0, 0.0, "nm"),
            AxisCal(scale, -offset / scale, "eV"),
        ),
        metadata={"source": "synthetic-eels"},
    )


def _spectrum_ds() -> DataStruct:
    """The same core-loss trace as a 1-D SPECTRUM (spectral, not a cube)."""
    cube = _eels_cube(1, 1)
    return DataStruct(
        data=cube.data[0, 0],
        kind=DataKind.SPECTRUM,
        axes=(cube.axes[2],),
        metadata={"source": "synthetic-eels"},
    )


def _image_ds() -> DataStruct:
    return DataStruct(
        data=np.ones((6, 7)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata={},
    )


def _lowloss_cube(h: int = 3, w: int = 3) -> DataStruct:
    """Low-loss SI cube with a ZLP at 0 eV + plasmon; pixel (0, 0) has its
    counts scaled to ~1 total so it fails thickness_map's min_counts and
    yields a NaN t/λ cell."""
    scale, n = 0.5, 200
    origin = 20.0  # energy -10..89.5 eV
    energy = (np.arange(n) - origin) * scale
    trace = 1000.0 * np.exp(-(energy**2) / (2 * 1.0**2))
    trace += 200.0 * np.exp(-((energy - 20.0) ** 2) / (2 * 5.0**2))
    cube = np.tile(trace, (h, w, 1))
    cube[0, 0] *= 1e-4
    return DataStruct(
        data=cube,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(1.0, 0.0, "nm"),
            AxisCal(1.0, 0.0, "nm"),
            AxisCal(scale, origin, "eV"),
        ),
        metadata={"source": "synthetic-lowloss"},
    )


def _edge_csv_params() -> tuple[dict, list[ElementEdge]]:
    """The six-CSV edge params for O K + Fe L23 and the equivalent
    ElementEdge list a route would build (windows around the tabulated
    onsets, never hard-coded energies)."""
    o_edge = _edge("O", "K")
    fe_edge = _edge("Fe", "L23")
    windows = {
        sym: (e.onset_ev, e.onset_ev + 50.0, e.onset_ev - 60.0, e.onset_ev - 10.0)
        for sym, e in (("O", o_edge), ("Fe", fe_edge))
    }
    params = {
        "elements": "O,Fe",
        "shells": "K,L",
        "z": "8,26",
        "onset_ev": f"{o_edge.onset_ev},{fe_edge.onset_ev}",
        "signal_windows": ",".join(f"{windows[s][0]}:{windows[s][1]}" for s in ("O", "Fe")),
        "bg_windows": ",".join(f"{windows[s][2]}:{windows[s][3]}" for s in ("O", "Fe")),
    }
    edges = [
        ElementEdge("O", "K", 8, o_edge.onset_ev, windows["O"][:2], windows["O"][2:]),
        ElementEdge("Fe", "L", 26, fe_edge.onset_ev, windows["Fe"][:2], windows["Fe"][2:]),
    ]
    return params, edges


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


def _raster(values: list[list]) -> np.ndarray:
    """Inline map values (None cells) back to a NaN ndarray."""
    return np.array(
        [[np.nan if v is None else v for v in row] for row in values],
        dtype=np.float64,
    )


# ── registration ─────────────────────────────────────────────────────


def test_wave_d_eels_ops_are_registered_with_expected_categories() -> None:
    by_name = {s.name: s for s in ops.list_ops()}
    for name in _WAVE_D_EELS:
        assert by_name[name].category == "eels", name
        # `eels` does NOT imply a value result (eels_map is an image
        # producer) — the explicit flag is required
        assert by_name[name].produces_value, name
        assert produces_value_result(by_name[name]), name


# ── eels_background ──────────────────────────────────────────────────


def test_eels_background_op_matches_direct_calc_call() -> None:
    ds = _eels_cube()
    o_edge = _edge("O", "K")
    fit_lo, fit_hi = o_edge.onset_ev - 80.0, o_edge.onset_ev - 10.0
    result = ops.run("eels_background", ds, {"fit_lo": fit_lo, "fit_hi": fit_hi})
    outs = _outputs(result)
    energy = ds.energy_axis
    spec = ds.sum_spectrum()
    signal, bg, params_out = background(energy, spec, (fit_lo, fit_hi), "powerlaw")
    assert outs["spectrum"]["data"]["x"] == energy.tolist()
    assert outs["spectrum"]["data"]["y"] == spec.tolist()
    assert outs["background"]["data"]["y"] == bg.tolist()
    assert outs["signal"]["data"]["y"] == signal.tolist()
    fit = outs["background_model"]["data"]
    assert fit["model"] == "powerlaw"
    assert fit["coefficients"] == params_out


def test_eels_background_error_paths() -> None:
    with pytest.raises(ValueError, match="requires spectral"):
        ops.run("eels_background", _image_ds(), {"fit_lo": 400.0, "fit_hi": 500.0})
    with pytest.raises(ParamError, match="missing required"):
        ops.run("eels_background", _eels_cube(), {"fit_lo": 400.0})
    with pytest.raises(ParamError, match="not in"):
        ops.run(
            "eels_background",
            _eels_cube(),
            {"fit_lo": 400.0, "fit_hi": 500.0, "method": "spline"},
        )


# ── elnes ────────────────────────────────────────────────────────────


def test_elnes_op_matches_direct_calc_call() -> None:
    ds = _spectrum_ds()
    o_edge = _edge("O", "K")
    onset = o_edge.onset_ev
    result = ops.run(
        "elnes",
        ds,
        {"edge_onset": onset, "fit_lo": onset - 80.0, "fit_hi": onset - 10.0},
    )
    outs = _outputs(result)
    direct = elnes(
        ds.energy_axis,
        ds.sum_spectrum(),
        onset,
        (onset - 80.0, onset - 10.0),
        (0.0, 30.0),
        "powerlaw",
        True,
    )
    curve = outs["elnes"]["data"]
    assert curve["x_name"] == "relative_energy"
    assert curve["x_unit"] == "eV"
    assert curve["x"] == direct.relative_energy.tolist()
    assert curve["y"] == direct.intensity.tolist()
    assert outs["edge_jump"]["data"]["value"] == pytest.approx(direct.edge_jump)
    assert outs["edge_onset"]["data"] == {"value": direct.edge_onset, "unit": "eV"}
    assert outs["background"]["data"]["coefficients"] == direct.background_params


def test_elnes_error_paths() -> None:
    onset = _edge("O", "K").onset_ev
    with pytest.raises(ParamError, match="missing required 'edge_onset'"):
        ops.run("elnes", _spectrum_ds(), {"fit_lo": 450.0, "fit_hi": 520.0})
    with pytest.raises(ValueError, match="requires spectral"):
        ops.run(
            "elnes",
            _image_ds(),
            {"edge_onset": onset, "fit_lo": onset - 80.0, "fit_hi": onset - 10.0},
        )
    # the calc's own contract errors surface unchanged (route's 422)
    with pytest.raises(ValueError, match="below edge_onset"):
        ops.run(
            "elnes",
            _spectrum_ds(),
            {"edge_onset": onset, "fit_lo": onset - 10.0, "fit_hi": onset + 10.0},
        )


# ── eels_auto_assign ─────────────────────────────────────────────────


def test_eels_auto_assign_op_matches_direct_calc_call() -> None:
    ds = _eels_cube()
    result = ops.run("eels_auto_assign", ds)
    outs = _outputs(result)
    direct = identify_edges(ds.energy_axis, ds.sum_spectrum())
    table = outs["edges"]["data"]
    assert table["columns"] == [
        "element",
        "edge",
        "symbol",
        "onset_ev",
        "fit_lo",
        "fit_hi",
        "signal_lo",
        "signal_hi",
        "net",
        "sigma",
        "significance",
        "confidence",
    ]
    assert len(table["rows"]) == len(direct) > 0
    for row, r in zip(table["rows"], direct, strict=True):
        assert row == [
            r.element,
            r.edge,
            r.symbol,
            r.onset_ev,
            r.fit_window[0],
            r.fit_window[1],
            r.signal_window[0],
            r.signal_window[1],
            r.net,
            r.sigma,
            r.significance,
            r.confidence,
        ]
    # the fixture's two real edges are found
    symbols = {row[2] for row in table["rows"]}
    assert {"O-K", "Fe-L23"} <= symbols


def test_eels_auto_assign_empty_edge_list_is_a_valid_result() -> None:
    # a narrow low-energy axis supports no tabulated edge — empty rows,
    # not a raise (the route's own 200-with-empty-list contract)
    n = 100
    ds = DataStruct(
        data=np.full(n, 5.0),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(0.5, 0.0, "eV"),),  # 0..49.5 eV
        metadata={},
    )
    outs = _outputs(ops.run("eels_auto_assign", ds))
    assert outs["edges"]["data"]["rows"] == []


def test_eels_auto_assign_rejects_non_spectral_input() -> None:
    with pytest.raises(ValueError, match="requires spectral"):
        ops.run("eels_auto_assign", _image_ds())


# ── eels_thickness ───────────────────────────────────────────────────


def test_eels_thickness_op_inlines_raw_map_and_matches_summary() -> None:
    ds = _lowloss_cube()
    result = ops.run("eels_thickness", ds)
    outs = _outputs(result)
    t, valid = thickness_map(ds.data, ds.energy_axis, (-5.0, 5.0), 100.0)
    mean_t, valid_frac = thickness_summary(t, valid)
    assert not valid[0, 0] and np.isnan(t[0, 0])  # the fixture's bad pixel
    assert valid[1, 1]
    values = outs["t_over_lambda"]["data"]["values"]
    # the RAW map with NaN -> null — NOT the route's nan_to_num session
    # image (the documented wave-D divergence)
    assert values[0][0] is None
    np.testing.assert_allclose(_raster(values), t)
    assert outs["mean_t_over_lambda"]["data"]["value"] == pytest.approx(mean_t)
    assert outs["valid_fraction"]["data"]["value"] == pytest.approx(valid_frac)
    assert 0.0 < valid_frac < 1.0


def test_eels_thickness_error_paths() -> None:
    with pytest.raises(ValueError, match="spectrum-image cube"):
        ops.run("eels_thickness", _spectrum_ds())
    with pytest.raises(ParamError, match="unknown param"):
        ops.run("eels_thickness", _lowloss_cube(), {"bogus": 1})


# ── eels_quantify_map ────────────────────────────────────────────────


def test_eels_quantify_map_op_matches_direct_calc_composition() -> None:
    ds = _eels_cube()
    params, edges = _edge_csv_params()
    result = ops.run("eels_quantify_map", ds, params)
    outs = _outputs(result)
    direct = quantify_map(ds.data, ds.energy_axis, edges, 200.0, 10.0, "powerlaw", None)
    means = mean_atomic_percent(direct.atomic_percent)
    for k, sym in enumerate(direct.elements):
        env = outs[sym]
        assert env["kind"] == "map"
        np.testing.assert_allclose(_raster(env["data"]["values"]), direct.atomic_percent[:, :, k])
    table = outs["composition"]["data"]
    assert table["columns"] == ["element", "sigma", "mean_atomic_percent"]
    for k, row in enumerate(table["rows"]):
        assert row[0] == direct.elements[k]
        assert row[1] == pytest.approx(float(direct.sigma[k]))
        assert row[2] == pytest.approx(means[k])
    # the fixture must actually exercise a two-element composition
    assert sorted(direct.elements) == ["Fe", "O"]


def test_eels_quantify_map_error_paths() -> None:
    params, _ = _edge_csv_params()
    with pytest.raises(ValueError, match="spectrum-image cube"):
        ops.run("eels_quantify_map", _spectrum_ds(), params)
    short = dict(params, z="8")  # mismatched CSV lengths
    with pytest.raises(ValueError, match="same non-zero number"):
        ops.run("eels_quantify_map", _eels_cube(), short)
    with pytest.raises(ParamError, match="missing required"):
        ops.run("eels_quantify_map", _eels_cube(), {"elements": "O"})


# ── eels_fit_map ─────────────────────────────────────────────────────


def test_eels_fit_map_op_matches_direct_calc_composition() -> None:
    ds = _eels_cube()
    params, edges = _edge_csv_params()
    result = ops.run("eels_fit_map", ds, params)
    outs = _outputs(result)
    direct = fit_edges_map(ds.data, ds.energy_axis, edges, 200.0, 10.0, fit_range=None)
    means = mean_atomic_percent(direct.atomic_percent)
    assert outs["background_exponent"]["data"]["value"] == pytest.approx(direct.background_exponent)
    for k, sym in enumerate(direct.elements):
        np.testing.assert_allclose(
            _raster(outs[sym]["data"]["values"]), direct.atomic_percent[:, :, k]
        )
    table = outs["composition"]["data"]
    assert table["columns"] == ["element", "mean_atomic_percent"]
    for k, row in enumerate(table["rows"]):
        assert row[0] == direct.elements[k]
        assert row[1] == pytest.approx(means[k])


def test_eels_fit_map_explicit_fit_range_matches_direct() -> None:
    ds = _eels_cube()
    params, edges = _edge_csv_params()
    o_onset = _edge("O", "K").onset_ev
    lo, hi = o_onset - 80.0, 1050.0
    result = ops.run("eels_fit_map", ds, dict(params, fit_range_lo=lo, fit_range_hi=hi))
    direct = fit_edges_map(ds.data, ds.energy_axis, edges, 200.0, 10.0, fit_range=(lo, hi))
    outs = _outputs(result)
    assert outs["background_exponent"]["data"]["value"] == pytest.approx(direct.background_exponent)


def test_eels_fit_map_rejects_non_cube_input() -> None:
    params, _ = _edge_csv_params()
    with pytest.raises(ValueError, match="spectrum-image cube"):
        ops.run("eels_fit_map", _spectrum_ds(), params)


# ── eels_maps ────────────────────────────────────────────────────────


def test_eels_maps_op_matches_direct_calc_and_keeps_failed_rows() -> None:
    ds = _eels_cube()
    o_edge = _edge("O", "K")
    fe_edge = _edge("Fe", "L23")
    sig = {
        "O-K": (o_edge.onset_ev, o_edge.onset_ev + 50.0),
        "Fe-L23": (fe_edge.onset_ev, fe_edge.onset_ev + 50.0),
        "bogus": (5000.0, 6000.0),  # off the energy axis
    }
    bg = {
        "O-K": (o_edge.onset_ev - 60.0, o_edge.onset_ev - 10.0),
        "Fe-L23": (fe_edge.onset_ev - 60.0, fe_edge.onset_ev - 10.0),
        "bogus": (4900.0, 4990.0),
    }
    labels = ["O-K", "Fe-L23", "bogus"]
    result = ops.run(
        "eels_maps",
        ds,
        {
            "labels": ",".join(labels),
            "signal_windows": ",".join(f"{sig[la][0]}:{sig[la][1]}" for la in labels),
            "bg_windows": ",".join(f"{bg[la][0]}:{bg[la][1]}" for la in labels),
        },
    )
    outs = _outputs(result)
    direct = species_maps(
        ds.data,
        ds.energy_axis,
        [SpeciesSpec(la, sig[la], bg[la], "powerlaw") for la in labels],
    )
    # one map envelope per SUCCESSFUL species; the failed one has no map
    # but keeps its table row (the op does NOT raise)
    assert direct[0].error is None and direct[1].error is None
    assert direct[2].error is not None
    assert "bogus" not in outs
    for k, la in enumerate(labels[:2]):
        np.testing.assert_allclose(_raster(outs[la]["data"]["values"]), direct[k].map)
    table = outs["species"]["data"]
    assert table["columns"] == [
        "label",
        "signal_lo",
        "signal_hi",
        "bg_lo",
        "bg_hi",
        "total_counts",
        "error",
    ]
    ok_row = table["rows"][0]
    assert ok_row[0] == "O-K"
    assert ok_row[1:3] == list(direct[0].signal_window)
    assert ok_row[3:5] == list(direct[0].bg_window)
    assert ok_row[5] == pytest.approx(direct[0].total_counts)
    assert ok_row[6] is None
    bad_row = table["rows"][2]
    assert bad_row[0] == "bogus"
    assert bad_row[1:6] == [None] * 5  # numeric cells null
    assert bad_row[6] == direct[2].error  # the reason string kept


def test_eels_maps_empty_bg_windows_is_a_direct_window_sum_for_all() -> None:
    ds = _eels_cube()
    o_edge = _edge("O", "K")
    result = ops.run(
        "eels_maps",
        ds,
        {
            "labels": "O-K",
            "signal_windows": f"{o_edge.onset_ev}:{o_edge.onset_ev + 50.0}",
        },
    )
    direct = species_maps(
        ds.data,
        ds.energy_axis,
        [SpeciesSpec("O-K", (o_edge.onset_ev, o_edge.onset_ev + 50.0), None)],
    )
    outs = _outputs(result)
    np.testing.assert_allclose(_raster(outs["O-K"]["data"]["values"]), direct[0].map)
    row = outs["species"]["data"]["rows"][0]
    assert row[3] is None and row[4] is None  # no background window


def test_eels_maps_error_paths() -> None:
    ds = _eels_cube()
    with pytest.raises(ValueError, match="spectrum-image cube"):
        ops.run(
            "eels_maps",
            _spectrum_ds(),
            {"labels": "A", "signal_windows": "532:582"},
        )
    with pytest.raises(ValueError, match="same number"):
        ops.run(
            "eels_maps",
            ds,
            {"labels": "A,B", "signal_windows": "532:582"},
        )
    with pytest.raises(ValueError, match="one 'lo:hi' window per species"):
        ops.run(
            "eels_maps",
            ds,
            {
                "labels": "A,B",
                "signal_windows": "532:582,708:758",
                "bg_windows": "470:520",
            },
        )
    # duplicate labels would shadow each other's map envelopes — the
    # documented narrowing over the route (unique-name rule)
    with pytest.raises(ValueError, match="duplicate/reserved"):
        ops.run(
            "eels_maps",
            ds,
            {"labels": "A,A", "signal_windows": "532:582,708:758"},
        )
    with pytest.raises(ParamError, match="missing required"):
        ops.run("eels_maps", ds, {"labels": "A"})
