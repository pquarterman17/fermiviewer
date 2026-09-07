"""Derived factor sets: store and record type (roadmap 5b, second box).

A factor set is what came out of measuring a standard: per-element
Cliff-Lorimer k or Watanabe ζ, each with its 1σ, plus enough provenance
to say what it is a factor FOR — which standard at which version, which
image and region, at what beam voltage and takeoff angle, with which
calibration profiles applied.

**Immutable, unlike a profile or a standard.** A profile is a description
that gets corrected; a factor set is a MEASUREMENT, and editing one in
place would silently change what a published composition was computed
with. Re-measuring produces a new set. So there is no `update` here and
no `history`: the two operations are create and delete.

The conditions are stored because a factor set is only valid near them.
`K_FACTORS_200KV` is the cautionary case: a table with no recorded
voltage, used at every voltage, with the extrapolation invisible in the
answer. A set derived here carries its kV so a consumer can say so.

``~/.fermiviewer/factors.json``; the profile store's rules throughout
(cross-process `StoreLock`, temp-then-replace, corrupt file preserved,
newer schema refused).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fermiviewer.storelock import StoreLock

__all__ = [
    "FACTOR_KINDS",
    "FACTOR_SCHEMA",
    "FactorEntry",
    "FactorSet",
    "FactorSetError",
    "create_factor_set",
    "db_path",
    "delete_factor_set",
    "factor_set_from_json",
    "factor_set_to_json",
    "get_factor_set",
    "list_factor_sets",
]

FACTOR_SCHEMA = 1

#: "k" is dimensionless and defined up to its reference element; "zeta"
#: is absolute, in kg/m², and specific to the detector geometry that
#: measured it. They are not interchangeable and the kind is stored.
FACTOR_KINDS = ("k", "zeta")


class FactorSetError(ValueError):
    """A factor set that cannot be read or does not make sense."""


@dataclass(frozen=True)
class FactorEntry:
    element: str
    value: float
    sigma: float = 0.0
    #: the measurement the factor came from, echoed so a reviewer can
    #: recompute it without re-running the fit
    intensity: float | None = None
    intensity_sigma: float | None = None
    weight_fraction: float | None = None
    weight_fraction_sigma: float | None = None


@dataclass(frozen=True)
class FactorSet:
    id: str
    name: str
    kind: str
    created_at: str
    factors: dict[str, FactorEntry]
    #: "k" only: which element is defined as 1.0
    reference_element: str = ""
    #: the acquisition conditions this set is a factor FOR
    conditions: dict[str, Any] = field(default_factory=dict)
    #: standard id/version, image, region — what it was derived from
    derived_from: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


_SET_KEYS = frozenset(
    {
        "id",
        "schema",
        "name",
        "kind",
        "created_at",
        "factors",
        "reference_element",
        "conditions",
        "derived_from",
        "provenance",
        "note",
    }
)

_LOCK = StoreLock(lambda: db_path())


def db_path() -> Path:
    """~/.fermiviewer/factors.json (FV_FACTORS_PATH overrides -- tests)."""
    override = os.environ.get("FV_FACTORS_PATH")
    if override:
        return Path(override)
    return Path.home() / ".fermiviewer" / "factors.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00"


def _number(value: Any, what: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise FactorSetError(f"{what} must be a number") from None
    if out != out or out in (float("inf"), float("-inf")):
        raise FactorSetError(f"{what} must be finite")
    return out


def _entry_from(symbol: str, raw: Any) -> FactorEntry:
    # A bare number is normalised into the mapping form rather than
    # short-circuiting: it used to bypass the positivity check below, so a
    # hand-edited {"Fe": 0} loaded as a factor of zero and `zeta_quantify`
    # then refused it far from where it was written.
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = {"value": raw}
    if not isinstance(raw, Mapping) or "value" not in raw:
        raise FactorSetError(f"factor {symbol!r} needs a value")
    value = _number(raw["value"], f"factor {symbol!r} value")
    if value <= 0:
        raise FactorSetError(f"factor {symbol!r} must be > 0")
    sigma = _number(raw.get("sigma", 0.0), f"factor {symbol!r} sigma")
    if sigma < 0:
        raise FactorSetError(f"factor {symbol!r} sigma must be >= 0")

    def _opt(key: str) -> float | None:
        return None if raw.get(key) is None else _number(raw[key], f"{symbol}.{key}")

    return FactorEntry(
        element=symbol,
        value=value,
        sigma=sigma,
        intensity=_opt("intensity"),
        intensity_sigma=_opt("intensity_sigma"),
        weight_fraction=_opt("weight_fraction"),
        weight_fraction_sigma=_opt("weight_fraction_sigma"),
    )


def factor_set_from_json(raw: Mapping[str, Any]) -> FactorSet:
    if not isinstance(raw, Mapping):
        raise FactorSetError("a factor set must be an object")
    for key in ("id", "name", "created_at"):
        if not str(raw.get(key, "")).strip():
            raise FactorSetError(f"a factor set needs a non-empty {key!r}")
    kind = raw.get("kind")
    if kind not in FACTOR_KINDS:
        raise FactorSetError(f"factor kind must be one of {list(FACTOR_KINDS)}, got {kind!r}")
    factors_raw = raw.get("factors")
    if not isinstance(factors_raw, Mapping) or not factors_raw:
        raise FactorSetError("a factor set needs at least one factor")
    factors = {str(sym): _entry_from(str(sym), val) for sym, val in factors_raw.items()}
    ref = str(raw.get("reference_element", "") or "")
    if kind == "k":
        if not ref:
            raise FactorSetError("a k factor set must name its reference element")
        if ref not in factors:
            raise FactorSetError(
                f"reference element {ref!r} is not among the set's factors"
            )
    elif ref:
        raise FactorSetError("a ζ factor set is absolute and has no reference element")
    return FactorSet(
        id=str(raw["id"]),
        name=str(raw["name"]),
        kind=str(kind),
        created_at=str(raw["created_at"]),
        factors=factors,
        reference_element=ref,
        conditions=dict(raw.get("conditions") or {}),
        derived_from=dict(raw.get("derived_from") or {}),
        provenance=dict(raw.get("provenance") or {}),
        note=str(raw.get("note", "") or ""),
        extra={k: v for k, v in raw.items() if k not in _SET_KEYS},
    )


def factor_set_to_json(fs: FactorSet) -> dict[str, Any]:
    return {
        **fs.extra,
        "id": fs.id,
        "schema": FACTOR_SCHEMA,
        "name": fs.name,
        "kind": fs.kind,
        "created_at": fs.created_at,
        "reference_element": fs.reference_element,
        "factors": {
            sym: {
                "value": e.value,
                "sigma": e.sigma,
                **({"intensity": e.intensity} if e.intensity is not None else {}),
                **(
                    {"intensity_sigma": e.intensity_sigma}
                    if e.intensity_sigma is not None
                    else {}
                ),
                **(
                    {"weight_fraction": e.weight_fraction}
                    if e.weight_fraction is not None
                    else {}
                ),
                **(
                    {"weight_fraction_sigma": e.weight_fraction_sigma}
                    if e.weight_fraction_sigma is not None
                    else {}
                ),
            }
            for sym, e in fs.factors.items()
        },
        "conditions": dict(fs.conditions),
        "derived_from": dict(fs.derived_from),
        "provenance": dict(fs.provenance),
        "note": fs.note,
    }


def _empty() -> dict[str, Any]:
    return {"schema": FACTOR_SCHEMA, "factor_sets": {}}


def _load() -> dict[str, Any]:
    p = db_path()
    if not p.is_file():
        return _empty()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        backup: Path | None = None
        candidate = p.with_name(f"{p.name}.corrupt-{int(time.time())}")
        try:
            os.replace(p, candidate)
            backup = candidate
        except OSError:
            pass
        warnings.warn(
            f"factor store at {p} is corrupt and could not be parsed; starting fresh"
            + (f" (bad file preserved at {backup})" if backup else ""),
            stacklevel=2,
        )
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("factor_sets"), dict):
        return _empty()
    try:
        schema = int(data.get("schema") or FACTOR_SCHEMA)
    except (TypeError, ValueError):
        raise FactorSetError(f"factor store {p} has an unreadable schema") from None
    if schema > FACTOR_SCHEMA:
        raise FactorSetError(
            f"factor store {p} has schema {schema}; this build reads {FACTOR_SCHEMA}"
        )
    return {"schema": FACTOR_SCHEMA, "factor_sets": data["factor_sets"]}


def _save(data: dict[str, Any]) -> None:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(dir=p.parent, prefix=f"{p.name}.tmp-", delete=False)
    tmp = Path(fd.name)
    try:
        with fd:
            fd.write(json.dumps(data, indent=1).encode("utf-8"))
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def list_factor_sets(kind: str | None = None) -> list[FactorSet]:
    out: list[FactorSet] = []
    with _LOCK:
        sets = _load()["factor_sets"]
    for fid, raw in sets.items():
        try:
            fs = factor_set_from_json({**raw, "id": fid})
        except (FactorSetError, TypeError, ValueError) as exc:
            warnings.warn(f"factor set {fid!r} skipped: {exc}", stacklevel=2)
            continue
        if kind is None or fs.kind == kind:
            out.append(fs)
    out.sort(key=lambda f: (f.created_at, f.id), reverse=True)
    return out


def get_factor_set(set_id: str) -> FactorSet | None:
    with _LOCK:
        raw = _load()["factor_sets"].get(set_id)
    if not isinstance(raw, Mapping):
        return None
    return factor_set_from_json({**raw, "id": set_id})


def create_factor_set(
    *,
    name: str,
    kind: str,
    factors: Mapping[str, Any],
    reference_element: str = "",
    conditions: Mapping[str, Any] | None = None,
    derived_from: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    note: str = "",
) -> FactorSet:
    if not str(name).strip():
        raise FactorSetError("a factor set needs a name")
    body = {
        "id": uuid.uuid4().hex[:12],
        "schema": FACTOR_SCHEMA,
        "name": str(name).strip(),
        "kind": kind,
        "created_at": _now(),
        "factors": dict(factors),
        "reference_element": reference_element,
        "conditions": dict(conditions or {}),
        "derived_from": dict(derived_from or {}),
        "provenance": dict(provenance or {}),
        "note": note,
    }
    fs = factor_set_from_json(body)  # validate before touching the file
    with _LOCK:
        data = _load()
        data["factor_sets"][fs.id] = {
            k: v for k, v in factor_set_to_json(fs).items() if k != "id"
        }
        _save(data)
    return fs


def delete_factor_set(set_id: str) -> bool:
    with _LOCK:
        data = _load()
        existed = data["factor_sets"].pop(set_id, None) is not None
        if existed:
            _save(data)
    return existed
