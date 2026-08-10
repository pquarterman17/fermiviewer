"""Folder-open endpoint (PROJECT_WORKFLOW_PLAN.md item 1, gate G3):
directory paths in, one candidate ImageMeta group per first-level
subfolder (or the selected folder itself, for loose images) out.

Scanning is delegated to the pure `io.folder_scan.scan_folders` (recursion,
extension filter, the OneDrive-safe per-entry guard, the 500-file cap); the
actual opening is delegated to `routes._open_paths.open_paths_as_metas` —
the SAME code path `/session/open` uses, including calibration auto-apply
— so importing a folder behaves exactly like opening its files one at a
time would.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.io.folder_scan import scan_folders
from fermiviewer.models import FourDMeta, ImageMeta
from fermiviewer.routes._open_paths import open_paths_as_metas

router = APIRouter(prefix="/api")


class OpenFolderRequest(BaseModel):
    paths: list[str]


class FolderGroupResult(BaseModel):
    name: str
    images: list[ImageMeta | FourDMeta]


class OpenFolderResponse(BaseModel):
    groups: list[FolderGroupResult]
    skipped: int
    truncated: bool


@router.post("/session/open-folder")
def session_open_folder(req: OpenFolderRequest) -> OpenFolderResponse:
    """Import one or more folders as candidate groups (gate G3).

    Each selected folder is recursed fully. A first-level subfolder
    holding supported images becomes one candidate group named after it,
    with deeper files flattened in; supported images sitting directly in
    a selected folder form a group named after that folder itself.
    Unsupported / non-image files anywhere are skipped and counted in the
    response rather than silently dropped, and the combined import is
    capped at 500 supported files (`truncated` flags the cap), mirroring
    `/session/launch-dir`.

    404s for a path that doesn't exist, 422s for one that isn't a
    directory or for a file this server can't parse — never a 500.
    """
    try:
        scan = scan_folders(req.paths)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except NotADirectoryError as e:
        raise HTTPException(422, str(e)) from None

    groups = [
        FolderGroupResult(
            name=g.name,
            images=open_paths_as_metas([str(p) for p in g.paths]),
        )
        for g in scan.groups
    ]
    return OpenFolderResponse(
        groups=groups, skipped=scan.skipped, truncated=scan.truncated
    )
