"""Force-curve files: sniffing and loading across vendors.

``force_kind`` tells the open path whether a file holds force curves and
whether it ALSO holds images (a Nanosurf .nid force map is recorded with
its topography), so the curves go to the force store and any images open
as usual.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fermiviewer.io.force_bruker import is_bruker_force, load_bruker_force
from fermiviewer.io.force_common import ForceError, ForceFile
from fermiviewer.io.force_ibw import is_ibw_force, load_ibw_force
from fermiviewer.io.force_nid import is_nid_force, load_nid_force, nid_has_images

__all__ = ["ForceError", "force_kind", "load_force"]


def force_kind(path: str | Path) -> Literal["only", "mixed"] | None:
    """"only" for a force-curve file, "mixed" when it also has images,
    None for anything else (including unreadable paths)."""
    p = Path(path)
    if not p.is_file():
        return None
    ext = p.suffix.lower()
    try:
        if ext == ".ibw":
            return "only" if is_ibw_force(p) else None
        if ext == ".nid":
            if not is_nid_force(p):
                return None
            return "mixed" if nid_has_images(p) else "only"
        with p.open("rb") as fh:
            head = fh.read(32)
    except OSError:
        return None
    return "only" if is_bruker_force(head) else None


def load_force(path: str | Path) -> ForceFile:
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".ibw":
        return load_ibw_force(p)
    if ext == ".nid":
        return load_nid_force(p)
    with p.open("rb") as fh:
        if is_bruker_force(fh.read(32)):
            return load_bruker_force(p)
    raise ForceError(f"{p.name}: not a force-curve file")
