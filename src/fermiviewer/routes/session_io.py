"""POST /session/save + /session/load — workspace persistence (plan #21).

Thin adapters over io.session_file; the client_state blob (views,
display, measures, overlay — frontend-owned state) round-trips opaquely.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.io.session_file import load_session, save_session
from fermiviewer.models import ImageMeta
from fermiviewer.session import store

router = APIRouter(prefix="/api")


class SaveRequest(BaseModel):
    path: str
    client_state: dict[str, Any] | None = None


@router.post("/session/save")
def session_save(req: SaveRequest) -> dict[str, Any]:
    entries = [(i, store.name(i), store.get(i)) for i in store.ids()]
    if not entries:
        raise HTTPException(422, "no images open — nothing to save")
    try:
        json_path, npz_path = save_session(
            req.path, entries, req.client_state
        )
    except OSError as e:
        raise HTTPException(422, f"cannot write session: {e}") from None
    return {
        "n_images": len(entries),
        "json_path": str(json_path),
        "npz_path": str(npz_path),
    }


class LoadRequest(BaseModel):
    path: str
    replace: bool = True


@router.post("/session/load")
def session_load(req: LoadRequest) -> dict[str, Any]:
    try:
        entries, client_state = load_session(req.path)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except (ValueError, OSError, KeyError) as e:
        raise HTTPException(422, f"corrupt session file: {e}") from None

    if req.replace:
        store.clear()

    metas = []
    for img_id, name, ds in entries:
        final_id = store.restore(img_id, ds, name)
        metas.append(
            ImageMeta.from_datastruct(final_id, name, ds).model_dump()
        )
    return {"images": metas, "client_state": client_state}
