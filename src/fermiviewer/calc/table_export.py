"""Structured table export — pure CSV/JSON serialization for quant/result
tables (at%, d-spacings, roughness, image_stats, ...) — Scripting #4.

Mirrors frontend/src/lib/resultsExport.ts's conventions so a server- and a
client-generated export of the same data are format-compatible:

- stable column order (rows given as dicts are re-keyed by `columns`,
  never by dict iteration order)
- CSV: numeric cells rounded to 7 significant figures (mirrors the
  frontend's ``fmt()``: ``Number(v.toPrecision(7))``); ``None``/NaN/±Inf
  render as an empty cell; quoting follows RFC 4180 via the stdlib ``csv``
  module
- JSON: cells keep their raw value (no precision rounding — the frontend's
  ``tableToJson`` doesn't round either); ``None``/NaN/±Inf all become
  ``null`` (``JSON.stringify`` does this for NaN/Infinity automatically on
  the JS side; Python's ``json`` module does not, so it is done here)

One deliberate addition with no frontend counterpart: an optional per-column
UNITS row. The frontend has no table-level units concept (a "unit" column
value is used instead, e.g. RoughnessWorkshop's ``["metric", "value",
"unit"]`` table) — but server-generated tables often have one physical unit
per *column* (e.g. "at%", "Å", "nm"), so ``units`` is emitted as the second
CSV line (a plain, uncommented row — the common "header, units, data"
scientific-CSV convention) and as a ``column -> unit`` map in the JSON.

Pure numpy/stdlib only — no fastapi/pydantic (calc/ purity is enforced by
tests/test_repo_integrity.py).
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "Cell",
    "ExportTable",
    "Row",
    "TableShapeError",
    "flatten_value_dict",
    "table_to_csv_bytes",
    "table_to_json_bytes",
]

Cell = Any  # str | float | int | bool | None
# a single row, either positional (must match len(columns)) or keyed by
# column name (missing keys -> None; extra keys are ignored) — callers may
# freely mix both shapes within one `rows` list
Row = list[Cell] | dict[str, Cell]


class TableShapeError(ValueError):
    """A row (or the units list) doesn't match the column count."""


def _is_number(value: Cell) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _row_to_list(row: Row, columns: list[str], index: int) -> list[Cell]:
    if isinstance(row, dict):
        # keyed by the caller's column order — dict iteration order (or a
        # differently-ordered/partial key set) never leaks into the table
        return [row.get(c) for c in columns]
    row_list = list(row)
    if len(row_list) != len(columns):
        raise TableShapeError(
            f"row {index} has {len(row_list)} cell(s), expected "
            f"{len(columns)} (columns={columns})"
        )
    return row_list


@dataclass(frozen=True)
class ExportTable:
    """A validated table: stable column order, every row exactly
    ``len(columns)`` cells, ready to serialize."""

    columns: list[str]
    rows: list[list[Cell]]
    units: list[str] | None = None

    @classmethod
    def build(
        cls,
        columns: list[str],
        rows: Sequence[Row],
        units: list[str] | None = None,
    ) -> ExportTable:
        columns = list(columns)
        if units is not None and len(units) != len(columns):
            raise TableShapeError(
                f"units has {len(units)} entries, columns has {len(columns)}"
            )
        if len(set(columns)) != len(columns):
            # CSV can represent duplicate headers positionally (both cells
            # survive), but to_json_bytes keys each row by column name —
            # `dict(zip(columns, row))` silently keeps only the LAST cell
            # under a repeated name and drops the rest. Rejecting here
            # keeps both formats representing the same table rather than
            # one of them quietly losing data.
            dupes = sorted({c for c in columns if columns.count(c) > 1})
            raise TableShapeError(f"duplicate column name(s): {dupes}")
        validated = [_row_to_list(row, columns, i) for i, row in enumerate(rows)]
        return cls(
            columns=columns,
            rows=validated,
            units=list(units) if units is not None else None,
        )

    # ── CSV ───────────────────────────────────────────────────────────

    def to_csv_bytes(self) -> bytes:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(self.columns)
        if self.units is not None:
            writer.writerow(self.units)
        for row in self.rows:
            writer.writerow([_fmt_csv_cell(cell) for cell in row])
        return buf.getvalue().encode("utf-8")

    # ── JSON ──────────────────────────────────────────────────────────

    def to_json_bytes(self) -> bytes:
        payload: dict[str, Any] = {
            "columns": self.columns,
            "rows": [
                {
                    col: _json_safe_cell(cell)
                    for col, cell in zip(self.columns, row, strict=True)
                }
                for row in self.rows
            ],
        }
        if self.units is not None:
            payload["units"] = dict(zip(self.columns, self.units, strict=True))
        return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def _fmt_csv_cell(value: Cell) -> str:
    """Text cell formatting — mirrors resultsExport.ts's ``fmt()``: numbers
    round to 7 significant figures; None/NaN/±Inf render as an empty cell."""
    if value is None:
        return ""
    if _is_number(value):
        f = float(value)
        if not math.isfinite(f):
            return ""
        return _format_number(f)
    return str(value)


def _format_number(f: float) -> str:
    """7-significant-figure text, trailing zeros/`.0` stripped — matches
    ``String(Number(v.toPrecision(7)))`` for the common (non-extreme
    magnitude) case. Very large/small values may format slightly
    differently than the JS side (different exponential-notation
    thresholds); both still round to 7 sig figs."""
    rounded = float(f"{f:.7g}")
    if rounded == int(rounded) and abs(rounded) < 1e15:
        return str(int(rounded))
    return repr(rounded)


def _json_safe_cell(value: Cell) -> Any:
    """Raw value passthrough (JSON does not precision-round); None/NaN/±Inf
    all collapse to ``null``."""
    if value is None:
        return None
    if _is_number(value):
        f = float(value)
        return value if math.isfinite(f) else None
    return value


def table_to_csv_bytes(
    columns: list[str],
    rows: Sequence[Row],
    units: list[str] | None = None,
) -> bytes:
    """Build + serialize a table to CSV bytes in one call."""
    return ExportTable.build(columns, rows, units).to_csv_bytes()


def table_to_json_bytes(
    columns: list[str],
    rows: Sequence[Row],
    units: list[str] | None = None,
) -> bytes:
    """Build + serialize a table to JSON bytes in one call."""
    return ExportTable.build(columns, rows, units).to_json_bytes()


def flatten_value_dict(value: dict[str, Cell]) -> tuple[list[str], list[list[Cell]]]:
    """Flatten a flat ``OpResult.value``-style dict (image_stats/noise/
    roughness/...: scalar fields, occasionally a short list like ``shape``)
    into a single-row table: ``columns`` = the dict's keys in insertion
    order, ``rows`` = one row of its values. A NON-SCALAR value — a
    list/tuple like ``shape: [12, 16]``, or a dict like the ``region``
    provenance ``image_stats`` now carries when scoped — is JSON-encoded
    into a single atomic cell rather than expanded into extra columns,
    since it isn't itself tabular.

    Dicts encode for the same reason lists do, and the failure was
    concrete rather than theoretical: falling through left `str(dict)`,
    so the CSV held a Python repr — single-quoted keys, ``False`` — that
    a consumer could not parse beside a ``shape`` cell it could. It also
    broke this module's promise to mirror
    ``frontend/src/lib/resultsExport.ts``, which JSON-stringifies any
    non-scalar, so one result exported two ways disagreed on encoding.
    """
    columns = list(value.keys())
    row: list[Cell] = [
        json.dumps(list(v))
        if isinstance(v, (list, tuple))
        else json.dumps(v, sort_keys=False)
        if isinstance(v, dict)
        else v
        for v in value.values()
    ]
    return columns, [row]
