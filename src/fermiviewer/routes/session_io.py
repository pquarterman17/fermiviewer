"""Named-workspace routes (design WS4b).

A *workspace* is a project addressed by display name instead of a path, kept
under the OS config dir — the menu-bar switcher. The naming layer lives in
`fermiviewer.workspaces`; the format and the store adapter are shared with the
path-based File-menu surface (`routes/project_io.py`) through
`routes/_project_adapter.py`, so a workspace and a `.fvp` on disk are the same
bytes and behave identically.

Since plan #32 a workspace is written as `<slug>.fvp`. A `<slug>.json` +
`<slug>.npz` pair saved by an older build still loads — it is upgraded in
memory and the next save writes the `.fvp` — and the pair is removed when the
workspace is deleted, so nothing is orphaned.

The path-based `/session/save` and `/session/load` are gone with the v1 write
path; the File menu now speaks `/api/project/{save,load}`.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer import workspaces
from fermiviewer.io.project_manifest import ProjectFormatError
from fermiviewer.routes._project_adapter import load_into_session, save_current

router = APIRouter(prefix="/api")


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
    slug = workspaces.slugify(name)
    try:
        result = save_current(
            workspaces.project_path(slug),
            mode="light",
            client_state=req.client_state,
            name=name,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except OSError as e:
        raise HTTPException(422, f"cannot write workspace: {e}") from None
    saved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    n_images = int(result["n_images"])
    workspaces.register(slug, name, n_images, saved_at)
    return {"slug": slug, "name": name, "n_images": n_images}


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
    path = workspaces.stored_path(req.slug)
    if path is None:
        raise HTTPException(404, f"workspace not found: {req.slug}")
    try:
        payload = load_into_session(path)
    except ProjectFormatError as e:
        raise HTTPException(422, f"not a readable workspace: {e}") from None
    except (FileNotFoundError, ValueError, OSError, KeyError) as e:
        raise HTTPException(422, f"corrupt workspace: {e}") from None

    info = next(
        (w for w in workspaces.list_workspaces() if w["slug"] == req.slug), None
    )
    return {**payload, "name": info["name"] if info else req.slug}


@router.delete("/workspaces/{slug}")
def workspace_delete(slug: str) -> dict[str, bool]:
    if not _valid_slug(slug):
        raise HTTPException(422, "invalid workspace slug")
    return {"deleted": workspaces.delete_workspace(slug)}
