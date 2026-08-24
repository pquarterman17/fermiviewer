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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.ops.shapes import (
    ANY_SCALAR,
    InputError,
    ParamError,
    RecordSpec,
    RowSpec,
    _as_rows,
    _coerce_scalar,
    _plural,
    _reject_fractional,
)

# re-exported so `from fermiviewer.ops.base import ParamError` (and the
# shape types) keeps working from every catalogue and consumer.
__all__ = [
    "ANY_SCALAR",
    "InputError",
    "OpInput",
    "OpParam",
    "OpResult",
    "OpSpec",
    "ParamError",
    "RecordSpec",
    "RowSpec",
    "produces_value_result",
]


@dataclass(frozen=True)
class OpParam:
    """One operation parameter's schema: type + default + bounds/choices.

    ``ptype`` is the Python type to coerce to (float/int/str/bool, or
    ``ANY_SCALAR``). A param with no default is required.

    A LIST-shaped param sets ``ptype=list`` and exactly one of ``row``
    (numeric rows) or ``record`` (rows of named fields); its value is a real
    JSON list, not a delimited string. Bounds and ``choices`` then apply to
    each scalar item rather than to the list.
    """

    ptype: type
    default: Any = None
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[Any, ...] | None = None
    doc: str = ""
    # exclusive bounds — the routes' Field(gt=)/Field(lt=) twins. Recorded as
    # a §4 fidelity gap in the wave-B and wave-C addenda (ctf.pixel_size_a's
    # gt=0, montage.overlap's lt=1.0), each worked around by a hand-written
    # ValueError in the op fn; the contract spells them now.
    exclusive_minimum: float | None = None
    exclusive_maximum: float | None = None
    # list shapes (ptype is list) — mutually exclusive
    row: RowSpec | None = None
    record: RecordSpec | None = None

    def __post_init__(self) -> None:
        structured = self.row is not None or self.record is not None
        if self.row is not None and self.record is not None:
            raise ValueError("a list param is either 'row'- or 'record'-shaped")
        if structured and self.ptype is not list:
            raise ValueError("a 'row'/'record' param must have ptype=list")
        if self.ptype is list and not structured:
            raise ValueError("a list param must declare 'row' or 'record'")

    @property
    def is_list(self) -> bool:
        return self.ptype is list

    def describe_type(self) -> str:
        """The rendered type name for docs/palette consumers."""
        if self.row is not None:
            return self.row.describe()
        if self.record is not None:
            return self.record.describe()
        return "scalar" if self.ptype is ANY_SCALAR else self.ptype.__name__

    def coerce(self, name: str, value: Any) -> Any:
        """Validate + coerce a supplied value to this param's type/bounds."""
        if self.row is not None:
            return self._coerce_rows(name, value)
        if self.record is not None:
            return self._coerce_records(name, value)
        return self._coerce_item(name, value)

    # ── scalar item (also every item inside a list) ───────────────────
    def _coerce_item(self, name: str, value: Any, ptype: type | None = None) -> Any:
        ptype = ptype or self.ptype
        if ptype is int:
            # int(1.5) == 1 would silently run a DIFFERENT window/reflection
            # than asked for, where the routes' pydantic int fields reject
            # the same input. Wave C hand-rolled this per op group
            # (`int_group`); the contract enforces it for every int now.
            _reject_fractional(name, value)
        out = _coerce_scalar(name, value, ptype)
        if self.choices is not None and out not in self.choices:
            raise ParamError(f"param '{name}': {out!r} not in {self.choices}")
        if isinstance(out, (int, float)) and not isinstance(out, bool):
            if self.minimum is not None and out < self.minimum:
                raise ParamError(f"param '{name}': {out} < min {self.minimum}")
            if self.maximum is not None and out > self.maximum:
                raise ParamError(f"param '{name}': {out} > max {self.maximum}")
            if self.exclusive_minimum is not None and not out > self.exclusive_minimum:
                raise ParamError(
                    f"param '{name}': {out} must be > {self.exclusive_minimum}"
                )
            if self.exclusive_maximum is not None and not out < self.exclusive_maximum:
                raise ParamError(
                    f"param '{name}': {out} must be < {self.exclusive_maximum}"
                )
        return out

    # ── list shapes ──────────────────────────────────────────────────
    def _coerce_rows(self, name: str, value: Any) -> list[Any]:
        spec = self.row
        assert spec is not None
        out: list[Any] = []
        for i, raw in enumerate(_as_rows(name, value)):
            where = f"{name}[{i}]"
            if raw is None:
                if not spec.allow_none_rows:
                    raise ParamError(f"param '{where}': row must not be null")
                out.append(None)
                continue
            items = _as_rows(where, raw)
            if spec.width is not None and len(items) != spec.width:
                raise ParamError(
                    f"param '{where}': expected {spec.width} values "
                    f"({'/'.join(spec.columns) or spec.item_type.__name__}), "
                    f"got {len(items)}"
                )
            row: list[Any] = []
            for j, item in enumerate(items):
                col = spec.columns[j] if j < len(spec.columns) else str(j)
                row.append(self._coerce_item(f"{where}.{col}", item, spec.item_type))
            out.append(row)
        self._check_rows(name, len(out), spec.min_rows, spec.max_rows)
        return out

    def _coerce_records(self, name: str, value: Any) -> list[dict[str, Any]]:
        spec = self.record
        assert spec is not None
        out: list[dict[str, Any]] = []
        for i, raw in enumerate(_as_rows(name, value)):
            where = f"{name}[{i}]"
            if not isinstance(raw, Mapping):
                raise ParamError(
                    f"param '{where}': expected an object with fields "
                    f"{sorted(spec.fields)}, got {type(raw).__name__}"
                )
            out.append(_resolve_fields(spec.fields, raw, where, prefix=f"{where}."))
        self._check_rows(name, len(out), spec.min_rows, spec.max_rows)
        return out

    @staticmethod
    def _check_rows(name: str, n: int, lo: int, hi: int | None) -> None:
        if n < lo:
            raise ParamError(
                f"param '{name}': needs at least {_plural(lo, 'entry', 'entries')}, "
                f"got {n}"
            )
        if hi is not None and n > hi:
            raise ParamError(
                f"param '{name}': at most {_plural(hi, 'entry', 'entries')}, got {n}"
            )


def _resolve_fields(
    schema: dict[str, OpParam],
    supplied: Mapping[str, Any],
    where: str,
    prefix: str = "",
) -> dict[str, Any]:
    """Fill defaults, coerce/validate supplied values, reject unknowns —
    shared by ``OpSpec.resolve_params`` (a step's params) and ``RecordSpec``
    (one record inside a list param) so both enforce one rule set."""
    unknown = set(supplied) - set(schema)
    if unknown:
        raise ParamError(
            f"{where}: unknown param(s) {sorted(unknown)} (have: {sorted(schema)})"
        )
    out: dict[str, Any] = {}
    for pname, spec in schema.items():
        if pname in supplied:
            out[pname] = spec.coerce(f"{prefix}{pname}", supplied[pname])
        elif spec.required:
            raise ParamError(f"{where}: missing required '{pname}'")
        else:
            out[pname] = spec.default
    return out


@dataclass(frozen=True)
class OpInput:
    """One named auxiliary ``DataStruct`` input, beyond the primary subject.

    Every op keeps exactly one primary subject (the ``ds`` positional, which
    stays the recipe chain's and the provenance root's spine); an op that
    needs MORE datasets declares them here by name. The caller resolves
    session ids to ``DataStruct``s and passes them in — ``ops/`` never reads
    the session store, which is what kept these endpoints unregisterable
    rather than merely awkward.

    ``variadic`` takes a list (a stack, a montage's tiles) instead of one.
    """

    doc: str = ""
    required: bool = True
    variadic: bool = False
    kinds: tuple[DataKind, ...] | None = None  # None: any kind
    min_count: int = 1  # variadic only
    max_count: int | None = None  # variadic only

    def resolve(self, name: str, value: Any) -> Any:
        """Validate one supplied input against this schema."""
        if not self.variadic:
            return self._one(name, value)
        if isinstance(value, DataStruct) or not isinstance(value, Sequence):
            raise InputError(
                f"input '{name}': expected a list of datasets, "
                f"got {type(value).__name__}"
            )
        items = [self._one(f"{name}[{i}]", v) for i, v in enumerate(value)]
        if len(items) < self.min_count:
            raise InputError(
                f"input '{name}': needs at least "
                f"{_plural(self.min_count, 'dataset', 'datasets')}, got {len(items)}"
            )
        if self.max_count is not None and len(items) > self.max_count:
            raise InputError(
                f"input '{name}': at most "
                f"{_plural(self.max_count, 'dataset', 'datasets')}, got {len(items)}"
            )
        return items

    def _one(self, name: str, value: Any) -> DataStruct:
        if not isinstance(value, DataStruct):
            raise InputError(
                f"input '{name}': expected a DataStruct, got {type(value).__name__}"
            )
        if self.kinds is not None and value.kind not in self.kinds:
            raise InputError(
                f"input '{name}': kind {value.kind.value} not in "
                f"{[k.value for k in self.kinds]}"
            )
        return value


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


def produces_value_result(spec: OpSpec) -> bool:
    """True for an op whose result is a value, False for an image producer.

    THE single home of the rule (ADR 0005): ``category == "analysis"``
    implies a value result without the flag; domain categories (eels, eds,
    diffraction, ...) opt in via ``produces_value``. Previously copied in
    ``routes/batch_ops.py`` and ``tools/gen_api_reference.py`` — three
    predicates that could drift apart is how a palette starts disagreeing
    with the docs about what an op returns.
    """
    return spec.category == "analysis" or spec.produces_value


@dataclass(frozen=True)
class OpSpec:
    """A registered operation: its schema + the pure function that runs it.

    ``fn`` receives the primary input ``DataStruct`` and the already-validated
    params dict and returns an ``OpResult``.

    An op that declares ``inputs`` (auxiliary datasets beyond the subject)
    takes a THIRD argument instead — ``fn(ds, params, inputs)``, where
    ``inputs`` maps each declared name to its resolved ``DataStruct`` (or
    list of them). The call convention follows the schema, so the 70-odd
    single-subject ops keep their two-argument signature unchanged;
    ``tests/test_ops_registry.py`` asserts every registered fn's arity
    against its spec so the two conventions cannot drift apart.
    """

    name: str
    category: str  # "filter" | "analysis" | "geometry" | "eels" | "eds" | ...
    fn: Callable[..., OpResult]
    params: dict[str, OpParam] = field(default_factory=dict)
    inputs: dict[str, OpInput] = field(default_factory=dict)
    summary: str = ""
    # Schema-time hint for /api/batch/operations: True for an op whose
    # OpResult always carries `.value` (not a derived image), even when its
    # `category` is a domain name (eels/eds/diffraction) rather than
    # "analysis". category == "analysis" implies this without needing to set
    # it explicitly (kept for the original filter/geometry/analysis set).
    produces_value: bool = False

    @property
    def multi_input(self) -> bool:
        """True for an op whose ``fn`` takes the third ``inputs`` argument."""
        return bool(self.inputs)

    def resolve_params(self, supplied: dict[str, Any] | None) -> dict[str, Any]:
        """Fill defaults, coerce/validate supplied values, reject unknowns."""
        return _resolve_fields(self.params, dict(supplied or {}), f"op '{self.name}'")

    def resolve_inputs(
        self, supplied: Mapping[str, Any] | None
    ) -> dict[str, DataStruct | list[DataStruct]]:
        """Validate auxiliary datasets against ``inputs``: reject unknown
        names, require the required ones, and check kind/count."""
        supplied = dict(supplied or {})
        unknown = set(supplied) - set(self.inputs)
        if unknown:
            raise InputError(
                f"op '{self.name}': unknown input(s) {sorted(unknown)} "
                f"(have: {sorted(self.inputs)})"
            )
        out: dict[str, DataStruct | list[DataStruct]] = {}
        for iname, ispec in self.inputs.items():
            if iname in supplied and supplied[iname] is not None:
                out[iname] = ispec.resolve(iname, supplied[iname])
            elif ispec.required:
                raise InputError(f"op '{self.name}': missing required input '{iname}'")
            else:
                out[iname] = [] if ispec.variadic else None  # type: ignore[assignment]
        return out
