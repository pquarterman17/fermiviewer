"""Pure directory scan for folder import (PROJECT_WORKFLOW_PLAN.md item 1,
gate G3): recurse a selected folder, group its supported images into
per-first-level-subfolder candidates, and count what got skipped.

No fastapi/pydantic/routes imports (pure-layer guard enforced by
tests/test_repo_integrity.py) — routes/folders.py adapts this into the
HTTP layer, translating FileNotFoundError/NotADirectoryError into 404/422.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fermiviewer.io.registry import supported_extensions

__all__ = ["FolderGroupScan", "FolderRootScan", "FolderScanResult", "scan_folders"]

# Mirrors /session/launch-dir's `files[:500]` cap so the two behave alike.
_MAX_FILES = 500


@dataclass(frozen=True)
class FolderGroupScan:
    """One candidate import group: a name plus its ordered supported files.

    `name` is a first-level subfolder's own name, or the selected folder's
    own name for images sitting loose directly inside it (gate G3).
    """

    name: str
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class FolderRootScan:
    """One selected top-level directory's own name and how many candidate
    groups its scan produced (item 27: import seeds projects).

    The frontend needs this boundary to tell a flat selected folder (one
    group) from a folder of folders (more than one) without a second
    request — a second request per directory would each get its own
    500-file budget instead of sharing ONE combined cap across the whole
    import, splitting the cap semantics `scan_folders` already implements.
    `group_count` is post-cap: if `_apply_cap` truncates, every root's count
    is trimmed to how many of its groups actually survived.
    """

    name: str
    group_count: int


@dataclass(frozen=True)
class FolderScanResult:
    """Everything one `scan_folders` call found, across every selected dir."""

    groups: tuple[FolderGroupScan, ...]
    skipped: int
    truncated: bool
    roots: tuple[FolderRootScan, ...]


def _sorted_entries(d: Path) -> list[Path]:
    """`d`'s direct entries, case-insensitive name order (like launch-dir).

    An unreadable directory scans as empty rather than raising, so one bad
    subfolder never aborts the whole import.
    """
    try:
        return sorted(d.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []


def _safe_is_dir(entry: Path) -> bool | None:
    """`entry.is_dir()`, swallowing the OSError a OneDrive cloud-only
    placeholder raises (launch-dir's per-entry guard) — None means "skip"."""
    try:
        return entry.is_dir()
    except OSError:
        return None


def _safe_is_file(entry: Path) -> bool | None:
    """`entry.is_file()` with the same OneDrive-safe guard as `_safe_is_dir`."""
    try:
        return entry.is_file()
    except OSError:
        return None


def _collect_recursive(d: Path, exts: frozenset[str]) -> tuple[list[Path], int]:
    """Every supported file anywhere under `d`, depth-first in the same
    case-insensitive name order at each level — the "flatten" side of G3:
    files nested arbitrarily deep inside a first-level subfolder all land
    in that subfolder's single candidate group."""
    files: list[Path] = []
    skipped = 0
    for entry in _sorted_entries(d):
        is_dir = _safe_is_dir(entry)
        if is_dir is None:
            continue
        if is_dir:
            sub_files, sub_skipped = _collect_recursive(entry, exts)
            files.extend(sub_files)
            skipped += sub_skipped
            continue
        if not _safe_is_file(entry):
            continue
        if entry.suffix.lower() in exts:
            files.append(entry)
        else:
            skipped += 1
    return files, skipped


def _scan_selected(
    d: Path, exts: frozenset[str]
) -> tuple[list[FolderGroupScan], int]:
    """One selected folder: its own loose images (if any) as a group named
    after itself, then each first-level subfolder holding supported images
    (recursively flattened) as its own group, in name order — gate G3's
    resolution in full."""
    groups: list[FolderGroupScan] = []
    skipped = 0
    loose: list[Path] = []
    subfolders: list[Path] = []
    for entry in _sorted_entries(d):
        is_dir = _safe_is_dir(entry)
        if is_dir is None:
            continue
        if is_dir:
            subfolders.append(entry)
            continue
        if not _safe_is_file(entry):
            continue
        if entry.suffix.lower() in exts:
            loose.append(entry)
        else:
            skipped += 1
    if loose:
        groups.append(FolderGroupScan(name=d.name, paths=tuple(loose)))
    for sub in subfolders:  # already case-insensitive name order
        sub_files, sub_skipped = _collect_recursive(sub, exts)
        skipped += sub_skipped
        if sub_files:
            groups.append(FolderGroupScan(name=sub.name, paths=tuple(sub_files)))
    return groups, skipped


def _apply_cap(
    groups: list[FolderGroupScan],
    skipped: int,
    roots_pre: list[FolderRootScan],
) -> FolderScanResult:
    total = sum(len(g.paths) for g in groups)
    if total <= _MAX_FILES:
        return FolderScanResult(tuple(groups), skipped, False, tuple(roots_pre))
    capped: list[FolderGroupScan] = []
    remaining = _MAX_FILES
    for g in groups:
        if remaining <= 0:
            break
        taken = g.paths[:remaining]
        remaining -= len(taken)
        capped.append(FolderGroupScan(g.name, taken))
    # capped is groups[0:len(capped)] (same order, last one maybe shorter) —
    # trim each root's pre-cap count to how much of its slice survived.
    kept = len(capped)
    consumed = 0
    roots: list[FolderRootScan] = []
    for r in roots_pre:
        adjusted = max(0, min(r.group_count, kept - consumed))
        roots.append(FolderRootScan(r.name, adjusted))
        consumed += r.group_count
    return FolderScanResult(tuple(capped), skipped, True, tuple(roots))


def scan_folders(
    dirs: Sequence[str | Path],
    extensions: Iterable[str] | None = None,
) -> FolderScanResult:
    """Scan one or more selected folders per gate G3's resolution.

    Each folder is recursed fully. A first-level subfolder holding
    supported images becomes one candidate group named after it, with
    deeper files flattened in; supported images sitting directly in a
    selected folder form a group named after that folder. Non-image /
    unsupported files anywhere are skipped and counted, never silently.
    The combined result across all `dirs` is capped at 500 supported
    files (`truncated` flags the cap), mirroring `/session/launch-dir`.

    `roots` reports, per selected directory in `dirs` order, its own name
    and how many candidate groups it produced — the boundary
    routes/folders.py hands the frontend so it can tell a flat selected
    folder from a folder of folders (item 27) without splitting this
    call's single combined cap into one request per directory.

    `extensions` defaults to `io.registry.supported_extensions()` — pass
    an explicit set to scan for something else (e.g. isolated tests).

    Raises `FileNotFoundError` for a path that doesn't exist, or
    `NotADirectoryError` for one that isn't a directory; routes/folders.py
    turns these into 404 / 422 rather than letting either become a 500.
    """
    exts = (
        frozenset(e.lower() for e in extensions)
        if extensions is not None
        else frozenset(supported_extensions())
    )
    all_groups: list[FolderGroupScan] = []
    roots_pre: list[FolderRootScan] = []
    skipped = 0
    for raw in dirs:
        d = Path(raw)
        if not d.exists():
            raise FileNotFoundError(f"directory not found: {raw}")
        if not d.is_dir():
            raise NotADirectoryError(f"not a directory: {raw}")
        groups, sk = _scan_selected(d, exts)
        all_groups.extend(groups)
        roots_pre.append(FolderRootScan(name=d.name, group_count=len(groups)))
        skipped += sk
    return _apply_cap(all_groups, skipped, roots_pre)
