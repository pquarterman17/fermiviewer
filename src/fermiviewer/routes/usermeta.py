"""User-configurable metadata: the schema (fields + filename patterns) and
per-image values (filename auto-fill + sidecar persistence). Thin adapter
over fermiviewer.usermeta."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
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
    values = usermeta.resolve_values(
        schema, store.name(img_id), path, ds.metadata
    )
    return {
        **_schema_dict(schema),
        "values": values,
        "source_path": path,
        "can_write_sidecar": path is not None,
        "has_sidecar": path is not None and usermeta.sidecar_path(path).exists(),
    }


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
    """Apply the filename pattern to many images at once: fill the
    pattern-derived fields and write each sidecar, preserving any other
    fields already saved there. Unknown ids and non-matching names are
    skipped (reported as matched: false)."""
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
        parsed = {
            k: v
            for k, v in usermeta.parse_filename(name, schema.patterns).items()
            if k in field_names
        }
        if not parsed:
            results.append(
                {"id": img_id, "name": name, "matched": False,
                 "filled": 0, "wrote_sidecar": False}
            )
            continue
        merged = usermeta.read_sidecar(path) if path else {}
        merged.update(parsed)
        for k, v in merged.items():
            ds.metadata[k] = v
        wrote = False
        if path:
            try:
                usermeta.write_sidecar(path, merged)
                wrote = True
            except OSError:
                wrote = False
        results.append(
            {"id": img_id, "name": name, "matched": True,
             "filled": len(parsed), "wrote_sidecar": wrote}
        )
    return {
        "results": results,
        "n_matched": sum(1 for r in results if r["matched"]),
        "n_total": len(results),
    }
