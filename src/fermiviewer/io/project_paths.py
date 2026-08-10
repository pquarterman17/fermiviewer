"""Where a project's data lives — data root, references, resolution order.

The path half of the `.fvp` container (ADR 0002 §3). A light-mode project
stores each source as a POSIX path relative to **one declared data root**
plus that root's absolute path as a *hint*, so relocating a study is one
folder pick that fixes every image at once rather than N absolute paths to
repair.

Both directions live here because they have to agree:

* **Save** — `data_root()` picks the root, `reference()` turns a source into
  `(rel, size_bytes)` under it, preserving whatever the manifest already
  carried whenever a fresh value cannot be computed.
* **Load** — `search_roots()` yields the roots to try in the ADR's order:
  the hint, then the directory containing the `.fvp`. A user re-point (plan
  #34) appends to that list without changing anything else.

Nothing here raises for a foreign, missing or unreadable path: an
unresolvable reference becomes a placeholder, not an error (ADR 0002 §4).
The one exception is a *hostile* reference — an absolute or root-escaping
`rel` — which `safe_posix_rel` rejects before any filesystem access.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fermiviewer.io.project_manifest import ProjectImage, safe_posix_rel

__all__ = [
    "absolute_source",
    "data_root",
    "data_root_hint",
    "existing_file",
    "reference",
    "search_roots",
]


def existing_file(candidate: Path | None) -> Path | None:
    """The path if it is a readable file, else None.

    OSError counts as a miss, not a failure: a OneDrive cloud-only
    placeholder or a permission-denied mount must skip itself rather than
    break the whole project (the guard `/session/launch-dir` already uses).
    """
    if candidate is None:
        return None
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def absolute_source(img: ProjectImage) -> Path | None:
    """Absolute source path for reference maths: where this load read the
    pixels from, else the import path the manifest recorded. Relative values
    are ignored — joining them against the working directory would invent a
    reference to whatever happens to sit there."""
    text = img.resolved_path or img.source
    if not text:
        return None
    candidate = Path(text).expanduser()
    return candidate if candidate.is_absolute() else None


def _usable_root(declared: str | Path) -> Path | None:
    """A declared root is usable for reference maths only if it is absolute
    on THIS platform. `C:/data` is a *relative* PurePosixPath, so a Windows
    hint replayed on POSIX must not be resolved against the cwd."""
    candidate = Path(declared).expanduser()
    if not candidate.is_absolute():
        return None
    try:
        return candidate.resolve()
    except OSError:
        return None


def data_root(
    declared: str | Path | None, images: Sequence[ProjectImage]
) -> Path | None:
    """The root that references are relative to, or None if there isn't one.

    Falls back to the common parent of the sources that exist *here*. Stale
    paths from another machine are excluded deliberately: including them
    would drag the common parent up towards `/` and produce references that
    describe neither machine.
    """
    if declared is not None:
        return _usable_root(declared)
    parents = [
        str(found.parent)
        for img in images
        if not img.derived and (found := existing_file(absolute_source(img)))
    ]
    if not parents:
        return None
    try:
        return Path(os.path.commonpath(parents))
    except ValueError:
        return None  # mixed drives, or mixed absolute and relative


def data_root_hint(declared: str | Path | None, root: Path | None) -> str | None:
    """The root's absolute path as seen here, forward slashes (ADR 0002 §3).

    A declared value is kept verbatim so a hint this platform cannot use — a
    Windows path opened on POSIX — still round-trips intact for the machine
    that can use it.
    """
    if declared is not None:
        return str(declared).replace("\\", "/")
    return root.as_posix() if root is not None else None


def reference(
    img: ProjectImage, index: int, root: Path | None
) -> tuple[str | None, int | None]:
    """`(rel, size_bytes)` for an image: recomputed against `root` when that
    is possible, otherwise whatever the manifest already carried.

    Preserving the carried value is the no-data-loss guarantee. A project
    opened where its sources are missing — or recorded under another
    machine's paths — must re-save with its references untouched, so opening
    a project without its data and pressing save cannot destroy it.

    Raises ProjectFormatError if the carried `rel` is absolute or escapes the
    root; a save must not launder a hostile reference back onto disk.
    """
    carried = safe_posix_rel(img.rel, where=f"images[{index}].rel") if img.rel else None
    fresh, size = _fresh_reference(absolute_source(img), root)
    return (fresh or carried), (size if size is not None else img.size_bytes)


def _fresh_reference(
    source: Path | None, root: Path | None
) -> tuple[str | None, int | None]:
    if source is None or root is None:
        return None, None
    try:
        resolved = source.resolve()
        rel = resolved.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None, None  # outside the declared root — not referenceable
    if not rel or rel == ".":
        return None, None
    try:
        size: int | None = resolved.stat().st_size
    except OSError:
        size = None  # referenceable but not readable right now
    return rel, size


def search_roots(hint: Any, project_dir: Path) -> tuple[Path, ...]:
    """Roots to try when resolving a reference, in ADR 0002 §3 order.

    A hint that is not absolute on this platform is skipped rather than
    joined against the working directory — that is both the Windows-hint-on-
    POSIX case (which then resolves via the project's own directory) and the
    guard that stops a crafted relative hint from reaching local files.
    """
    roots: list[Path] = []
    if isinstance(hint, str) and hint:
        candidate = Path(hint).expanduser()
        if candidate.is_absolute():
            roots.append(candidate)
    roots.append(project_dir)
    return tuple(roots)
