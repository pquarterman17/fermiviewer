"""Tests for calc/table_export.py + POST /api/export/table (Scripting #4):
structured CSV/JSON export of quant/result tables."""

from __future__ import annotations

import csv
import io
import json
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

import fermiviewer.ops as ops
from fermiviewer.calc.table_export import (
    TableShapeError,
    flatten_value_dict,
    table_to_csv_bytes,
    table_to_json_bytes,
)
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.server import create_app

pytestmark = pytest.mark.api

COLS = ["element", "at%"]
ROWS = [["Fe", 62.5], ["O", 37.5]]


# ── pure calc/table_export.py ─────────────────────────────────────────


def test_csv_stable_column_order() -> None:
    """Rows given as dicts are re-keyed by `columns`, never dict order —
    even when a dict's own key order or key set differs."""
    columns = ["a", "b", "c"]
    rows = [
        {"c": 3, "a": 1, "b": 2},   # scrambled key order
        {"a": 4, "c": 6},           # missing "b" entirely
    ]
    csv_bytes = table_to_csv_bytes(columns, rows)
    lines = csv_bytes.decode("utf-8").splitlines()
    assert lines[0] == "a,b,c"
    assert lines[1] == "1,2,3"
    assert lines[2] == "4,,6"       # missing "b" -> blank cell


def test_csv_units_row_is_second_line() -> None:
    csv_bytes = table_to_csv_bytes(COLS, ROWS, units=["", "%"])
    lines = csv_bytes.decode("utf-8").splitlines()
    assert lines[0] == "element,at%"
    assert lines[1] == ",%"        # units row, uncommented, line 2
    assert lines[2] == "Fe,62.5"
    assert lines[3] == "O,37.5"


def test_csv_no_units_omits_second_line() -> None:
    csv_bytes = table_to_csv_bytes(COLS, ROWS)
    lines = csv_bytes.decode("utf-8").splitlines()
    assert lines[1] == "Fe,62.5"   # data starts right after the header


def test_csv_numeric_rounding_matches_frontend_convention() -> None:
    """Mirrors resultsExport.test.ts: numbers to 7 sig figs, trailing
    zeros/`.0` stripped (e.g. 62.5 not 62.5000000, 100 not 100.0)."""
    csv_bytes = table_to_csv_bytes(["x", "y", "z"], [[1 / 3, 100.0, 2]])
    text = csv_bytes.decode("utf-8")
    assert "0.3333333," in text
    assert ",100," in text
    assert text.strip().endswith(",2")


def test_csv_nan_none_inf_are_blank_and_round_trip() -> None:
    csv_bytes = table_to_csv_bytes(["x", "y", "z"], [[float("nan"), None, float("inf")]])
    reader = csv.reader(io.StringIO(csv_bytes.decode("utf-8")))
    header = next(reader)
    data_row = next(reader)
    assert header == ["x", "y", "z"]
    assert data_row == ["", "", ""]  # all three blank


def test_csv_quoting_via_stdlib_csv() -> None:
    csv_bytes = table_to_csv_bytes(["label"], [["a,b"], ['he said "hi"']])
    text = csv_bytes.decode("utf-8")
    assert '"a,b"' in text
    assert '"he said ""hi"""' in text
    # round-trip through csv.reader recovers the original strings
    reader = csv.reader(io.StringIO(text))
    next(reader)  # header
    assert next(reader) == ["a,b"]
    assert next(reader) == ['he said "hi"']


def test_json_columns_and_rows_stable_order() -> None:
    payload = json.loads(table_to_json_bytes(COLS, ROWS).decode("utf-8"))
    assert payload["columns"] == COLS
    assert payload["rows"] == [
        {"element": "Fe", "at%": 62.5},
        {"element": "O", "at%": 37.5},
    ]


def test_json_units_map() -> None:
    payload = json.loads(
        table_to_json_bytes(COLS, ROWS, units=["", "%"]).decode("utf-8")
    )
    assert payload["units"] == {"element": "", "at%": "%"}


def test_json_no_units_key_when_omitted() -> None:
    payload = json.loads(table_to_json_bytes(COLS, ROWS).decode("utf-8"))
    assert "units" not in payload


def test_json_nan_none_inf_become_null_no_precision_rounding() -> None:
    """JSON keeps the raw value (unlike CSV, no 7-sig-fig rounding) but
    still nulls out non-finite values, mirroring JSON.stringify(NaN)."""
    raw_bytes = table_to_json_bytes(["x", "y", "z", "w"],
                                    [[1 / 3, None, float("nan"), float("inf")]])
    # valid JSON (no bare NaN/Infinity tokens) — would raise if not
    payload = json.loads(raw_bytes.decode("utf-8"))
    row = payload["rows"][0]
    assert row["x"] == 1 / 3           # full precision, not rounded to 7sf
    assert row["y"] is None
    assert row["z"] is None
    assert row["w"] is None


def test_ragged_row_rejected() -> None:
    with pytest.raises(TableShapeError):
        table_to_csv_bytes(["a", "b"], [[1, 2], [3]])  # short row


def test_units_length_mismatch_rejected() -> None:
    with pytest.raises(TableShapeError):
        table_to_csv_bytes(["a", "b"], [[1, 2]], units=["only-one"])


def test_units_longer_than_columns_also_rejected() -> None:
    """The mismatch check must catch BOTH directions, not just too-few."""
    with pytest.raises(TableShapeError):
        table_to_csv_bytes(["a"], [[1]], units=["u1", "u2", "u3"])


def test_duplicate_column_names_rejected() -> None:
    """CSV can hold two same-named columns positionally, but to_json_bytes
    keys each row by name — a repeated column would silently drop all but
    the last cell under that name. Rejected in both formats so the same
    table always means the same thing regardless of export format."""
    with pytest.raises(TableShapeError, match="duplicate column"):
        table_to_csv_bytes(["a", "b", "a"], [[1, 2, 3]])
    with pytest.raises(TableShapeError, match="duplicate column"):
        table_to_json_bytes(["a", "b", "a"], [[1, 2, 3]])


def test_zero_rows() -> None:
    csv_bytes = table_to_csv_bytes(["a", "b"], [])
    assert csv_bytes.decode("utf-8").splitlines() == ["a,b"]
    payload = json.loads(table_to_json_bytes(["a", "b"], []).decode("utf-8"))
    assert payload == {"columns": ["a", "b"], "rows": []}


def test_zero_columns() -> None:
    csv_bytes = table_to_csv_bytes([], [])
    assert csv_bytes.decode("utf-8") == "\n"
    payload = json.loads(table_to_json_bytes([], []).decode("utf-8"))
    assert payload == {"columns": [], "rows": []}


def test_single_column() -> None:
    csv_bytes = table_to_csv_bytes(["x"], [[1], [2]])
    assert csv_bytes.decode("utf-8").splitlines() == ["x", "1", "2"]


def test_mixed_cell_types_bool_str_none_in_one_row() -> None:
    """bool must not be formatted as a number (Python's bool IS an int
    subclass) — it should render as True/False text, not 1/0."""
    csv_bytes = table_to_csv_bytes(
        ["flag", "label", "missing", "count"], [[True, "note", None, 5]]
    )
    lines = csv_bytes.decode("utf-8").splitlines()
    assert lines[1] == "True,note,,5"
    payload = json.loads(
        table_to_json_bytes(
            ["flag", "label", "missing", "count"], [[True, "note", None, 5]]
        ).decode("utf-8")
    )
    row = payload["rows"][0]
    assert row["flag"] is True
    assert row["missing"] is None


def test_extreme_float_values_do_not_crash() -> None:
    values = [-0.0, 1e308, 5e-320]  # negative zero, near-overflow, subnormal
    csv_bytes = table_to_csv_bytes(["a", "b", "c"], [values])
    assert len(csv_bytes.decode("utf-8").splitlines()) == 2  # header + 1 row
    payload = json.loads(table_to_json_bytes(["a", "b", "c"], [values]).decode("utf-8"))
    row = payload["rows"][0]
    assert math.isclose(row["b"], 1e308)
    assert row["c"] > 0  # subnormal preserved, not flushed to 0 or null


def test_large_table_no_quadratic_blowup() -> None:
    """100k-row timing sanity, not a benchmark: catches an accidental
    O(n^2) regression (e.g. string-concatenating rows) without pinning a
    tight time budget that would make the suite flaky on a slow runner."""
    import time

    rows = [[i, i * 0.5, f"row{i}"] for i in range(100_000)]
    start = time.perf_counter()
    csv_bytes = table_to_csv_bytes(["idx", "val", "label"], rows)
    table_to_json_bytes(["idx", "val", "label"], rows)
    elapsed = time.perf_counter() - start
    assert csv_bytes.count(b"\n") == 100_001  # header + 100k rows
    assert elapsed < 10.0


def test_flatten_value_dict_scalar_and_list_fields() -> None:
    value = {"mean": 1.5, "std": 0.25, "shape": [12, 16]}
    columns, rows = flatten_value_dict(value)
    assert columns == ["mean", "std", "shape"]
    assert len(rows) == 1
    assert rows[0][0] == 1.5
    assert rows[0][1] == 0.25
    assert rows[0][2] == "[12, 16]"    # list atomically JSON-encoded

    csv_bytes = table_to_csv_bytes(columns, rows)
    text = csv_bytes.decode("utf-8")
    assert "mean,std,shape" in text
    assert "[12, 16]" in text          # survives CSV as one quoted cell


def _synthetic_image(h: int = 12, w: int = 16) -> DataStruct:
    rng = np.random.default_rng(0)
    data = rng.normal(loc=10.0, scale=1.0, size=(h, w))
    return DataStruct(
        data=data,
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
        metadata={"source": "synthetic"},
    )


def test_real_roughness_op_flattens_and_exports() -> None:
    """A real OpResult.value (surface roughness op from ops/catalogue.py)
    flattened and exported through the same helpers the route uses."""
    ds = _synthetic_image()
    result = ops.run("roughness", ds, {"level": "plane"})
    assert isinstance(result.value, dict)
    columns, rows = flatten_value_dict(result.value)
    assert {"Ra", "Rq", "Rz", "unit"} <= set(columns)

    csv_bytes = table_to_csv_bytes(columns, rows)
    csv_text = csv_bytes.decode("utf-8")
    reader = csv.DictReader(io.StringIO(csv_text))
    csv_row = next(reader)
    assert csv_row["unit"] == result.value["unit"]
    assert math.isclose(float(csv_row["Ra"]), result.value["Ra"], rel_tol=1e-6)

    payload = json.loads(table_to_json_bytes(columns, rows).decode("utf-8"))
    json_row = payload["rows"][0]
    assert json_row["Ra"] == result.value["Ra"]   # full precision preserved
    assert json_row["unit"] == result.value["unit"]


# ── POST /api/export/table ────────────────────────────────────────────


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_route_csv_export(client: TestClient) -> None:
    r = client.post("/api/export/table", json={
        "columns": COLS, "rows": ROWS, "format": "csv",
    })
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="results.csv"' in r.headers["content-disposition"]
    lines = r.content.decode("utf-8").splitlines()
    assert lines[0] == "element,at%"
    assert lines[1] == "Fe,62.5"


def test_route_json_export(client: TestClient) -> None:
    r = client.post("/api/export/table", json={
        "columns": COLS, "rows": ROWS, "format": "json",
    })
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert 'filename="results.json"' in r.headers["content-disposition"]
    payload = r.json()
    assert payload["columns"] == COLS
    assert payload["rows"][0] == {"element": "Fe", "at%": 62.5}


def test_route_units_row(client: TestClient) -> None:
    r = client.post("/api/export/table", json={
        "columns": COLS, "rows": ROWS, "units": ["", "%"], "format": "csv",
    })
    lines = r.content.decode("utf-8").splitlines()
    assert lines[1] == ",%"


def test_route_custom_filename_sanitized(client: TestClient) -> None:
    r = client.post("/api/export/table", json={
        "columns": COLS, "rows": ROWS, "format": "csv",
        "filename": "../../etc/evil\r\nname\".txt",
    })
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert "\r" not in cd and "\n" not in cd
    assert "/" not in cd.split("filename=")[1]
    assert cd.endswith('.csv"')


def test_route_default_filename_when_omitted(client: TestClient) -> None:
    r = client.post("/api/export/table", json={
        "columns": COLS, "rows": ROWS, "format": "json",
    })
    assert 'filename="results.json"' in r.headers["content-disposition"]


def test_route_ragged_rows_is_422(client: TestClient) -> None:
    r = client.post("/api/export/table", json={
        "columns": ["a", "b"], "rows": [[1, 2], [3]], "format": "csv",
    })
    assert r.status_code == 422


def test_route_bad_format_is_422(client: TestClient) -> None:
    r = client.post("/api/export/table", json={
        "columns": COLS, "rows": ROWS, "format": "xml",
    })
    assert r.status_code == 422


def test_route_duplicate_columns_is_422(client: TestClient) -> None:
    r = client.post("/api/export/table", json={
        "columns": ["a", "a"], "rows": [[1, 2]], "format": "csv",
    })
    assert r.status_code == 422


def test_route_units_longer_than_columns_is_422(client: TestClient) -> None:
    r = client.post("/api/export/table", json={
        "columns": ["a"], "rows": [[1]], "units": ["u1", "u2"], "format": "csv",
    })
    assert r.status_code == 422


def test_route_filename_with_only_non_latin1_unicode_falls_back_gracefully(
    client: TestClient,
) -> None:
    """A filename with no ASCII characters at all (e.g. CJK) must not crash
    building the response — Starlette encodes header values as latin-1, so
    an unfiltered CJK filename raises UnicodeEncodeError constructing the
    Response rather than degrading gracefully."""
    r = client.post("/api/export/table", json={
        "columns": COLS, "rows": ROWS, "format": "csv",
        "filename": "文件名",
    })
    assert r.status_code == 200
    assert r.headers["content-disposition"].endswith('.csv"')


def test_route_filename_with_mixed_ascii_and_unicode_keeps_the_ascii_part(
    client: TestClient,
) -> None:
    r = client.post("/api/export/table", json={
        "columns": COLS, "rows": ROWS, "format": "csv",
        "filename": "sample Å⁻¹ data.csv",
    })
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert "sample" in cd
    assert cd.endswith('.csv"')


def test_route_filename_semicolon_does_not_inject_a_second_header_param(
    client: TestClient,
) -> None:
    """A semicolon in the filename stays INSIDE the quoted value — it must
    not be interpreted as starting a new Content-Disposition parameter."""
    r = client.post("/api/export/table", json={
        "columns": COLS, "rows": ROWS, "format": "csv",
        "filename": 'evil"; injected=yes; foo="bar.csv',
    })
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert cd.count('"') == 2  # exactly one opening + one closing quote
    assert "injected=yes" not in cd or cd.index('"') < cd.index("injected=yes")


def test_route_filename_reserved_windows_device_name_does_not_crash(
    client: TestClient,
) -> None:
    """CON/NUL/etc are only unsafe if THIS server writes the file to a
    Windows path directly — this route only ever suggests a download name
    to the client, so the reasonable bar is "does not crash", not
    renaming it. Pins current behavior rather than mandating a rename."""
    r = client.post("/api/export/table", json={
        "columns": COLS, "rows": ROWS, "format": "csv", "filename": "CON",
    })
    assert r.status_code == 200
    assert r.headers["content-disposition"].endswith('.csv"')


def test_route_very_long_filename_does_not_crash(client: TestClient) -> None:
    r = client.post("/api/export/table", json={
        "columns": COLS, "rows": ROWS, "format": "csv",
        "filename": "a" * 400,
    })
    assert r.status_code == 200
    assert r.headers["content-disposition"].endswith('.csv"')


def test_route_dict_rows_accepted(client: TestClient) -> None:
    r = client.post("/api/export/table", json={
        "columns": COLS, "format": "csv",
        "rows": [{"at%": 62.5, "element": "Fe"}, {"element": "O", "at%": 37.5}],
    })
    assert r.status_code == 200
    lines = r.content.decode("utf-8").splitlines()
    assert lines[1] == "Fe,62.5"
    assert lines[2] == "O,37.5"
