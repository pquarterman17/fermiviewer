"""GET /jobs/{id} — poll background-job progress (plan item 22)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from fermiviewer.jobs import jobs

router = APIRouter(prefix="/api")


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"unknown job id: {job_id}")
    return job.snapshot()


@router.delete("/jobs/{job_id}")
def job_cancel(job_id: str) -> dict[str, str]:
    """Cancel a still-queued job — a running worker can't be interrupted."""
    if jobs.get(job_id) is None:
        raise HTTPException(404, f"unknown job id: {job_id}")
    if not jobs.cancel(job_id):
        raise HTTPException(409, "job already running or finished")
    return {"cancelled": job_id}
