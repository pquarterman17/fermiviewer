"""Wave-C ops (roadmap 3D): diffraction_detect, diffraction_calibrate,
diffraction_simulate. Parity contract (ADR 0005 §1): each op's numbers
must equal a direct call to the SAME calc/ composition its route calls —
the wave-C lifts (calc/diffraction.find_spots_roi,
calc/diffraction_calib.calibrate_rings,
calc/phase_registry.standard_d_spacing) exist so this is one code path.
One route-vs-op test (diffraction_detect with a rect ROI) checks the
shared-path claim end-to-end through the HTTP layer, exercising the
_Roi discriminator flattening and the offset lift.

Envelope contract (ADR 0005 §5): every op returns
value = {"outputs": [...]} of ADR 0004 {kind, name, data} envelopes;
diffraction_simulate's rendered pattern inlines as a `map` envelope per
the wave-B standing rule.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

import fermiviewer.ops as ops
from fermiviewer.calc.diffraction import find_spots_roi, simulate
from fermiviewer.calc.diffraction_calib import calibrate_rings, camera_constant
from fermiviewer.calc.phase_registry import registry, standard_d_spacing
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops._envelopes import OUTPUT_KINDS
from fermiviewer.ops.base import ParamError, produces_value_result
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.parser

_WAVE_C = ("diffraction_detect", "diffraction_calibrate", "diffraction_simulate")


def _spots_image(n: int = 64, ring_r: float = 16.0) -> np.ndarray:
    """Four bright Gaussian spots on a ring around the pattern centre —
    far enough out to clear detect's min_radius default (10 px)."""
    yy, xx = np.mgrid[0:n, 0:n]
    centre = (n // 2 + 1, n // 2 + 1)  # 1-based (matches calc conventions)
    img = np.full((n, n), 0.05)
    for ang_deg in (0, 90, 180, 270):
        ang = np.deg2rad(ang_deg)
        sr = centre[0] + ring_r * np.sin(ang)
        sc = centre[1] + ring_r * np.cos(ang)
        img += np.exp(-(((yy + 1 - sr) ** 2 + (xx + 1 - sc) ** 2) / (2 * 2.0**2)))
    return img


def _ring_image(n: int = 64, radius: float = 20.0) -> np.ndarray:
    """A single sharp diffraction ring — calibrate_rings' happy path."""
    yy, xx = np.mgrid[0:n, 0:n]
    centre = (n // 2 + 1, n // 2 + 1)
    rad = np.hypot(yy + 1 - centre[0], xx + 1 - centre[1])
    return np.exp(-((rad - radius) ** 2) / (2 * 1.5**2))


def _ds(img: np.ndarray) -> DataStruct:
    return DataStruct(
        data=img,
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata={"source": "synthetic"},
    )


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


def test_wave_c_ops_are_registered_with_expected_categories() -> None:
    by_name = {s.name: s for s in ops.list_ops()}
    for name in _WAVE_C:
        assert by_name[name].category == "diffraction", name
        # `diffraction` does NOT imply a value result (radial_profile
        # precedent) — the explicit flag is required
        assert by_name[name].produces_value, name
        assert produces_value_result(by_name[name]), name


# ── diffraction_detect ────────────────────────────────────────────────


def test_detect_op_matches_direct_calc_call() -> None:
    result = ops.run("diffraction_detect", _ds(_spots_image()))
    outs = _outputs(result)
    direct = find_spots_roi(_spots_image())
    assert outs["n_spots"]["data"]["value"] == direct.shape[0]
    assert direct.shape[0] > 0  # the fixture must actually exercise spots
    assert outs["spots"]["data"]["rows"] == direct.tolist()
    assert outs["spots"]["data"]["position_convention"] == "(row, col), 1-based"
    assert outs["spot_positions"]["data"]["points"] == direct.tolist()


def test_detect_op_rect_and_circle_rois_match_direct_composition() -> None:
    ds = _ds(_spots_image())
    rect = ops.run(
        "diffraction_detect",
        ds,
        {
            "roi_kind": "rect",
            "roi_r0": 0,
            "roi_c0": 0,
            "roi_r1": 40,
            "roi_c1": 64,
        },
    )
    direct_rect = find_spots_roi(
        _spots_image(), {"kind": "rect", "r0": 0, "c0": 0, "r1": 40, "c1": 64}
    )
    assert _outputs(rect)["spots"]["data"]["rows"] == direct_rect.tolist()
    # spots come back in FULL-image coordinates (the offset lift)
    assert _outputs(rect)["n_spots"]["data"]["value"] < 8  # ROI cut some out

    circle = ops.run(
        "diffraction_detect",
        ds,
        {
            "roi_kind": "circle",
            "roi_cr": 32,
            "roi_cc": 32,
            "roi_radius": 20,
        },
    )
    direct_circle = find_spots_roi(
        _spots_image(), {"kind": "circle", "cr": 32, "cc": 32, "radius": 20}
    )
    assert _outputs(circle)["spots"]["data"]["rows"] == direct_circle.tolist()


def test_detect_op_roi_discriminator_validation() -> None:
    ds = _ds(_spots_image())
    with pytest.raises(ValueError, match="roi_r0/roi_c0/roi_r1/roi_c1"):
        ops.run("diffraction_detect", ds, {"roi_kind": "rect"})  # no coords
    with pytest.raises(ValueError, match="must be given together"):
        ops.run(
            "diffraction_detect",
            ds,
            {
                "roi_kind": "rect",
                "roi_r0": 0,
                "roi_c0": 0,
                "roi_r1": 40,
            },
        )  # 3 of 4
    with pytest.raises(ValueError, match="roi_cr/roi_cc/roi_radius"):
        ops.run("diffraction_detect", ds, {"roi_kind": "circle"})
    with pytest.raises(ParamError, match="not in"):
        ops.run("diffraction_detect", ds, {"roi_kind": "ellipse"})


def test_detect_op_rejects_non_image_input() -> None:
    cube = DataStruct(
        data=np.ones((4, 5, 7)),
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(), AxisCal(), AxisCal(1.0, 0.0, "eV")),
        metadata={},
    )
    # raster_of would silently SUM the cube — the op must mirror the
    # route's explicit 400 guard instead
    with pytest.raises(ValueError, match="2D image"):
        ops.run("diffraction_detect", cube)


def test_detect_op_matches_the_route_payload(tmp_path) -> None:
    """The ADR 0005 verification clause end-to-end: op output vs the HTTP
    route's payload for the same input, ROI included."""
    store.clear()
    try:
        client = TestClient(create_app())
        img = _spots_image()
        h, w = img.shape
        f = write_mini_dm4(tmp_path / "dp.dm4", dims=[w, h], data=img.ravel())
        img_id = client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]
        route = client.post(
            "/api/diffraction/detect",
            json={
                "image_id": img_id,
                "roi": {"kind": "rect", "r0": 0, "c0": 0, "r1": 40, "c1": 64},
            },
        ).json()

        # run the op on the SAME parsed DataStruct the route analyzed — the
        # DM4 round-trip is lossy for this float image, so comparing against
        # a fresh in-memory copy would compare different inputs
        outs = _outputs(
            ops.run(
                "diffraction_detect",
                store.get(img_id),
                {
                    "roi_kind": "rect",
                    "roi_r0": 0,
                    "roi_c0": 0,
                    "roi_r1": 40,
                    "roi_c1": 64,
                },
            )
        )
        assert outs["n_spots"]["data"]["value"] == route["n"]
        assert outs["spots"]["data"]["rows"] == route["spots"]
    finally:
        store.clear()


# ── diffraction_calibrate ─────────────────────────────────────────────


def test_calibrate_op_matches_direct_calc_composition() -> None:
    result = ops.run("diffraction_calibrate", _ds(_ring_image()))
    outs = _outputs(result)
    direct = calibrate_rings(_ring_image())
    fit = outs["ellipse"]["data"]
    assert fit["n_points"] == direct.n_points
    assert fit["rms_residual_px"] == pytest.approx(direct.rms_residual_px)
    coeff = fit["coefficients"]
    assert coeff["mean_radius"] == pytest.approx(direct.ellipse.mean_radius)
    assert coeff["a"] == pytest.approx(direct.ellipse.a)
    assert coeff["center_row"] == pytest.approx(direct.ellipse.center_row)
    # no anchor given: the two anchor scalars are absent — not null
    assert "d_known_ang" not in outs
    assert "camera_constant_px_ang" not in outs


def test_calibrate_op_standard_phase_anchor_matches_direct() -> None:
    result = ops.run(
        "diffraction_calibrate",
        _ds(_ring_image()),
        {
            "standard_phase": "Gold",
            "hkl_h": 1,
            "hkl_k": 1,
            "hkl_l": 1,
        },
    )
    outs = _outputs(result)
    d = standard_d_spacing("Gold", (1, 1, 1))
    assert d is not None and d > 0
    direct = calibrate_rings(_ring_image())
    assert outs["d_known_ang"]["data"] == {
        "value": pytest.approx(d),
        "unit": "A",
    }
    assert outs["camera_constant_px_ang"]["data"]["value"] == pytest.approx(
        camera_constant(d, direct.ellipse.mean_radius)
    )
    # explicit d_known_ang wins over the phase anchor, like the route
    explicit = ops.run(
        "diffraction_calibrate",
        _ds(_ring_image()),
        {
            "d_known_ang": 2.0,
            "standard_phase": "Gold",
            "hkl_h": 1,
            "hkl_k": 1,
            "hkl_l": 1,
        },
    )
    assert _outputs(explicit)["d_known_ang"]["data"]["value"] == pytest.approx(2.0)


def test_calibrate_op_error_paths() -> None:
    # too few ring points (image too small for any ring: auto r_max
    # 0.95*min(margins) falls at or below r_min) — the route's 422
    with pytest.raises(ValueError, match="too few ring points"):
        ops.run("diffraction_calibrate", _ds(np.zeros((8, 10)) + 0.5))
    # unknown standard phase
    with pytest.raises(ValueError, match="unknown standard phase"):
        ops.run(
            "diffraction_calibrate",
            _ds(_ring_image()),
            {
                "standard_phase": "Unobtainium",
                "hkl_h": 1,
                "hkl_k": 1,
                "hkl_l": 1,
            },
        )


# ── diffraction_simulate ──────────────────────────────────────────────


def test_simulate_op_matches_direct_calc_composition() -> None:
    result = ops.run(
        "diffraction_simulate",
        _ds(_ring_image()),
        {
            "phase_name": "Gold",
            "image_rows": 64,
            "image_cols": 64,
        },
    )
    outs = _outputs(result)
    direct = simulate("Gold", image_size=(64, 64), phase=registry.find("Gold"))
    np.testing.assert_allclose(np.asarray(outs["pattern"]["data"]["values"]), direct.image)
    table = outs["spots"]["data"]
    assert table["phase"] == direct.phase_name
    assert table["formula"] == direct.formula
    assert table["zone_axis"] == list(direct.zone_axis)
    assert len(table["rows"]) == len(direct.spots)
    # spots[0] is the direct beam: infinite d -> None, like the route
    assert table["rows"][0][3] is None
    for row, s in zip(table["rows"][1:], direct.spots[1:], strict=True):
        assert row[:3] == [s.hkl[0], s.hkl[1], s.hkl[2]]
        assert row[3] == pytest.approx(s.d_spacing)
        assert row[4] == pytest.approx(s.intensity)
    assert outs["lam_angstrom"]["data"]["value"] == pytest.approx(direct.lam)


def test_simulate_op_zone_axis_and_errors() -> None:
    ds = _ds(_ring_image())
    tilted = ops.run(
        "diffraction_simulate",
        ds,
        {
            "phase_name": "Gold",
            "zone_u": 0,
            "zone_v": 1,
            "zone_w": 1,
            "image_rows": 64,
            "image_cols": 64,
        },
    )
    direct = simulate(
        "Gold",
        zone_axis=(0, 1, 1),
        image_size=(64, 64),
        phase=registry.find("Gold"),
    )
    assert _outputs(tilted)["spots"]["data"]["zone_axis"] == [0, 1, 1]
    assert len(_outputs(tilted)["spots"]["data"]["rows"]) == len(direct.spots)
    with pytest.raises((KeyError, ValueError)):
        ops.run("diffraction_simulate", ds, {"phase_name": "Unobtainium"})
    with pytest.raises(ParamError, match="missing required"):
        ops.run("diffraction_simulate", ds)
    with pytest.raises(ParamError, match="not in"):
        ops.run(
            "diffraction_simulate",
            ds,
            {
                "phase_name": "Gold",
                "scattering_model": "dft",
            },
        )
