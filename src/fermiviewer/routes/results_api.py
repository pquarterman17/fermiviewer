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

from typing import Any

from fastapi import APIRouter, HTTPException

from fermiviewer.io.project_results import ResultRecord
from fermiviewer.io.project_sections import finite_json
from fermiviewer.project_session import project
from fermiviewer.routes._project_adapter import results_payload

router = APIRouter(prefix="/api")


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


@router.delete("/results/{result_id}")
def delete_result(result_id: str) -> dict[str, Any]:
    """Remove a record from the session; the next save writes it out of the
    project. 404 for an unknown id so a stale UI notices."""
    if not project.remove_result(result_id):
        raise HTTPException(404, f"unknown result id: {result_id}")
    return {"removed": result_id, "n_results": len(project.current().results)}
