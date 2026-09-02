"""The three grain endpoints registered under the re-opened op contract:
`grains_edit` (ADR 0005 §8 — an auxiliary `source` input), `train_segment`
and `train_preview` (§9 — a `strokes` RECORD list whose `points` field is
itself an (x, y) row list).

Parity contract (§1): each op's numbers must equal a direct call to the
SAME calc composition its route runs — `calc.grain_edit.edit_grains` +
`calc.grain_report.grain_report` for the edit, and rasterize -> train ->
segment/preview (+ `confidence_summary`) for the trained pair. Envelope
contract (§5): value is ONLY {"outputs": [...]} of ADR 0004
{kind, name, data} envelopes.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

import fermiviewer.ops as ops
from fermiviewer.calc.grain_edit import edit_grains
from fermiviewer.calc.grain_report import grain_report
from fermiviewer.calc.grains_trained import (
    confidence_summary,
    preview_trained,
    rasterize_strokes,
    segment_trained,
    train_from_scribbles,
)
from fermiviewer.calc.roi import embed_rect_roi, extract_rect_roi, roi_slices
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops import catalogue_grains_edit  # noqa: F401  (registers the ops)
from fermiviewer.ops._envelopes import OUTPUT_KINDS
from fermiviewer.ops.base import InputError, ParamError, produces_value_result

pytestmark = pytest.mark.parser

_OPS = ("grains_edit", "train_segment", "train_preview")


# ── fixtures ─────────────────────────────────────────────────────────


def _textured(h: int = 40, w: int = 40) -> np.ndarray:
    """Two intensity regions with a hard vertical boundary plus a little
    deterministic noise — separable by the trained classifier, and enough
    contrast for the split watershed."""
    rng = np.random.default_rng(3)
    img = np.zeros((h, w), dtype=np.float64)
    img[:, : w // 2] = 1.0
    img[:, w // 2 :] = 8.0
    return img + rng.normal(0.0, 0.05, img.shape)


def _image_ds(data: np.ndarray | None = None, calibrated: bool = True) -> DataStruct:
    axes = (
        (AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm"))
        if calibrated
        else (AxisCal(), AxisCal())
    )
    return DataStruct(
        data=_textured() if data is None else data,
        kind=DataKind.IMAGE,
        axes=axes,
        metadata={"source": "synthetic"},
    )


def _two_grain_labels(h: int = 40, w: int = 40) -> np.ndarray:
    """The label map /analyze/grains would have produced for `_textured`:
    grain 1 left, grain 2 right, no background."""
    labels = np.ones((h, w), dtype=np.int64)
    labels[:, w // 2 :] = 2
    return labels


def _labels_ds(labels: np.ndarray | None = None) -> DataStruct:
    """A grain-label map as the session holds it — float64 pixels, the
    source image's calibration (routes/structure._register keeps the
    parent axes)."""
    arr = _two_grain_labels() if labels is None else labels
    return _image_ds(arr.astype(np.float64))


_STROKES: list[dict[str, Any]] = [
    {"class_id": 1, "radius": 2.0, "points": [[4.0, 6.0], [4.0, 30.0]]},
    {"class_id": 2, "radius": 2.0, "points": [[32.0, 6.0], [32.0, 30.0]]},
]


def _outputs(result: ops.OpResult) -> dict[str, dict]:
    """{name: envelope} for a wave op's value, validating the §5 contract."""
    assert set(result.value) == {"outputs"}, "new ops carry ONLY the envelope list"
    by_name: dict[str, dict] = {}
    for env in result.value["outputs"]:
        assert set(env) == {"kind", "name", "data"}
        assert env["kind"] in OUTPUT_KINDS
        assert isinstance(env["data"], dict)
        assert env["name"] not in by_name, f"duplicate envelope name {env['name']}"
        by_name[env["name"]] = env
    return by_name


# ── registration ─────────────────────────────────────────────────────


def test_ops_are_registered_in_the_structure_category() -> None:
    by_name = {s.name: s for s in ops.list_ops()}
    for name in _OPS:
        assert by_name[name].category == "structure", name
        # "structure" does not imply a value result, so the flag is explicit
        assert by_name[name].produces_value, name
        assert produces_value_result(by_name[name]), name


def test_only_grains_edit_declares_an_auxiliary_input() -> None:
    """§8: the edit needs the intensity image its label map came from; the
    trained pair works on its subject alone."""
    assert ops.get_spec("grains_edit").multi_input
    assert set(ops.get_spec("grains_edit").inputs) == {"source"}
    assert not ops.get_spec("train_segment").multi_input
    assert not ops.get_spec("train_preview").multi_input


def test_min_area_is_on_train_segment_only() -> None:
    """The two route models differ here and the ops mirror them (§4): the
    preview labels no connected components, so it has no min area."""
    assert "min_area" in ops.get_spec("train_segment").params
    assert "min_area" not in ops.get_spec("train_preview").params


# ── grains_edit ──────────────────────────────────────────────────────


def test_grains_edit_merge_matches_the_calc_composition() -> None:
    labels_ds, source = _labels_ds(), _image_ds()
    points = [[4.0, 6.0], [32.0, 6.0]]  # (x, y), 0-based: one click per grain
    result = ops.run(
        "grains_edit",
        labels_ds,
        {"op": "merge", "points": points},
        inputs={"source": source},
    )
    edit = edit_grains(
        np.asarray(labels_ds.data, dtype=np.int64),
        source.data,
        "merge",
        [(4.0, 6.0), (32.0, 6.0)],
        granularity=0.03,
    )
    expected = grain_report(
        edit.labels, source.data, pixel_size=source.pixel_size, unit=source.pixel_unit
    )
    envs = _outputs(result)
    assert envs["n_grains"]["data"]["value"] == expected.n_grains
    assert expected.n_grains == 1, "the two adjacent grains merge into one"
    assert np.array_equal(np.asarray(envs["labels"]["data"]["values"]), expected.labels)
    assert envs["mean_diameter_px"]["data"]["value"] == expected.mean_diameter_px
    assert envs["labels"]["data"]["method"] == "merge"
    assert result.op == "grains_edit"


def test_grains_edit_split_matches_the_calc_composition() -> None:
    """One grain over the whole two-region image; the split watershed cuts
    it at the intensity boundary."""
    labels_ds = _labels_ds(np.ones((40, 40), dtype=np.int64))
    source = _image_ds()
    result = ops.run(
        "grains_edit",
        labels_ds,
        {"op": "split", "points": [[4.0, 6.0]], "granularity": 0.05},
        inputs={"source": source},
    )
    edit = edit_grains(
        np.asarray(labels_ds.data, dtype=np.int64),
        source.data,
        "split",
        [(4.0, 6.0)],
        granularity=0.05,
    )
    expected = grain_report(
        edit.labels, source.data, pixel_size=source.pixel_size, unit=source.pixel_unit
    )
    envs = _outputs(result)
    assert np.array_equal(np.asarray(envs["labels"]["data"]["values"]), expected.labels)
    assert envs["n_grains"]["data"]["value"] == expected.n_grains
    table = envs["grains"]["data"]
    assert len(table["rows"]) == expected.n_grains
    assert table["columns"][0] == "area_px"


def test_grains_edit_carries_the_roi_through_to_the_result_map() -> None:
    """The route reads the segmentation rectangle from
    metadata['grain_roi']; a pure op takes it as a param and echoes it so a
    follow-up edit can pass it back."""
    result = ops.run(
        "grains_edit",
        _labels_ds(),
        {"op": "merge", "points": [[4.0, 6.0], [32.0, 6.0]], "roi": "1,1,40,40"},
        inputs={"source": _image_ds()},
    )
    assert _outputs(result)["labels"]["data"]["roi"] == "1,1,40,40"


def test_grains_edit_rejects_a_mismatched_shape_source() -> None:
    """calc.grain_edit checks it (the route never could — it fetched the two
    from separate session entries)."""
    with pytest.raises(ValueError, match="must have the same shape"):
        ops.run(
            "grains_edit",
            _labels_ds(),
            {"op": "merge", "points": [[4.0, 6.0], [32.0, 6.0]]},
            inputs={"source": _image_ds(np.zeros((12, 12)))},
        )


def test_grains_edit_rejects_a_background_split_click() -> None:
    labels = _two_grain_labels()
    labels[:, 18:22] = 0  # a background gutter between the grains
    with pytest.raises(ValueError, match="not on a grain"):
        ops.run(
            "grains_edit",
            _labels_ds(labels),
            {"op": "split", "points": [[20.0, 6.0]]},
            inputs={"source": _image_ds()},
        )


def test_grains_edit_requires_the_source_input() -> None:
    with pytest.raises(InputError, match="source"):
        ops.run(
            "grains_edit", _labels_ds(), {"op": "merge", "points": [[4.0, 6.0]]}
        )


def test_grains_edit_points_must_be_xy_pairs() -> None:
    with pytest.raises(ParamError, match="expected 2 values"):
        ops.run(
            "grains_edit",
            _labels_ds(),
            {"op": "merge", "points": [[4.0, 6.0, 1.0]]},
            inputs={"source": _image_ds()},
        )


# ── train_segment ────────────────────────────────────────────────────


def _direct_model(
    raster: np.ndarray,
    roi: tuple[int, int, int, int] | None = None,
    **kw: Any,
) -> Any:
    """The front half both trained routes run, called directly."""
    mask = rasterize_strokes(raster.shape, _STROKES)
    rows, cols = roi_slices(raster.shape, roi)
    return train_from_scribbles(
        extract_rect_roi(raster, roi),
        mask[rows, cols],
        scales=kw.get("scales", (2.0, 4.0)),
        gradient_sigma=kw.get("gradient_sigma", 0.0),
        classifier=kw.get("classifier", "softmax"),
    )


def test_train_segment_matches_the_calc_composition() -> None:
    ds = _image_ds()
    result = ops.run("train_segment", ds, {"strokes": _STROKES})
    model = _direct_model(ds.data)
    seg = segment_trained(ds.data, model, boundary_class=(), min_area=25)
    expected = grain_report(
        seg.labels,
        np.asarray(ds.data, dtype=np.float64),
        pixel_size=ds.pixel_size,
        unit=ds.pixel_unit,
    )
    envs = _outputs(result)
    assert envs["n_grains"]["data"]["value"] == expected.n_grains == 2
    assert np.array_equal(np.asarray(envs["labels"]["data"]["values"]), expected.labels)
    assert envs["labels"]["data"]["method"] == "trained"
    assert len(envs["grains"]["data"]["rows"]) == expected.n_grains


def test_train_segment_honours_roi_and_boundary_class() -> None:
    ds = _image_ds()
    roi = (5, 5, 36, 36)
    result = ops.run(
        "train_segment",
        ds,
        {
            "strokes": _STROKES,
            "roi": "5,5,36,36",
            "boundary_class": [[2]],
            "min_area": 10,
        },
    )
    model = _direct_model(ds.data, roi)
    seg = segment_trained(
        extract_rect_roi(ds.data, roi), model, boundary_class=(2,), min_area=10
    )
    labels = embed_rect_roi(seg.labels, ds.data.shape, roi)
    expected = grain_report(
        labels,
        np.asarray(ds.data, dtype=np.float64),
        pixel_size=ds.pixel_size,
        unit=ds.pixel_unit,
    )
    envs = _outputs(result)
    assert np.array_equal(np.asarray(envs["labels"]["data"]["values"]), expected.labels)
    assert envs["n_grains"]["data"]["value"] == expected.n_grains
    assert envs["labels"]["data"]["roi"] == "5,5,36,36"


def test_train_segment_rejects_an_empty_segmentation() -> None:
    """The route's 422 is part of the composition: every predicted class is
    the boundary class, so nothing is left to label."""
    with pytest.raises(ValueError, match="no grains found"):
        ops.run(
            "train_segment",
            _image_ds(),
            {"strokes": _STROKES, "boundary_class": [[1], [2]]},
        )


# ── train_preview ────────────────────────────────────────────────────


def test_train_preview_matches_the_calc_composition() -> None:
    ds = _image_ds()
    result = ops.run("train_preview", ds, {"strokes": _STROKES})
    prev = preview_trained(ds.data, _direct_model(ds.data))
    mean_conf, low_frac = confidence_summary(prev.max_prob, threshold=0.6)
    envs = _outputs(result)
    assert envs["mean_confidence"]["data"]["value"] == mean_conf
    assert envs["low_confidence_fraction"]["data"]["value"] == low_frac
    assert envs["confidence_threshold"]["data"]["value"] == 0.6
    assert envs["classes"]["data"]["rows"] == [
        [int(c), prev.fractions[int(c)], False] for c in prev.classes
    ]
    assert np.array_equal(
        np.asarray(envs["class_map"]["data"]["values"]), prev.class_map
    )
    assert np.allclose(
        np.asarray(envs["confidence_map"]["data"]["values"]), prev.max_prob
    )


def test_train_preview_emits_both_maps_inline_and_no_derived() -> None:
    """Two rasters exceed OpResult.derived's single slot — the wave-B
    standing rule inlines them as `map` envelopes instead."""
    result = ops.run("train_preview", _image_ds(), {"strokes": _STROKES})
    envs = _outputs(result)
    assert result.derived is None
    assert envs["class_map"]["kind"] == "map"
    assert envs["confidence_map"]["kind"] == "map"


def test_train_preview_marks_the_boundary_classes() -> None:
    result = ops.run(
        "train_preview", _image_ds(), {"strokes": _STROKES, "boundary_class": [[2]]}
    )
    rows = _outputs(result)["classes"]["data"]["rows"]
    assert [(row[0], row[2]) for row in rows] == [(1, False), (2, True)]


def test_train_preview_roi_embeds_into_the_full_image() -> None:
    ds = _image_ds()
    roi = (5, 5, 36, 36)
    result = ops.run("train_preview", ds, {"strokes": _STROKES, "roi": "5,5,36,36"})
    prev = preview_trained(extract_rect_roi(ds.data, roi), _direct_model(ds.data, roi))
    expected = embed_rect_roi(prev.class_map, ds.data.shape, roi)
    envs = _outputs(result)
    assert np.array_equal(np.asarray(envs["class_map"]["data"]["values"]), expected)
    # outside the ROI the map is zero-filled, as the route's registered image is
    assert envs["class_map"]["data"]["values"][0][0] == 0


# ── the §9 record schema ─────────────────────────────────────────────


def test_a_stroke_without_points_is_rejected() -> None:
    with pytest.raises(ParamError, match="missing required 'points'"):
        ops.run("train_segment", _image_ds(), {"strokes": [{"class_id": 1}]})


def test_a_stroke_class_id_of_zero_is_rejected() -> None:
    """The route's Field(ge=1) twin — class 0 means "unlabelled" to
    `rasterize_strokes`, so painting it would silently paint nothing."""
    bad = [{"class_id": 0, "radius": 2.0, "points": [[4.0, 6.0]]}]
    with pytest.raises(ParamError, match=r"strokes\[0\].class_id.*0 < min 1"):
        ops.run("train_segment", _image_ds(), {"strokes": bad})


def test_strokes_needs_at_least_one_record() -> None:
    with pytest.raises(ParamError, match="at least 1 entry"):
        ops.run("train_segment", _image_ds(), {"strokes": []})


def test_stroke_radius_defaults_to_the_route_value() -> None:
    result = ops.run(
        "train_segment",
        _image_ds(),
        {"strokes": [{"class_id": s["class_id"], "points": s["points"]} for s in _STROKES]},
    )
    assert result.params["strokes"][0]["radius"] == 4.0


def test_scales_and_boundary_class_are_width_one_row_lists() -> None:
    """§9 forbids minting a NEW CSV flattening, and RowSpec is the contract's
    only native list vocabulary — so a flat [2.0, 4.0] is an error, not a
    re-shape, exactly as a CSV string reaching a row list is."""
    with pytest.raises(ParamError, match="expected a list, got float"):
        ops.run(
            "train_preview", _image_ds(), {"strokes": _STROKES, "scales": [2.0, 4.0]}
        )
    with pytest.raises(ParamError, match="expected a list, got str"):
        ops.run(
            "train_preview", _image_ds(), {"strokes": _STROKES, "boundary_class": "1,2"}
        )


def test_empty_scales_falls_back_to_the_route_default() -> None:
    ds = _image_ds()
    empty = ops.run("train_preview", ds, {"strokes": _STROKES, "scales": []})
    default = ops.run("train_preview", ds, {"strokes": _STROKES})
    assert (
        _outputs(empty)["class_map"]["data"]["values"]
        == _outputs(default)["class_map"]["data"]["values"]
    )


# ── calibration provenance (review finding on #202) ──────────────────


def _ds_with_axes(
    data: np.ndarray, row: float, col: float, unit: str = "nm"
) -> DataStruct:
    return DataStruct(
        data=data,
        kind=DataKind.IMAGE,
        axes=(AxisCal(row, 0.0, unit), AxisCal(col, 0.0, unit)),
        metadata={"source": "synthetic"},
    )


def test_grains_edit_calibrates_from_the_source_not_the_label_map() -> None:
    """`source_ds` is the single calibration authority, and the guard has
    to use a label map whose axes DIFFER from the source.

    Every in-repo flow registers the label map with the parent's axes, so
    a fixture that shares them agrees no matter which side the op reads —
    it cannot tell the two apart, which is why this drifted unnoticed.
    Here the source is anisotropic 3:1 and the label map carries stale
    1:1 axes, so reading the wrong one is visible: the op answered 45.14
    where the route answers 78.18, and labelled it with the source's unit
    either way.

    The oracle is the ROUTE's composition (ADR 0005 §1: the op and the
    route compute the same report), not a number copied from the op.
    """
    source = _ds_with_axes(_textured(), 3.0, 1.0)
    # differs in SCALE, ASPECT and UNIT: each of the three calibration
    # arguments reads a different value from the two images, so no single
    # one of them can be misdirected without a visible effect.
    stale_labels = _ds_with_axes(
        _two_grain_labels().astype(np.float64), 1.0, 1.0, unit="um"
    )
    assert source.pixel_spacing != stale_labels.pixel_spacing
    assert source.pixel_unit != stale_labels.pixel_unit

    points = [[10.0, 10.0], [30.0, 10.0]]
    result = ops.run(
        "grains_edit",
        stale_labels,
        {"op": "merge", "points": points, "granularity": 0.05, "roi": ""},
        inputs={"source": source},
    )
    table = _outputs(result)["grains"]["data"]
    col = table["columns"].index("diameter_calibrated")
    got = [row[col] for row in table["rows"]]

    raster = np.asarray(source.data, dtype=np.float64)
    edit = edit_grains(
        _two_grain_labels(), raster, "merge",
        [(float(x), float(y)) for x, y in points], granularity=0.05,
    )
    expected = grain_report(
        edit.labels, raster,
        pixel_size=source.pixel_size, pixel_area=source.pixel_area,
        unit=source.pixel_unit, spacing=source.pixel_spacing,
    )
    np.testing.assert_allclose(got, expected.diameter_calibrated, rtol=1e-12)
    # `diameter_calibrated` rides on pixel_area alone, so it cannot see a
    # misdirected SPACING. Eccentricity can: it is measured on the
    # physical grid, and 3:1 against 1:1 moves it 0.986 -> 0.866 here.
    ecc = table["columns"].index("eccentricity")
    np.testing.assert_allclose(
        [row[ecc] for row in table["rows"]], expected.eccentricity, rtol=1e-12
    )
    # and the declared unit must come from the same image as the numbers,
    # which only bites because the two fixtures disagree about it
    assert table["units"][col] == source.pixel_unit == "nm"


def test_grains_edit_does_not_mix_two_images_calibrations() -> None:
    """A report that takes its unit from one image and its magnitude from
    another is worse than either alone, because the unit stops saying
    which calibration produced the number. Reading the label map's 1:1
    axes here would give exactly the source-independent answer."""
    source = _ds_with_axes(_textured(), 3.0, 1.0)
    stale_labels = _ds_with_axes(
        _two_grain_labels().astype(np.float64), 1.0, 1.0, unit="um"
    )
    result = ops.run(
        "grains_edit",
        stale_labels,
        {"op": "merge", "points": [[10.0, 10.0], [30.0, 10.0]], "granularity": 0.05,
         "roi": ""},
        inputs={"source": source},
    )
    table = _outputs(result)["grains"]["data"]
    col = table["columns"].index("diameter_calibrated")
    px_col = table["columns"].index("equiv_diameter_px")
    for row in table["rows"]:
        # uncalibrated pixels x the label map's 1:1 scale would leave the
        # calibrated column equal to the pixel one
        assert row[col] != pytest.approx(row[px_col]), "read the label map's axes"
