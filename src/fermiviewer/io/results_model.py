"""Persistent-result structures — the data half of the `.fvp` `results`
section (ADR 0004). Split from `project_results.py` on the
`project_manifest.py` / `project_file.py` precedent: the record types and
their invariants stay separately readable from the serialisation that
enforces them, both under the module ceiling.

The design argument (member storage, status vocabulary, degrade-not-fail,
snapshot-not-reference) lives in `project_results.py`'s docstring and
ADR 0004; this module holds the frozen dataclasses, the modelled-key sets,
and the id/snapshot helpers.

Pure layer: plain frozen dataclasses over plain values, numpy only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from fermiviewer.datastruct import AxisCal, DataStruct

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
    "new_result_id",
    "snapshot_calibration",
]

RESULTS_DIR = "results"

#: Revision of the per-record shape, written into each entry so a future
#: build can migrate old records individually instead of re-versioning the
#: whole container format.
RESULT_SCHEMA = 1

#: The closed set of output kinds (roadmap item 1: scalar, table, curve,
#: fit, map, overlay, figure — one shared envelope instead of a persistence
#: format per workshop). Per-kind `data` conventions are ADR 0004 §3.
OUTPUT_KINDS = frozenset({"scalar", "table", "curve", "fit", "map", "overlay", "figure"})

RESULT_STATUSES = frozenset({"completed", "failed", "cancelled"})

#: Keys this build models on a `results[]` entry / an `outputs[]` entry.
#: Anything else round-trips verbatim via `extra`, same as images.
RESULT_KEYS = frozenset(
    {
        "id",
        "schema",
        "analysis",
        "label",
        "created_at",
        "app_version",
        "status",
        "source_ids",
        "derived_ids",
        "region_ids",
        "regions",
        "params",
        "calibration",
        "warnings",
        "error",
        "outputs",
        # RESERVED, never written: the load response's route-only health
        # flag. Listed so a hand-crafted manifest key of the same name
        # cannot ride the `extra` carry or shadow the real value.
        "missing_members",
    }
)
OUTPUT_KEYS = frozenset({"kind", "name", "data", "member"})
CAL_KEYS = frozenset({"image_id", "axes", "source"})


# ── structures ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class CalibrationSnapshot:
    """The calibration one source image had when the result was computed.

    A copy, not a reference (module docstring): `axes` are the image's
    `AxisCal` values at compute time, `source` is the image's
    ``metadata["calibration_source"]`` if it recorded one (``"fei"``,
    ``"db:<key>"``, ...) — the existing provenance convention.

    Axes are the first supported snapshot content, not the last: roadmap
    item 5's quantitative calibration (detector/profile/standard identity,
    efficiency, dose, factor sets and their uncertainties) extends these
    entries with further keys. `extra` carries any such key this build does
    not model verbatim through a load → re-save, so a richer snapshot
    written by a later build survives an older one untouched.
    """

    image_id: str
    axes: tuple[AxisCal, ...] = ()
    source: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResultOutput:
    """One named output of a result.

    ``data`` is the small inline JSON payload (a scalar's value/unit/sigma,
    a table's columns/units, a curve's axis names — ADR 0004 §3). ``array``
    is the large numeric payload, carried here in memory and stored as the
    ``member`` ZIP entry, never inline. An output may have either, both
    (a table: columns inline, rows as the member) or neither (a scalar).
    """

    kind: str
    name: str
    data: dict[str, Any] = field(default_factory=dict)
    #: `results/<result-id>/<n>.npy` entry holding `array`. Allocated at
    #: save by `prepare_results`; preserved verbatim on re-save.
    member: str | None = None
    #: The array payload. Never written to the manifest. None after a load
    #: whose member was missing — see `ResultRecord.missing_members`.
    array: np.ndarray | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResultRecord:
    """One persisted analysis result — the roadmap item-1 contract.

    `params` are the RESOLVED parameters (defaults filled in), because they
    are the reproduction key: re-running the analysis with them must mean
    the same computation even if a default changes in a later release.
    `source_ids`/`derived_ids`/`region_ids` may name things no longer in
    the project; readers prune for display and MUST keep them on save
    (the same rule the schema states for `samples.image_ids`).

    `region_ids` are links to the LIVE regions; `regions` are snapshots of
    their definitions at compute time. Both exist because a region can be
    edited or deleted after the result is computed: the link lets the UI
    highlight a region that still exists, the snapshot keeps the record
    able to say exactly what geometry produced its numbers regardless —
    the same copy-not-reference rule as `calibration`.
    """

    id: str
    analysis: str
    created_at: str
    status: str
    label: str | None = None
    app_version: str | None = None
    schema: int = RESULT_SCHEMA
    source_ids: tuple[str, ...] = ()
    derived_ids: tuple[str, ...] = ()
    region_ids: tuple[str, ...] = ()
    #: JSON-safe copies of the region definitions used, as at compute time
    #: (conventionally the measure's `{id, kind, pts, holes, ...}` shape).
    #: Deliberately permissive until roadmap item 4's geometry contract.
    regions: tuple[dict[str, Any], ...] = ()
    params: dict[str, Any] = field(default_factory=dict)
    calibration: tuple[CalibrationSnapshot, ...] = ()
    warnings: tuple[str, ...] = ()
    #: What went wrong, for a failed/cancelled record. None when completed.
    error: str | None = None
    outputs: tuple[ResultOutput, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)
    #: Load-only, never written to the manifest (like `ProjectImage.thumb`):
    #: member entries the manifest named but the container did not hold, or
    #: held unreadably. Non-empty means this record's arrays are partial.
    missing_members: tuple[str, ...] = ()


def new_result_id() -> str:
    """Mint a result id — the repo's stable-id convention (`session.py`)."""
    return uuid.uuid4().hex[:12]


def snapshot_calibration(image_id: str, ds: DataStruct) -> CalibrationSnapshot:
    """Copy an image's calibration for embedding into a result record."""
    source = ds.metadata.get("calibration_source")
    return CalibrationSnapshot(
        image_id=str(image_id),
        axes=tuple(ds.axes),
        source=str(source) if isinstance(source, str) else None,
    )
