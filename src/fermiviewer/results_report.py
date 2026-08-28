"""Report MANIFESTS over persisted results — roadmap item 2B, report half.

One selection of `ResultRecord`s in, one JSON-safe manifest out: the
records themselves (with their arrays either inlined or *cited*), a
deduped calibration summary across every source they name, generated
methods prose, and every warning attributed to the record that raised it.
This is what "build a report ... figures, tables, captions, calibration
summary, software version, and generated methods text" reduces to once the
numbers already live in the item-1 record contract (ADR 0004).

**This is a manifest, not a self-contained export**, and the distinction is
load-bearing rather than pedantic. An output whose array exceeds
`MAX_INLINE_ARRAY_VALUES` contributes its `member` name, shape and dtype
and no values — and that member is a path *inside the originating `.fvp`
container*, not a durable reference anyone outside this session can
resolve. Saving a manifest for such a result therefore yields a document
that cannot reconstruct the table or curve it names without the original
project and a second API call. That is fine for the report/preview this
module exists to build, and it is NOT the roadmap's "export selected
results as a structured bundle": that item stays open, and satisfying it
needs a container that carries the member payloads (or durable references
to them) alongside this manifest. Do not let the word "bundle" in
`ReportBundle` blur the two — the name is kept for API stability.

Three properties this module owes its callers:

* **Deterministic.** The same records, the same `app_version` and the same
  `clock` produce a byte-identical bundle. Nothing here reads a clock, a
  session, a random source or a set; every ordering is either the caller's
  record order or first-appearance order derived from it.
* **JSON-safe.** Every payload goes through `finite_json`, the repo's one
  NaN/Inf-safe coercion (`io/project_sections.py`): non-finite floats
  become ``null`` in a list and drop out of a dict, numpy scalars become
  plain numbers, and arrays are converted with `.tolist()` before they get
  there. `json.dumps(bundle_payload(...))` therefore always succeeds and
  always parses in a browser.
* **Honest about size.** An output's member array is inlined only when it
  holds at most `MAX_INLINE_ARRAY_VALUES` values; a larger one contributes
  its member name, shape and dtype and no values at all. Silently
  truncating a 10^6-row particle table into "the first few rows" would
  misrepresent the data, so the manifest cites it instead of abridging it
  — with the citation's limits stated above, not implied.

App layer only by placement: this module is pure (stdlib + numpy +
`fermiviewer.io.*`), takes `app_version` as an argument rather than
importing it, and knows nothing about HTTP. Routes adapt.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any, cast

from fermiviewer.datastruct import AxisCal
from fermiviewer.io.project_results import results_to_manifest
from fermiviewer.io.project_sections import finite_json
from fermiviewer.io.results_model import ResultOutput, ResultRecord
from fermiviewer.results_methods import methods_paragraph, output_caption

__all__ = [
    "MAX_INLINE_ARRAY_VALUES",
    "REPORT_VERSION",
    "ReportBundle",
    "build_report",
    "bundle_payload",
    "utc_now",
]

#: Bundle format version, stamped into every bundle so a later reader can
#: migrate an exported file instead of guessing its shape. Bumped when the
#: bundle's own structure changes; the records inside
#: carry the separate per-record `schema` the manifest already versions.
REPORT_VERSION = 1

#: Largest member array, in VALUES (``array.size``, not rows), that the
#: bundle inlines as nested lists. 4096 values is ~80 kB of JSON text — a
#: 2048-point curve, a 64x64 map, a 512-row seven-column table — which is
#: the scale a report actually reproduces. Anything larger is cited by
#: member name, shape and dtype and fetched from the project container,
#: because a report that silently truncated it would be wrong rather than
#: merely large.
MAX_INLINE_ARRAY_VALUES = 4096


def utc_now() -> str:
    """ISO-8601 UTC, seconds precision — the provenance-log convention.

    Deliberately a local copy of `result_capture.utc_now` rather than an
    import: that module reaches into the session store, and this one stays
    pure and importable from anywhere. Injectable via `build_report`'s
    `clock` so tests are deterministic.
    """
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ReportBundle:
    """A report over a selection of results.

    `results` are manifest-shaped record entries (`results_to_manifest`)
    plus, per record, `missing_members` and a `methods` paragraph, and per
    output `shape`/`dtype`/`values`/`values_inlined`/`caption`.
    `calibration` is one entry per distinct source image id. `methods` is
    the per-record paragraphs joined by blank lines, in record order.
    `warnings` carries every record's warnings — plus its non-completed
    status, its degraded members and any calibration disagreement — each
    prefixed with the id of the record it belongs to.
    """

    version: int
    generated_at: str
    app_version: str
    results: tuple[dict[str, Any], ...]
    calibration: tuple[dict[str, Any], ...]
    methods: str
    warnings: tuple[str, ...]


def build_report(
    records: Sequence[ResultRecord],
    *,
    app_version: str,
    clock: Callable[[], str] = utc_now,
) -> ReportBundle:
    """Assemble a `ReportBundle` from `records`, in the order given.

    `app_version` is the build generating the report (never imported here,
    so the module stays pure and the value stays injectable). `clock`
    supplies `generated_at` and is the bundle's only impurity.
    """
    entries = results_to_manifest(records)
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    for entry, record in zip(entries, records, strict=True):
        entry["missing_members"] = [str(m) for m in record.missing_members]
        entry["methods"] = methods_paragraph(record, app_version=app_version)
        outputs = cast(list[dict[str, Any]], entry.get("outputs", []))
        for out_entry, output in zip(outputs, record.outputs, strict=True):
            warnings.extend(_describe_array(out_entry, output, record.id))
        warnings.extend(_record_warnings(record))
        results.append(cast(dict[str, Any], finite_json(entry)))
    calibration, cal_warnings = _calibration_summary(records)
    warnings.extend(cal_warnings)
    return ReportBundle(
        version=REPORT_VERSION,
        generated_at=clock(),
        app_version=app_version,
        results=tuple(results),
        calibration=calibration,
        methods="\n\n".join(str(r["methods"]) for r in results),
        warnings=tuple(warnings),
    )


def bundle_payload(bundle: ReportBundle) -> dict[str, Any]:
    """The bundle as a plain JSON-safe dict — what a route or file writes."""
    return {
        "version": bundle.version,
        "generated_at": bundle.generated_at,
        "app_version": bundle.app_version,
        "results": [dict(r) for r in bundle.results],
        "calibration": [dict(c) for c in bundle.calibration],
        "methods": bundle.methods,
        "warnings": list(bundle.warnings),
    }


# ── outputs ──────────────────────────────────────────────────────────


def _describe_array(
    entry: dict[str, Any], output: ResultOutput, result_id: str
) -> list[str]:
    """Add array shape/dtype/values and a caption to one output entry.

    The bundle's own keys win over any same-named key an unknown-key carry
    put on the entry: within a bundle, `shape` means this array's shape.
    """
    array = output.array
    shape: tuple[int, ...] | None = None
    notes: list[str] = []
    if array is None:
        entry.update(shape=None, dtype=None, values=None, values_inlined=False)
    else:
        shape = tuple(int(n) for n in array.shape)
        inline = int(array.size) <= MAX_INLINE_ARRAY_VALUES
        entry.update(
            shape=[int(n) for n in shape],
            dtype=str(array.dtype),
            values=finite_json(array.tolist()) if inline else None,
            values_inlined=inline,
        )
        if not inline and output.member is None:
            notes.append(
                f"{result_id}: output '{output.name}' holds {int(array.size)} values "
                f"(over the {MAX_INLINE_ARRAY_VALUES}-value inline limit) and has no "
                f"stored member, so the bundle records its shape and dtype only"
            )
    entry["caption"] = output_caption(output, shape=shape)
    return notes


def _record_warnings(record: ResultRecord) -> list[str]:
    """This record's review state, each line attributed to its record id.

    Warnings are the record's own; the status and degraded-member lines are
    added because a report that listed neither would present an incomplete
    or failed record as ordinary science.
    """
    notes = [f"{record.id}: {w}" for w in record.warnings]
    if record.status != "completed":
        reason = record.error or "no reason was recorded"
        notes.append(f"{record.id}: analysis recorded as {record.status}: {reason}")
    if record.missing_members:
        members = ", ".join(str(m) for m in record.missing_members)
        notes.append(
            f"{record.id}: {len(record.missing_members)} member array(s) were missing "
            f"or unreadable when the project loaded ({members}); this record is degraded"
        )
    return notes


# ── calibration ──────────────────────────────────────────────────────


def _finite(value: float) -> float | None:
    """A float, or None when it is not finite — an uncalibrated axis often
    carries ``scale=NaN``, and ``null`` says that where a dropped key would
    not (`finite_json` removes a non-finite dict value outright)."""
    number = float(value)
    return number if isfinite(number) else None


def _axes_summary(axes: Sequence[AxisCal]) -> list[dict[str, Any]]:
    return [
        {
            "index": i,
            "scale": _finite(ax.scale),
            "origin": _finite(ax.origin),
            "units": ax.units,
            "calibrated": bool(ax.calibrated),
        }
        for i, ax in enumerate(axes)
    ]


def _variant_key(axes: Sequence[dict[str, Any]], source: str | None) -> tuple[Any, ...]:
    """Hashable identity of one calibration state, for exact-match dedupe."""
    return (tuple((a["scale"], a["origin"], a["units"]) for a in axes), source)


def _calibration_summary(
    records: Sequence[ResultRecord],
) -> tuple[tuple[dict[str, Any], ...], list[str]]:
    """One entry per source image id, in first-appearance order.

    Records that snapshotted the *same* image under *different* calibration
    (a recalibration between runs) produce several `variants` and
    ``consistent: false``: the bundle reports every state with the results
    that used it and never picks a winner, because there is no fact of the
    matter about which one "the" calibration was.
    """
    images: dict[str, dict[str, Any]] = {}
    variants: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {}
    for record in records:
        for snap in record.calibration:
            image_id = str(snap.image_id)
            axes = _axes_summary(snap.axes)
            entry = images.setdefault(
                image_id, {"image_id": image_id, "result_ids": [], "consistent": True}
            )
            if record.id not in entry["result_ids"]:
                entry["result_ids"].append(record.id)
            slot = variants.setdefault(image_id, {})
            key = _variant_key(axes, snap.source)
            variant = slot.get(key)
            if variant is None:
                slot[key] = {"axes": axes, "source": snap.source, "result_ids": [record.id]}
            elif record.id not in variant["result_ids"]:
                variant["result_ids"].append(record.id)
    notes: list[str] = []
    for image_id, entry in images.items():
        entry["variants"] = list(variants[image_id].values())
        entry["consistent"] = len(entry["variants"]) == 1
        if not entry["consistent"]:
            notes.append(
                f"calibration: image {image_id} was recorded under "
                f"{len(entry['variants'])} different calibrations by results "
                f"{', '.join(entry['result_ids'])}; the bundle lists every variant "
                f"and selects none"
            )
    return tuple(images.values()), notes
