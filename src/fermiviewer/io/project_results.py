"""Persistent analysis results — the `.fvp` v2 `results` section (ADR 0004).

Analyses today end their lives as transient HTTP responses: an EDS
quantification, a line profile, a particle table or a diffraction indexing
exists only until its workshop closes. This module gives them a typed,
versioned record in the project manifest (roadmap item 1A,
`plans/MICROSCOPY_FEATURE_ROADMAP.md`), so a saved project can reopen,
inspect, compare and re-run them with their provenance intact.

Design rules, argued in ADR 0004:

* A result record is **lightweight metadata**. Large arrays are ZIP members
  under ``results/<result-id>/``, never inline manifest JSON — a particle
  table or elemental map inlined into `manifest.json` would make every
  load parse megabytes of numbers it may never look at.
* ``status`` is ``completed | failed | cancelled`` — the vocabulary of a
  scientific *record*, deliberately distinct from the job poller's
  ``queued/running/done/error`` (`jobs.py`): a run that did not finish is
  recorded separately from completed science, never as some of it.
* A **missing or unreadable member degrades the record** — arrays absent,
  the entry listed in `missing_members` — and never fails the project
  load, mirroring unavailable image placeholders. A re-save keeps the
  dangling member reference, so opening a damaged project and pressing
  save cannot also destroy the evidence of what the result carried
  (ADR 0002 §4's guarantee, applied to results).
* The **calibration snapshot is a copy taken at compute time**, not a
  reference: recalibrating an image later must not silently rewrite what a
  stored composition or distance meant when it was measured. This is the
  deliberate inverse of the `measures` rule (areas derived, never stored)
  — a measure is a *definition* that should track calibration, a result is
  a *record* that must not.

Pure layer: plain frozen dataclasses over plain values, numpy only — routes
adapt. Untrusted input is assumed: ids and member paths are path-checked
before any ZIP access; member payloads load with ``allow_pickle=False``.
"""

from __future__ import annotations

import zipfile
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import numpy as np

from fermiviewer.io.project_manifest import (
    ProjectFormatError,
    axes_from_manifest,
    axes_to_manifest,
    extra_keys,
    merge_extra,
    safe_image_id,
    safe_posix_rel,
)
from fermiviewer.io.project_sections import finite_json

# Structures live in results_model.py (module-ceiling split); re-exported
# here so every existing import site keeps one canonical entry point.
from fermiviewer.io.results_model import (  # noqa: F401
    CAL_KEYS,
    OUTPUT_KEYS,
    OUTPUT_KINDS,
    RESULT_KEYS,
    RESULT_SCHEMA,
    RESULT_STATUSES,
    RESULTS_DIR,
    CalibrationSnapshot,
    ResultOutput,
    ResultRecord,
    new_result_id,
    snapshot_calibration,
)

__all__ = [
    "CAL_KEYS",
    "OUTPUT_KINDS",
    "OUTPUT_KEYS",
    "RESULTS_DIR",
    "RESULT_KEYS",
    "RESULT_SCHEMA",
    "RESULT_STATUSES",
    "CalibrationSnapshot",
    "ResultOutput",
    "ResultRecord",
    "load_results",
    "new_result_id",
    "prepare_results",
    "results_to_manifest",
    "snapshot_calibration",
    "write_result_members",
]

# ── save side ────────────────────────────────────────────────────────


def prepare_results(results: Sequence[ResultRecord]) -> tuple[ResultRecord, ...]:
    """Validate records and allocate member names, before anything is written.

    Same posture as `_check_ids` for images: id uniqueness is load-bearing
    (the id names the ``results/<id>/`` member directory), so a duplicate —
    of a record id or of an allocated member entry — is an error here, not
    a silently overwritten ZIP entry later.
    """
    seen_ids: set[str] = set()
    seen_members: set[str] = set()
    prepared: list[ResultRecord] = []
    for index, record in enumerate(results):
        where = f"results[{index}]"
        rid = safe_image_id(record.id, where=f"{where}.id")
        if rid in seen_ids:
            raise ProjectFormatError(
                f"{where}.id: duplicate result id {rid!r} — ids name the "
                f"member directory and must be unique within a project"
            )
        seen_ids.add(rid)
        if record.status not in RESULT_STATUSES:
            raise ProjectFormatError(
                f"{where}.status: {record.status!r} is not one of {sorted(RESULT_STATUSES)}"
            )
        outputs: list[ResultOutput] = []
        for out_index, output in enumerate(record.outputs):
            out_where = f"{where}.outputs[{out_index}]"
            if output.kind not in OUTPUT_KINDS:
                raise ProjectFormatError(
                    f"{out_where}.kind: {output.kind!r} is not one of {sorted(OUTPUT_KINDS)}"
                )
            member = output.member
            if member is None and output.array is not None:
                member = f"{RESULTS_DIR}/{rid}/{out_index}.npy"
            if member is not None:
                member = safe_member(member, owner_id=rid, where=f"{out_where}.member")
                if member in seen_members:
                    raise ProjectFormatError(
                        f"{out_where}.member: duplicate member entry "
                        f"{member!r} — a repeat would write a duplicate ZIP "
                        f"entry and one output would shadow the other"
                    )
                seen_members.add(member)
            outputs.append(replace(output, member=member) if member != output.member else output)
        prepared.append(replace(record, outputs=tuple(outputs)))
    return tuple(prepared)


def results_to_manifest(results: Sequence[ResultRecord]) -> list[dict[str, Any]]:
    """`results[]` manifest entries — metadata only, arrays stay out.

    `params` and output `data` pass through `finite_json`: `json.dumps`
    writes a NaN as the bare token ``NaN``, which strict JSON readers (and
    the browser's `JSON.parse`) refuse, so one non-finite float anywhere
    would produce a project this app can write and not read back.
    """
    return [_result_entry(record) for record in results]


def _result_entry(record: ResultRecord) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": record.id,
        "schema": int(record.schema),
        "analysis": record.analysis,
        "label": record.label,
        "created_at": record.created_at,
        "app_version": record.app_version,
        "status": record.status,
        "source_ids": [str(i) for i in record.source_ids],
        "derived_ids": [str(i) for i in record.derived_ids],
        "region_ids": [str(i) for i in record.region_ids],
        "regions": [finite_json(region) or {} for region in record.regions],
        "params": finite_json(record.params) or {},
        "calibration": [_calibration_entry(snap) for snap in record.calibration],
        "warnings": [str(w) for w in record.warnings],
        "error": record.error,
        "outputs": [_output_entry(output) for output in record.outputs],
    }
    return merge_extra(entry, record.extra, RESULT_KEYS)


def _output_entry(output: ResultOutput) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "kind": output.kind,
        "name": output.name,
        "data": finite_json(output.data) or {},
        "member": output.member,
    }
    return merge_extra(entry, output.extra, OUTPUT_KEYS)


def _calibration_entry(snap: CalibrationSnapshot) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "image_id": snap.image_id,
        "axes": axes_to_manifest(snap.axes),
        "source": snap.source,
    }
    # Item-5 keys a later build wrote (detector, factors, ...) ride through
    # this build's re-save untouched, like every other carried structure.
    return merge_extra(entry, finite_json(snap.extra) or {}, CAL_KEYS)


def write_result_members(zf: zipfile.ZipFile, results: Sequence[ResultRecord]) -> None:
    """Write each output's array as its member entry.

    An output with a member reference but no array — a record loaded from a
    container that had already lost the member — writes nothing and keeps
    the reference, the same way an unavailable image placeholder keeps its
    `rel` (module docstring).
    """
    for record in results:
        for output in record.outputs:
            if output.member is None or output.array is None:
                continue
            # Streamed like pixels: an elemental-map stack can be large and
            # must not be buffered whole; force_zip64 because the size is
            # unknown up front.
            with zf.open(output.member, "w", force_zip64=True) as dest:
                np.save(dest, output.array, allow_pickle=False)


# ── load side ────────────────────────────────────────────────────────


def load_results(
    zf: zipfile.ZipFile, entries: Sequence[Mapping[str, Any]]
) -> tuple[ResultRecord, ...]:
    """Manifest `results[]` (already schema-validated) back as records.

    Ids and member paths are path-checked BEFORE any ZIP access, matching
    `load_project`'s rule for image ids and rels: one hostile path
    invalidates the manifest rather than being skipped mid-read. The
    save-side identity invariants hold here too — the schema cannot check
    them, and a crafted manifest must not be able to alias one member into
    many outputs, claim another record's member directory, or smuggle in
    duplicate ids that a later session merge would resolve unpredictably.
    """
    seen_ids: set[str] = set()
    seen_members: set[str] = set()
    records: list[ResultRecord] = []
    for index, raw in enumerate(entries):
        record = _record_from_entry(raw, index)
        if record.id in seen_ids:
            raise ProjectFormatError(
                f"results[{index}].id: duplicate result id {record.id!r} — "
                f"ids name the member directory and must be unique"
            )
        seen_ids.add(record.id)
        for out_index, output in enumerate(record.outputs):
            if output.member is None:
                continue
            if output.member in seen_members:
                raise ProjectFormatError(
                    f"results[{index}].outputs[{out_index}].member: duplicate "
                    f"member entry {output.member!r} — one array must not be "
                    f"aliased into several outputs"
                )
            seen_members.add(output.member)
        records.append(record)
    return tuple(_read_arrays(zf, record) for record in records)


def _record_from_entry(raw: Mapping[str, Any], index: int) -> ResultRecord:
    where = f"results[{index}]"
    rid = safe_image_id(str(raw["id"]), where=f"{where}.id")
    outputs: list[ResultOutput] = []
    for out_index, raw_out in enumerate(raw.get("outputs") or ()):
        member = raw_out.get("member")
        outputs.append(
            ResultOutput(
                kind=str(raw_out["kind"]),
                name=str(raw_out["name"]),
                data=dict(raw_out.get("data") or {}),
                member=safe_member(
                    str(member), owner_id=rid, where=f"{where}.outputs[{out_index}].member"
                )
                if member is not None
                else None,
                extra=extra_keys(raw_out, OUTPUT_KEYS),
            )
        )
    calibration = tuple(
        CalibrationSnapshot(
            image_id=str(snap.get("image_id") or ""),
            axes=axes_from_manifest(snap.get("axes") or ()),
            source=snap.get("source"),
            extra=extra_keys(snap, CAL_KEYS),
        )
        for snap in raw.get("calibration") or ()
    )
    return ResultRecord(
        id=rid,
        analysis=str(raw["analysis"]),
        created_at=str(raw["created_at"]),
        status=str(raw["status"]),
        label=raw.get("label"),
        app_version=raw.get("app_version"),
        schema=int(raw.get("schema") or RESULT_SCHEMA),
        source_ids=tuple(str(i) for i in raw.get("source_ids") or ()),
        derived_ids=tuple(str(i) for i in raw.get("derived_ids") or ()),
        region_ids=tuple(str(i) for i in raw.get("region_ids") or ()),
        regions=tuple(
            dict(region) for region in raw.get("regions") or () if isinstance(region, Mapping)
        ),
        params=dict(raw.get("params") or {}),
        calibration=calibration,
        warnings=tuple(str(w) for w in raw.get("warnings") or ()),
        error=raw.get("error"),
        outputs=tuple(outputs),
        extra=extra_keys(raw, RESULT_KEYS),
    )


def _read_arrays(zf: zipfile.ZipFile, record: ResultRecord) -> ResultRecord:
    """Attach member arrays; a missing or unreadable member degrades the
    record instead of failing the load (module docstring)."""
    outputs: list[ResultOutput] = []
    missing: list[str] = []
    for output in record.outputs:
        if output.member is None:
            outputs.append(output)
            continue
        try:
            with zf.open(output.member) as fh:
                # allow_pickle=False: an object-array payload in a file a
                # stranger sent is arbitrary code execution, not a result.
                array: np.ndarray = np.load(fh, allow_pickle=False)
        except KeyError:
            missing.append(output.member)
            outputs.append(output)
            continue
        except (OSError, ValueError, EOFError, zipfile.BadZipFile, zlib.error):
            # Unreadable degrades like missing, not fatal: the images still
            # load and the record keeps its metadata. BadZipFile = member
            # CRC corruption, zlib.error = corrupted DEFLATE stream — both
            # are THIS member's damage, not the container's, and letting
            # either escape would turn one damaged result into a project
            # that cannot open.
            missing.append(output.member)
            outputs.append(output)
            continue
        outputs.append(replace(output, array=array))
    return replace(record, outputs=tuple(outputs), missing_members=tuple(missing))


# ── member-path safety ───────────────────────────────────────────────


def safe_member(member: str, *, owner_id: str, where: str) -> str:
    """Validate a member path as `results/<owner_id>/<component>…`.

    Same threat model as `safe_image_id`: `unzip project.fvp` is an
    advertised inspection route, so a crafted member path would plant a
    zip-slip entry. Beyond `safe_posix_rel`'s absolute/drive/`..` checks,
    the path must live in the OWNING record's directory with clean
    components — a reference into another record's directory would
    silently associate that record's data: aliasing, not sharing.
    """
    posix = safe_posix_rel(member, where=where)
    parts = posix.split("/")
    if parts[0] != RESULTS_DIR or len(parts) < 3 or parts[1] != owner_id:
        raise ProjectFormatError(
            f"{where}: result member must live under {RESULTS_DIR}/{owner_id}/, got {member!r}"
        )
    for part in parts[1:]:
        safe_image_id(part, where=where)
    return posix
