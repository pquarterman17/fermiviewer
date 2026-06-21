"""Operation vocabulary core types — Scripting #1.

An *operation* is a named, parameterized step over a ``DataStruct``: the shared
unit the public API, the analysis-batch runner, and the provenance log all
speak. ``OpResult`` is what running one yields — either a derived image or a
plain value (scalar/table) — plus the resolved params for provenance.

Schemas are plain dataclasses (NOT pydantic) so this layer stays pure
(``ops`` is in PURE_LAYERS — no fastapi/pydantic, enforced by the layering
guard). Pure-library: datastruct/numpy/stdlib only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fermiviewer.datastruct import DataStruct

__all__ = ["OpParam", "OpResult", "OpSpec", "ParamError"]


class ParamError(ValueError):
    """Raised when supplied params don't satisfy an op's schema."""


def _to_bool(value: Any) -> bool:
    """Coerce a value to bool, treating the common JSON/string falsy spellings
    ("false"/"no"/"0"/"off"/"") as False — plain ``bool("false")`` is True,
    a footgun for params arriving as strings over the wire."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "no", "0", "off")
    return bool(value)


@dataclass(frozen=True)
class OpParam:
    """One operation parameter's schema: type + default + bounds/choices.

    ``ptype`` is the Python type to coerce to (float/int/str/bool). A param
    with no default is required."""

    ptype: type
    default: Any = None
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[Any, ...] | None = None
    doc: str = ""

    def coerce(self, name: str, value: Any) -> Any:
        """Validate + coerce a supplied value to this param's type/bounds."""
        try:
            out = _to_bool(value) if self.ptype is bool else self.ptype(value)
        except (TypeError, ValueError):
            raise ParamError(
                f"param '{name}': cannot coerce {value!r} to {self.ptype.__name__}"
            ) from None
        if self.choices is not None and out not in self.choices:
            raise ParamError(
                f"param '{name}': {out!r} not in {self.choices}"
            )
        if isinstance(out, (int, float)) and not isinstance(out, bool):
            if self.minimum is not None and out < self.minimum:
                raise ParamError(f"param '{name}': {out} < min {self.minimum}")
            if self.maximum is not None and out > self.maximum:
                raise ParamError(f"param '{name}': {out} > max {self.maximum}")
        return out


@dataclass(frozen=True)
class OpResult:
    """The outcome of running an op. Exactly one of ``derived`` (a produced
    image) or ``value`` (a scalar/table/dict) is the payload; ``params`` are
    the resolved values (defaults filled) for provenance, ``label`` is a short
    human description."""

    op: str
    params: dict[str, Any]
    label: str
    derived: DataStruct | None = None
    value: Any = None

    @property
    def produces_image(self) -> bool:
        return self.derived is not None


@dataclass(frozen=True)
class OpSpec:
    """A registered operation: its schema + the pure function that runs it.

    ``fn`` receives the input ``DataStruct`` and the already-validated params
    dict and returns an ``OpResult``."""

    name: str
    category: str  # "filter" | "analysis" | "geometry" | ...
    fn: Callable[[DataStruct, dict[str, Any]], OpResult]
    params: dict[str, OpParam] = field(default_factory=dict)
    summary: str = ""

    def resolve_params(self, supplied: dict[str, Any] | None) -> dict[str, Any]:
        """Fill defaults, coerce/validate supplied values, reject unknowns."""
        supplied = dict(supplied or {})
        unknown = set(supplied) - set(self.params)
        if unknown:
            raise ParamError(
                f"op '{self.name}': unknown param(s) {sorted(unknown)} "
                f"(have: {sorted(self.params)})"
            )
        out: dict[str, Any] = {}
        for pname, spec in self.params.items():
            if pname in supplied:
                out[pname] = spec.coerce(pname, supplied[pname])
            elif spec.required:
                raise ParamError(f"op '{self.name}': missing required '{pname}'")
            else:
                out[pname] = spec.default
        return out
