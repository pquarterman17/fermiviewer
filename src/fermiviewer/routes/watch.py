"""Folder-watch route — auto-run a saved recipe on new files (Scripting #7).

Thin adapter over :class:`fermiviewer.watch.FolderWatcher`: this module
supplies the two callables the pure poller needs — ``on_file`` (submit a
``run_recipe`` job on the shared ``jobs`` pool for the new file, mirroring
what ``routes/batch_ops.py`` does per-input for the synchronous multi-image
endpoint) and ``is_openable`` (the io registry's default extension check,
via ``watch.default_is_openable``).

Only ONE watch may be active per process — the simplest correct semantics
for a single-user desktop session: ``POST /watch/start`` while a watch is
already running is 409 (stop it, or wait for it to be stopped, before
starting another). All state — the active ``FolderWatcher``, the job ids it
has submitted, and the last known status snapshot (kept around so ``GET
/watch/status`` still reports something useful right after a stop) — lives
in module globals guarded by one lock, the same singleton pattern
``jobs.py``/``session.py`` use.

AUTO-SHUTDOWN INTERACTION: an active watch means the user has deliberately
left the app with no browser tab open at all — that IS the point of
"watching a folder unattended". ``is_watch_active()`` is the hook
``server.py``'s desktop-auto-shutdown grace-check consults before treating
"last tab closed" as "time to exit"; see that module's docstring for the
full reasoning. ``shutdown_watch()`` is wired to the FastAPI lifespan
(NEVER atexit — see ``jobs.py``'s shutdown docstring for why that
distinction matters for a bounded, orderly exit) so the poller thread is
always cleanly joined when the server stops, and it is reused directly as
the body of ``POST /watch/stop`` so both paths behave identically.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.io.regions_model import RegionSet
from fermiviewer.io.registry import load_auto
from fermiviewer.jobs import ProgressFn, jobs
from fermiviewer.ops.batch import run_recipe
from fermiviewer.project_session import project
from fermiviewer.recipe_regions import substitute_region_refs
from fermiviewer.routes._paths import checked_data_path
from fermiviewer.routes.batch_ops import (
    BatchStepRequest,
    json_safe,
    register_final_image,
    resolve_recipe_inputs,
    validate_recipe_steps,
)
from fermiviewer.session import store
from fermiviewer.watch import FolderWatcher, default_is_openable

__all__ = ["is_watch_active", "router", "shutdown_watch"]

router = APIRouter(prefix="/api")

_lock = threading.Lock()
_watcher: FolderWatcher | None = None
_job_ids: list[str] = []
_last_status: dict[str, Any] = {
    "dir": None, "seen": 0, "processed": 0, "errors": 0, "last_error": None,
}


class WatchStartRequest(BaseModel):
    dir: str
    steps: list[BatchStepRequest] = Field(min_length=1, max_length=30)
    interval: float = Field(default=1.0, gt=0, le=60)
    # the recipe's auxiliary-input pool (ADR 0005 §8): recipe input name ->
    # session image id(s). Bound once when the watch starts, so every file
    # the watch picks up is processed against the SAME reference datasets
    inputs: dict[str, str | list[str]] = Field(default_factory=dict)


def is_watch_active() -> bool:
    """server.py's desktop auto-shutdown grace-check consults this before
    exiting — an active watch must inhibit the "last tab closed" timer."""
    with _lock:
        return _watcher is not None


def shutdown_watch() -> None:
    """Stop any active watch, joining its poll thread. Wired to the FastAPI
    lifespan (see server.py's ``_lifespan``) and reused as ``POST
    /watch/stop``'s body; idempotent when nothing is watching."""
    global _watcher, _last_status
    with _lock:
        watcher, _watcher = _watcher, None
        if watcher is not None:
            _last_status = watcher.status()
    if watcher is not None:
        watcher.stop()


def _run_watch_job(
    path: Path,
    steps: list[dict[str, Any]],
    report: ProgressFn,
    pool: dict[str, Any] | None = None,
    recipe_inputs: dict[str, str | list[str]] | None = None,
    region_sets: tuple[RegionSet, ...] = (),
) -> dict[str, Any]:
    """The job body queued per new file: load it fresh, register it, run
    the recipe, and register the final chained image — the single-input
    analogue of ``routes/batch_ops.py``'s ``_run_batch``."""
    ds = load_auto(path)
    image_id = store.add_parsed(ds, path.name)

    def step_progress(index: int, total: int, result: Any) -> None:
        report(index / total, result.label)

    bindings = dict(recipe_inputs or {})
    # the datasets resolved when the watch STARTED, closed over — a watch
    # runs for hours over many files, and every one of them must see the
    # same reference data the caller bound at /watch/start
    # A named region is resolved HERE, against the file just loaded, for
    # the same reason as in `_run_batch`: `run_recipe` is pure and only
    # ever reads `step["params"]`, so a `region_ref` left unsubstituted
    # would be silently ignored and the new file analyzed whole-image —
    # the quiet wrong answer, not an error.
    scoped_steps = substitute_region_refs(steps, region_sets, image_id)
    recipe = run_recipe(
        ds, scoped_steps, progress=step_progress, inputs=dict(pool or {})
    )
    has_image = any(step.produces_image for step in recipe.steps)
    derived = (
        register_final_image(image_id, path.name, recipe.final, steps, bindings)
        if has_image
        else None
    )
    return {
        "image_id": image_id,
        "name": path.name,
        "derived": derived,
        "values": [
            {
                "op": result.op,
                "label": result.label,
                "params": result.params,
                "value": json_safe(result.value),
            }
            for result in recipe.values
        ],
    }


def _on_new_file(
    path: Path,
    steps: list[dict[str, Any]],
    pool: dict[str, Any] | None = None,
    recipe_inputs: dict[str, str | list[str]] | None = None,
    region_sets: tuple[RegionSet, ...] = (),
) -> None:
    """``FolderWatcher``'s ``on_file`` callback: submit and return right
    away so a slow recipe never blocks the poll loop from noticing the next
    file (a JobQueueFullError here is caught by FolderWatcher and surfaced
    through ``last_error`` — the file stays marked processed, not retried)."""
    job_id = jobs.submit(
        lambda report: _run_watch_job(
            path, steps, report, pool, recipe_inputs, region_sets
        )
    )
    with _lock:
        _job_ids.append(job_id)


@router.post("/watch/start")
def watch_start(req: WatchStartRequest) -> dict[str, str]:
    directory = Path(checked_data_path(req.dir, where="dir"))
    if not directory.exists():
        raise HTTPException(404, f"directory not found: {req.dir}")
    if not directory.is_dir():
        raise HTTPException(422, f"not a directory: {req.dir}")
    steps = validate_recipe_steps(
        [step.model_dump() for step in req.steps], req.inputs
    )
    # fail the START call on an unknown auxiliary id, rather than every file
    # the watch later picks up — and keep the resolved datasets, so a watch
    # running for hours is not re-reading ids that may since have been
    # removed (which is what the "bound once at start" promise means)
    pool = resolve_recipe_inputs(req.inputs)
    # Snapshotted at START, exactly like `pool` and for the same promise:
    # every file this watch picks up is measured over the region the
    # caller bound here, not over whatever the project holds hours later.
    region_sets = project.current().region_sets

    global _watcher, _job_ids
    with _lock:
        if _watcher is not None:
            raise HTTPException(
                409, "a folder watch is already active — stop it first"
            )
        _job_ids = []
        watcher = FolderWatcher(
            directory=directory,
            on_file=lambda path: _on_new_file(
                path, steps, pool, req.inputs, region_sets
            ),
            is_openable=default_is_openable,
            interval=req.interval,
        )
        watcher.start()
        _watcher = watcher
    return {"status": "watching"}


@router.post("/watch/stop")
def watch_stop() -> dict[str, str]:
    shutdown_watch()
    return {"status": "stopped"}


@router.get("/watch/status")
def watch_status() -> dict[str, Any]:
    with _lock:
        watcher = _watcher
        job_ids = list(_job_ids)
        snapshot = _last_status
    if watcher is not None:
        snapshot = watcher.status()
    return {**snapshot, "watching": watcher is not None, "job_ids": job_ids}
