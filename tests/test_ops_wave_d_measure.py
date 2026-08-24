"""Wave-D measure ops (roadmap 3E): line_profile, roi_stats, box_profile,
tilted_distance, sum_spectrum, intensity_histogram, scalebar_detect
(ops/catalogue_measure.py) and the strip_databar filter op appended to
ops/catalogue.py. Parity contract (ADR 0005 §1): each op's numbers must
equal a direct call to the SAME calc/ (or io/) function its route calls.

Envelope contract (ADR 0005 §5): every value op returns
value = {"outputs": [...]} of ADR 0004 {kind, name, data} envelopes with
unique names; non-finite scalars and dishonest sigmas are absent, not
null.
"""

from __future__ import annotations

import numpy as np
import pytest

import fermiviewer.ops as ops
from fermiviewer.calc.profile_stats import box_integrate, measure_distance, roi_stats
from fermiviewer.calc.profiles import line_profile_stats
from fermiviewer.calc.raster import region_sum_spectrum
from fermiviewer.calc.render import histogram
from fermiviewer.calc.scalebar_detect import detect_scale_bar
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops import (
    catalogue_measure,  # noqa: F401
    catalogue_measure_reads,  # noqa: F401  (registers the wave-D measure ops)
)
from fermiviewer.ops._envelopes import OUTPUT_KINDS
from fermiviewer.ops.base import ParamError, produces_value_result

pytestmark = pytest.mark.parser

_ANALYSIS = (
    "line_profile",
    "roi_stats",
    "box_profile",
    "tilted_distance",
    "intensity_histogram",
    "scalebar_detect",
)


def _image_data(h: int = 12, w: int = 16) -> np.ndarray:
    """A smooth but non-trivial surface (distinct row/col gradients plus a
    bump) so profiles and stats have real structure."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    return 0.7 * yy + 0.3 * xx + 5.0 * np.exp(-((yy - 5) ** 2 + (xx - 8) ** 2) / 18.0)


def _ds(data: np.ndarray, calibrated: bool = True) -> DataStruct:
    cal = AxisCal(0.5, 0.0, "nm") if calibrated else AxisCal()
    return DataStruct(
        data=data,
        kind=DataKind.IMAGE,
        axes=(cal, cal),
        metadata={"source": "synthetic"},
    )


def _cube() -> DataStruct:
    data = np.arange(4 * 5 * 7, dtype=np.float64).reshape(4, 5, 7)
    return DataStruct(
        data=data,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm"), AxisCal(0.3, 100.0, "eV")),
        metadata={"source": "synthetic"},
    )


def _spectrum() -> DataStruct:
    return DataStruct(
        data=np.arange(9, dtype=np.float64),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(1.0, 0.0, "eV"),),
        metadata={"source": "synthetic"},
    )


def _scalebar_image(h: int = 32, w: int = 64) -> np.ndarray:
    """A dark image with a synthetic white horizontal bar in the bottom-15%
    strip — detect_scale_bar's found path (run of 30 px: >= 20, >= 3% of
    w, <= 60% of w, bar height 1)."""
    img = np.zeros((h, w), dtype=np.float64)
    img[h - 5, 10:40] = 255.0
    return img


def _databar_ds(h: int = 24, w: int = 16, image_rows: int = 20) -> DataStruct:
    """A metadata-bearing image whose parser recorded the scanned raster
    height (`image_rows` < the array height) — databar_content_rows'
    authoritative path."""
    return DataStruct(
        data=np.arange(h * w, dtype=np.float64).reshape(h, w),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
        metadata={"source": "synthetic", "image_rows": image_rows, "hv_kv": 5.0},
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


def test_wave_d_measure_ops_registered_with_expected_categories() -> None:
    by_name = {s.name: s for s in ops.list_ops()}
    for name in _ANALYSIS:
        spec = by_name[name]
        assert spec.category == "analysis", name
        # "analysis" implies the value result: the flag stays UNSET…
        assert spec.produces_value is False, name
        # …and the single predicate still reports a value result
        assert produces_value_result(spec), name
    ss = by_name["sum_spectrum"]
    # spectral category (auto-skipped by the registry sweep's spectral
    # filter), so the explicit flag is required
    assert ss.category == "spectral"
    assert ss.produces_value is True
    assert produces_value_result(ss)
    sd = by_name["strip_databar"]
    assert sd.category == "filter"
    assert sd.produces_value is False
    assert not produces_value_result(sd)


def test_unknown_param_is_a_param_error() -> None:
    with pytest.raises(ParamError, match="unknown param"):
        ops.run(
            "line_profile",
            _ds(_image_data()),
            # the route's polyline mode is deliberately not mirrored: a
            # caller supplying it gets a hard error, never silence
            {"a_row": 1, "a_col": 1, "b_row": 5, "b_col": 5, "points": "1,1"},
        )
    with pytest.raises(ParamError, match="unknown param"):
        ops.run("scalebar_detect", _ds(_image_data()), {"image_id": "abc"})


# ── line_profile ─────────────────────────────────────────────────────


def test_line_profile_matches_direct_calc_call() -> None:
    ds = _ds(_image_data())
    params = {"a_row": 2.0, "a_col": 3.0, "b_row": 9.0, "b_col": 12.0}
    result = ops.run("line_profile", ds, params)
    outs = _outputs(result)
    dist, inten, sem = line_profile_stats(
        np.asarray(ds.data), x1=3.0, y1=2.0, x2=12.0, y2=9.0, pixel_size=0.5
    )
    assert sem is None  # width=1 → the calc itself reports no spread
    curve = outs["intensity"]["data"]
    assert outs["intensity"]["kind"] == "curve"
    assert curve["x"] == dist.tolist()
    assert curve["y"] == pytest.approx(np.asarray(inten).tolist())
    assert curve["x_unit"] == "nm"  # calibrated distances
    assert "y_sigma" not in curve  # absent — not null — when not honest
    assert outs["length"]["data"] == {"value": pytest.approx(float(dist[-1])), "unit": "nm"}


def test_line_profile_sigma_only_for_width_gt_1_mean() -> None:
    ds = _ds(_image_data())
    base = {"a_row": 3.0, "a_col": 2.0, "b_row": 8.0, "b_col": 13.0}
    wide_mean = ops.run("line_profile", ds, {**base, "width": 3.0, "reduce": "mean"})
    curve = _outputs(wide_mean)["intensity"]["data"]
    _, _, sem = line_profile_stats(
        np.asarray(ds.data),
        x1=2.0,
        y1=3.0,
        x2=13.0,
        y2=8.0,
        pixel_size=0.5,
        width=3.0,
        reduce="mean",
    )
    assert sem is not None
    assert curve["y_sigma"] == pytest.approx(np.asarray(sem).tolist())

    # an integral has no honest per-point σ — absent for reduce='sum'
    wide_sum = ops.run("line_profile", ds, {**base, "width": 3.0, "reduce": "sum"})
    assert "y_sigma" not in _outputs(wide_sum)["intensity"]["data"]


def test_line_profile_endpoints_are_required() -> None:
    with pytest.raises(ParamError, match="missing required"):
        ops.run("line_profile", _ds(_image_data()), {"a_row": 1, "a_col": 1})


# ── roi_stats ────────────────────────────────────────────────────────


def test_roi_stats_matches_direct_calc_and_is_1_based_inclusive() -> None:
    data = _image_data()
    ds = _ds(data)
    params = {"row1": 1.0, "col1": 1.0, "row2": 2.0, "col2": 3.0}
    outs = _outputs(ops.run("roi_stats", ds, params))
    direct = roi_stats(data, 1.0, 1.0, 2.0, 3.0, pixel_size=0.5, shape="rect")
    for name in ("mean", "std", "min", "max", "n_pixels", "area"):
        assert outs[name]["data"]["value"] == pytest.approx(direct[name]), name
    # 1-based INCLUSIVE: rows 1..2 and cols 1..3 are the top-left 2x3 block
    assert outs["mean"]["data"]["value"] == pytest.approx(float(data[0:2, 0:3].mean()))
    assert outs["n_pixels"]["data"]["value"] == 6
    assert outs["area"]["data"] == {"value": pytest.approx(6 * 0.5**2), "unit": "nm^2"}

    ell = _outputs(
        ops.run("roi_stats", ds, {"row1": 2, "col1": 2, "row2": 10, "col2": 12, "shape": "ellipse"})
    )
    direct_ell = roi_stats(data, 2, 2, 10, 12, pixel_size=0.5, shape="ellipse")
    assert ell["mean"]["data"]["value"] == pytest.approx(direct_ell["mean"])
    assert ell["n_pixels"]["data"]["value"] == direct_ell["n_pixels"]


def test_roi_stats_empty_roi_errors_from_calc() -> None:
    # clamping never silently falls back to the whole image — the shared
    # calc raises, exactly what the route maps to its 422
    with pytest.raises(ValueError, match="empty after clamping"):
        ops.run(
            "roi_stats",
            _ds(_image_data()),
            {"row1": 100.0, "col1": 1.0, "row2": 200.0, "col2": 3.0},
        )


# ── box_profile ──────────────────────────────────────────────────────


def test_box_profile_matches_direct_calc_call() -> None:
    data = _image_data()
    ds = _ds(data)
    params = {"row1": 2.0, "col1": 3.0, "row2": 9.0, "col2": 30.0}  # col2 clamps to 16
    outs = _outputs(ops.run("box_profile", ds, params))
    x_pos, x_int, y_pos, y_int, rect = box_integrate(data, 2, 3, 9, 30, reduce="sum")
    xp, ypr = outs["x_profile"]["data"], outs["y_profile"]["data"]
    assert xp["x"] == x_pos.tolist()  # 0-based px from the box edge
    assert xp["y"] == pytest.approx(np.asarray(x_int).tolist())
    assert ypr["x"] == y_pos.tolist()
    assert ypr["y"] == pytest.approx(np.asarray(y_int).tolist())
    for d in (xp, ypr):
        assert d["x_unit"] == "px"
        assert d["pixel_size"] == pytest.approx(0.5)  # calibration rides the data
        assert d["pixel_unit"] == "nm"
        assert d["reduce"] == "sum"
    # the clamped rect comes back (1-based inclusive)
    assert (
        outs["rect_row1"]["data"]["value"],
        outs["rect_col1"]["data"]["value"],
        outs["rect_row2"]["data"]["value"],
        outs["rect_col2"]["data"]["value"],
    ) == rect
    assert rect == (2, 3, 9, 16)

    mean = ops.run("box_profile", ds, {**params, "reduce": "mean"})
    _, x_int_m, _, _, _ = box_integrate(data, 2, 3, 9, 30, reduce="mean")
    assert _outputs(mean)["x_profile"]["data"]["y"] == pytest.approx(np.asarray(x_int_m).tolist())


# ── tilted_distance ──────────────────────────────────────────────────


def test_tilted_distance_matches_direct_calc_call() -> None:
    ds = _ds(_image_data())
    params = {"x1": 1.0, "y1": 1.0, "x2": 4.0, "y2": 5.0, "tilt_angle_deg": 30.0}
    outs = _outputs(ops.run("tilted_distance", ds, params))
    direct = measure_distance(
        1.0, 1.0, 4.0, 5.0, pixel_size=0.5, pixel_unit="nm", tilt_angle_deg=30.0
    )
    assert outs["raw_px"]["data"] == {"value": pytest.approx(direct.raw_px), "unit": "px"}
    assert outs["corrected_px"]["data"]["value"] == pytest.approx(direct.corrected_px)
    assert outs["raw_calibrated"]["data"] == {
        "value": pytest.approx(direct.raw_calibrated),
        "unit": "nm",
    }
    assert outs["corrected_calibrated"]["data"]["value"] == pytest.approx(
        direct.corrected_calibrated
    )


def test_tilted_distance_calibrated_scalars_absent_when_uncalibrated() -> None:
    ds = _ds(_image_data(), calibrated=False)
    outs = _outputs(ops.run("tilted_distance", ds, {"x1": 0.0, "y1": 0.0, "x2": 3.0, "y2": 4.0}))
    assert outs["raw_px"]["data"]["value"] == pytest.approx(5.0)
    # the route spells these null; the envelope contract spells them ABSENT
    assert "raw_calibrated" not in outs
    assert "corrected_calibrated" not in outs


def test_tilted_distance_invalid_tilt_errors() -> None:
    with pytest.raises(ValueError, match="tilt_angle_deg"):
        ops.run(
            "tilted_distance",
            _ds(_image_data()),
            {"x1": 0, "y1": 0, "x2": 1, "y2": 1, "tilt_angle_deg": 90.0},
        )


# ── sum_spectrum ─────────────────────────────────────────────────────


def test_sum_spectrum_whole_cube_matches_datastruct_sum() -> None:
    cube = _cube()
    outs = _outputs(ops.run("sum_spectrum", cube))
    curve = outs["counts"]["data"]
    assert curve["y"] == cube.sum_spectrum().tolist()
    assert curve["x"] == cube.energy_axis.tolist()
    assert curve["x_unit"] == "eV"
    assert "region" not in outs  # absent — not null — without a region


def test_sum_spectrum_region_matches_direct_calc_call() -> None:
    cube = _cube()
    outs = _outputs(
        ops.run(
            "sum_spectrum",
            cube,
            # corners in either order + clamped, like the calc contract
            {"region_row0": 3, "region_col0": 4, "region_row1": 2, "region_col1": 99},
        )
    )
    counts, rect = region_sum_spectrum(np.asarray(cube.data), 3, 4, 2, 99)
    assert outs["counts"]["data"]["y"] == counts.tolist()
    assert outs["region"]["data"]["rows"] == [list(rect)]
    assert rect == (2, 4, 3, 5)


def test_sum_spectrum_error_paths() -> None:
    cube = _cube()
    # a half-given region must not silently fall back to the whole cube
    with pytest.raises(ValueError, match="given together"):
        ops.run("sum_spectrum", cube, {"region_row0": 1, "region_col0": 1})
    # fractional region corners would silently sum a DIFFERENT region
    with pytest.raises(ValueError, match="whole numbers"):
        ops.run(
            "sum_spectrum",
            cube,
            {"region_row0": 1.5, "region_col0": 1, "region_row1": 2, "region_col1": 2},
        )
    # region empty after clamping (shared calc raises, the route's 422)
    with pytest.raises(ValueError, match="empty after clamping"):
        ops.run(
            "sum_spectrum",
            cube,
            {"region_row0": 50, "region_col0": 1, "region_row1": 60, "region_col1": 2},
        )
    # a 2D image has no spectral axis at all (the route's 400 guard)
    with pytest.raises(ValueError, match="no spectral axis"):
        ops.run("sum_spectrum", _ds(_image_data()))
    # a region on a non-cube spectral input: the route silently ignores it
    # and returns the whole spectrum — this op is deliberately stricter
    with pytest.raises(ValueError, match="spectrum-image cube"):
        ops.run(
            "sum_spectrum",
            _spectrum(),
            {"region_row0": 1, "region_col0": 1, "region_row1": 2, "region_col1": 2},
        )


def test_sum_spectrum_of_a_1d_spectrum_is_the_spectrum() -> None:
    spec = _spectrum()
    outs = _outputs(ops.run("sum_spectrum", spec))
    assert outs["counts"]["data"]["y"] == spec.sum_spectrum().tolist()
    assert "region" not in outs


# ── intensity_histogram ──────────────────────────────────────────────


def test_intensity_histogram_matches_direct_calc_call() -> None:
    data = _image_data()
    ds = _ds(data)
    outs = _outputs(ops.run("intensity_histogram", ds, {"bins": 32}))
    centers, counts = histogram(data, 32)
    curve = outs["histogram"]["data"]
    assert curve["x"] == centers.tolist()  # bin CENTERS, like the route
    assert curve["y"] == counts.tolist()
    assert sum(curve["y"]) == data.size


def test_intensity_histogram_bins_bounds() -> None:
    ds = _ds(_image_data())
    with pytest.raises(ParamError, match="min"):
        ops.run("intensity_histogram", ds, {"bins": 1})
    with pytest.raises(ParamError, match="max"):
        ops.run("intensity_histogram", ds, {"bins": 5000})


# ── scalebar_detect ──────────────────────────────────────────────────


def test_scalebar_detect_found_matches_direct_calc_call() -> None:
    img = _scalebar_image()
    outs = _outputs(ops.run("scalebar_detect", _ds(img)))
    direct = detect_scale_bar(img)
    assert direct.found  # the fixture must actually exercise the found path
    table = outs["detection"]["data"]
    assert table["columns"] == ["found", "bar_len", "bar_x1", "bar_x2", "bar_y", "msg"]
    (row,) = table["rows"]
    assert row == [
        direct.found,
        direct.bar_len,
        direct.bar_x1,
        direct.bar_x2,
        direct.bar_y,
        direct.msg,
    ]
    assert row[1] == 30  # the synthetic 30-px run, 1-based inclusive ends
    assert (row[2], row[3]) == (11, 40)


def test_scalebar_detect_not_found_is_a_valid_result() -> None:
    outs = _outputs(ops.run("scalebar_detect", _ds(np.zeros((32, 64)))))
    (row,) = outs["detection"]["data"]["rows"]
    assert row[0] is False
    assert "Could not detect" in row[5]
    # and the registry sweep's 8x10 ramp path: too small → found=False,
    # never an exception
    small = _outputs(ops.run("scalebar_detect", _ds(np.arange(80.0).reshape(8, 10))))
    assert small["detection"]["data"]["rows"][0][0] is False


def test_scalebar_detect_kind_guards() -> None:
    with pytest.raises(ValueError, match="no scale bar"):
        ops.run("scalebar_detect", _spectrum())
    rgb = DataStruct(
        data=np.zeros((16, 24, 3), dtype=np.uint8),
        kind=DataKind.RGB_IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata={},
    )
    # the route's local reduction would hand detect_scale_bar a 3-D array
    # (an unhandled 500) — the op raises cleanly instead
    with pytest.raises(ValueError, match="rgb_image"):
        ops.run("scalebar_detect", rgb)


# ── strip_databar ────────────────────────────────────────────────────


def test_strip_databar_crops_and_carries_metadata() -> None:
    ds = _databar_ds()
    result = ops.run("strip_databar", ds)
    assert result.produces_image
    derived = result.derived
    assert derived is not None
    assert derived.kind is DataKind.IMAGE
    assert derived.data.shape == (20, 16)  # image_rows kept, databar cropped
    np.testing.assert_array_equal(derived.data, np.asarray(ds.data)[:20, :])
    assert derived.axes == (ds.axes[0], ds.axes[1])  # calibration preserved
    md = derived.metadata
    assert md["parser"] == "derived"
    assert md["source"] == "strip_databar"
    assert md["filter_kind"] == "strip_databar"
    assert md["hv_kv"] == 5.0  # acquisition provenance carried forward
    # the geometry keys are dropped, so the derivative reports "no databar"
    assert "image_rows" not in md and "databar_height" not in md


def test_strip_databar_second_strip_errors_no_databar() -> None:
    derived = ops.run("strip_databar", _databar_ds()).derived
    assert derived is not None
    with pytest.raises(ValueError, match="no vendor databar recorded"):
        ops.run("strip_databar", derived)


def test_strip_databar_guards() -> None:
    # no databar recorded at all (plain metadata)
    with pytest.raises(ValueError, match="no vendor databar recorded"):
        ops.run("strip_databar", _ds(_image_data()))
    # only 2-D images carry a vendor databar (the route's 400)
    with pytest.raises(ValueError, match="2-D images"):
        ops.run("strip_databar", _cube())
