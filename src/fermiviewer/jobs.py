"""Background job registry — long-op progress (plan item 22).

Thread-pool execution with polled status: routes submit a callable
(usually a closure over an existing handler body) and return a job id;
the frontend polls GET /jobs/{id}. No FastAPI imports here — routes
adapt, mirroring the session-store layering.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Job", "JobStore", "jobs"]

ProgressFn = Callable[[float, str], None]


@dataclass
class Job:
    id: str
    status: str = "running"  # running | done | error
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def report(self, fraction: float, message: str = "") -> None:
        with self._lock:
            self.progress = max(0.0, min(1.0, fraction))
            if message:
                self.message = message

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            out: dict[str, Any] = {
                "id": self.id,
                "status": self.status,
                "progress": self.progress,
                "message": self.message,
            }
            if self.status == "done":
                out["result"] = self.result
            if self.status == "error":
                out["error"] = self.error
            return out


class JobStore:
    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, Job] = {}
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="fv-job"
        )
        self._lock = threading.Lock()

    def submit(self, fn: Callable[[ProgressFn], Any]) -> str:
        """Run fn(progress) in the pool; returns the job id immediately."""
        job = Job(id=uuid.uuid4().hex[:12])
        with self._lock:
            # bound the registry: drop oldest finished jobs past 100
            if len(self._jobs) > 100:
                done = [
                    k for k, j in self._jobs.items() if j.status != "running"
                ]
                for k in done[:50]:
                    del self._jobs[k]
            self._jobs[job.id] = job

        def run() -> None:
            try:
                result = fn(job.report)
                with job._lock:
                    job.result = result
                    job.progress = 1.0
                    job.status = "done"
            except Exception as e:  # noqa: BLE001 — surfaced to the client
                with job._lock:
                    job.error = str(e)
                    job.status = "error"

        self._pool.submit(run)
        return job.id

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)


jobs = JobStore()
"""Process-wide default job store."""
