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
