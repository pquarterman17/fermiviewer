"""Shared server-side-path opener — the code `/session/open` and
`/session/open-folder` (routes/folders.py, PROJECT_WORKFLOW_PLAN.md item 1)
both need to turn a list of on-disk paths into opened images.

Extracted out of routes/images.py so folder import opens files EXACTLY the
same way a manual multi-path open does — same 4D-STEM split, same
calibration auto-apply — without either endpoint reimplementing the other.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import HTTPException

from fermiviewer.io.force import force_kind, load_force
from fermiviewer.io.force_common import ForceError
from fermiviewer.io.registry import (
    UnsupportedFormatError,
    is_fourd_path,
    load_auto,
    load_fourd_auto,
)
from fermiviewer.models import ForceMeta, FourDMeta, ImageMeta
from fermiviewer.session import store
from fermiviewer.session_force import force_store
from fermiviewer.session_fourd import UploadDir, fourd_store

__all__ = ["open_paths_as_metas", "open_uploaded_file"]


OpenedMeta = ImageMeta | FourDMeta | ForceMeta


def _open_force(path: str | Path, name: str) -> ForceMeta:
    try:
        f = load_force(path)
    except ForceError as e:
        raise HTTPException(422, f"{name}: {e}") from None
    return ForceMeta.from_file(force_store.add(f, name), name, f)


def open_paths_as_metas(paths: list[str]) -> list[OpenedMeta]:
    """Open `paths` by server-side path, exactly like `/session/open`.

    4D-STEM files (Merlin .mib, 4D HyperSpy .hspy/.h5/.hdf5 — sniffed by
    `is_fourd_path`) are split out BEFORE the normal image loader ever sees
    them: they register in the separate FourD store and come back as
    `FourDMeta` entries (the `is_fourd` discriminator marks them so a
    frontend that doesn't yet know about 4D datasets can filter them out
    instead of mis-treating one as a normal image — see store/viewer.ts's
    `openPaths`). AFM force-curve files go to the force store the same way
    (`ForceMeta`, `is_force`); one that also holds images (a Nanosurf force
    map with its topography) opens those as well. Everything else goes
    through the unchanged 2D/3D path, with calibration auto-applied per
    image.
    """
    fourd_metas: list[FourDMeta] = []
    force_metas: list[ForceMeta] = []
    remaining: list[str] = []
    for raw_path in paths:
        if (fk := force_kind(raw_path)) is not None:
            force_metas.append(_open_force(raw_path, Path(raw_path).name))
            if fk == "mixed":
                remaining.append(raw_path)
            continue
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
    return [*image_metas, *fourd_metas, *force_metas]


def open_uploaded_file(staged: Path, name: str) -> OpenedMeta:
    """Open one browser-uploaded file staged at `staged` (original `name`),
    routed exactly like `open_paths_as_metas`: 4D-STEM files go to the FourD
    store, everything else through `load_auto` + calibration auto-apply.

    The 4D loaders are lazy (an open ``h5py.File`` / ``np.memmap``) and a
    Merlin reshape re-opens the file by path, so a 4D upload is moved out
    of the request's throw-away staging dir into one that outlives it. The
    FourD store owns that dir and deletes it when the dataset is closed.
    Force-curve files are read whole, so they need no kept copy. One meta
    per uploaded file (lib/folderDrop.ts relies on it): a file with both
    curves and images returns its image, its curves going to the force
    store and their `ForceMeta` riding on the image as `force_file`.
    """
    fk = force_kind(staged)
    if fk == "only":
        return _open_force(staged, name)
    force = _open_force(staged, name) if fk == "mixed" else None
    if is_fourd_path(staged):
        keep = UploadDir()
        kept = keep.path / name
        shutil.move(staged, kept)
        try:
            ds4 = load_fourd_auto(kept)
        except Exception as e:
            keep.release()
            if isinstance(e, UnsupportedFormatError):
                raise HTTPException(415, str(e)) from None
            if isinstance(e, ValueError):
                raise HTTPException(422, f"{name}: {e}") from None
            raise
        fourd_id = fourd_store.add(ds4, name, source_path=kept, owned_dir=keep)
        return FourDMeta.from_dataset(fourd_id, name, ds4)
    try:
        ds = load_auto(staged)
    except UnsupportedFormatError as e:
        raise HTTPException(415, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, f"{name}: {e}") from None
    # don't leak the vanishing temp path as the source
    ds.metadata["source"] = name
    img_id = store.add_parsed(ds, name)
    from fermiviewer.io.spm_channels import SPM_PARSERS

    if ds.metadata.get("parser") in SPM_PARSERS:
        from fermiviewer.routes.afm import stash_upload_channels

        stash_upload_channels(img_id, staged)  # file is gone after the request
    from fermiviewer.routes.calibration import auto_apply_calibration

    auto_apply_calibration(img_id, ds)
    meta = ImageMeta.from_datastruct(img_id, name, store.get(img_id))
    meta.force_file = force
    return meta
