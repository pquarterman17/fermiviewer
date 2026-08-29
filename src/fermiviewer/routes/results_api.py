"""Persisted-result query surface — the read half of the 1C result API.

The Results & Methods workspace (1B) receives record *metadata* on project
load; these endpoints are what lets detail, comparison and export views
reach the rest without parsing `.fvp` containers in the browser
(`docs/persisted-results-ux.md`): list and fetch records session-wide,
pull one output's member-backed array as JSON, and drop a record the user
no longer wants saved.

Array data comes back as finite-scrubbed nested lists with shape/dtype —
honest JSON for the table/curve/fit payloads these views consume. Bulk
binary transfer for large maps is item 7's disk-backed store, not this
surface. A degraded output (member lost or unreadable at load) is a 404
naming the member, never invented zeros.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from typing import IO, Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from fermiviewer import __version__
from fermiviewer.io.project_manifest import ProjectFormatError
from fermiviewer.io.project_results import ResultRecord
from fermiviewer.io.project_sections import finite_json
from fermiviewer.project_session import project
from fermiviewer.results_compare import compare_results
from fermiviewer.results_export import build_archive, write_archive
from fermiviewer.results_report import build_report, bundle_payload
from fermiviewer.routes._project_adapter import results_payload
from fermiviewer.routes.export_table import _safe_filename

router = APIRouter(prefix="/api")


#: Archive bytes held in RAM before the spool rolls to a temp file. 32 MiB
#: covers an ordinary selection outright; past it the cost of a disk file
#: is much cheaper than the alternative, which is the whole ZIP resident.
SPOOL_MAX_BYTES = 32 << 20

#: Read size when draining the spool to the client.
_CHUNK_BYTES = 1 << 20


def _safe_zip_name(filename: str | None) -> str:
    """The repo's one download-name sanitiser, with the extension forced to
    `.zip` — reused rather than re-derived so the latin-1 header hazard it
    documents stays fixed in one place."""
    return _safe_filename(filename, "zip")


def _drain(spool: IO[bytes]) -> Iterator[bytes]:
    """Yield the spooled archive in chunks, closing it however we leave.

    `finally` rather than a plain close at the end: a client that
    disconnects mid-download causes the generator to be closed rather than
    exhausted, and a spool that rolled to disk would otherwise leak its
    temp file for the life of the process.
    """
    try:
        while chunk := spool.read(_CHUNK_BYTES):
            yield chunk
    finally:
        spool.close()


def _record(result_id: str) -> ResultRecord:
    for record in project.current().results:
        if record.id == result_id:
            return record
    raise HTTPException(404, f"unknown result id: {result_id}")


@router.get("/results")
def list_results() -> dict[str, Any]:
    """Every record the session carries, in manifest form + health flag —
    the same shape a project load returns, so the client has one parser."""
    return {"results": results_payload(project.current().results)}


@router.get("/results/{result_id}")
def result_detail(result_id: str) -> dict[str, Any]:
    record = _record(result_id)
    (entry,) = results_payload((record,))
    return entry


@router.get("/results/{result_id}/outputs/{index}/data")
def output_data(result_id: str, index: int) -> dict[str, Any]:
    """One output's full payload: inline `data` plus the member array as
    finite-scrubbed nested lists (non-finite → null, indices preserved)."""
    record = _record(result_id)
    if not 0 <= index < len(record.outputs):
        raise HTTPException(404, f"result {result_id} has no output {index}")
    output = record.outputs[index]
    if output.member is not None and output.array is None:
        raise HTTPException(
            404,
            f"output data unavailable: member {output.member} was missing or "
            f"unreadable when the project loaded",
        )
    array = output.array
    return {
        "kind": output.kind,
        "name": output.name,
        "data": finite_json(output.data) or {},
        "member": output.member,
        "shape": list(array.shape) if array is not None else None,
        "dtype": str(array.dtype) if array is not None else None,
        "values": finite_json(array.tolist()) if array is not None else None,
    }


class CompareRequest(BaseModel):
    reference_id: str
    #: Omit to compare the reference against every other record in the
    #: session — the "what else can I put beside this?" question a results
    #: browser asks first. An explicit list answers "can I put THESE
    #: beside it?", and each id gets its own verdict either way.
    candidate_ids: list[str] | None = None


@router.post("/results/compare")
def results_compare(req: CompareRequest) -> dict[str, Any]:
    """Which of `candidate_ids` can be compared with `reference_id`, and —
    for each that cannot — exactly why (item 2B).

    The rejection MESSAGE is the payload here, not the boolean: "different
    analyses", "units differ", "this one failed" are all answerable from
    the record, and a browser that only greys a card out makes the user
    guess which of those it was.
    """
    records = project.current().results
    reference = _record(req.reference_id)
    if req.candidate_ids is None:
        candidates = [r for r in records if r.id != req.reference_id]
    else:
        candidates = [_record(rid) for rid in req.candidate_ids]
    result = compare_results(reference, candidates)
    return {
        "reference_id": result.reference_id,
        # The cumulative intersection: comparable with EVERY entry below.
        # Honestly empty when the candidates are only pairwise comparable
        # (each match carries its own `outputs`, which is what a pairwise
        # comparison view should render), and `notes` says so when it is.
        "outputs": list(result.outputs),
        "compatible": [
            {
                "id": match.id,
                "outputs": list(match.outputs),
                # Structured, not collapsed to its differences: "agrees" and
                # "nothing in common to compare" are different answers, and
                # for the cross-image case — the primary one — the second is
                # what actually happens. `verified` is the honest boolean;
                # `agrees` is vacuously true with no shared source.
                "calibration_agreement": {
                    "verified": match.calibration_agreement.verified,
                    "agrees": match.calibration_agreement.agrees,
                    "shared_sources": list(
                        match.calibration_agreement.shared_sources
                    ),
                    "reference_only": list(
                        match.calibration_agreement.reference_only
                    ),
                    "candidate_only": list(
                        match.calibration_agreement.candidate_only
                    ),
                    "differences": list(match.calibration_agreement.differences),
                },
            }
            for match in result.compatible
        ],
        "rejected": [
            {"id": rid, "code": why.code, "message": why.message}
            for rid, why in result.rejected
        ],
        "notes": list(result.notes),
    }


class ReportRequest(BaseModel):
    #: The records to report on, in the order the caller wants them read —
    #: a report is a composed document, so selection order is the author's
    #: and is preserved rather than re-sorted here.
    result_ids: list[str] = Field(min_length=1, max_length=200)


@router.post("/results/report")
def results_report(req: ReportRequest) -> dict[str, Any]:
    """A structured report bundle over the selected records (item 2B).

    Deterministic apart from `generated_at`: the same selection of the same
    records yields the same bundle, which is what makes a report worth
    citing. Large member arrays are referenced by member name with their
    shape and dtype rather than inlined or — worse — truncated; the
    threshold is `results_report.MAX_INLINE_ARRAY_VALUES`.

    Unknown ids are a 404 naming ALL of them, not just the first: a report
    is assembled from a selection, and telling the caller about one missing
    id at a time turns fixing the selection into a guessing game.
    """
    known = {record.id: record for record in project.current().results}
    missing = [rid for rid in req.result_ids if rid not in known]
    if missing:
        raise HTTPException(404, f"unknown result id(s): {missing}")
    bundle = build_report(
        [known[rid] for rid in req.result_ids], app_version=__version__
    )
    return bundle_payload(bundle)


class ExportRequest(ReportRequest):
    """Same selection contract as a report — an export IS a report plus the
    arrays it cites, so the two must not drift on which records they can
    take or in what order they read."""

    #: Download name; the extension is forced to `.zip` server-side.
    filename: str | None = None


@router.post("/results/export")
def results_export(req: ExportRequest) -> StreamingResponse:
    """The selected records as a SELF-CONTAINED archive (item 2's last box).

    `/results/report` returns a manifest whose `member` citations point
    into the originating `.fvp`; this returns a ZIP in which those same
    citations resolve, because the member arrays travel with it. Nothing in
    the download needs the project it came from.

    A degraded output — its member already lost when the project loaded —
    contributes no entry, keeps its citation, and is named in the
    manifest's warnings. Filling the gap with zeros would turn a missing
    array into a wrong one.
    """
    known = {record.id: record for record in project.current().results}
    missing = [rid for rid in req.result_ids if rid not in known]
    if missing:
        raise HTTPException(404, f"unknown result id(s): {missing}")
    try:
        archive = build_archive(
            [known[rid] for rid in req.result_ids], app_version=__version__
        )
    except ProjectFormatError as exc:
        # `prepare_results` rejects duplicate ids and unsafe member names.
        # A malformed selection is the caller's 422, not a 500 — and it is
        # caught before any bytes are produced, so no half-written download.
        raise HTTPException(422, f"cannot export this selection: {exc}") from None

    # The archive accumulates in a SPOOLED file, not a `BytesIO`: an
    # ordinary export stays in RAM, but a selection carrying elemental-map
    # stacks or spectrum cubes — the payloads this endpoint exists to make
    # portable — rolls to disk instead of holding the whole ZIP, and a
    # second copy of it, in memory. `write_archive` streams each array into
    # its entry; this is the other half of keeping the endpoint bounded.
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES)
    try:
        write_archive(archive, spool)
        spool.seek(0)
    except BaseException:
        spool.close()
        raise
    return StreamingResponse(
        _drain(spool),
        media_type="application/zip",
        headers={
            "Content-Disposition":
                f'attachment; filename="{_safe_zip_name(req.filename)}"'
        },
    )


@router.delete("/results/{result_id}")
def delete_result(result_id: str) -> dict[str, Any]:
    """Remove a record from the session; the next save writes it out of the
    project. 404 for an unknown id so a stale UI notices."""
    if not project.remove_result(result_id):
        raise HTTPException(404, f"unknown result id: {result_id}")
    return {"removed": result_id, "n_results": len(project.current().results)}
