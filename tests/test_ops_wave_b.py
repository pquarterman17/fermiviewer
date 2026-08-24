"""Wave-B ops (roadmap 3C): fft, vdf, gpa, lattice, ctf, atoms,
template_match, defects. Parity contract (ADR 0005 §1): each op's numbers
must equal a direct call to the SAME calc/ composition its route calls —
the wave-B lifts (calc/fourier.local_fft_region, calc/gpa.gpa_mean_strain,
calc/texture.template_match_rect, calc/atom_report.py) exist so this is
one code path, not two. One route-vs-op test (defects) checks the
shared-path claim end-to-end through the HTTP layer, including the ROI
CSV flattening and the inline-map resolution for the route's two
registered diagnostic images.

Envelope contract (ADR 0005 §5): every value op returns
value = {"outputs": [...]} of ADR 0004 {kind, name, data} envelopes; the
image producers (fft, vdf) return OpResult.derived like the filter ops.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

import fermiviewer.ops as ops
from fermiviewer.calc.atom_report import atom_column_report, pair_strain_payload
from fermiviewer.calc.ctf import estimate_ctf
from fermiviewer.calc.defects import count_defect_lines
from fermiviewer.calc.eds_maps import virtual_dark_field
from fermiviewer.calc.fourier import compute_fft, local_fft_region
from fermiviewer.calc.gpa import geometric_phase_analysis, gpa_mean_strain
from fermiviewer.calc.lattice import lattice_measure
from fermiviewer.calc.roi import embed_rect_roi
from fermiviewer.calc.texture import template_match_rect
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops._envelopes import OUTPUT_KINDS
from fermiviewer.ops.base import ParamError, produces_value_result
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.parser


def _lattice_image(n: int = 64, period: float = 8.0) -> np.ndarray:
    """A crossed sinusoid — clean FFT spots, detectable atom columns."""
    rng = np.random.default_rng(3)
    idx = np.arange(n, dtype=np.float64)
    yy, xx = np.meshgrid(idx, idx, indexing="ij")
    img = np.sin(2 * np.pi * xx / period) * np.sin(2 * np.pi * yy / period)
    return img + 2.0 + rng.normal(0.0, 0.05, (n, n))


def _lattice_ds() -> DataStruct:
    return DataStruct(
        data=_lattice_image(),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
        metadata={"source": "synthetic"},
    )


def _lines_image() -> np.ndarray:
    """A bright horizontal stripe on flat background — one defect line."""
    img = np.full((48, 56), 1.0)
    img[20:24, 5:50] = 8.0
    return img


def _lines_ds() -> DataStruct:
    return DataStruct(
        data=_lines_image(),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
        metadata={"source": "synthetic"},
    )


def _outputs(result) -> dict[str, dict]:
    """{name: envelope} for a wave op's value, validating the §5 contract."""
    assert set(result.value) == {"outputs"}
    by_name = {}
    for env in result.value["outputs"]:
        assert set(env) == {"kind", "name", "data"}
        assert env["kind"] in OUTPUT_KINDS
        assert isinstance(env["data"], dict)
        by_name[env["name"]] = env
    return by_name


# ── registration ─────────────────────────────────────────────────────


def test_wave_b_ops_are_registered_with_expected_categories() -> None:
    by_name = {s.name: s for s in ops.list_ops()}
    # image producers: filter category, no value flag
    for name in ("fft", "vdf"):
        assert by_name[name].category == "filter", name
        assert not by_name[name].produces_value, name
        assert not produces_value_result(by_name[name]), name
    # analysis implies a value result — the flag correctly stays False
    for name in ("gpa", "lattice", "ctf"):
        assert by_name[name].category == "analysis", name
        assert not by_name[name].produces_value, name
        assert produces_value_result(by_name[name]), name
    # structure does NOT imply it — explicit flag required
    for name in ("atoms", "template_match", "defects"):
        assert by_name[name].category == "structure", name
        assert by_name[name].produces_value, name
        assert produces_value_result(by_name[name]), name


# ── fft ───────────────────────────────────────────────────────────────


def test_fft_op_matches_direct_calc_and_drops_calibration() -> None:
    ds = _lattice_ds()
    result = ops.run("fft", ds)
    mag, _ = compute_fft(_lattice_image())
    assert result.produces_image
    np.testing.assert_allclose(result.derived.data, mag)
    # FFT space is not real space: parent calibration must NOT carry over
    assert not result.derived.axes[0].calibrated
    assert not result.derived.axes[1].calibrated


def test_fft_op_local_region_matches_direct_composition() -> None:
    ds = _lattice_ds()
    result = ops.run(
        "fft",
        ds,
        {
            "rect_r1": 1,
            "rect_c1": 1,
            "rect_r2": 32,
            "rect_c2": 32,
        },
    )
    mag, _ = compute_fft(local_fft_region(_lattice_image(), (1, 1, 32, 32)))
    np.testing.assert_allclose(result.derived.data, mag)
    with pytest.raises(ValueError, match="must be given together"):
        ops.run("fft", ds, {"rect_r1": 1, "rect_c1": 1})  # half a rect
    with pytest.raises(ValueError, match="too small"):
        ops.run(
            "fft",
            ds,
            {
                "rect_r1": 1,
                "rect_c1": 1,
                "rect_r2": 3,
                "rect_c2": 3,
            },
        )


# ── vdf ───────────────────────────────────────────────────────────────


def test_vdf_op_matches_direct_calc_and_keeps_calibration() -> None:
    ds = _lattice_ds()
    result = ops.run("vdf", ds, {"center_row": 33, "center_col": 41})
    direct = virtual_dark_field(_lattice_image(), (33, 41), mask_radius=10.0)
    np.testing.assert_allclose(result.derived.data, direct)
    # VDF is real space: calibration carries through, unlike fft
    assert result.derived.axes[0].calibrated


def test_vdf_op_rejects_bad_shape_choice() -> None:
    with pytest.raises(ParamError, match="not in"):
        ops.run(
            "vdf",
            _lattice_ds(),
            {
                "center_row": 33,
                "center_col": 41,
                "shape": "square",
            },
        )


# ── gpa ───────────────────────────────────────────────────────────────


def test_gpa_op_matches_direct_calc_composition() -> None:
    ds = _lattice_ds()
    result = ops.run("gpa", ds, {"g1x": 8.0, "g1y": 0.0, "g2x": 0.0, "g2y": 8.0})
    outs = _outputs(result)

    res = geometric_phase_analysis(_lattice_image(), (8.0, 0.0), (0.0, 8.0))
    means = gpa_mean_strain(res)
    np.testing.assert_allclose(np.asarray(outs["exx"]["data"]["values"]), res.exx)
    np.testing.assert_allclose(np.asarray(outs["rotation"]["data"]["values"]), res.rotation)
    assert outs["exx_mean"]["data"]["value"] == pytest.approx(means["exx"])
    assert outs["rotation_mean"]["data"]["unit"] == "rad"


def test_gpa_op_rejects_collinear_g_vectors() -> None:
    with pytest.raises(ValueError, match="linearly dependent"):
        ops.run(
            "gpa",
            _lattice_ds(),
            {
                "g1x": 8.0,
                "g1y": 0.0,
                "g2x": 16.0,
                "g2y": 0.0,
            },
        )


# ── lattice ───────────────────────────────────────────────────────────


def test_lattice_op_matches_direct_calc_and_image_calibration() -> None:
    ds = _lattice_ds()
    result = ops.run(
        "lattice",
        ds,
        {
            "spot1_row": 33,
            "spot1_col": 41,
            "spot2_row": 41,
            "spot2_col": 33,
        },
    )
    outs = _outputs(result)
    # pixel_size unset (NaN) -> the image's own calibration (0.5 nm/px)
    direct = lattice_measure((33, 41), (41, 33), (64, 64), pixel_size=0.5)
    assert outs["a"]["data"] == {"value": pytest.approx(direct.a), "unit": "nm"}
    assert outs["gamma_deg"]["data"]["value"] == pytest.approx(direct.gamma_deg)
    assert outs["d_spacing1"]["data"]["value"] == pytest.approx(direct.d_spacing1)
    assert outs["unit_cell_area"]["data"]["unit"] == "nm^2"

    # explicit pixel_size overrides the image's calibration (route parity)
    override = ops.run(
        "lattice",
        ds,
        {
            "spot1_row": 33,
            "spot1_col": 41,
            "spot2_row": 41,
            "spot2_col": 33,
            "pixel_size": 1.0,
        },
    )
    direct1 = lattice_measure((33, 41), (41, 33), (64, 64), pixel_size=1.0)
    assert _outputs(override)["a"]["data"]["value"] == pytest.approx(direct1.a)


def test_lattice_op_rejects_centre_spot() -> None:
    with pytest.raises(ValueError, match="centre"):
        ops.run(
            "lattice",
            _lattice_ds(),
            {
                "spot1_row": 33,
                "spot1_col": 33,
                "spot2_row": 41,
                "spot2_col": 33,
            },
        )


# ── ctf ───────────────────────────────────────────────────────────────


def test_ctf_op_matches_direct_calc_call() -> None:
    ds = _lattice_ds()
    result = ops.run("ctf", ds, {"voltage_kv": 300.0, "pixel_size_a": 0.8})
    outs = _outputs(result)
    direct = estimate_ctf(_lattice_image(), voltage_kv=300.0, pixel_size=0.8)
    fit = outs["ctf"]["data"]
    assert fit["coefficients"]["defocus_a"] == pytest.approx(direct.defocus)
    assert fit["coefficients"]["defocus_nm"] == pytest.approx(direct.defocus_nm)
    assert fit["coefficients"]["lambda_a"] == pytest.approx(direct.lambda_a)
    assert fit["r_squared"] == pytest.approx(direct.r_squared)
    assert fit["y_fit"] == direct.ctf_fit.tolist()
    curve = outs["radial_power"]["data"]
    assert curve["x"] == direct.radial_freq.tolist()
    assert curve["y"] == direct.radial_power.tolist()


def test_ctf_op_enforces_the_routes_exclusive_pixel_size_bound() -> None:
    # Field(gt=0) on the route; OpParam has no exclusive minimum, so the
    # op fn enforces it (ADR 0005 wave-B addendum)
    with pytest.raises(ValueError, match="pixel_size_a"):
        ops.run("ctf", _lattice_ds(), {"pixel_size_a": 0.0})
    # NaN slips through both `< minimum` and `<= 0` — the fn's
    # `not (x > 0)` spelling must reject it like the route's gt=0 does
    with pytest.raises(ValueError, match="pixel_size_a"):
        ops.run("ctf", _lattice_ds(), {"pixel_size_a": float("nan")})


# ── atoms ─────────────────────────────────────────────────────────────


def test_atoms_op_matches_direct_calc_composition() -> None:
    ds = _lattice_ds()
    result = ops.run("atoms", ds, {"min_separation": 4.0})
    outs = _outputs(result)

    report = atom_column_report(_lattice_image(), min_separation=4.0)
    assert outs["n_columns"]["data"]["value"] == report.n_columns
    table = outs["columns"]["data"]
    assert table["columns"] == ["x", "y", "amplitude"]
    assert table["position_convention"] == "(x, y), 1-based"
    assert len(table["rows"]) == report.n_columns
    np.testing.assert_allclose(np.asarray(table["rows"])[:, :2], report.positions)
    assert table["converged"] == report.converged
    lattice_fit = outs["lattice"]["data"]
    assert lattice_fit["valid"] == bool(report.lattice.valid)
    if report.lattice.valid:
        assert lattice_fit["coefficients"]["spacing"] == pytest.approx(
            float(report.lattice.spacing)
        )
    assert "strain" not in outs  # not requested


def test_atoms_op_strain_and_sublattice_match_direct_composition() -> None:
    ds = _lattice_ds()
    result = ops.run(
        "atoms",
        ds,
        {
            "min_separation": 4.0,
            "strain": True,
            "sublattices": 2,
        },
    )
    outs = _outputs(result)
    report = atom_column_report(_lattice_image(), min_separation=4.0, strain=True, sublattices=2)
    payload = pair_strain_payload(report.strain)
    strain = outs["strain"]["data"]
    assert strain["valid"] == payload["valid"]
    assert [row[0] for row in strain["rows"]] == payload["exx"]
    assert [row[3] for row in strain["rows"]] == payload["rotation"]
    if payload["exx_mean"] is not None:
        assert outs["exx_mean"]["data"]["value"] == pytest.approx(payload["exx_mean"])
    assert outs["columns"]["data"]["sublattice"] == report.sublattice.tolist()


# ── template_match ────────────────────────────────────────────────────


def test_template_match_op_matches_direct_calc_composition() -> None:
    ds = _lattice_ds()
    result = ops.run(
        "template_match",
        ds,
        {
            "rect_row": 5,
            "rect_col": 5,
            "rect_height": 8,
            "rect_width": 8,
        },
    )
    outs = _outputs(result)
    direct = template_match_rect(_lattice_image(), (5, 5, 8, 8))
    assert outs["n_matches"]["data"]["value"] == direct.n_matches
    table = outs["matches"]["data"]
    assert len(table["rows"]) == direct.n_matches
    np.testing.assert_allclose(np.asarray(table["rows"])[:, :2], direct.locations)
    np.testing.assert_allclose([row[2] for row in table["rows"]], direct.scores)
    assert outs["locations"]["data"]["points"] == direct.locations.tolist()


def test_template_match_op_rejects_out_of_bounds_rect() -> None:
    with pytest.raises(ValueError, match="out of bounds"):
        ops.run(
            "template_match",
            _lattice_ds(),
            {
                "rect_row": 60,
                "rect_col": 60,
                "rect_height": 10,
                "rect_width": 10,
            },
        )


# ── defects ───────────────────────────────────────────────────────────


def test_defects_op_matches_direct_calc_composition() -> None:
    ds = _lines_ds()
    result = ops.run("defects", ds, {"direction": 0.0})
    outs = _outputs(result)
    direct = count_defect_lines(_lines_image(), direction=0.0, pixel_size=0.5, pixel_unit="nm")
    assert outs["intersections"]["data"]["value"] == direct.intersection_count
    assert outs["density"]["data"] == {
        "value": pytest.approx(direct.density),
        "unit": direct.density_unit,
    }
    # calc reports intercept length in the CALIBRATED unit (it multiplies
    # by pixel_size), so the envelope must say "nm" here, never "px"
    assert outs["total_line_length"]["data"]["unit"] == "nm"
    assert outs["test_lines"]["data"]["value"] == direct.num_test_lines
    assert outs["test_line_positions"]["data"]["h_rows"] == direct.h_rows.tolist()
    np.testing.assert_allclose(np.asarray(outs["enhanced"]["data"]["values"]), direct.enhanced)
    np.testing.assert_array_equal(
        np.asarray(outs["mask"]["data"]["values"]),
        direct.binary_mask.astype(np.uint8),
    )


def test_defects_op_roi_and_foil_thickness_validation() -> None:
    ds = _lines_ds()
    roi = (10, 3, 30, 52)
    result = ops.run("defects", ds, {"direction": 0.0, "roi": "10,3,30,52"})
    direct = count_defect_lines(
        _lines_image(), roi=roi, direction=0.0, pixel_size=0.5, pixel_unit="nm"
    )
    # ROI-local maps come back embedded in the full frame, like the route
    embedded = embed_rect_roi(direct.enhanced, (48, 56), roi)
    np.testing.assert_allclose(np.asarray(_outputs(result)["enhanced"]["data"]["values"]), embedded)
    with pytest.raises(ValueError, match="foil_thickness"):
        ops.run("defects", ds, {"foil_thickness": -1.0})
    with pytest.raises(ValueError, match="r1,c1,r2,c2"):
        ops.run("defects", ds, {"roi": "10,3,30"})


def test_defects_op_matches_the_route_payload(tmp_path) -> None:
    """The ADR 0005 verification clause end-to-end: op output vs the HTTP
    route's payload for the same input — including the two diagnostic
    maps the route registers as session images and the op inlines."""
    store.clear()
    try:
        client = TestClient(create_app())
        img = _lines_image()
        h, w = img.shape
        f = write_mini_dm4(
            tmp_path / "lines.dm4",
            dims=[w, h],
            data=img.ravel(),
            cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
        )
        img_id = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]
        route = client.post(
            "/api/analyze/defects",
            json={"image_id": img_id, "direction": 0.0, "roi": [10, 3, 30, 52]},
        ).json()

        outs = _outputs(
            ops.run(
                "defects",
                _lines_ds(),
                {
                    "direction": 0.0,
                    "roi": "10,3,30,52",
                },
            )
        )
        assert outs["intersections"]["data"]["value"] == route["intersections"]
        assert outs["density"]["data"]["value"] == pytest.approx(route["density"])
        assert outs["density"]["data"]["unit"] == route["density_unit"]
        assert outs["test_lines"]["data"]["value"] == route["test_lines"]
        overlay = outs["test_line_positions"]
        # same overlay content the route returns inline
        assert overlay["data"]["h_rows"] == route["h_rows"]
        assert overlay["data"]["v_cols"] == route["v_cols"]
        # the route's registered "enhanced" image and the op's inline map
        # are the same pixels
        enhanced_id = route["enhanced"]["id"]
        enhanced_route = store.get(enhanced_id).data
        np.testing.assert_allclose(np.asarray(outs["enhanced"]["data"]["values"]), enhanced_route)
    finally:
        store.clear()


# ── schema hygiene ────────────────────────────────────────────────────


def test_wave_b_ops_reject_unknown_and_missing_params() -> None:
    ds = _lattice_ds()
    with pytest.raises(ParamError, match="unknown param"):
        ops.run("fft", ds, {"rect": "1,1,32,32"})
    with pytest.raises(ParamError, match="missing required"):
        ops.run("vdf", ds)
    with pytest.raises(ParamError, match="missing required"):
        ops.run("gpa", ds, {"g1x": 8.0, "g1y": 0.0})
    with pytest.raises(ParamError, match="missing required"):
        ops.run("template_match", ds, {"rect_row": 5})
