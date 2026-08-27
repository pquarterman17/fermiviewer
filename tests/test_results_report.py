"""Report-bundle backend (roadmap item 2B): `fermiviewer.results_report`.

Records are built directly rather than through HTTP — the bundle is pure
logic over the item-1 record contract, and the properties that matter
(determinism, JSON safety, honest array handling, honest prose) are
properties of that logic, not of a route.
"""

from __future__ import annotations

import json
import re

import numpy as np
import pytest

from fermiviewer.datastruct import AxisCal
from fermiviewer.io.results_model import CalibrationSnapshot, ResultOutput, ResultRecord
from fermiviewer.results_methods import METHODS_TEMPLATES, methods_paragraph
from fermiviewer.results_report import (
    MAX_INLINE_ARRAY_VALUES,
    REPORT_VERSION,
    build_report,
    bundle_payload,
    utc_now,
)

FIXED_TIME = "2026-08-27T12:00:00+00:00"
APP = "9.9.9"


def fixed_clock() -> str:
    return FIXED_TIME


def make_record(
    result_id: str = "aaa111",
    analysis: str = "eds.quantify",
    **kwargs: object,
) -> ResultRecord:
    """A completed record with the fields every bundle path touches."""
    fields: dict = {
        "label": f"{analysis} of img-1",
        "app_version": "0.1.32",
        "source_ids": ("img-1",),
        "params": {"image_id": "img-1"},
        "calibration": (
            CalibrationSnapshot(
                image_id="img-1",
                axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
                source="fei",
            ),
        ),
    }
    fields.update(kwargs)  # type: ignore[arg-type]
    return ResultRecord(
        id=result_id,
        analysis=analysis,
        created_at="2026-08-26T08:30:00+00:00",
        status=str(fields.pop("status", "completed")),
        **fields,
    )


def eds_record() -> ResultRecord:
    return make_record(
        params={
            "image_id": "img-1",
            "elements": ["Fe", "Cr", "Ni"],
            "method": "zaf",
            "half_window_kev": 0.085,
            "thickness_nm": 100.0,
            "take_off_angle_deg": 20.0,
        },
        outputs=(
            ResultOutput(
                kind="scalar", name="Fe", data={"value": 42.1, "unit": "at%", "sigma": 1.2}
            ),
            ResultOutput(
                kind="table",
                name="composition",
                data={"columns": ["element", "atomic_pct"], "units": ["", "at%"],
                      "rows": [["Fe", 42.1]]},
            ),
        ),
    )


def profile_record() -> ResultRecord:
    return make_record(
        result_id="bbb222",
        analysis="measure.profile",
        params={
            "image_id": "img-1",
            "a": [10.0, 20.0],
            "b": [110.0, 20.0],
            "points": None,
            "width": 3.0,
            "reduce": "mean",
            "tilt_angle_deg": 30.0,
            "tilt_axis": "Y",
            "geometry": "cross-section",
        },
        outputs=(
            ResultOutput(
                kind="curve",
                name="profile",
                data={"x_name": "distance", "x_unit": "nm", "y_name": "intensity", "y_unit": ""},
                member="results/bbb222/0.npy",
                array=np.arange(20.0).reshape(10, 2),
            ),
        ),
    )


def particles_record() -> ResultRecord:
    return make_record(
        result_id="ccc333",
        analysis="structure.particles",
        params={
            "image_id": "img-1",
            "threshold": 0.42,
            "polarity": "bright",
            "min_area": 12,
            "use_watershed": True,
            "min_marker_distance": 3.0,
            "class_thresholds": {"aspect_ratio": 1.5},
        },
    )


def index_record(**params: object) -> ResultRecord:
    resolved = {
        "image_id": "img-1",
        "spots": [[10.0, 12.0], [40.0, 44.0], [80.0, 12.0]],
        "pixel_size_mm": 0.01,
        "camera_length_mm": None,
        "acc_voltage_kv": 200.0,
        "tolerance": 0.05,
        "top_n": 5,
    }
    resolved.update(params)
    return make_record(
        result_id="ddd444",
        analysis="diffraction.index",
        params=resolved,
        regions=({"kind": "circle", "cr": 50, "cc": 50, "radius": 30},),
    )


# ── determinism ──────────────────────────────────────────────────────


def test_bundle_is_deterministic() -> None:
    records = [eds_record(), profile_record(), particles_record(), index_record()]
    first = build_report(records, app_version=APP, clock=fixed_clock)
    second = build_report(records, app_version=APP, clock=fixed_clock)
    assert first == second
    assert json.dumps(bundle_payload(first)) == json.dumps(bundle_payload(second))


def test_fixed_clock_fixes_generated_at() -> None:
    bundle = build_report([eds_record()], app_version=APP, clock=fixed_clock)
    assert bundle.generated_at == FIXED_TIME
    assert bundle.version == REPORT_VERSION
    assert bundle.app_version == APP


def test_default_clock_is_iso_utc_seconds() -> None:
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", utc_now())


def test_record_order_is_preserved() -> None:
    records = [profile_record(), eds_record(), particles_record()]
    bundle = build_report(records, app_version=APP, clock=fixed_clock)
    assert [r["id"] for r in bundle.results] == ["bbb222", "aaa111", "ccc333"]
    assert [e["image_id"] for e in bundle.calibration] == ["img-1"]


def test_empty_input() -> None:
    bundle = build_report([], app_version=APP, clock=fixed_clock)
    assert bundle.results == ()
    assert bundle.calibration == ()
    assert bundle.warnings == ()
    assert bundle.methods == ""
    assert bundle.generated_at == FIXED_TIME
    assert json.loads(json.dumps(bundle_payload(bundle)))["results"] == []


# ── JSON safety ──────────────────────────────────────────────────────


def test_non_finite_values_survive_json() -> None:
    """NaN in inline `data` and in a member array both stay strict JSON.

    `finite_json`'s two documented behaviours: a non-finite dict value
    loses its key, a non-finite list element becomes null so the remaining
    indices stay aligned.
    """
    record = make_record(
        outputs=(
            ResultOutput(
                kind="scalar",
                name="Fe",
                data={"value": float("nan"), "unit": "at%", "sigma": float("inf")},
            ),
            ResultOutput(
                kind="curve",
                name="profile",
                data={"x_name": "distance", "x_unit": "nm"},
                member="results/aaa111/0.npy",
                array=np.array([[0.0, 1.0], [1.0, float("nan")]]),
            ),
        ),
        params={"image_id": "img-1", "bad": float("nan"), "good": 1.5},
    )
    bundle = build_report([record], app_version=APP, clock=fixed_clock)
    text = json.dumps(bundle_payload(bundle))
    assert "NaN" not in text and "Infinity" not in text
    entry = json.loads(text)["results"][0]
    assert "bad" not in entry["params"] and entry["params"]["good"] == 1.5
    scalar, curve = entry["outputs"]
    assert "value" not in scalar["data"] and "sigma" not in scalar["data"]
    assert scalar["data"]["unit"] == "at%"
    assert curve["values"] == [[0.0, 1.0], [1.0, None]]


def test_numpy_scalars_and_arrays_become_plain_json() -> None:
    record = make_record(
        params={"image_id": "img-1", "n": np.int64(7), "scale": np.float32(0.5)},
        outputs=(
            ResultOutput(
                kind="table",
                name="particles",
                data={"columns": ["area"], "units": ["px"]},
                member="results/aaa111/0.npy",
                array=np.arange(6, dtype=np.int32).reshape(3, 2),
            ),
        ),
    )
    payload = bundle_payload(build_report([record], app_version=APP, clock=fixed_clock))
    entry = json.loads(json.dumps(payload))["results"][0]
    assert entry["params"]["n"] == 7
    output = entry["outputs"][0]
    assert output["values"] == [[0, 1], [2, 3], [4, 5]]
    assert output["dtype"] == "int32"
    assert output["shape"] == [3, 2]


# ── array size rule ──────────────────────────────────────────────────


def array_output(size: int) -> ResultOutput:
    return ResultOutput(
        kind="table",
        name="particles",
        data={"columns": ["a", "b"], "units": ["", ""]},
        member="results/aaa111/0.npy",
        array=np.zeros((size // 2, 2), dtype=np.float64),
    )


def test_array_at_the_threshold_is_inlined() -> None:
    record = make_record(outputs=(array_output(MAX_INLINE_ARRAY_VALUES),))
    bundle = build_report([record], app_version=APP, clock=fixed_clock)
    output = bundle.results[0]["outputs"][0]
    assert output["values_inlined"] is True
    assert len(output["values"]) == MAX_INLINE_ARRAY_VALUES // 2
    assert output["shape"] == [MAX_INLINE_ARRAY_VALUES // 2, 2]
    assert output["dtype"] == "float64"
    assert bundle.warnings == ()


def test_array_over_the_threshold_is_referenced_not_truncated() -> None:
    record = make_record(outputs=(array_output(MAX_INLINE_ARRAY_VALUES + 2),))
    bundle = build_report([record], app_version=APP, clock=fixed_clock)
    output = bundle.results[0]["outputs"][0]
    assert output["values_inlined"] is False
    assert output["values"] is None
    assert output["shape"] == [(MAX_INLINE_ARRAY_VALUES + 2) // 2, 2]
    assert output["dtype"] == "float64"
    assert output["member"] == "results/aaa111/0.npy"
    assert output["caption"].startswith("Table 'particles'")
    assert bundle.warnings == ()


def test_oversized_array_without_a_member_is_warned_about() -> None:
    output = ResultOutput(
        kind="map",
        name="Fe",
        data={},
        array=np.zeros((MAX_INLINE_ARRAY_VALUES + 1,), dtype=np.float64),
    )
    bundle = build_report([make_record(outputs=(output,))], app_version=APP, clock=fixed_clock)
    assert bundle.results[0]["outputs"][0]["values"] is None
    (note,) = bundle.warnings
    assert note.startswith("aaa111: output 'Fe' holds 4097 values")
    assert "no stored member" in note


def test_degraded_output_reports_no_array_and_is_flagged() -> None:
    record = make_record(
        outputs=(
            ResultOutput(
                kind="table",
                name="particles",
                data={"columns": ["a"], "units": [""]},
                member="results/aaa111/0.npy",
            ),
        ),
        missing_members=("results/aaa111/0.npy",),
    )
    bundle = build_report([record], app_version=APP, clock=fixed_clock)
    output = bundle.results[0]["outputs"][0]
    assert output["shape"] is None and output["values"] is None
    assert bundle.results[0]["missing_members"] == ["results/aaa111/0.npy"]
    assert any("degraded" in w for w in bundle.warnings)


# ── calibration summary ──────────────────────────────────────────────


def test_calibration_is_deduped_by_source_image() -> None:
    bundle = build_report(
        [eds_record(), profile_record()], app_version=APP, clock=fixed_clock
    )
    (entry,) = bundle.calibration
    assert entry["image_id"] == "img-1"
    assert entry["consistent"] is True
    assert entry["result_ids"] == ["aaa111", "bbb222"]
    (variant,) = entry["variants"]
    assert variant["source"] == "fei"
    assert variant["axes"][0] == {
        "index": 0,
        "scale": 0.5,
        "origin": 0.0,
        "units": "nm",
        "calibrated": True,
    }
    assert bundle.warnings == ()


def test_calibration_disagreement_lists_every_variant_and_says_so() -> None:
    recalibrated = make_record(
        result_id="bbb222",
        calibration=(
            CalibrationSnapshot(
                image_id="img-1",
                axes=(AxisCal(0.25, 0.0, "nm"), AxisCal(0.25, 0.0, "nm")),
                source="db:my-scope",
            ),
        ),
    )
    bundle = build_report([eds_record(), recalibrated], app_version=APP, clock=fixed_clock)
    (entry,) = bundle.calibration
    assert entry["consistent"] is False
    assert [v["result_ids"] for v in entry["variants"]] == [["aaa111"], ["bbb222"]]
    assert [v["axes"][0]["scale"] for v in entry["variants"]] == [0.5, 0.25]
    assert [v["source"] for v in entry["variants"]] == ["fei", "db:my-scope"]
    (note,) = bundle.warnings
    assert "img-1" in note and "aaa111" in note and "bbb222" in note
    assert "selects none" in note


def test_uncalibrated_axis_scale_is_null_not_dropped() -> None:
    record = make_record(
        calibration=(
            CalibrationSnapshot(
                image_id="img-1", axes=(AxisCal(float("nan"), 0.0, ""),), source=None
            ),
        ),
    )
    bundle = build_report([record], app_version=APP, clock=fixed_clock)
    axis = bundle.calibration[0]["variants"][0]["axes"][0]
    assert axis["scale"] is None
    assert axis["calibrated"] is False
    assert bundle.calibration[0]["variants"][0]["source"] is None
    json.dumps(bundle_payload(bundle))


def test_records_without_calibration_contribute_no_entries() -> None:
    bundle = build_report(
        [make_record(calibration=())], app_version=APP, clock=fixed_clock
    )
    assert bundle.calibration == ()


# ── methods prose ────────────────────────────────────────────────────


def test_eds_methods_paragraph() -> None:
    text = methods_paragraph(eds_record(), app_version=APP)
    assert "FermiViewer 0.1.32" in text
    assert "Fe, Cr and Ni" in text
    assert "ZAF" in text
    assert "0.085 keV" in text
    assert "100 nm" in text and "20 deg" in text
    assert "0.5 nm per sample" in text and "fei" in text


def test_profile_methods_paragraph() -> None:
    text = methods_paragraph(profile_record(), app_version=APP)
    assert "intensity profile" in text
    assert "(10, 20) to (110, 20)" in text
    assert "width of 3 px" in text
    assert "by the mean" in text
    assert "tilt of 30 deg about the Y axis in cross-section geometry" in text


def test_particles_methods_paragraph() -> None:
    text = methods_paragraph(particles_record(), app_version=APP)
    assert "threshold of 0.42" in text
    assert "bright features" in text
    assert "12 pixels in area" in text
    assert "watershed" in text and "3 px" in text
    assert "resolved cutoffs" in text


def test_diffraction_methods_paragraph_uncalibrated_camera_length() -> None:
    text = methods_paragraph(index_record(), app_version=APP)
    assert "3 measured spots" in text
    assert "200 kV" in text
    assert "tolerance of 0.05" in text
    assert "5 best-scoring candidate phases" in text
    assert "No camera length was recorded" in text
    assert "pixel size of 0.01 mm" in text
    assert "recorded ROI (circle)" in text


def test_diffraction_methods_paragraph_with_camera_length() -> None:
    text = methods_paragraph(index_record(camera_length_mm=195.0), app_version=APP)
    assert "camera length of 195 mm" in text
    assert "No camera length" not in text


def test_generic_fallback_names_resolved_parameters() -> None:
    record = make_record(
        result_id="eee555",
        analysis="eels.zlp",
        params={"window_ev": 5.0, "image_id": "img-1", "mode": "auto", "flags": [1, 2]},
    )
    assert record.analysis not in METHODS_TEMPLATES
    text = methods_paragraph(record, app_version=APP)
    # key-sorted, so the same params always render the same sentence
    assert "flags = [2 values], image_id = img-1, mode = auto, window_ev = 5" in text


def test_uncalibrated_record_says_so_and_invents_nothing() -> None:
    record = make_record(
        calibration=(
            CalibrationSnapshot(
                image_id="img-1", axes=(AxisCal(float("nan"), 0.0, ""),), source=None
            ),
        ),
        params={"image_id": "img-1"},
    )
    text = methods_paragraph(record, app_version=APP)
    assert "no finite axis calibration" in text
    assert "index units" in text
    assert "calibration source not recorded" in text


def test_record_without_calibration_snapshot_says_so() -> None:
    text = methods_paragraph(make_record(calibration=()), app_version=APP)
    assert "No calibration snapshot was recorded" in text


def test_missing_scientific_parameters_are_named_not_invented() -> None:
    record = make_record(params={"image_id": "img-1"})  # eds.quantify, nothing resolved
    text = methods_paragraph(record, app_version=APP)
    assert "not recorded with this result: elements, method, half_window_kev" in text
    assert not re.search(r"\b0\.085\b|\b100\b", text)


def test_unrecorded_app_version_falls_back_to_the_reporting_build() -> None:
    text = methods_paragraph(make_record(app_version=None), app_version=APP)
    assert "a FermiViewer version that is not recorded" in text
    assert f"report was generated by FermiViewer {APP}" in text


def test_failed_record_prose_and_bundle_do_not_imply_science() -> None:
    record = make_record(
        status="failed", error="no usable element lines in the energy range", outputs=()
    )
    bundle = build_report([record], app_version=APP, clock=fixed_clock)
    assert "recorded as failed: no usable element lines" in bundle.methods
    assert "The record carries no outputs." in bundle.methods
    assert bundle.warnings == (
        "aaa111: analysis recorded as failed: no usable element lines in the energy range",
    )


def test_methods_joins_one_paragraph_per_record_in_order() -> None:
    records = [eds_record(), profile_record()]
    bundle = build_report(records, app_version=APP, clock=fixed_clock)
    paragraphs = bundle.methods.split("\n\n")
    assert len(paragraphs) == 2
    assert paragraphs[0] == bundle.results[0]["methods"]
    assert paragraphs[1].startswith("measure.profile of img-1 (measure.profile)")


# ── captions ─────────────────────────────────────────────────────────


def test_captions_describe_each_output_kind() -> None:
    bundle = build_report([eds_record(), profile_record()], app_version=APP, clock=fixed_clock)
    scalar, table = (o["caption"] for o in bundle.results[0]["outputs"])
    (curve,) = (o["caption"] for o in bundle.results[1]["outputs"])
    assert scalar == "Scalar 'Fe': 42.1 at% +/- 1.2."
    assert table == "Table 'composition': 1 row; columns: element, atomic_pct."
    assert curve == "Curve 'profile': intensity versus distance (nm), 10 points."


# ── warning attribution ──────────────────────────────────────────────


def test_warnings_are_attributed_to_the_record_that_raised_them() -> None:
    first = make_record(result_id="aaa111", warnings=("image has no finite pixel size",))
    second = make_record(
        result_id="bbb222",
        analysis="measure.profile",
        warnings=("2 of 40 sampled intensities are non-finite", "another note"),
    )
    bundle = build_report([first, second], app_version=APP, clock=fixed_clock)
    assert bundle.warnings == (
        "aaa111: image has no finite pixel size",
        "bbb222: 2 of 40 sampled intensities are non-finite",
        "bbb222: another note",
    )


@pytest.mark.parametrize("analysis", sorted(METHODS_TEMPLATES))
def test_every_shipped_template_produces_prose(analysis: str) -> None:
    """Even a record whose params are entirely absent must produce honest
    prose rather than raise or invent a number."""
    record = make_record(analysis=analysis, params={})
    text = methods_paragraph(record, app_version=APP)
    assert text.endswith(".")
    assert analysis in text
