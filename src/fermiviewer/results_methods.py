"""Generated methods prose and output captions for report bundles.

The text half of roadmap item 2B ("Build a report from selected results:
figures, tables, captions, calibration summary, software version, and
generated methods text"). Split from `results_report.py` on the
`io/project_results.py` / `io/results_model.py` precedent — the bundle
assembly and the prose templates each stay readable, and both stay under
the module ceiling.

Two rules govern everything here:

* **Never invent a number.** Every value in a paragraph comes from the
  record's own resolved `params`, `calibration` or `outputs`. A parameter
  that is absent, ``None`` or non-finite is not rendered at all; the
  paragraph ends with an explicit "not recorded" list instead, and an
  uncalibrated source says so in words rather than being quietly described
  in pixels as if they were nanometres.
* **Deterministic.** Same record in, same string out: no clocks, no
  randomness, no set iteration, and parameter listings are key-sorted.

`METHODS_TEMPLATES` is keyed on `ResultRecord.analysis` and covers the four
shipped 1C adopters; any other analysis falls back to `generic_template`,
which names the resolved parameters without pretending to understand them.

Pure layer: stdlib + numpy + `fermiviewer.io.*` only.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from math import isfinite
from typing import Any

import numpy as np

from fermiviewer.io.results_model import CalibrationSnapshot, ResultOutput, ResultRecord

__all__ = [
    "METHODS_TEMPLATES",
    "UNRECORDED",
    "calibration_sentence",
    "generic_template",
    "methods_paragraph",
    "output_caption",
]

#: How the prose names something the record does not carry. Never a number.
UNRECORDED = "not recorded"

#: Scientifically load-bearing parameters each template reads. Any of these
#: the record does not carry is named in the paragraph's closing sentence,
#: so a reader can tell "0.085 keV" from "we never wrote it down".
_EXPECTED: dict[str, tuple[str, ...]] = {
    "eds.quantify": ("elements", "method", "half_window_kev"),
    "measure.profile": ("width", "reduce"),
    "structure.particles": ("threshold", "polarity", "min_area"),
    "diffraction.index": ("spots", "acc_voltage_kv", "tolerance"),
}

#: The quantification routes' closed `method` set (`routes/eds_quant.py`),
#: spelled the way `calc/eds.py` implements it.
_EDS_METHODS = {
    "cliff-lorimer": "Cliff-Lorimer ratio method",
    "zaf": "Cliff-Lorimer ratio method with an iterative thin-film ZAF correction",
}


# ── value rendering ──────────────────────────────────────────────────


def _num(value: Any) -> str | None:
    """A recorded number, exactly, or None when it is absent/non-finite.

    Integral floats lose their ``.0`` and nothing else is rounded: the
    string round-trips to the same value, so the prose can never claim
    precision the record does not hold.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, float) or not isfinite(value):
        return None
    return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)


def _param(record: ResultRecord, key: str) -> str | None:
    return _num(record.params.get(key))


def _text(record: ResultRecord, key: str) -> str | None:
    value = record.params.get(key)
    return value if isinstance(value, str) and value else None


def _seq(record: ResultRecord, key: str) -> Sequence[Any] | None:
    value = record.params.get(key)
    return value if isinstance(value, (list, tuple)) and value else None


def _present(record: ResultRecord, key: str) -> bool:
    value = record.params.get(key)
    if isinstance(value, (str, list, tuple, dict)):
        return bool(value)
    if isinstance(value, bool):
        return True
    return _num(value) is not None


def _join(parts: Sequence[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _point(value: Any) -> str | None:
    """``(row, col)`` as prose, or None if either coordinate is unrecorded."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    row, col = _num(value[0]), _num(value[1])
    return None if row is None or col is None else f"({row}, {col})"


def _missing_sentence(record: ResultRecord) -> str:
    absent = [k for k in _EXPECTED.get(record.analysis, ()) if not _present(record, k)]
    if not absent:
        return ""
    return (
        "The following scientifically relevant parameters were "
        f"{UNRECORDED} with this result: {', '.join(absent)}."
    )


# ── shared frame ─────────────────────────────────────────────────────


def _sources(record: ResultRecord) -> str:
    if not record.source_ids:
        return f"a source image that is {UNRECORDED}"
    kind = "image" if len(record.source_ids) == 1 else "images"
    return f"{kind} {_join([str(i) for i in record.source_ids])}"


def _opening(record: ResultRecord, app_version: str) -> str:
    who = record.label or record.analysis
    if record.app_version:
        software = f"FermiViewer {record.app_version}"
    else:
        software = (
            f"a FermiViewer version that is {UNRECORDED} "
            f"(this report was generated by FermiViewer {app_version})"
        )
    return (
        f"{who} ({record.analysis}) was computed with {software} "
        f"on {record.created_at} from {_sources(record)}."
    )


def _snapshot_phrase(snap: CalibrationSnapshot) -> str:
    axes = [
        f"axis {i} at {_num(ax.scale)} {ax.units} per sample"
        for i, ax in enumerate(snap.axes)
        if ax.calibrated and _num(ax.scale) is not None
    ]
    source = f"calibration source {snap.source or UNRECORDED}"
    if not axes:
        return (
            f"image {snap.image_id} carried no finite axis calibration at compute "
            f"time, so its values are in index units, not calibrated ones ({source})"
        )
    return f"image {snap.image_id} calibrated {_join(axes)} ({source})"


def calibration_sentence(record: ResultRecord) -> str:
    """What the record says about the calibration it was computed under."""
    if not record.calibration:
        return (
            "No calibration snapshot was recorded with this result, so the "
            "record cannot state the scale its numbers are in."
        )
    return (
        "Calibration was snapshotted at compute time: "
        f"{_join([_snapshot_phrase(s) for s in record.calibration])}."
    )


def _outputs_sentence(record: ResultRecord) -> str:
    if not record.outputs:
        return "The record carries no outputs."
    named = _join([f"{o.kind} '{o.name}'" for o in record.outputs])
    count = "one output" if len(record.outputs) == 1 else f"{len(record.outputs)} outputs"
    return f"It produced {count}: {named}."


# ── per-analysis templates ───────────────────────────────────────────


def _eds_quantify(record: ResultRecord) -> str:
    elements = _seq(record, "elements")
    method = _text(record, "method")
    half = _param(record, "half_window_kev")
    clauses = []
    if elements:
        clauses.append(f"for the elements {_join([str(e) for e in elements])}")
    if method:
        clauses.append(f"using the {_EDS_METHODS.get(method, method)}")
    if half:
        clauses.append(
            f"integrating each element's principal line over a window of "
            f"+/-{half} keV"
        )
    quantified = f" {_join(clauses)}" if clauses else ""
    sentences = [f"Elemental composition was quantified{quantified}."]
    if method == "zaf":
        assumed = []
        thickness = _param(record, "thickness_nm")
        take_off = _param(record, "take_off_angle_deg")
        if thickness:
            assumed.append(f"a specimen thickness of {thickness} nm")
        if take_off:
            assumed.append(f"an X-ray take-off angle of {take_off} deg")
        if assumed:
            sentences.append(f"The ZAF correction assumed {_join(assumed)}.")
    return " ".join(sentences)


def _measure_profile(record: ResultRecord) -> str:
    a, b = _point(record.params.get("a")), _point(record.params.get("b"))
    points = _seq(record, "points")
    if a and b:
        geometry = f"a line from {a} to {b} (1-based row, col)"
    elif points:
        geometry = f"a polyline of {len(points)} vertices (1-based row, col)"
    else:
        geometry = f"a line whose end points are {UNRECORDED}"
    clauses = []
    width = _param(record, "width")
    if width:
        clauses.append(f"averaged over a perpendicular width of {width} px")
    reduce_by = _text(record, "reduce")
    if reduce_by:
        clauses.append(f"reduced across that width by the {reduce_by}")
    sentences = [
        "An intensity profile was sampled along "
        + geometry
        + (f", {_join(clauses)}" if clauses else "")
        + "."
    ]
    tilt = _param(record, "tilt_angle_deg")
    axis, geom = _text(record, "tilt_axis"), _text(record, "geometry")
    if tilt and float(tilt) != 0.0:
        about = f" about the {axis} axis" if axis else ""
        in_geom = f" in {geom} geometry" if geom else ""
        sentences.append(
            f"Distances were corrected for a specimen tilt of {tilt} deg{about}{in_geom}."
        )
    elif tilt:
        sentences.append("No tilt correction was applied (the recorded tilt angle is 0 deg).")
    return " ".join(sentences)


def _structure_particles(record: ResultRecord) -> str:
    clauses = []
    threshold = _param(record, "threshold")
    if threshold:
        clauses.append(f"at the resolved intensity threshold of {threshold}")
    polarity = _text(record, "polarity")
    if polarity:
        clauses.append(f"keeping {polarity} features")
    min_area = _param(record, "min_area")
    if min_area:
        clauses.append(f"discarding features smaller than {min_area} pixels in area")
    sentences = [
        "Particles were segmented by thresholding"
        + (f", {_join(clauses)}" if clauses else "")
        + "."
    ]
    watershed = record.params.get("use_watershed")
    distance = _param(record, "min_marker_distance")
    if watershed is True:
        marker = f" with a minimum marker distance of {distance} px" if distance else ""
        sentences.append(f"Touching particles were separated by a watershed{marker}.")
    elif watershed is False:
        sentences.append("No watershed separation was applied.")
    if isinstance(record.params.get("class_thresholds"), dict):
        sentences.append(
            "Shape classes were assigned with the fully resolved cutoffs recorded "
            "in this result's parameters."
        )
    return " ".join(sentences)


def _diffraction_index(record: ResultRecord) -> str:
    clauses = []
    spots = _seq(record, "spots")
    if spots:
        clauses.append(f"from {len(spots)} measured spots")
    voltage = _param(record, "acc_voltage_kv")
    if voltage:
        clauses.append(f"at an accelerating voltage of {voltage} kV")
    tolerance = _param(record, "tolerance")
    if tolerance:
        clauses.append(
            f"accepting reflections within a relative d-spacing tolerance of {tolerance}"
        )
    top_n = _param(record, "top_n")
    if top_n:
        clauses.append(f"keeping the {top_n} best-scoring candidate phases")
    sentences = [
        "The diffraction pattern was indexed"
        + (f" {_join(clauses)}" if clauses else "")
        + "."
    ]
    camera = _param(record, "camera_length_mm")
    pixel = _param(record, "pixel_size_mm")
    if camera:
        sentences.append(f"d-spacings were derived from a camera length of {camera} mm.")
    else:
        size = f" with a pixel size of {pixel} mm" if pixel else ""
        sentences.append(
            f"No camera length was recorded, so d-spacings come from the "
            f"uncalibrated width-scaled geometry{size} and are only as absolute "
            f"as that pixel size is."
        )
    if record.regions:
        kinds = _join([str(r.get("kind", UNRECORDED)) for r in record.regions])
        sentences.append(f"Indexing was restricted to the recorded ROI ({kinds}).")
    return " ".join(sentences)


def _render(value: Any) -> str:
    number = _num(value)
    if number is not None:
        return number
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value if value else "''"
    if isinstance(value, (list, tuple)):
        return f"[{len(value)} values]"
    if isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    return UNRECORDED


def generic_template(record: ResultRecord) -> str:
    """Fallback for an analysis with no template: name the parameters.

    Key-sorted so two records with equal params always produce the same
    sentence, and containers are summarised by size rather than dumped —
    a paragraph is not a data file.
    """
    if not record.params:
        return "No resolved parameters were recorded for this analysis."
    rendered = ", ".join(f"{k} = {_render(record.params[k])}" for k in sorted(record.params))
    return f"The analysis was run with the resolved parameters {rendered}."


METHODS_TEMPLATES: dict[str, Callable[[ResultRecord], str]] = {
    "eds.quantify": _eds_quantify,
    "measure.profile": _measure_profile,
    "structure.particles": _structure_particles,
    "diffraction.index": _diffraction_index,
}


def methods_paragraph(record: ResultRecord, *, app_version: str) -> str:
    """One deterministic prose paragraph describing how this record was made.

    `app_version` names the build generating the report; it is used only
    when the record itself did not record the version that computed it.
    """
    template = METHODS_TEMPLATES.get(record.analysis, generic_template)
    sentences = [
        _opening(record, app_version),
        template(record),
        _missing_sentence(record),
        calibration_sentence(record),
        _outputs_sentence(record),
    ]
    if record.status != "completed":
        sentences.append(
            f"The run is recorded as {record.status}: "
            f"{record.error or f'the reason is {UNRECORDED}'}."
        )
    if record.warnings:
        n = len(record.warnings)
        count = "1 warning was" if n == 1 else f"{n} warnings were"
        sentences.append(f"{count} recorded with this result.")
    return " ".join(s for s in sentences if s)


# ── captions ─────────────────────────────────────────────────────────


def _scalar_caption(output: ResultOutput) -> str:
    value = _num(output.data.get("value"))
    if value is None:
        return f"its value is {UNRECORDED}"
    unit = output.data.get("unit")
    sigma = _num(output.data.get("sigma"))
    text = f"{value}{f' {unit}' if isinstance(unit, str) and unit else ''}"
    return f"{text} +/- {sigma}" if sigma is not None else text


def _table_caption(output: ResultOutput, shape: tuple[int, ...] | None) -> str:
    columns = output.data.get("columns")
    names = (
        ", ".join(str(c) for c in columns)
        if isinstance(columns, (list, tuple)) and columns
        else f"columns {UNRECORDED}"
    )
    rows = output.data.get("rows")
    if isinstance(rows, (list, tuple)):
        n_rows: int | None = len(rows)
    elif shape:
        n_rows = int(shape[0])
    else:
        n_rows = None
    if n_rows is None:
        count = f"a row count that is {UNRECORDED}"
    else:
        count = "1 row" if n_rows == 1 else f"{n_rows} rows"
    return f"{count}; columns: {names}"


def _curve_caption(output: ResultOutput, shape: tuple[int, ...] | None) -> str:
    def named(prefix: str) -> str:
        name = output.data.get(f"{prefix}_name")
        unit = output.data.get(f"{prefix}_unit")
        label = str(name) if isinstance(name, str) and name else prefix
        return f"{label} ({unit})" if isinstance(unit, str) and unit else label

    n_points = int(shape[0]) if shape else None
    if n_points is None:
        points = f"a point count that is {UNRECORDED}"
    else:
        points = "1 point" if n_points == 1 else f"{n_points} points"
    axes = f"{named('y')} versus {named('x')}"
    model = output.data.get("model")
    fitted = f", model {model}" if isinstance(model, str) and model else ""
    return f"{axes}, {points}{fitted}"


def output_caption(output: ResultOutput, *, shape: tuple[int, ...] | None) -> str:
    """A one-line caption for an output, from what the record actually holds.

    `shape` is the member array's shape (None when the record carries no
    array for this output — a degraded member, or an inline-only output).
    """
    head = f"{output.kind.capitalize()} '{output.name}'"
    if output.kind == "scalar":
        body = _scalar_caption(output)
    elif output.kind == "table":
        body = _table_caption(output, shape)
    elif output.kind in ("curve", "fit"):
        body = _curve_caption(output, shape)
    elif output.kind in ("map", "overlay"):
        body = (
            f"raster of shape {'x'.join(str(int(n)) for n in shape)}"
            if shape
            else f"raster whose shape is {UNRECORDED} in this bundle"
        )
    else:
        caption = output.data.get("caption")
        body = str(caption) if isinstance(caption, str) and caption else "rendered output"
    return f"{head}: {body}."
