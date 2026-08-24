"""Operation registry — single-registration name → OpSpec (Scripting #1).

Mirrors ``io/registry.py``'s one-map pattern: ``register(spec)`` once per op,
``run(name, ds, params)`` validates params against the spec and dispatches to
the pure function. The public API, batch runner, and provenance log all go
through ``run`` so a recorded, scripted, or replayed step is the same object.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fermiviewer.datastruct import DataStruct
from fermiviewer.ops.base import InputError, OpResult, OpSpec

__all__ = [
    "InputError",
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
    name: str,
    ds: DataStruct,
    params: dict | None = None,
    inputs: Mapping[str, Any] | None = None,
) -> OpResult:
    """Validate params against the op's schema and run it on ``ds``.

    ``ds`` is the primary subject. An op that declares auxiliary ``inputs``
    (image math's second image, a stack's remaining frames) takes them here
    as already-resolved ``DataStruct``s — the caller owns the session store,
    so the pure layer never looks an id up — and its ``fn`` is called with
    the third argument.
    """
    spec = get_spec(name)
    resolved = spec.resolve_params(params)
    if not spec.multi_input:
        if inputs:
            raise InputError(
                f"op '{name}': takes no auxiliary inputs "
                f"(got {sorted(inputs)})"
            )
        return spec.fn(ds, resolved)
    return spec.fn(ds, resolved, spec.resolve_inputs(inputs))
