"""Project save / open / relocate — the `.fvp` v2 surface (plan #32–#38).

Three endpoints, one per user action:

* ``POST /api/project/save`` — **Save Project** (`mode="light"`) and **Export
  Project Bundle** (`mode="bundle"`) are the same call with the one field that
  distinguishes them (ADR 0002 §2). Derived images and thumbnails (plan #37)
  embed in both modes. `hash_sources` (plan #38) opts into per-image sha256,
  off by default.
* ``POST /api/project/load`` — **Open Project…**, accepting a `.fvp` or a
  legacy v1 `.json`/`.npz` pair, which is upgraded in memory (plan #32).
* ``POST /api/project/relocate`` — **Locate folder…**, re-resolving whatever is
  still unavailable against a folder the user picked (plan #34). Invokable at
  any time and repeatable, so samples that moved to different folders can each
  be pointed at their own. Reports a `sha256` mismatch (plan #38) distinctly
  from a `size_bytes` one — the former only fires for an image that was
  actually hashed, and means something a size match cannot.

A separate module because `routes/images.py` is at its ceiling, and because
this is one cohesive surface: the store adapter it shares with the named
workspaces lives in `routes/_project_adapter.py`.

Every failure is a 4xx with a reason. A `.fvp` is a file a stranger can send,
so `ProjectFormatError` (bad ZIP, schema violation, hostile `rel`) is a 422 and
never a 500.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.io.project_file import PayloadMode
from fermiviewer.io.project_manifest import ProjectFormatError
from fermiviewer.project_session import project
from fermiviewer.routes._project_adapter import (
    load_into_session,
    meta_of,
    save_current,
    unavailable_payload,
)

router = APIRouter(prefix="/api")


class SaveProjectRequest(BaseModel):
    path: str
    #: "light" references source pixels (everyday save, megabytes); "bundle"
    #: embeds everything (transfer to another machine, hundreds of MB).
    mode: PayloadMode = "light"
    client_state: dict[str, Any] | None = None
    name: str | None = None
    #: Opt-in content hashing (plan #38) — off by default, since hashing a
    #: whole study on every save is not worth the time for callers who never
    #: asked for strict post-relocation verification.
    hash_sources: bool = False


@router.post("/project/save")
def project_save(req: SaveProjectRequest) -> dict[str, Any]:
    """Write the session to a `.fvp`. The suffix is applied if absent."""
    try:
        return save_current(
            req.path,
            mode=req.mode,
            client_state=req.client_state,
            name=req.name,
            hash_sources=req.hash_sources,
        )
    except ValueError as e:
        # ProjectFormatError is a ValueError: a manifest that would not
        # validate, or a carried reference that is not safe to write back.
        raise HTTPException(422, str(e)) from None
    except OSError as e:
        raise HTTPException(422, f"cannot write project: {e}") from None


class LoadProjectRequest(BaseModel):
    path: str
    replace: bool = True


@router.post("/project/load")
def project_load(req: LoadProjectRequest) -> dict[str, Any]:
    """Open a `.fvp` (or a v1 workspace) into the session."""
    try:
        return load_into_session(req.path, replace=req.replace)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except ProjectFormatError as e:
        raise HTTPException(422, f"not a readable project: {e}") from None
    except (ValueError, OSError, KeyError) as e:
        raise HTTPException(422, f"corrupt project file: {e}") from None


class RelocateRequest(BaseModel):
    #: Folder the user picked — the data root its images now live under.
    root: str


@router.post("/project/relocate")
def project_relocate(req: RelocateRequest) -> dict[str, Any]:
    """Re-resolve unavailable images against `root`.

    Never 404s for "nothing was unavailable" — a user may pick a folder before
    a project is open, or pick the same one twice, and an empty result is the
    honest answer to both.
    """
    try:
        outcome = project.relocate(req.root)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except NotADirectoryError as e:
        raise HTTPException(422, str(e)) from None

    resolved = [meta for img in outcome.resolved if (meta := meta_of(img)) is not None]
    return {
        "root": outcome.root,
        "resolved": resolved,
        "still_unavailable": unavailable_payload(outcome.still_unavailable),
        # Reported, not enforced — see project_session.SizeMismatch.
        "mismatches": [vars(m) for m in outcome.mismatches],
        # Distinct from "mismatches" (plan #38): only ever populated for an
        # image saved with hash_sources=True, and a hash mismatch is strong
        # evidence the bytes differ rather than a byte count matching by luck.
        "hash_mismatches": [vars(m) for m in outcome.hash_mismatches],
        # Found under the chosen root but holding something else: a
        # wrong-data folder, which needs a different message from a
        # wrong-path one.
        "rejected": [{"id": img.id, "name": img.name} for img in outcome.rejected],
    }
