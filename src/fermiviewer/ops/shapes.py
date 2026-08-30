"""Param and error vocabulary for the op contract — the pieces
``OpParam`` is built from, split out of ``base.py`` so the contract's home
file keeps headroom under the repo's module ceiling.

``RowSpec`` and ``RecordSpec`` are the list shapes ADR 0005 §9 opened: the
coordinate lists, mask triples and nested stroke/tile records that waves
A-D had to bounce because an op param could only be a scalar.

Pure-library (stdlib only) — imported by ``base``, never the other way.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # the field schema is an OpParam, which is built on
    from fermiviewer.ops.base import OpParam  # these shapes — annotation only

__all__ = [
    "ANY_SCALAR",
    "InputError",
    "ParamError",
    "RecordSpec",
    "RingsSpec",
    "RowSpec",
]


class ParamError(ValueError):
    """Raised when supplied params don't satisfy an op's schema."""


class InputError(ValueError):
    """Raised when supplied auxiliary inputs don't satisfy an op's schema.

    Separate from ``ParamError`` because the two carry different operator
    fixes: a param error is a bad number in a recipe, an input error is the
    wrong dataset (or the wrong count of them) handed to a multi-input op.
    """


def _to_bool(value: Any) -> bool:
    """Coerce a value to bool, treating the common JSON/string falsy spellings
    ("false"/"no"/"0"/"off"/"") as False — plain ``bool("false")`` is True,
    a footgun for params arriving as strings over the wire."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "no", "0", "off")
    return bool(value)


@dataclass(frozen=True)
class RowSpec:
    """A list-shaped param's row schema: numeric rows of a declared width.

    The shape behind every coordinate list the waves bounced — ``points`` and
    ``positions`` and ``spots`` (width 2), ``fft-mask``'s ``masks`` (width 3),
    ``eds_recalibrate``'s non-coordinate ``pairs`` (width 2).

    ``width=None`` accepts ragged rows (``layers/grains``'s
    ``interface_traces``), and ``allow_none_rows`` additionally accepts a
    null row, for the routes whose list elements are nullable. Both are
    deliberately narrow: a fixed width is the default because a width
    mismatch is the coordinate-list typo worth catching.
    """

    width: int | None
    item_type: type = float  # float | int
    columns: tuple[str, ...] = ()  # per-column names, for docs and errors
    min_rows: int = 0
    max_rows: int | None = None
    allow_none_rows: bool = False

    def describe(self) -> str:
        """Human-readable shape, e.g. ``list[3 x float]`` — the API reference
        and the batch palette both render params by this."""
        cols = "/".join(self.columns) if self.columns else self.item_type.__name__
        width = "..." if self.width is None else self.width
        return f"list[{width} x {cols}]"


@dataclass(frozen=True)
class RecordSpec:
    """A list-shaped param's record schema: rows of named fields.

    The shape behind ``train-segment``'s ``strokes`` (a class id, a radius,
    and a polyline), ``layers/grains``'s layer bands, and
    ``montage-compare``'s tiles. Each field is itself an ``OpParam``, so a
    record field may be a scalar OR a row list (``strokes.points``) — but
    NOT another record list. One level of nesting is all the evidence set
    needs, and a bounded depth is what keeps the generated schema, the
    palette, and the error messages renderable.
    """

    fields: dict[str, OpParam]
    min_rows: int = 0
    max_rows: int | None = None

    def __post_init__(self) -> None:
        for fname, fparam in self.fields.items():
            if fparam.record is not None:
                raise ValueError(
                    f"record field '{fname}': records do not nest "
                    f"(a record field may be a scalar or a row list)"
                )

    def describe(self) -> str:
        return f"list[record({', '.join(self.fields)})]"


@dataclass(frozen=True)
class RingsSpec:
    """A list-shaped param's ring schema: a list of RINGS, each a row list.

    One level deeper than `RowSpec`, and the only shape that can carry
    `calc.regions.Shape.holes` — a SEQUENCE of inner rings, not one ring.
    A `RowSpec(width=2)` field accepts `[[r, c], ...]`, which is exactly
    one ring, so a perfectly valid two-hole region could not be written
    down at all; that is what this exists to fix.

    Deliberately not spelled as a nested `RecordSpec`: records do not nest
    (see above), and this is not a record — it is a homogeneous list of
    coordinate lists, which `describe` can render and errors can index
    without the unbounded depth that rule is protecting against.
    """

    width: int | None
    item_type: type = float
    columns: tuple[str, ...] = ()
    min_rings: int = 0
    max_rings: int | None = None

    def as_row_spec(self) -> RowSpec:
        """One ring's schema — so ring coercion reuses `RowSpec`'s rules
        rather than restating them."""
        return RowSpec(
            width=self.width, item_type=self.item_type, columns=self.columns
        )

    def describe(self) -> str:
        cols = "/".join(self.columns) if self.columns else self.item_type.__name__
        width = "..." if self.width is None else self.width
        return f"list[ring[{width} x {cols}]]"


#: ``ptype`` for a param that accepts any JSON scalar — a number, a string,
#: a bool, or null. The one union the route models need that no single
#: constructor covers (``montage-compare``'s ``param_value``, whose values
#: are whatever the compared parameter was). Containers are still rejected:
#: this is "any scalar", not "anything".
ANY_SCALAR = object


def _coerce_scalar(name: str, value: Any, ptype: type) -> Any:
    if ptype is ANY_SCALAR:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        raise ParamError(
            f"param '{name}': expected a number, string, bool or null, "
            f"got {type(value).__name__}"
        )
    try:
        return _to_bool(value) if ptype is bool else ptype(value)
    except (TypeError, ValueError):
        raise ParamError(
            f"param '{name}': cannot coerce {value!r} to {ptype.__name__}"
        ) from None


def _as_rows(name: str, value: Any) -> Sequence[Any]:
    """A list-shaped param's outer sequence — strings and mappings are NOT
    sequences here: ``"1,2"`` reaching a row list means a caller used the
    older CSV spelling, and silently splitting it would resurrect exactly
    the per-op encoding §4 forbids."""
    if isinstance(value, (str, bytes)) or isinstance(value, Mapping):
        raise ParamError(
            f"param '{name}': expected a list, got {type(value).__name__}"
        )
    if not isinstance(value, Sequence):
        raise ParamError(
            f"param '{name}': expected a list, got {type(value).__name__}"
        )
    return value


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _reject_fractional(where: str, value: Any) -> None:
    """An int-typed item must be whole: ``int()`` truncation would silently
    address a DIFFERENT pixel/reflection than asked for, where the routes'
    pydantic int fields reject the same input (the wave-C ``int_group``
    rationale, now enforced by the contract itself)."""
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return  # the coercion above already raised for un-numeric input
    if as_float != int(as_float):
        raise ParamError(f"param '{where}': {value!r} must be a whole number")
