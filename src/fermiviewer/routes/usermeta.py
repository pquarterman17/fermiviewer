"""User-configurable metadata: the schema (fields + filename patterns) and
per-image values (filename auto-fill + sidecar persistence). Thin adapter
over fermiviewer.usermeta."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from fermiviewer import usermeta
from fermiviewer.datastruct import DataStruct
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _get(img_id: str) -> DataStruct:
    try:
        return store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None


def _schema_dict(s: usermeta.MetaSchema) -> dict:
    return {
        "fields": [
            {"name": f.name, "type": f.type, "options": list(f.options)}
            for f in s.fields
        ],
        "patterns": list(s.patterns),
        "config_path": s.path,
    }


def _sidecar_basename(name: str, path: str | None) -> str:
    """The sidecar's basename whether or not the image has a disk path, so
    the frontend never has to re-derive the ``<name>.fvmeta.yaml`` naming
    convention itself."""
    return usermeta.sidecar_path(path if path else name).name


def _safe_filename(name: str) -> str:
    """Strip path separators and header-unsafe characters before a
    server-derived filename reaches Content-Disposition (mirrors
    routes/export_table.py's ``_safe_filename``): Starlette encodes header
    values as latin-1, so a name with e.g. CJK characters would raise an
    uncaught UnicodeEncodeError (a 500) rather than just rendering oddly."""
    stripped = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in stripped if 0x20 <= ord(ch) <= 0x7E and ch != '"')
    return cleaned or "metadata.fvmeta.yaml"


@router.get("/metadata-schema")
def metadata_schema() -> dict:
    """The user's configured metadata fields + filename auto-fill patterns."""
    return _schema_dict(usermeta.load_schema())


@router.get("/image/{img_id}/usermeta")
def get_usermeta(img_id: str) -> dict:
    """Resolved field values for one image (filename → sidecar → session)."""
    ds = _get(img_id)
    schema = usermeta.load_schema()
    path = store.source_path(img_id)
    name = store.name(img_id)
    values = usermeta.resolve_values(schema, name, path, ds.metadata)
    return {
        **_schema_dict(schema),
        "values": values,
        "source_path": path,
        "can_write_sidecar": path is not None,
        "has_sidecar": path is not None and usermeta.sidecar_path(path).exists(),
        "sidecar_name": _sidecar_basename(name, path),
    }


@router.get("/image/{img_id}/usermeta/sidecar")
def download_usermeta_sidecar(img_id: str) -> Response:
    """Download the resolved field values as a ``.fvmeta.yaml`` file — for
    images with no path on disk (browser upload, or a derived/computed
    image) so the values can still be carried by hand to sit beside the
    original file. Uses the exact serialization `write_sidecar` uses, so
    a downloaded file and a written sidecar are byte-identical."""
    ds = _get(img_id)
    schema = usermeta.load_schema()
    path = store.source_path(img_id)
    name = store.name(img_id)
    values = usermeta.resolve_values(schema, name, path, ds.metadata)
    data = usermeta.sidecar_bytes(values)
    filename = _safe_filename(_sidecar_basename(name, path))
    return Response(
        content=data,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class UserMetaPatch(BaseModel):
    values: dict[str, str]


@router.post("/image/{img_id}/usermeta")
def save_usermeta(img_id: str, req: UserMetaPatch) -> dict:
    """Persist field values to the image (session) and, when the image was
    opened from disk, to its ``<name>.fvmeta.yaml`` sidecar."""
    ds = _get(img_id)
    schema = usermeta.load_schema()
    field_names = {f.name for f in schema.fields}
    clean = {k: str(v) for k, v in req.values.items() if k in field_names}
    for k, v in clean.items():
        ds.metadata[k] = v
    path = store.source_path(img_id)
    wrote = False
    if path:
        try:
            usermeta.write_sidecar(path, clean)
            wrote = True
        except OSError:
            wrote = False
    return {"values": clean, "wrote_sidecar": wrote}


class BatchAutofillRequest(BaseModel):
    image_ids: list[str]


@router.post("/usermeta/batch-autofill")
def batch_autofill(req: BatchAutofillRequest) -> dict:
    """Apply the filename pattern to many images at once. For each file whose
    name matches, resolve its fields with the canonical precedence
    (filename → sidecar → session, so a manually-corrected sidecar value is
    preserved, not clobbered) and persist the non-empty result to the image
    + its sidecar. Only schema fields are written (no ghost fields). Unknown
    ids are skipped (absent from results)."""
    schema = usermeta.load_schema()
    field_names = {f.name for f in schema.fields}
    results: list[dict[str, object]] = []
    for img_id in req.image_ids:
        try:
            ds = store.get(img_id)
        except UnknownImageError:
            continue
        name = store.name(img_id)
        path = store.source_path(img_id)
        matched = any(
            k in field_names
            for k in usermeta.parse_filename(name, schema.patterns)
        )
        if not matched:
            results.append(
                {"id": img_id, "name": name, "matched": False,
                 "filled": 0, "wrote_sidecar": False}
            )
            continue
        resolved = usermeta.resolve_values(schema, name, path, ds.metadata)
        filled = {k: v for k, v in resolved.items() if v != ""}
        for k, v in filled.items():
            ds.metadata[k] = v
        wrote = False
        if path:
            try:
                usermeta.write_sidecar(path, filled)
                wrote = True
            except OSError:
                wrote = False
        results.append(
            {"id": img_id, "name": name, "matched": True,
             "filled": len(filled), "wrote_sidecar": wrote}
        )
    return {
        "results": results,
        "n_matched": sum(1 for r in results if r["matched"]),
        "n_total": len(results),
    }
