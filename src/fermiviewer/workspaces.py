"""Named-workspace registry (design WS4b).

A *workspace* is just a named project. The bytes are written by the project
serializer (``<slug>.fvp``, ADR 0002) under the OS config dir at
``<config>/workspaces/``; this module adds the thin naming layer on top —
slugs, a display-name/timestamp index, listing, and deletion. It owns no
pixel I/O of its own, so the save/load contract stays in one place
(``io.project_file``).

Workspaces saved by a build before plan #32 are a v1 ``<slug>.json`` +
``<slug>.npz`` pair. ``stored_path`` prefers the ``.fvp`` and falls back to
the pair, so an old workspace keeps opening (upgraded in memory) and the next
save writes the ``.fvp`` beside it; ``delete_workspace`` removes all three
names so nothing is left orphaned.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fermiviewer.io.project_file import PROJECT_SUFFIX
from fermiviewer.usermeta import config_dir

__all__ = [
    "delete_workspace",
    "list_workspaces",
    "project_path",
    "register",
    "session_path",
    "slugify",
    "stored_path",
    "workspaces_dir",
]

_INDEX_VERSION = 1


def workspaces_dir() -> Path:
    """Directory holding every named workspace + the index."""
    return config_dir() / "workspaces"


def _index_path() -> Path:
    return workspaces_dir() / "index.json"


def project_path(slug: str) -> Path:
    """The ``.fvp`` project path for a slug — where a save goes."""
    return workspaces_dir() / f"{slug}{PROJECT_SUFFIX}"


def session_path(slug: str) -> Path:
    """The legacy v1 ``.json`` manifest path (``.npz`` is its sibling).
    Read-only: nothing writes this any more."""
    return workspaces_dir() / f"{slug}.json"


def stored_path(slug: str) -> Path | None:
    """Where this workspace actually is, or None if it is gone.

    The ``.fvp`` wins over a legacy pair left beside it, so re-saving an old
    workspace upgrades it in place rather than leaving two sources of truth
    with the newer one ignored.
    """
    project = project_path(slug)
    if project.is_file():
        return project
    legacy = session_path(slug)
    return legacy if legacy.is_file() else None


def slugify(name: str) -> str:
    """Filesystem-safe slug from a display name. Collisions overwrite —
    saving the same name twice updates the workspace in place."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "workspace"


def _empty_index() -> dict[str, Any]:
    return {"version": _INDEX_VERSION, "workspaces": {}}


def _read_index() -> dict[str, Any]:
    path = _index_path()
    if not path.is_file():
        return _empty_index()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_index()
    if not isinstance(data, dict) or not isinstance(data.get("workspaces"), dict):
        return _empty_index()
    return data


def _write_index(data: dict[str, Any]) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def list_workspaces() -> list[dict[str, Any]]:
    """Saved workspaces as ``[{slug, name, saved_at, n_images}]``, sorted
    by display name. Self-healing: index entries whose manifest is gone
    (deleted out-of-band) are pruned on read."""
    data = _read_index()
    entries = data["workspaces"]
    out: list[dict[str, Any]] = []
    keep: dict[str, Any] = {}
    for slug, info in entries.items():
        if stored_path(slug) is None:
            continue
        keep[slug] = info
        out.append(
            {
                "slug": slug,
                "name": info.get("name", slug),
                "saved_at": info.get("saved_at"),
                "n_images": int(info.get("n_images", 0)),
            }
        )
    if len(keep) != len(entries):  # stale entries pruned → persist
        data["workspaces"] = keep
        _write_index(data)
    out.sort(key=lambda w: w["name"].lower())
    return out


def register(slug: str, name: str, n_images: int, saved_at: str) -> None:
    """Record (or update) a workspace's index entry."""
    data = _read_index()
    data["workspaces"][slug] = {
        "name": name,
        "saved_at": saved_at,
        "n_images": n_images,
    }
    _write_index(data)


def delete_workspace(slug: str) -> bool:
    """Remove a workspace's index entry + its files, current and legacy.
    Returns True if anything was actually removed."""
    data = _read_index()
    existed = data["workspaces"].pop(slug, None) is not None
    _write_index(data)
    removed = False
    for ext in (PROJECT_SUFFIX, ".json", ".npz"):
        f = workspaces_dir() / f"{slug}{ext}"
        if f.is_file():
            f.unlink()
            removed = True
    return existed or removed
