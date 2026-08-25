"""Ops registered against the re-opened contract: the point-list fits, spot
indexing, and the two multi-map layer operations.

Each op is checked against the SAME `calc/` function its route calls — the
ADR 0005 §1 parity proof — plus the guards that differ from the route on
purpose.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.special import erf

import fermiviewer.ops as ops
from fermiviewer.calc.atom_report import pair_strain_payload
from fermiviewer.calc.atom_strain import peak_pair_strain
from fermiviewer.calc.diffraction_index import index_spots_roi
from fermiviewer.calc.phase_registry import registry
from fermiviewer.calc.shape_fit import fit_circle, fit_ellipse
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops.base import InputError, ParamError

pytestmark = pytest.mark.parser


def _image(h: int = 64, w: int = 64, fill: float = 0.0) -> DataStruct:
    return DataStruct(
        data=np.full((h, w), fill, dtype=np.float64),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
    )


def _ring(cy: float = 20.0, cx: float = 30.0, r: float = 10.0, n: int = 12) -> list:
    t = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    return [[float(cy + r * np.cos(a)), float(cx + r * np.sin(a))] for a in t]


def _erf_map(shift: float = 0.0) -> DataStruct:
    y = np.arange(40)[:, None] * np.ones((1, 30))
    data = 0.5 * (1.0 + erf((y - (15.0 + shift)) / 2.0))
    return DataStruct(
        data=data,
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
    )


# ── fit_shape ─────────────────────────────────────────────────────────


def test_fit_shape_matches_the_calc_functions() -> None:
    points = _ring()
    result = ops.run("fit_shape", _image(), {"points": points})
    pts = np.asarray(points, dtype=np.float64)
    circle, ellipse = fit_circle(pts), fit_ellipse(pts)

    by_name = {o["name"]: o for o in result.value["outputs"]}
    assert by_name["circle"]["data"]["params"]["r"] == pytest.approx(circle.r)
    assert by_name["circle"]["data"]["rms"] == pytest.approx(circle.rms)
    assert by_name["ellipse"]["data"]["params"]["a"] == pytest.approx(ellipse.a)
    assert by_name["ellipse"]["data"]["params"]["theta_rad"] == pytest.approx(
        ellipse.theta_rad
    )


def test_fit_shape_needs_enough_points() -> None:
    """calc owns the per-shape minimums; the op must not add a second copy
    of the thresholds, so the error still names the shape that failed."""
    with pytest.raises(ParamError, match="needs at least 3 entries"):
        ops.run("fit_shape", _image(), {"points": [[1.0, 2.0], [3.0, 4.0]]})
    with pytest.raises(ValueError, match="ellipse"):
        ops.run("fit_shape", _image(), {"points": _ring(n=4)})


# ── atoms_strain ──────────────────────────────────────────────────────


def _lattice_positions() -> list[list[float]]:
    return [[float(x), float(y)] for x in range(1, 7) for y in range(1, 7)]


def test_atoms_strain_matches_the_calc_composition() -> None:
    positions = _lattice_positions()
    result = ops.run("atoms_strain", _image(), {"positions": positions})
    expected = pair_strain_payload(
        peak_pair_strain(np.asarray(positions, dtype=np.float64), neighbors=8)
    )
    by_name = {o["name"]: o for o in result.value["outputs"]}
    assert by_name["exx_mean"]["data"]["value"] == pytest.approx(
        expected["exx_mean"], nan_ok=True
    )
    assert len(by_name["per_column_strain"]["data"]["rows"]) == len(expected["exx"])


def test_atoms_strain_origin_is_a_sentinel_pair() -> None:
    """A fixed-arity optional pair rides the frozen NaN-sentinel group, so a
    half-given origin errors instead of silently falling back."""
    positions = _lattice_positions()
    with pytest.raises(ValueError, match="must be given together"):
        ops.run("atoms_strain", _image(), {"positions": positions, "origin_x": 2.0})


# ── diffraction_index ─────────────────────────────────────────────────


_SPOTS = [[20.0, 33.0], [45.0, 33.0], [33.0, 20.0], [33.0, 45.0]]


def test_diffraction_index_matches_the_calc_composition() -> None:
    ds = _image()
    result = ops.run(
        "diffraction_index", ds, {"spots": _SPOTS, "camera_length_mm": 200.0}
    )
    direct = index_spots_roi(
        ds.data.shape,
        np.asarray(_SPOTS, dtype=np.float64),
        None,
        camera_length=200.0,
        extra_phases=list(registry.custom),
    )
    by_name = {o["name"]: o for o in result.value["outputs"]}
    assert (
        by_name["center_row"]["data"]["value"],
        by_name["center_col"]["data"]["value"],
    ) == direct.center
    assert by_name["n_candidates"]["data"]["value"] == len(direct.candidates)
    assert len(by_name["measured_radii"]["data"]["rows"]) == len(_SPOTS)


def test_diffraction_index_refuses_a_roi_that_selects_nothing() -> None:
    """Strict-ROI discipline: the route's zero-defaults would otherwise
    index the whole pattern while the caller believed a region applied."""
    with pytest.raises(ValueError, match="selects no pixels"):
        ops.run(
            "diffraction_index",
            _image(),
            {
                "spots": _SPOTS,
                "roi_kind": "rect",
                "roi_r0": 10,
                "roi_c0": 10,
                "roi_r1": 10,
                "roi_c1": 10,
            },
        )


def test_diffraction_index_rejects_a_fractional_roi() -> None:
    """`int_group` raises a plain ValueError from inside the op fn — the
    NaN-sentinel group rides float params, so the schema cannot catch it."""
    with pytest.raises(ValueError, match="whole numbers"):
        ops.run(
            "diffraction_index",
            _image(),
            {
                "spots": _SPOTS,
                "roi_kind": "rect",
                "roi_r0": 1.5,
                "roi_c0": 2,
                "roi_r1": 10,
                "roi_c1": 10,
            },
        )


def test_diffraction_index_refuses_a_spectrum_image() -> None:
    """The route has no kind check and would silently SUM the cube; detect
    already refuses that, and index reads the same geometry."""
    cube = DataStruct(
        data=np.zeros((6, 6, 8)),
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "eV")),
    )
    with pytest.raises(ValueError, match="needs a 2D image"):
        ops.run("diffraction_index", cube, {"spots": _SPOTS})


# ── layers_multi ──────────────────────────────────────────────────────


def test_layers_multi_reports_every_map_including_the_subject() -> None:
    result = ops.run(
        "layers_multi", _erf_map(), {"axis": "y"}, inputs={"others": [_erf_map(1.0)]}
    )
    names = {o["name"] for o in result.value["outputs"]}
    assert {"map_0_interfaces", "map_1_interfaces"} <= names
    by_name = {o["name"]: o for o in result.value["outputs"]}
    assert by_name["n_maps"]["data"]["value"] == 2


def test_layers_multi_requires_one_pixel_grid() -> None:
    with pytest.raises(ValueError, match="same pixel grid"):
        ops.run(
            "layers_multi", _erf_map(), {"axis": "y"}, inputs={"others": [_image(10, 10)]}
        )


def test_layers_multi_needs_something_to_compare_against() -> None:
    with pytest.raises(InputError, match="needs at least 1 dataset"):
        ops.run("layers_multi", _erf_map(), {"axis": "y"}, inputs={"others": []})


def test_layers_multi_drops_the_routes_reference_param() -> None:
    """The subject IS the reference — passing an index would be a second,
    contradictory way to say the same thing."""
    assert "reference" not in ops.get_spec("layers_multi").params


# ── layers_grains ─────────────────────────────────────────────────────


def _label_map() -> DataStruct:
    labels = np.zeros((20, 20), dtype=np.float64)
    labels[2:8, 2:8] = 1
    labels[12:18, 12:18] = 2
    return DataStruct(
        data=labels,
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
    )


_BANDS = [
    {"index": 0, "top": 0.0, "bottom": 10.0},
    {"index": 1, "top": 10.0, "bottom": 20.0},
]


def test_layers_grains_inlines_the_assignment_raster() -> None:
    result = ops.run(
        "layers_grains",
        _label_map(),
        {
            "axis": "y",
            "layers": _BANDS,
            "selected_indices": "0,1",
            "interface_traces": [],
        },
        inputs={"source": _image(20, 20)},
    )
    by_name = {o["name"]: o for o in result.value["outputs"]}
    assert by_name["assignment"]["kind"] == "map"
    assert np.asarray(by_name["assignment"]["data"]["values"]).shape == (20, 20)
    assert result.derived is None  # a map envelope, not the derived slot


def test_layers_grains_takes_ragged_nullable_traces() -> None:
    """`interface_traces` is the one param that accepts a null row — an
    interface with no measured trace."""
    result = ops.run(
        "layers_grains",
        _label_map(),
        {
            "axis": "y",
            "layers": _BANDS,
            "selected_indices": "0,1",
            # a trace spans the ROI's lateral dimension (20 columns here)
            "interface_traces": [None, [10.0] * 20],
        },
        inputs={"source": _image(20, 20)},
    )
    assert result.value["outputs"]


def test_layers_grains_needs_its_source_image() -> None:
    with pytest.raises(InputError, match="missing required input 'source'"):
        ops.run(
            "layers_grains",
            _label_map(),
            {"axis": "y", "layers": _BANDS, "interface_traces": []},
        )


def test_layers_ops_accept_a_roi_string() -> None:
    """`RectRoi` is a plain 4-tuple alias, not a dataclass — attribute
    access on it typechecked as an object and would have crashed the first
    time anyone passed an ROI. Neither op's tests exercised that path."""
    multi = ops.run(
        "layers_multi",
        _erf_map(),
        {"axis": "y", "roi": "5,3,35,28"},
        inputs={"others": [_erf_map(1.0)]},
    )
    assert multi.value["outputs"]

    grains = ops.run(
        "layers_grains",
        _label_map(),
        {
            "axis": "y",
            "layers": _BANDS,
            "selected_indices": "0,1",
            "interface_traces": [],
            "roi": "2,2,18,18",
        },
        inputs={"source": _image(20, 20)},
    )
    assert grains.value["outputs"]


def test_layer_grains_table_holds_only_scalars() -> None:
    """A table cell is a scalar (ADR 0004 §3 — rows go to a 2-D member in
    column order). `LayerGrainSummary.grains` is a tuple of nested
    `GrainSlice` records, so it rides its own table instead of a cell."""
    result = ops.run(
        "layers_grains",
        _label_map(),
        {
            "axis": "y",
            "layers": _BANDS,
            "selected_indices": "0,1",
            "interface_traces": [],
        },
        inputs={"source": _image(20, 20)},
    )
    by_name = {o["name"]: o for o in result.value["outputs"]}
    summary = by_name["layer_grains"]["data"]
    assert "grains" not in summary["columns"]
    for row in summary["rows"]:
        for cell in row:
            assert isinstance(cell, (int, float, str, bool)) or cell is None

    slices = by_name["layer_grain_slices"]["data"]
    assert slices["columns"][0] == "layer"
    assert "source_grain_id" in slices["columns"]
    # both seeded grains are clipped into a band, so neither is lost
    assert {row[0] for row in slices["rows"]} == {0, 1}
    assert all(len(row) == len(slices["columns"]) for row in slices["rows"])


def test_layers_grains_rejects_an_empty_interface_trace() -> None:
    """An EMPTY trace is a length mismatch (the route's 422), not "no
    trace" — treating it as absent would silently measure the grains
    against a flat band boundary instead."""
    with pytest.raises(ValueError, match="interface trace length"):
        ops.run(
            "layers_grains",
            _label_map(),
            {
                "axis": "y",
                "layers": _BANDS,
                "selected_indices": "0,1",
                "interface_traces": [[]],
            },
            inputs={"source": _image(20, 20)},
        )


# ── grains_edit subject rank ──────────────────────────────────────────


def test_grains_edit_refuses_a_non_2d_subject() -> None:
    """A 3-D subject shares its first two axes with the source raster, so
    the shape check alone let it through — and it died inside
    `merge_labels_at` on numpy's ambiguous-truth-value error."""
    labels = np.zeros((20, 20, 3), dtype=np.float64)
    labels[2:8, 2:8, :] = 1
    labels[12:18, 12:18, :] = 2
    cube = DataStruct(
        data=labels,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(0.5, 0.0, "nm"),
            AxisCal(0.5, 0.0, "nm"),
            AxisCal(1.0, 0.0, "eV"),
        ),
    )
    with pytest.raises(ValueError, match="grain-label map"):
        ops.run(
            "grains_edit",
            cube,
            {"op": "merge", "points": [[4.0, 4.0], [14.0, 14.0]]},
            inputs={"source": _image(20, 20)},
        )


def test_edit_grains_rejects_a_3d_label_map() -> None:
    """The calc guard itself, independent of the op's kind check."""
    from fermiviewer.calc.grain_edit import edit_grains

    labels = np.ones((8, 8, 3), dtype=np.int64)
    with pytest.raises(ValueError, match="must be 2-D"):
        edit_grains(labels, np.zeros((8, 8)), "merge", [(1.0, 1.0)])
