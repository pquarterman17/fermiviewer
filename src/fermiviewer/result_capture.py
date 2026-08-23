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
* **Failure is recorded, not decorated**: a `failed` capture carries
  `error` and whatever outputs genuinely exist (usually none). Adopters
  record COMPUTATION failures — anything raised after their inputs
  resolved — when recording was requested; request-validation failures
  (unknown image id, wrong data kind, schema-invalid params) are
  deliberately not captured, because no computation was attempted.
  `cancelled` is reserved for job-backed adopters, none of which exist
  yet (the grains job is the first candidate).

App layer on purpose: this module needs the session store and the project
session, so it must not live in `io/`/`ops/` — the pure record types stay
in `io/project_results.py` and routes import from here.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from fermiviewer import __version__
from fermiviewer.io.project_results import (
    ResultOutput,
    ResultRecord,
    new_result_id,
    prepare_results,
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
    record = ResultRecord(
        id=new_result_id(),
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
    # Validate BEFORE the record joins the server-carried session: the 1A
    # save-side invariants (status/kind vocabulary, member ownership and
    # uniqueness) run here, and member names for array outputs are
    # allocated by the same code the save path uses — so a bad capture
    # fails this call, not the next project save after the session is
    # already poisoned. `add_result` additionally rejects duplicate ids.
    (record,) = prepare_results([record])
    project.add_result(record)
    return record
