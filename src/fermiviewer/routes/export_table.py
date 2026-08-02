"""POST /export/table — structured export of quant/result tables (at%,
d-spacings, roughness, image_stats, ...) as CSV/JSON (Scripting #4).

A thin adapter over calc/table_export.py: no session/image lookup at all
(the caller already has a table — from a batch-run's ``values``, an
``fermiviewer.api`` ``Result.value``, or hand-built rows). Kept as its own
module rather than folded into export_batch.py, whose job is rendering
image *sets* (ZIP/GIF/figure) — a generic tabular export is a different
job and export_batch.py has no session/store involvement to share with it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from fermiviewer.calc.table_export import (
    Row,
    TableShapeError,
    table_to_csv_bytes,
    table_to_json_bytes,
)

router = APIRouter(prefix="/api")

_MEDIA = {"csv": "text/csv", "json": "application/json"}


class TableExportRequest(BaseModel):
    columns: list[str]
    units: list[str] | None = None
    rows: list[Row]
    format: str = "csv"
    filename: str | None = None


def _safe_filename(filename: str | None, fmt: str) -> str:
    """Server-derived filename (mirrors the `stem` pattern in
    routes/export.py): strip any path components and quote/CRLF characters
    from a caller-supplied name before it reaches the Content-Disposition
    header, then force the extension matching `fmt`."""
    if not filename:
        return f"results.{fmt}"
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch not in '"\r\n')
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return f"{stem or 'results'}.{fmt}"


@router.post("/export/table")
def export_table(req: TableExportRequest) -> Response:
    if req.format not in _MEDIA:
        raise HTTPException(422, f"format must be one of {sorted(_MEDIA)}")
    try:
        if req.format == "csv":
            data = table_to_csv_bytes(req.columns, req.rows, req.units)
        else:
            data = table_to_json_bytes(req.columns, req.rows, req.units)
    except TableShapeError as exc:
        raise HTTPException(422, str(exc)) from None
    filename = _safe_filename(req.filename, req.format)
    return Response(
        content=data,
        media_type=_MEDIA[req.format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
