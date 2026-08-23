"""Shared result capture — the creation half of the 1C result API.

The one place an analysis route turns its computation into a persisted
`ResultRecord` (ADR 0004): mints the id, stamps time and app version,
snapshots every resolvable source's calibration at compute time, and hands
the record to the server-carried session so the next project save writes it
(`OpenProject.results` — the client never echoes records back).

Contract points enforced here rather than trusted to each caller
(`docs/persisted-results-ux.md`, the 1B adopter contract):

* **Params are the RESOLVED values** — the caller passes the full resolved
  parameter dict (defaults filled), not just what the user touched, because
  params are the reproduction key.
* **Calibration is snapshotted per source, at compute time.** A source that
  cannot be resolved right now (an unavailable placeholder) simply
  contributes no snapshot — the id reference stays, per the keep-on-save
  rule, and nothing is invented.
* **Failure is recorded, not decorated**: a `failed`/`cancelled` capture
  carries `error` and whatever outputs genuinely exist (usually none).

App layer on purpose: this module needs the session store and the project
session, so it must not live in `io/`/`ops/` — the pure record types stay
in `io/project_results.py` and routes import from here.
"""

from __future__ import annotations

import dataclasses
import datetime
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from fermiviewer import __version__
from fermiviewer.io.project_results import (
    RESULTS_DIR,
    ResultOutput,
    ResultRecord,
    new_result_id,
    snapshot_calibration,
)
from fermiviewer.project_session import project
from fermiviewer.session import UnknownImageError, store

__all__ = ["capture_result", "utc_now"]


def utc_now() -> str:
    """ISO-8601 UTC, seconds precision — the provenance-log convention."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def capture_result(
    *,
    analysis: str,
    label: str,
    source_ids: Sequence[str],
    params: dict[str, Any],
    outputs: Iterable[ResultOutput] = (),
    derived_ids: Sequence[str] = (),
    region_ids: Sequence[str] = (),
    regions: Sequence[dict[str, Any]] = (),
    warnings: Sequence[str] = (),
    status: str = "completed",
    error: str | None = None,
    clock: Callable[[], str] = utc_now,
) -> ResultRecord:
    """Build a `ResultRecord`, add it to the open session, and return it.

    `clock` is injectable so tests stay deterministic (the same rule
    `ops/provenance.py` follows).
    """
    calibration = []
    for source_id in source_ids:
        try:
            ds = store.get(source_id)
        except UnknownImageError:
            continue  # unresolved source: keep the id, invent no snapshot
        calibration.append(snapshot_calibration(source_id, ds))
    result_id = new_result_id()
    # Allocate member names NOW, not at first save: the query surface and
    # the 1B output inventory report `member` from the moment of capture,
    # and `prepare_results` preserves (and ownership-checks) existing names.
    outputs = tuple(
        dataclasses.replace(output, member=f"{RESULTS_DIR}/{result_id}/{index}.npy")
        if output.array is not None and output.member is None
        else output
        for index, output in enumerate(outputs)
    )
    record = ResultRecord(
        id=result_id,
        analysis=analysis,
        created_at=clock(),
        status=status,
        label=label,
        app_version=__version__,
        source_ids=tuple(str(i) for i in source_ids),
        derived_ids=tuple(str(i) for i in derived_ids),
        region_ids=tuple(str(i) for i in region_ids),
        regions=tuple(dict(region) for region in regions),
        params=dict(params),
        calibration=tuple(calibration),
        warnings=tuple(str(w) for w in warnings),
        error=error,
        outputs=tuple(outputs),
    )
    project.add_result(record)
    return record
