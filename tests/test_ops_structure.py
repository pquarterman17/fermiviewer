"""Wave-A structure/layer ops (roadmap 3B): particles, efd_similarity,
propose_region, grains, layers, layers_edit — plus interface_width in the
analysis category. Parity contract (ADR 0005 §1): each op's numbers must
equal a direct call to the SAME calc/ composition its route calls — the
wave-A lifts (calc/efd_rank.py, calc/region_propose.py,
calc/grain_report.py, calc/layers_report.py) exist so this is one code
path, not two. One route-vs-op test (particles) checks the shared-path
claim end-to-end through the HTTP layer.

Envelope contract (ADR 0005 §5): every new op returns
value = {"outputs": [...]} of ADR 0004 {kind, name, data} envelopes —
never a flat dict (that set is frozen).
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from fastapi.testclient import TestClient

import fermiviewer.ops as ops
from fermiviewer.calc.efd_rank import rank_by_efd
from fermiviewer.calc.grain_report import grain_report
from fermiviewer.calc.grains import segment_watershed
from fermiviewer.calc.layers import analyze_layers, recompute_layers
from fermiviewer.calc.layers_report import layer_result_to_dict
from fermiviewer.calc.particles import particle_analysis
from fermiviewer.calc.profile_stats import fit_interface_width
from fermiviewer.calc.region_propose import propose_region
from fermiviewer.calc.roi import embed_rect_roi, extract_rect_roi
from fermiviewer.calc.shape_metrics import (
    ClassThresholds,
    classify_shapes,
    shape_descriptors,
)
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops._envelopes import OUTPUT_KINDS
from fermiviewer.ops.base import ParamError, produces_value_result
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.parser

_WAVE_A_STRUCTURE = (
    "particles",
    "efd_similarity",
    "propose_region",
    "grains",
    "layers",
    "layers_edit",
)


def _blobs(h: int = 48, w: int = 56) -> np.ndarray:
    """Two well-separated bright blobs on a dark background — one squarish,
    one elongated — enough structure for particles/EFD/region proposal."""
    img = np.full((h, w), 1.0)
    img[6:16, 8:18] = 10.0  # squarish
    img[26:34, 20:44] = 12.0  # elongated rod
    return img


def _blobs_ds(calibrated: bool = True) -> DataStruct:
    axes = (
        (AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")) if calibrated else (AxisCal(), AxisCal())
    )
    return DataStruct(
        data=_blobs(),
        kind=DataKind.IMAGE,
        axes=axes,
        metadata={"source": "synthetic"},
    )


def _layered() -> np.ndarray:
    """Three flat bands with sharp interfaces + a little deterministic noise."""
    rng = np.random.default_rng(7)
    bands = np.concatenate([np.full((18, 40), v) for v in (0.1, 0.9, 0.35)], axis=0)
    return bands + rng.normal(0.0, 0.01, bands.shape)


def _layered_ds() -> DataStruct:
    return DataStruct(
        data=_layered(),
        kind=DataKind.IMAGE,
        axes=(AxisCal(2.0, 0.0, "nm"), AxisCal(2.0, 0.0, "nm")),
        metadata={"source": "synthetic"},
    )


def _outputs(result) -> dict[str, dict]:
    """{name: envelope} for a wave op's value, validating the §5 contract."""
    assert set(result.value) == {"outputs"}, "wave ops carry ONLY the envelope list"
    by_name = {}
    for env in result.value["outputs"]:
        assert set(env) == {"kind", "name", "data"}
        assert env["kind"] in OUTPUT_KINDS
        assert isinstance(env["data"], dict)
        by_name[env["name"]] = env
    return by_name


# ── registration ─────────────────────────────────────────────────────


def test_wave_a_ops_are_registered_with_expected_categories() -> None:
    by_name = {s.name: s for s in ops.list_ops()}
    for name in _WAVE_A_STRUCTURE:
        assert by_name[name].category == "structure", name
        # "structure" is a NEW category — not "analysis" — so the flag must
        # be explicit for produces_value_result to classify these as values
        assert by_name[name].produces_value, name
        assert produces_value_result(by_name[name]), name
    # interface_width rides the analysis category (distribution_fit's
    # ds-ignoring precedent): the category implies a value result, so the
    # explicit flag correctly stays False
    assert by_name["interface_width"].category == "analysis"
    assert not by_name["interface_width"].produces_value
    assert produces_value_result(by_name["interface_width"])


def test_every_wave_a_op_returns_the_envelope_contract() -> None:
    blobs, layered = _blobs_ds(), _layered_ds()
    x = np.linspace(0.0, 10.0, 40)
    y = np.tanh(x - 5.0)
    runs = {
        "particles": (blobs, {}),
        "efd_similarity": (blobs, {"ref_id": 1}),
        "propose_region": (blobs, {"seed_x": 0.22, "seed_y": 0.22}),
        "grains": (blobs, {"min_area": 5}),
        "layers": (layered, {}),
        "layers_edit": (layered, {"positions": "18,36"}),
        "interface_width": (
            blobs,
            {
                "x": ",".join(map(str, x)),
                "y": ",".join(map(str, y)),
            },
        ),
    }
    for name, (ds, params) in runs.items():
        result = ops.run(name, ds, params)
        assert not result.produces_image, name
        assert _outputs(result), name  # at least one envelope


# ── particles ─────────────────────────────────────────────────────────


def test_particles_op_matches_direct_calc_composition() -> None:
    ds = _blobs_ds()
    result = ops.run("particles", ds)
    outs = _outputs(result)

    res = particle_analysis(
        _blobs(), threshold=None, polarity="bright", min_area=1,
        pixel_size=0.5, pixel_area=0.25,  # the op reads ds.pixel_area
    )
    desc = shape_descriptors(res.labels)
    classes = classify_shapes(desc.aspect_ratio, desc.circularity, desc.solidity, None)
    assert outs["n_particles"]["data"]["value"] == res.n_particles
    assert outs["threshold"]["data"]["value"] == pytest.approx(res.threshold)
    table = outs["table"]["data"] if "table" in outs else outs["particles"]["data"]
    assert table["columns"][:4] == ["id", "centroid_row", "centroid_col", "area"]
    assert table["centroid_convention"] == "(row, col), 1-based"
    assert table["shape_class"] == list(classes)
    assert len(table["rows"]) == res.n_particles
    for row, p, i in zip(table["rows"], res.particles, range(res.n_particles), strict=True):
        assert row[0] == p.id
        assert row[1] == pytest.approx(p.centroid[0])
        assert row[2] == pytest.approx(p.centroid[1])
        assert row[3] == pytest.approx(p.area)
        assert row[8] == pytest.approx(float(desc.circularity[i]))
    np.testing.assert_array_equal(np.asarray(outs["labels"]["data"]["values"]), res.labels)
    # calibrated columns are real numbers on a calibrated image
    area_cal = table["rows"][0][table["columns"].index("area_calibrated")]
    assert area_cal == pytest.approx(res.particles[0].area_calibrated)


def test_particles_op_class_threshold_sentinels_resolve_to_calc_defaults() -> None:
    """A partial override must merge into calc's ClassThresholds — never
    into literal defaults copied here (the documented drift bug)."""
    ds = _blobs_ds()
    res = particle_analysis(
        _blobs(), threshold=None, polarity="bright", min_area=1,
        pixel_size=0.5, pixel_area=0.25,  # the op reads ds.pixel_area
    )
    desc = shape_descriptors(res.labels)

    # sentinel default (all NaN) == thresholds=None == pure calc defaults
    default_run = ops.run("particles", ds)
    expected_default = classify_shapes(desc.aspect_ratio, desc.circularity, desc.solidity, None)
    assert _outputs(default_run)["particles"]["data"]["shape_class"] == list(expected_default)

    # one override rides on top of the calc defaults for the other three
    # (10.0 pushes the elongated blob's ~3:1 aspect out of rod-like, so the
    # override observably changes the outcome)
    override_run = ops.run("particles", ds, {"rod_min_aspect": 10.0})
    expected_override = classify_shapes(
        desc.aspect_ratio,
        desc.circularity,
        desc.solidity,
        dataclasses.replace(ClassThresholds(), rod_min_aspect=10.0),
    )
    assert _outputs(override_run)["particles"]["data"]["shape_class"] == list(expected_override)
    assert list(expected_override) != list(expected_default)  # override bites


def test_particles_op_matches_the_route_payload(tmp_path) -> None:
    """The ADR 0005 verification clause, literally: op output vs the HTTP
    route's payload for the same input."""
    store.clear()
    try:
        client = TestClient(create_app())
        img = _blobs()
        h, w = img.shape
        f = write_mini_dm4(
            tmp_path / "blobs.dm4",
            dims=[w, h],
            data=img.ravel(),
            cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
        )
        img_id = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]
        route = client.post("/api/analyze/particles", json={"image_id": img_id}).json()

        result = ops.run("particles", _blobs_ds())
        outs = _outputs(result)
        table = outs["particles"]["data"]
        assert outs["n_particles"]["data"]["value"] == route["n_particles"]
        assert outs["threshold"]["data"]["value"] == pytest.approx(route["threshold"])
        assert table["shape_class"] == [p["shape_class"] for p in route["particles"]]
        for row, p in zip(table["rows"], route["particles"], strict=True):
            assert row[0] == p["id"]
            assert row[1] == pytest.approx(p["centroid"][0])
            assert row[3] == pytest.approx(p["area"])
            assert row[6] == pytest.approx(p["area_calibrated"])
            assert row[13] == pytest.approx(p["feret_max"])
    finally:
        store.clear()


# ── efd_similarity ────────────────────────────────────────────────────


def test_efd_similarity_op_matches_direct_calc_composition() -> None:
    ds = _blobs_ds()
    result = ops.run("efd_similarity", ds, {"ref_id": 1})
    outs = _outputs(result)

    res = particle_analysis(_blobs(), threshold=None, polarity="bright", min_area=1)
    ranking = rank_by_efd(res.labels, [p.id for p in res.particles], 1)
    assert outs["ranked"]["data"]["rows"] == [
        [r["id"], pytest.approx(r["distance"])] for r in ranking.ranked
    ]
    assert outs["ranked"]["data"]["rows"][0][0] == 1  # reference ranks first at 0
    assert outs["ranked"]["data"]["rows"][0][1] == pytest.approx(0.0)
    assert outs["skipped"]["data"]["rows"] == [[s["id"], s["reason"]] for s in ranking.skipped]
    assert outs["n_harmonics"]["data"]["value"] == 10


def test_efd_similarity_op_rejects_unknown_ref_id() -> None:
    with pytest.raises(ValueError, match="unknown ref_id"):
        ops.run("efd_similarity", _blobs_ds(), {"ref_id": 99})


# ── propose_region ────────────────────────────────────────────────────


def test_propose_region_op_matches_direct_calc_call() -> None:
    ds = _blobs_ds()
    result = ops.run("propose_region", ds, {"seed_x": 0.22, "seed_y": 0.22})
    outs = _outputs(result)

    direct = propose_region(
        _blobs(), seed=(0.22, 0.22), pixel_size=0.5, pixel_area=0.25, unit="nm"
    )
    assert outs["proposal"]["data"]["points"] == [list(p) for p in direct.points]
    assert outs["proposal"]["data"]["closed"] is False
    assert outs["area_px"]["data"]["value"] == pytest.approx(direct.area_px)
    assert outs["area_calibrated"]["data"] == {
        "value": pytest.approx(direct.area_calibrated),
        "unit": "nm^2",
    }


def test_propose_region_op_uncalibrated_omits_calibrated_area() -> None:
    result = ops.run(
        "propose_region",
        _blobs_ds(calibrated=False),
        {"seed_x": 0.22, "seed_y": 0.22},
    )
    assert "area_calibrated" not in _outputs(result)


def test_propose_region_op_sentinel_validation() -> None:
    ds = _blobs_ds()
    with pytest.raises(ValueError, match="need either seed or rect"):
        ops.run("propose_region", ds)  # all sentinels NaN
    with pytest.raises(ValueError, match="must be given together"):
        ops.run("propose_region", ds, {"seed_x": 0.2})  # half a seed
    with pytest.raises(ValueError, match="must be given together"):
        ops.run(
            "propose_region",
            ds,
            {
                "rect_x0": 0.1,
                "rect_y0": 0.1,
                "rect_x1": 0.4,  # 3 of 4
            },
        )
    # a rect seed alone works (centre becomes the seed point)
    result = ops.run(
        "propose_region",
        ds,
        {
            "rect_x0": 0.1,
            "rect_y0": 0.08,
            "rect_x1": 0.36,
            "rect_y1": 0.38,
        },
    )
    direct = propose_region(
        _blobs(), rect=(0.1, 0.08, 0.36, 0.38), pixel_size=0.5,
        pixel_area=0.25, unit="nm",
    )
    assert _outputs(result)["area_px"]["data"]["value"] == pytest.approx(direct.area_px)


# ── grains ────────────────────────────────────────────────────────────


def test_grains_op_matches_direct_calc_composition() -> None:
    ds = _blobs_ds()
    result = ops.run("grains", ds, {"min_area": 5})
    outs = _outputs(result)

    raster = _blobs()
    seg = segment_watershed(
        raster,
        method="gradient",
        granularity=0.05,
        compactness=0.001,
        min_area=5,
        n_superpixels=400,
        merge_threshold=0.08,
        orientation_sigma=2.0,
        denoise_sigma=0.0,
        robust=True,
    )
    report = grain_report(
        seg.labels, raster, pixel_size=0.5, pixel_area=0.25, unit="nm",
        spacing=(0.5, 0.5),
    )
    assert outs["n_grains"]["data"]["value"] == report.n_grains
    assert outs["boundary_network_px"]["data"]["value"] == pytest.approx(report.boundary_network_px)
    assert outs["mean_diameter_px"]["data"]["value"] == pytest.approx(report.mean_diameter_px)
    if np.isfinite(report.astm_grain_size):
        assert outs["astm_grain_size"]["data"]["value"] == pytest.approx(report.astm_grain_size)
    table = outs["grains"]["data"]
    assert table["columns"] == [
        "area_px",
        "perimeter_crofton_px",
        "perimeter_calibrated",
        "eccentricity",
        "equiv_diameter_px",
        "diameter_calibrated",
    ]
    assert len(table["rows"]) == report.n_grains
    np.testing.assert_allclose([row[0] for row in table["rows"]], report.area_px)
    # the calibrated perimeter is the op's, not a re-scaling of the pixel one
    np.testing.assert_allclose(
        [row[2] for row in table["rows"]], report.perimeter_calibrated
    )
    np.testing.assert_array_equal(np.asarray(outs["labels"]["data"]["values"]), report.labels)


def test_grains_op_roi_matches_direct_roi_composition() -> None:
    ds = _blobs_ds()
    roi = (3, 3, 40, 50)
    result = ops.run("grains", ds, {"min_area": 5, "roi": "3,3,40,50"})

    raster = _blobs()
    seg = segment_watershed(
        extract_rect_roi(raster, roi),
        method="gradient",
        granularity=0.05,
        compactness=0.001,
        min_area=5,
        n_superpixels=400,
        merge_threshold=0.08,
        orientation_sigma=2.0,
        denoise_sigma=0.0,
        robust=True,
    )
    labels = embed_rect_roi(seg.labels, raster.shape, roi)
    report = grain_report(
        labels, raster, pixel_size=0.5, pixel_area=0.25, unit="nm"
    )
    outs = _outputs(result)
    assert outs["n_grains"]["data"]["value"] == report.n_grains
    np.testing.assert_array_equal(np.asarray(outs["labels"]["data"]["values"]), report.labels)


def test_grains_op_rejects_a_malformed_roi() -> None:
    with pytest.raises(ValueError, match="r1,c1,r2,c2"):
        ops.run("grains", _blobs_ds(), {"roi": "3,3,40"})


# ── layers / layers_edit ──────────────────────────────────────────────


def test_layers_op_matches_the_route_serialisation() -> None:
    ds = _layered_ds()
    result = ops.run("layers", ds, {"waviness": True})
    outs = _outputs(result)

    res = analyze_layers(_layered(), pixel_size=2.0, unit="nm", waviness=True)
    report = layer_result_to_dict(res)

    curve = outs["depth_profile"]["data"]
    assert curve["x"] == report["depth_pos"]
    assert curve["y"] == report["depth_profile"]
    assert curve["axis"] == report["axis"]
    assert curve["pixel_size"] == report["pixel_size"]

    table = outs["layers"]["data"]
    assert len(table["rows"]) == len(report["layers"])
    for row, lyr in zip(table["rows"], report["layers"], strict=True):
        assert row[3] == pytest.approx(lyr["thickness"])
        assert row[5] == (
            lyr["conformality"]
            if lyr["conformality"] is None
            else pytest.approx(lyr["conformality"])
        )

    assert len(report["interfaces"]) >= 1
    for k, interface in enumerate(report["interfaces"]):
        fit = outs[f"interface_{k}"]["data"]
        assert fit["model"] == "erf"
        assert fit["coefficients"]["position"] == pytest.approx(interface["position"])
        assert fit["coefficients"]["sigma_erf"] == pytest.approx(interface["sigma_erf"])
        assert fit["r_squared"] == pytest.approx(interface["r_squared"])
        assert fit["trace"] == interface["trace"]
        assert fit["roughness"] == interface["roughness"]

    if report["tilt_deg"] is not None:
        assert outs["tilt_deg"]["data"]["value"] == pytest.approx(report["tilt_deg"])


def test_layers_edit_op_matches_direct_recompute() -> None:
    ds = _layered_ds()
    result = ops.run("layers_edit", ds, {"positions": "18,36"})
    outs = _outputs(result)

    res = recompute_layers(_layered(), [18.0, 36.0], axis="y", pixel_size=2.0, unit="nm")
    report = layer_result_to_dict(res)
    table = outs["layers"]["data"]
    assert [row[0] for row in table["rows"]] == [lyr["index"] for lyr in report["layers"]]
    for row, lyr in zip(table["rows"], report["layers"], strict=True):
        assert row[3] == pytest.approx(lyr["thickness"])
    assert outs["interface_0"]["data"]["coefficients"]["position"] == pytest.approx(
        report["interfaces"][0]["position"]
    )


def test_layers_op_rejects_non_image_input() -> None:
    spec = DataStruct(
        data=np.arange(6, dtype=np.float64),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(1.0, 0.0, "eV"),),
    )
    with pytest.raises(ValueError, match="2-D image"):
        ops.run("layers", spec)


# ── interface_width ───────────────────────────────────────────────────


def test_interface_width_op_matches_direct_calc_call() -> None:
    x = np.linspace(0.0, 10.0, 60)
    y = 2.0 + 3.0 * (1.0 + np.tanh((x - 4.5) / 1.2)) / 2.0
    result = ops.run(
        "interface_width",
        _blobs_ds(),
        {
            "x": ",".join(map(str, x)),
            "y": ",".join(map(str, y)),
            "model": "sigmoid",
        },
    )
    outs = _outputs(result)
    fit = fit_interface_width(x, y, model="sigmoid")
    data = outs["interface_width"]["data"]
    assert data["model"] == fit.model
    assert data["coefficients"]["center"] == pytest.approx(fit.center)
    assert data["coefficients"]["sigma"] == pytest.approx(fit.sigma)
    assert data["coefficients"]["width_10_90"] == pytest.approx(fit.width_10_90)
    assert data["r_squared"] == pytest.approx(fit.r_squared)
    assert data["x_fit"] == fit.x_fit.tolist()
    assert data["y_fit"] == fit.y_fit.tolist()


def test_interface_width_op_rejects_mismatched_lists() -> None:
    with pytest.raises(ValueError):
        ops.run("interface_width", _blobs_ds(), {"x": "1,2,3,4", "y": "1,2,3"})


# ── schema hygiene ────────────────────────────────────────────────────


def test_wave_a_ops_reject_unknown_params() -> None:
    with pytest.raises(ParamError, match="unknown param"):
        ops.run("particles", _blobs_ds(), {"thershold": 0.5})
    with pytest.raises(ParamError, match="not in"):
        ops.run("particles", _blobs_ds(), {"polarity": "sideways"})
    with pytest.raises(ParamError, match="missing required"):
        ops.run("efd_similarity", _blobs_ds())
    with pytest.raises(ParamError, match="not in"):
        ops.run("grains", _blobs_ds(), {"method": "psychic"})
