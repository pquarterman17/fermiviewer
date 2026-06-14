"""Dev-only convenience endpoints (inert in packaged builds)."""

from __future__ import annotations

from fastapi import APIRouter

from fermiviewer.devsamples import find_sample_files

router = APIRouter(prefix="/api/dev")


@router.get("/sample-files")
def dev_sample_files() -> list[str]:
    """Absolute paths of a few sample datasets (jpeg/dm3/dm4/tif) from
    the sibling fermi-viewer corpus, for the frontend's auto-load
    testing mode. Empty when the corpus isn't present (CI / installed
    app), so the frontend just skips the auto-load."""
    return [str(p) for p in find_sample_files()]
