"""Background job registry — long-op progress (plan item 22).

Thread-pool execution with polled status: routes submit a callable
(usually a closure over an existing handler body) and return a job id;
the frontend polls GET /jobs/{id}. No FastAPI imports here — routes
adapt, mirroring the session-store layering.

Lifecycle: jobs are born ``queued``, flip to ``running`` when a worker
picks them up, and end ``done`` or ``error``. Cancellation reports as
``error`` so pollers always reach a terminal state. Admission is
bounded — ``submit`` raises :class:`JobQueueFullError` once
``max_pending`` jobs are queued — and :meth:`JobStore.shutdown`
(wired to the FastAPI lifespan) cancels still-queued work so quitting
the app never waits behind a queue backlog.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Job", "JobQueueFullError", "JobStore", "jobs"]

ProgressFn = Callable[[float, str], None]

MAX_PENDING = 32
"""Queued-job admission bound — generous for a single local user."""


class JobQueueFullError(RuntimeError):
    """Raised by submit() when the pending-job bound is reached."""


@dataclass
class Job:
    id: str
    status: str = "queued"  # queued | running | done | error
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _future: Future[None] | None = None

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
    def __init__(
        self, max_workers: int = 2, max_pending: int = MAX_PENDING
    ) -> None:
        self._jobs: dict[str, Job] = {}
        self._max_workers = max_workers
        self._max_pending = max_pending
        self._pool: ThreadPoolExecutor | None = self._new_pool()
        self._lock = threading.Lock()

    def _new_pool(self) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix="fv-job"
        )

    def submit(self, fn: Callable[[ProgressFn], Any]) -> str:
        """Queue fn(progress) for the pool; returns the job id immediately."""
        job = Job(id=uuid.uuid4().hex[:12])

        def run() -> None:
            with job._lock:
                if job.status != "queued":  # cancelled before starting
                    return
                job.status = "running"
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

        # Everything — pending count, eviction, pool (re)creation, AND the
        # pool.submit — happens under _lock so submit and shutdown fully
        # serialize: shutdown can never tear the pool down mid-submit (which
        # would raise RuntimeError and strand a phantom "queued" job), and a
        # submit racing shutdown either lands on the live pool before it is
        # cancelled or transparently starts a fresh one.
        with self._lock:
            pending = sum(
                1 for j in self._jobs.values() if j.status == "queued"
            )
            if pending >= self._max_pending:
                raise JobQueueFullError(
                    f"{pending} jobs already queued — retry when some finish"
                )
            # bound the registry: drop oldest finished jobs past 100
            if len(self._jobs) > 100:
                finished = [
                    k
                    for k, j in self._jobs.items()
                    if j.status in ("done", "error")
                ]
                for k in finished[:50]:
                    del self._jobs[k]
            if self._pool is None:  # restarted after shutdown()
                self._pool = self._new_pool()
            self._jobs[job.id] = job
            job._future = self._pool.submit(run)
        return job.id

    def cancel(self, job_id: str) -> bool:
        """Cancel a still-queued job. Running/finished jobs return False
        (a worker thread can't be interrupted mid-computation)."""
        job = self._jobs.get(job_id)
        if job is None or job._future is None or not job._future.cancel():
            return False
        with job._lock:
            job.status = "error"
            job.error = "cancelled"
        return True

    def shutdown(self) -> None:
        """Cancel queued work when the app stops; running jobs finish on
        their worker thread. A later submit() starts a fresh pool."""
        with self._lock:
            pool, self._pool = self._pool, None
            queued = [j for j in self._jobs.values() if j.status == "queued"]
        if pool is None:
            return
        pool.shutdown(wait=False, cancel_futures=True)
        for job in queued:
            if job._future is not None and job._future.cancelled():
                with job._lock:
                    job.status = "error"
                    job.error = "cancelled at shutdown"

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)


jobs = JobStore()
"""Process-wide default job store."""
