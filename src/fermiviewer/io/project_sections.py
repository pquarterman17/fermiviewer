"""The v1 `client_state` blob ⇄ the v2 manifest's specified sections.

ADR 0002 §5 promotes the scientific content out of v1's one opaque blob into
sections the schema validates — `samples` (named member sets with **parameter
values and units**) and `measures` (annotations and regions per image) — while
genuinely presentational state stays opaque under `ui_state`.

The client still speaks one `client_state` object, because the store slice it
serialises is one object (`frontend/src/store/viewerSession.ts` `clientState`).
So the split happens exactly once, here, and both directions live together
because they have to agree:

    split_client_state(client_state) -> Sections(samples, measures, ui_state)
    join_sections(samples, measures, ui_state) -> client_state

The same split migrates a v1 workspace (plan #32) — a v1 file's `client_state`
IS this shape, so migration is this function plus the pixels.

**Nothing here may make a save fail.** A malformed sample or measure is
dropped and counted, never raised: the manifest is schema-validated before the
container is committed, so a stray entry that cannot satisfy the schema would
otherwise take the whole project down with it. Parameter values and point
coordinates are additionally required to be *finite* — `json.dumps` happily
writes `NaN`, which `JSON.parse` then refuses, so one bad float would produce a
project this app can write and not read.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from fermiviewer.io.project_manifest import json_safe

__all__ = [
    "MEASURE_KINDS",
    "PROMOTED_KEYS",
    "Sections",
    "finite_json",
    "join_sections",
    "split_client_state",
]

#: Client-state keys promoted into their own validated manifest sections.
#: Everything else in `client_state` is presentational and rides `ui_state`.
PROMOTED_KEYS = ("imageGroups", "measures")

#: The measure kinds the schema accepts, mirroring `MeasureKind` in
#: `frontend/src/store/viewerTypes.ts` (and its `lib/measureKinds.ts`
#: partition). A kind outside this set cannot be written, so it is dropped
#: rather than allowed to fail the save.
MEASURE_KINDS = frozenset(
    {
        "distance",
        "profile",
        "angle",
        "roi",
        "ellipse",
        "polyline",
        "polygon",
        "lasso",
        "text",
        "arrow",
        "box",
        "circle",
    }
)

_SAMPLE_MODELLED = frozenset({"id", "name", "ids", "image_ids", "parent", "params", "color"})
_MEASURE_MODELLED = frozenset({"id", "kind", "pts"})


@dataclass(frozen=True)
class Sections:
    """A `client_state` split into what the schema checks and what it doesn't."""

    samples: list[dict[str, Any]] = field(default_factory=list)
    measures: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    ui_state: dict[str, Any] = field(default_factory=dict)
    #: Entries that could not be represented, so a caller can say so instead
    #: of the user finding out later that something vanished.
    dropped_samples: int = 0
    dropped_measures: int = 0


# ── scalars ──────────────────────────────────────────────────────────


def _scalar(value: Any) -> Any:
    """A JSON scalar the schema will accept, or None.

    Bools are tested before ints on purpose: `isinstance(True, int)` is true,
    and a boolean parameter must stay boolean rather than becoming 1.
    """
    if isinstance(value, bool) or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else None
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if isfinite(value) else None


def finite_json(value: Any) -> Any:
    """`json_safe`, with non-finite floats removed as well.

    `json_safe` keeps a NaN, because to `json.dumps` a float IS
    representable — it writes the bare token `NaN`, which `JSON.parse` then
    refuses. A single one anywhere in a nested unknown field or in `ui_state`
    would therefore make the entire load response unparseable in the browser,
    not just that field. `_scalar` and `_number` guard the values this reader
    models; this guards the ones it carries verbatim, which is the whole point
    of carrying them.

    Follows `json_safe`'s conventions for what it drops: an unrepresentable
    dict value loses its key, an unrepresentable list element becomes None so
    the remaining indices stay aligned with the source list.
    """
    return _scrub(json_safe(value))


def _scrub(value: Any) -> Any:
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            scrubbed = _scrub(item)
            if scrubbed is not None or item is None:
                out[key] = scrubbed
        return out
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _carry(
    entry: dict[str, Any], source: Mapping[str, Any], modelled: frozenset[str]
) -> None:
    """Copy the keys this reader does not model, keeping only what survives a
    JSON round-trip. A newer client's extra field on a measure or a sample
    therefore rides through a save by an older build (ADR 0002 §6)."""
    for key, value in source.items():
        if key in modelled or not isinstance(key, str):
            continue
        nested = isinstance(value, (Mapping, list, tuple))
        carried = finite_json(value) if nested else _scalar(value)
        if carried is not None or value is None:
            entry[key] = carried


# ── samples ──────────────────────────────────────────────────────────


def _params(raw: Any) -> dict[str, Any]:
    """`params` narrowed to the schema's `{value, unit}` shape.

    Mirrors `normalizeGroupParams` in `frontend/src/lib/groups.ts` — the store
    normalises on the way in, and this normalises on the way out, so a value
    hand-edited into a file cannot make the next save unwritable.
    """
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key, param in raw.items():
        if not isinstance(key, str) or not key or not isinstance(param, Mapping):
            continue
        value = _scalar(param.get("value"))
        if value is None:
            continue
        unit = param.get("unit")
        out[key] = {"value": value, "unit": unit if isinstance(unit, str) else None}
    return out


def _sample(group: Any) -> dict[str, Any] | None:
    """One `imageGroups[]` entry as a manifest `samples[]` entry.

    A sample IS an ImageGroup (ADR 0002 §5); only `ids` is renamed, to
    `image_ids`. Member ids are NOT pruned here — the schema says a reader
    prunes for display and must keep them on save, which is what lets a
    sample remember an image whose data is missing on this machine.
    """
    if not isinstance(group, Mapping):
        return None
    group_id = group.get("id")
    if not isinstance(group_id, str) or not group_id:
        return None
    raw_ids = group.get("ids", group.get("image_ids"))
    ids = (
        [i for i in raw_ids if isinstance(i, str) and i]
        if isinstance(raw_ids, (list, tuple))
        else []
    )
    name = group.get("name")
    parent = group.get("parent")
    color = group.get("color")
    sample: dict[str, Any] = {
        "id": group_id,
        "name": name if isinstance(name, str) else group_id,
        "image_ids": ids,
        "parent": parent if isinstance(parent, str) and parent else None,
        "params": _params(group.get("params")),
        "color": color if isinstance(color, str) else None,
    }
    _carry(sample, group, _SAMPLE_MODELLED)
    return sample


def _group(sample: Mapping[str, Any]) -> dict[str, Any]:
    """A manifest `samples[]` entry back as the store's `ImageGroup` shape."""
    raw_ids = sample.get("image_ids")
    group: dict[str, Any] = {
        "id": str(sample.get("id", "")),
        "name": str(sample.get("name", "")),
        "ids": [i for i in raw_ids if isinstance(i, str)]
        if isinstance(raw_ids, (list, tuple))
        else [],
        "parent": sample.get("parent"),
        "params": _params(sample.get("params")),
        "color": sample.get("color"),
    }
    _carry(group, sample, _SAMPLE_MODELLED)
    return group


# ── measures ─────────────────────────────────────────────────────────


def _points(raw: Any) -> list[dict[str, float]] | None:
    if not isinstance(raw, (list, tuple)):
        return None
    out: list[dict[str, float]] = []
    for point in raw:
        if not isinstance(point, Mapping):
            return None
        x, y = _number(point.get("x")), _number(point.get("y"))
        if x is None or y is None:
            return None
        out.append({"x": x, "y": y})
    return out


def _measure(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    measure_id = raw.get("id")
    kind = raw.get("kind")
    if not isinstance(measure_id, str) or not measure_id or kind not in MEASURE_KINDS:
        return None
    pts = _points(raw.get("pts"))
    if pts is None:
        return None
    measure: dict[str, Any] = {"id": measure_id, "kind": kind, "pts": pts}
    _carry(measure, raw, _MEASURE_MODELLED)
    return measure


# ── the split ────────────────────────────────────────────────────────


def split_client_state(client_state: Mapping[str, Any] | None) -> Sections:
    """Promote `imageGroups` → `samples` and validate `measures`; the rest is
    `ui_state`, passed through verbatim so its shape stays free to change
    without a format revision (ADR 0002 §5)."""
    state = client_state or {}
    samples: list[dict[str, Any]] = []
    dropped_samples = 0
    raw_groups = state.get("imageGroups")
    if isinstance(raw_groups, (list, tuple)):
        for group in raw_groups:
            sample = _sample(group)
            if sample is None:
                dropped_samples += 1
            else:
                samples.append(sample)

    measures: dict[str, list[dict[str, Any]]] = {}
    dropped_measures = 0
    raw_measures = state.get("measures")
    if isinstance(raw_measures, Mapping):
        for image_id, entries in raw_measures.items():
            if not isinstance(image_id, str) or not isinstance(entries, (list, tuple)):
                dropped_measures += 1 if entries else 0
                continue
            kept = []
            for entry in entries:
                measure = _measure(entry)
                if measure is None:
                    dropped_measures += 1
                else:
                    kept.append(measure)
            # An image with no surviving measures gets no key at all rather
            # than an empty list, so the manifest does not grow a row per
            # image the user never annotated.
            if kept:
                measures[image_id] = kept

    ui_state = {
        key: finite_json(value)
        for key, value in state.items()
        if key not in PROMOTED_KEYS and isinstance(key, str)
    }
    return Sections(
        samples=samples,
        measures=measures,
        ui_state=ui_state,
        dropped_samples=dropped_samples,
        dropped_measures=dropped_measures,
    )


def join_sections(
    samples: Sequence[Mapping[str, Any]],
    measures: Mapping[str, Sequence[Mapping[str, Any]]],
    ui_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The inverse: one `client_state` object for the client to restore from.

    `ui_state` cannot shadow a promoted key — a hand-edited file that put
    `measures` in both places must not be able to hide the validated copy.
    """
    client_state: dict[str, Any] = {
        key: value
        for key, value in (ui_state or {}).items()
        if key not in PROMOTED_KEYS
    }
    client_state["imageGroups"] = [_group(sample) for sample in samples]
    client_state["measures"] = {
        image_id: [dict(measure) for measure in entries]
        for image_id, entries in measures.items()
    }
    return client_state
