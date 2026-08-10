"""Shared server-side-path opener — the code `/session/open` and
`/session/open-folder` (routes/folders.py, PROJECT_WORKFLOW_PLAN.md item 1)
both need to turn a list of on-disk paths into opened images.

Extracted out of routes/images.py so folder import opens files EXACTLY the
same way a manual multi-path open does — same 4D-STEM split, same
calibration auto-apply — without either endpoint reimplementing the other.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from fermiviewer.io.registry import (
    UnsupportedFormatError,
    is_fourd_path,
    load_fourd_auto,
)
from fermiviewer.models import FourDMeta, ImageMeta
from fermiviewer.session import store
from fermiviewer.session_fourd import fourd_store

__all__ = ["open_paths_as_metas"]


def open_paths_as_metas(paths: list[str]) -> list[ImageMeta | FourDMeta]:
    """Open `paths` by server-side path, exactly like `/session/open`.

    4D-STEM files (Merlin .mib, 4D HyperSpy .hspy/.h5/.hdf5 — sniffed by
    `is_fourd_path`) are split out BEFORE the normal image loader ever sees
    them: they register in the separate FourD store and come back as
    `FourDMeta` entries (the `is_fourd` discriminator marks them so a
    frontend that doesn't yet know about 4D datasets can filter them out
    instead of mis-treating one as a normal image — see store/viewer.ts's
    `openPaths`). Everything else goes through the unchanged 2D/3D path,
    with calibration auto-applied per image.
    """
    fourd_metas: list[FourDMeta] = []
    remaining: list[str] = []
    for raw_path in paths:
        if not is_fourd_path(raw_path):
            remaining.append(raw_path)
            continue
        try:
            ds4 = load_fourd_auto(raw_path)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from None
        except UnsupportedFormatError as e:
            raise HTTPException(415, str(e)) from None
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        name = Path(raw_path).name
        fourd_id = fourd_store.add(ds4, name, source_path=raw_path)
        fourd_metas.append(FourDMeta.from_dataset(fourd_id, name, ds4))

    try:
        opened = store.open_paths(remaining)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except UnsupportedFormatError as e:
        raise HTTPException(415, str(e)) from None
    except ValueError as e:  # parser format errors
        raise HTTPException(422, str(e)) from None
    from fermiviewer.routes.calibration import auto_apply_calibration

    for i, ds in opened:
        auto_apply_calibration(i, ds)
    image_metas = [
        ImageMeta.from_datastruct(i, store.name(i), store.get(i))
        for i, _ in opened
    ]
    return [*image_metas, *fourd_metas]
