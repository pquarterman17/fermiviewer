"""Session store ⇄ `.fvp` project — the adapter both save/load surfaces use.

Two routes reach the same project format: the path-based one the File menu
drives (`routes/project_io.py`) and the named-workspace switcher
(`routes/session_io.py`). Everything they share lives here so they cannot
drift apart — in particular the two rules that make save/reload trustworthy:

1. **Unresolved references are carried by the SERVER**, from
   `project_session`, not by the client. The client cannot forget them, so
   opening a project without its data and pressing save cannot destroy it
   (ADR 0002 §4).
2. **When any image is unresolved, the loaded data root is re-declared**
   rather than re-derived. A placeholder's `rel` is only meaningful against
   the root it was written under; letting the root drift to this machine's
   layout would leave every placeholder's reference pointing somewhere else
   entirely — technically preserved, silently wrong.

   Two consequences, both deliberate. A resolved image now living outside that
   root keeps the reference it arrived with, so it still describes the machine
   that wrote it rather than acquiring one relative to the wrong root. And an
   image opened fresh this session, which has no carried reference and cannot
   compute one under that root, is EMBEDDED by a light save: heavier, never
   lossy. Once everything resolves, the root is re-derived from where the
   files actually are and the hint is updated with it — so a fully relocated
   project stops depending on the machine it came from.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.project_file import (
    PayloadMode,
    ProjectEntry,
    load_project,
    save_project,
)
from fermiviewer.io.project_manifest import LoadedProject, ProjectImage
from fermiviewer.io.project_sections import join_sections, split_client_state
from fermiviewer.models import ImageMeta
from fermiviewer.project_session import project
from fermiviewer.session import store

__all__ = [
    "load_into_session",
    "meta_of",
    "open_entries",
    "restore_into_store",
    "save_current",
    "unavailable_payload",
]


def open_entries() -> list[tuple[str, str, DataStruct]]:
    """(id, name, DataStruct) for every open image."""
    return [(i, store.name(i), store.get(i)) for i in store.ids()]


def restore_into_store(
    entries: list[tuple[str, str, DataStruct]], *, replace: bool
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


def meta_of(img: ProjectImage) -> dict[str, Any] | None:
    """A resolved `ProjectImage` registered in the store, as its meta."""
    ds = img.datastruct
    if ds is None:
        return None
    final_id = store.restore(img.id, ds, img.name)
    return ImageMeta.from_datastruct(final_id, img.name, ds).model_dump()


def unavailable_payload(images: tuple[ProjectImage, ...]) -> list[dict[str, Any]]:
    """Placeholders as the client's `unavailable` list.

    Deliberately NOT an `ImageMeta`: there is no shape, no dtype and nothing
    to render, and inventing zeros would put a broken image in the library
    instead of an honest placeholder. The library keeps name and reference; the
    sample membership, parameters and measurements that go with it ride the
    project's own `samples` / `measures` sections, which never prune.

    `thumb` (plan #37) is the one exception to "nothing to render": a
    placeholder's pixels are gone, but its `thumbs/<id>.png` — baked in at a
    previous save, before the source went missing — survived that save
    regardless, so the library can still show a preview instead of a blank
    card. Base64-inlined rather than a second endpoint: it is already
    <= 256 px, and this is the one response that needs it.
    """
    return [
        {
            "id": img.id,
            "name": img.name,
            "rel": img.rel,
            "source": img.source,
            "size_bytes": img.size_bytes,
            "thumb": base64.b64encode(img.thumb).decode("ascii")
            if img.thumb
            else None,
        }
        for img in images
        if img.data is None
    ]


def load_into_session(path: str | Path, *, replace: bool = True) -> dict[str, Any]:
    """Open a project (or a v1 workspace) and restore it into the session.

    `replace=False` APPENDS to the session, so the project state is merged
    rather than overwritten — see `ProjectSession.adopt`. Getting that wrong
    would drop the previously open project's unresolved references.
    """
    loaded = load_project(path)
    metas = restore_into_store(loaded.entries, replace=replace)
    project.adopt(loaded, path, merge=not replace)
    return {
        "images": metas,
        "client_state": join_sections(
            loaded.samples, loaded.measures, loaded.ui_state
        ),
        # Every placeholder the SESSION now tracks, not just this file's: on an
        # append load the client must see the ones it already had too, or its
        # library would stop listing them while the server still saves them.
        "unavailable": unavailable_payload(project.placeholders()),
        "project": _project_info(loaded),
    }


def _project_info(loaded: LoadedProject) -> dict[str, Any]:
    """Describes what the session now has open — which after an append load is
    the project that was already there, not the file just read."""
    state = project.current()
    return {
        "path": state.path,
        "name": state.name,
        "payload_mode": state.payload_mode,
        "data_root_hint": state.data_root_hint,
        "primary_param": state.primary_param,
        "n_unavailable": len(state.placeholders),
        # The one field that describes the FILE rather than the session, so an
        # append load can still say what it just read.
        "loaded_payload_mode": loaded.payload_mode,
    }


def save_current(
    path: str | Path,
    *,
    mode: PayloadMode = "light",
    client_state: dict[str, Any] | None = None,
    name: str | None = None,
    hash_sources: bool = False,
) -> dict[str, Any]:
    """Write everything the session holds to `path` as a `.fvp`.

    Raises ValueError when there is nothing at all to save. Note that
    *placeholders count*: a project whose data is entirely missing on this
    machine must still be saveable, or the no-data-loss guarantee would only
    hold for projects that did not need it.

    `hash_sources` (plan #38) is passed straight through to `save_project` —
    see its docstring for what it does and why it defaults off.
    """
    sections = split_client_state(client_state)
    placeholders = project.placeholders()
    entries: list[ProjectEntry] = [*open_entries(), *placeholders]
    if not entries:
        raise ValueError("no images open — nothing to save")

    state = project.current()
    written = save_project(
        path,
        entries,
        mode=mode,
        samples=sections.samples,
        measures=sections.measures,
        ui_state=sections.ui_state,
        # See rule 2 in the module docstring.
        data_root=state.data_root_hint if placeholders else None,
        primary_param=state.primary_param,
        name=name if name is not None else state.name,
        unknown_keys=state.unknown_keys,
        hash_sources=hash_sources,
    )
    project.note_save(written, mode, name)
    return {
        "path": str(written),
        "payload_mode": mode,
        "n_images": len(entries),
        "n_unavailable": len(placeholders),
        "dropped_samples": sections.dropped_samples,
        "dropped_measures": sections.dropped_measures,
    }
