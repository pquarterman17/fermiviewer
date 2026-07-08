"""Workspace persistence routes.

Two surfaces over the same serializer (io.session_file):
  • path-based  POST /session/{save,load}  — export/import a session to an
    arbitrary .json+.npz path the user names.
  • named       /workspaces[/save,/load] + DELETE — the menu-bar workspace
    switcher (design WS4b): the same sessions, addressed by a display name
    and kept under the OS config dir. The naming layer lives in
    fermiviewer.workspaces; this module stays a thin store↔serializer adapter.
The client_state blob (views, display, measures, overlay) round-trips opaquely.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer import workspaces
from fermiviewer.io.session_file import load_session, save_session
from fermiviewer.models import ImageMeta
from fermiviewer.session import store

router = APIRouter(prefix="/api")


def _open_entries() -> list[tuple[str, str, Any]]:
    """(id, name, DataStruct) for every open image."""
    return [(i, store.name(i), store.get(i)) for i in store.ids()]


def _restore_into_store(
    entries: list[tuple[str, str, Any]], *, replace: bool
) -> list[dict[str, Any]]:
    """Push loaded entries back into the session store; return their metas."""
    if replace:
        store.clear()
        from fermiviewer.routes.images import clear_level_cache

        clear_level_cache()  # every id it could reference is gone too
    metas = []
    for img_id, name, ds in entries:
        final_id = store.restore(img_id, ds, name)
        metas.append(ImageMeta.from_datastruct(final_id, name, ds).model_dump())
    return metas


# ── path-based session export/import (plan #21) ─────────────────────


class SaveRequest(BaseModel):
    path: str
    client_state: dict[str, Any] | None = None


@router.post("/session/save")
def session_save(req: SaveRequest) -> dict[str, Any]:
    entries = _open_entries()
    if not entries:
        raise HTTPException(422, "no images open — nothing to save")
    try:
        json_path, npz_path = save_session(req.path, entries, req.client_state)
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

    metas = _restore_into_store(entries, replace=req.replace)
    return {"images": metas, "client_state": client_state}


# ── named workspaces (design WS4b) ──────────────────────────────────


@router.get("/workspaces")
def workspaces_list() -> dict[str, Any]:
    return {"workspaces": workspaces.list_workspaces()}


class SaveNamedRequest(BaseModel):
    name: str
    client_state: dict[str, Any] | None = None


@router.post("/workspaces/save")
def workspace_save(req: SaveNamedRequest) -> dict[str, Any]:
    name = req.name.strip()
    if not name:
        raise HTTPException(422, "workspace name required")
    entries = _open_entries()
    if not entries:
        raise HTTPException(422, "no images open — nothing to save")
    slug = workspaces.slugify(name)
    try:
        save_session(workspaces.session_path(slug), entries, req.client_state)
    except OSError as e:
        raise HTTPException(422, f"cannot write workspace: {e}") from None
    saved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    workspaces.register(slug, name, len(entries), saved_at)
    return {"slug": slug, "name": name, "n_images": len(entries)}


def _valid_slug(slug: str) -> bool:
    # slugs are produced by slugify ([a-z0-9-]); reject anything else so a
    # crafted slug like "../../foo" can't escape the workspaces directory
    return bool(re.fullmatch(r"[a-z0-9-]+", slug))


class LoadNamedRequest(BaseModel):
    slug: str


@router.post("/workspaces/load")
def workspace_load(req: LoadNamedRequest) -> dict[str, Any]:
    if not _valid_slug(req.slug):
        raise HTTPException(422, "invalid workspace slug")
    path = workspaces.session_path(req.slug)
    if not path.is_file():
        raise HTTPException(404, f"workspace not found: {req.slug}")
    try:
        entries, client_state = load_session(path)
    except (FileNotFoundError, ValueError, OSError, KeyError) as e:
        raise HTTPException(422, f"corrupt workspace: {e}") from None

    metas = _restore_into_store(entries, replace=True)
    info = next(
        (w for w in workspaces.list_workspaces() if w["slug"] == req.slug), None
    )
    return {
        "images": metas,
        "client_state": client_state,
        "name": info["name"] if info else req.slug,
    }


@router.delete("/workspaces/{slug}")
def workspace_delete(slug: str) -> dict[str, bool]:
    if not _valid_slug(slug):
        raise HTTPException(422, "invalid workspace slug")
    return {"deleted": workspaces.delete_workspace(slug)}
