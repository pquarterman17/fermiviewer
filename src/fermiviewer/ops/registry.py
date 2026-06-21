"""Operation registry — single-registration name → OpSpec (Scripting #1).

Mirrors ``io/registry.py``'s one-map pattern: ``register(spec)`` once per op,
``run(name, ds, params)`` validates params against the spec and dispatches to
the pure function. The public API, batch runner, and provenance log all go
through ``run`` so a recorded, scripted, or replayed step is the same object.
"""

from __future__ import annotations

from fermiviewer.datastruct import DataStruct
from fermiviewer.ops.base import OpResult, OpSpec

__all__ = [
    "UnknownOpError",
    "get_spec",
    "list_ops",
    "register",
    "run",
]

_OPS: dict[str, OpSpec] = {}


class UnknownOpError(KeyError):
    """Raised when an operation name is not registered."""


def register(spec: OpSpec) -> OpSpec:
    """Register an op (idempotent re-registration of the same name replaces)."""
    _OPS[spec.name] = spec
    return spec


def get_spec(name: str) -> OpSpec:
    try:
        return _OPS[name]
    except KeyError:
        raise UnknownOpError(
            f"unknown op '{name}' (have: {sorted(_OPS)})"
        ) from None


def list_ops(category: str | None = None) -> list[OpSpec]:
    """All registered specs, optionally filtered to one category."""
    specs = sorted(_OPS.values(), key=lambda s: (s.category, s.name))
    return [s for s in specs if category is None or s.category == category]


def run(
    name: str, ds: DataStruct, params: dict | None = None
) -> OpResult:
    """Validate params against the op's schema and run it on ``ds``."""
    spec = get_spec(name)
    resolved = spec.resolve_params(params)
    return spec.fn(ds, resolved)
