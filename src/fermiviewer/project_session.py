"""The project this session has open — and its unresolved images.

`session.store` holds decoded pixels. A light-mode project can also carry
images whose pixels this machine could not find (ADR 0002 §4), and those have
no DataStruct, so they cannot live in the store. They live here, and that is
what makes two guarantees possible:

* **Saving preserves an unresolved reference.** The placeholder list is owned
  by the server and fed straight back into `save_project`, so opening a
  project on a machine without its data and pressing save cannot destroy it —
  the guarantee holds even if the client never mentions the missing images.
* **"Locate folder…" works at any time, repeatedly** (plan #34/#35). Each
  re-point appends to the resolution order rather than replacing the hint, so
  samples that moved to *different* folders can each be pointed at their own,
  and a hint that starts working again still wins.

Also remembered: the loaded `data_root_hint`, `primary_param`, project name
and the manifest keys this build does not model — all of which a re-save must
write back unchanged for the round-trip to be lossless.

No FastAPI/Pydantic here (routes adapt), and no session-store import either:
resolving produces plain `ProjectImage` values and the caller registers them.
Thread-safe for the single-process uvicorn deployment, like `SessionStore`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from fermiviewer.io import project_paths as paths
from fermiviewer.io import project_resolve as resolving
from fermiviewer.io.project_manifest import LoadedProject, ProjectImage
from fermiviewer.io.project_results import ResultRecord
from fermiviewer.io.regions_model import (
    RegionClass,
    RegionSet,
    free_set_id,
    regions_to_manifest,
    same_region_set,
)

__all__ = [
    "HashMismatch",
    "OpenProject",
    "ProjectSession",
    "Relocation",
    "SizeMismatch",
    "project",
]


@dataclass(frozen=True)
class OpenProject:
    """What a re-save has to carry over from the load that produced it."""

    path: str | None = None
    name: str | None = None
    payload_mode: str = "light"
    data_root_hint: str | None = None
    primary_param: str | None = None
    unknown_keys: dict[str, Any] = field(default_factory=dict)
    #: Images whose pixels are missing on this machine, in manifest order.
    placeholders: tuple[ProjectImage, ...] = ()
    #: Folders the user has re-pointed this session, oldest first.
    extra_roots: tuple[str, ...] = ()
    #: Persisted analysis results (ADR 0004), carried by the SERVER for the
    #: same reason placeholders are: the client never echoes them back, so
    #: a re-save that forgot them would silently destroy recorded science.
    results: tuple[ResultRecord, ...] = ()
    #: Named region sets and their class vocabulary (ADR 0006), carried for
    #: exactly the same reason as `results`: the client does not echo them
    #: back, so a re-save that forgot them would silently destroy the
    #: regions a user drew.
    region_sets: tuple[RegionSet, ...] = ()
    region_classes: tuple[RegionClass, ...] = ()
    #: Where each carried set came from: `(source path, the id it had in
    #: that file)` → the id it ended up under here. An append load renames
    #: a genuine id collision (see `_merge_region_sets`), so without this
    #: a second append of the SAME project would not recognise its own
    #: renamed set and would add another copy on every reload.
    region_set_origins: dict[tuple[str, str], str] = field(default_factory=dict)

    @property
    def project_dir(self) -> Path:
        return Path(self.path).parent if self.path else Path()


@dataclass(frozen=True)
class SizeMismatch:
    """A resolved file whose byte count is not the one recorded at save.

    Reported, not enforced (ADR 0002 §3 calls `size_bytes` a *cheap sanity
    check*): the shape/kind check in `project_resolve` is the real guard, and a
    legitimately re-exported file can differ in bytes while holding the same
    image. Telling the user beats both silently accepting it and refusing a
    folder that is almost certainly right.
    """

    id: str
    name: str
    rel: str
    expected_bytes: int
    actual_bytes: int


@dataclass(frozen=True)
class HashMismatch:
    """A resolved file whose sha256 does not match the one recorded at save
    (plan #38). Unlike `SizeMismatch`, this is only ever produced for an
    image that was actually hashed — `save_project(hash_sources=True)` — so
    it means something a size match cannot: the bytes really do differ, not
    just their count. Reported, not enforced, same as `SizeMismatch`."""

    id: str
    name: str
    rel: str
    expected_sha256: str
    actual_sha256: str


@dataclass(frozen=True)
class Relocation:
    """The outcome of one "Locate folder…"."""

    root: str
    resolved: tuple[ProjectImage, ...] = ()
    still_unavailable: tuple[ProjectImage, ...] = ()
    mismatches: tuple[SizeMismatch, ...] = ()
    #: Distinct from `mismatches`: a byte-count match is weak evidence, a
    #: hash mismatch is strong evidence the bytes really differ.
    hash_mismatches: tuple[HashMismatch, ...] = ()
    #: Images whose file WAS found under the chosen root but did not describe
    #: what the manifest says — a wrong-data folder, not a wrong-path one.
    rejected: tuple[ProjectImage, ...] = ()


class ProjectSession:
    """Mutable, process-wide record of the open project."""

    def __init__(self) -> None:
        self._state = OpenProject()
        self._lock = threading.Lock()

    def current(self) -> OpenProject:
        with self._lock:
            return self._state

    def clear(self) -> None:
        with self._lock:
            self._state = OpenProject()

    def adopt(self, loaded: LoadedProject, path: str | Path, *, merge: bool = False) -> None:
        """Take over from a fresh load, replacing whatever was open.

        `merge=True` is the append load (`/project/load` with
        `replace: false`), which adds a second project's images to the session
        instead of replacing them. It must NOT discard what is already tracked:
        overwriting the placeholder list there would drop the first project's
        unresolved references, and the next save would write that loss to its
        file — the one thing ADR 0002 §4 forbids. So the identity of the
        project already open is kept, and the arriving placeholders are
        appended (by id, so re-loading the same file twice does not double
        them).

        The merged project's own hint and directory are remembered as extra
        search roots, because the kept `data_root_hint` is the *first*
        project's: without them the arriving references would be resolvable
        only by hand. One declared root per project is the format's design
        (ADR 0002 §3), so a merged session genuinely has more roots than it can
        record — a re-save keeps every reference verbatim, and whichever set no
        longer matches the declared root can be re-pointed like any other.
        """
        arriving = tuple(
            # Drop the resolved-path of a previous load: these have no pixels,
            # and a stale absolute path must never be mistaken for provenance
            # on a re-save.
            replace(img, resolved_path=None)
            for img in loaded.images
            if img.data is None
        )
        with self._lock:
            previous = self._state
            if not merge or previous.path is None:
                self._state = OpenProject(
                    path=str(path),
                    name=loaded.name,
                    payload_mode=loaded.payload_mode,
                    data_root_hint=loaded.data_root_hint,
                    primary_param=loaded.primary_param,
                    unknown_keys=dict(loaded.unknown_keys),
                    placeholders=arriving,
                    results=loaded.results,
                    region_sets=loaded.region_sets,
                    region_classes=loaded.region_classes,
                    region_set_origins={
                        (str(path), group.id): group.id
                        for group in loaded.region_sets
                    },
                )
                return
            known = {img.id for img in previous.placeholders}
            # Same append-not-overwrite rule as placeholders: a merge load
            # must not drop the first project's recorded results, and
            # re-loading the same file twice must not double them.
            known_results = {rec.id for rec in previous.results}
            known_classes = {entry.id for entry in previous.region_classes}
            merged_sets, merged_origins = _merge_region_sets(
                previous.region_sets,
                loaded.region_sets,
                origins=previous.region_set_origins,
                source=str(path),
            )
            extra = list(previous.extra_roots)
            for root in (loaded.data_root_hint, str(Path(path).parent)):
                if root and root not in extra:
                    extra.append(root)
            self._state = replace(
                previous,
                placeholders=(
                    *previous.placeholders,
                    *(img for img in arriving if img.id not in known),
                ),
                results=(
                    *previous.results,
                    *(r for r in loaded.results if r.id not in known_results),
                ),
                region_sets=merged_sets,
                region_set_origins=merged_origins,
                region_classes=(
                    *previous.region_classes,
                    *(c for c in loaded.region_classes if c.id not in known_classes),
                ),
                extra_roots=tuple(extra),
            )

    def add_result(self, record: ResultRecord) -> None:
        """Append a captured result (1C). Server-carried like placeholders:
        the record survives every save from this moment on, whether or not
        the client ever mentions it. A duplicate id is refused HERE — ids
        key the member directories, and discovering a collision at the
        next save would poison every save after it."""
        with self._lock:
            if any(r.id == record.id for r in self._state.results):
                raise ValueError(f"duplicate result id: {record.id!r}")
            self._state = replace(self._state, results=(*self._state.results, record))

    def remove_result(self, result_id: str) -> bool:
        """Drop a record by id; returns whether anything was removed."""
        with self._lock:
            kept = tuple(r for r in self._state.results if r.id != result_id)
            removed = len(kept) != len(self._state.results)
            if removed:
                self._state = replace(self._state, results=kept)
        return removed

    def replace_regions(
        self,
        region_sets: tuple[RegionSet, ...],
        region_classes: tuple[RegionClass, ...],
    ) -> None:
        """Atomically replace the live region workspace.

        Region sets are server-carried project data, so the browser edits the
        session rather than echoing them through every save request. Validate
        the complete replacement before taking the lock: duplicate ids or
        unserializable structure must leave the previous workspace intact.
        """
        regions_to_manifest(region_sets, region_classes)
        with self._lock:
            kept_ids = {group.id for group in region_sets}
            self._state = replace(
                self._state,
                region_sets=region_sets,
                region_classes=region_classes,
                region_set_origins={
                    key: value
                    for key, value in self._state.region_set_origins.items()
                    if value in kept_ids
                },
            )

    def note_save(self, path: str | Path, mode: str, name: str | None) -> None:
        """Record where the project now lives, after a save.

        The project's own directory is one of the resolution roots, so a
        Save-As to a folder beside the data makes those images resolve on the
        next open with no re-point at all.
        """
        with self._lock:
            self._state = replace(
                self._state,
                path=str(path),
                payload_mode=mode,
                name=name if name is not None else self._state.name,
            )

    def placeholders(self) -> tuple[ProjectImage, ...]:
        return self.current().placeholders

    def search_order(self, extra: Path | None = None) -> tuple[Path, ...]:
        """Roots to try, in ADR 0002 §3 order with user re-points APPENDED.

        The hint and the project directory keep their precedence; every folder
        the user has picked follows, oldest first, with `extra` last. Appending
        rather than replacing is what lets a remounted drive take over again
        without the user having to undo a re-point.
        """
        state = self.current()
        roots = list(paths.search_roots(state.data_root_hint, state.project_dir))
        roots.extend(Path(root) for root in state.extra_roots)
        if extra is not None:
            roots.append(extra)
        return tuple(roots)

    def relocate(self, root: str | Path) -> Relocation:
        """Re-resolve every placeholder against `root` (plan #34).

        Raises FileNotFoundError / NotADirectoryError for a folder that is not
        one; everything else is reported, never raised — an image that stays
        unavailable can simply be pointed somewhere else next time.
        """
        chosen = Path(root).expanduser()
        if not chosen.exists():
            raise FileNotFoundError(f"folder not found: {chosen}")
        if not chosen.is_dir():
            raise NotADirectoryError(f"not a folder: {chosen}")

        order = self.search_order(chosen)
        resolved: list[ProjectImage] = []
        unresolved: list[ProjectImage] = []
        rejected: list[ProjectImage] = []
        mismatches: list[SizeMismatch] = []
        hash_mismatches: list[HashMismatch] = []
        for img in self.placeholders():
            outcome = resolving.resolve(img, order)
            if outcome.image is None:
                unresolved.append(img)
                if outcome.found is not None:
                    rejected.append(img)
                continue
            resolved.append(outcome.image)
            if outcome.size_bytes is not None and img.size_bytes is not None:
                mismatches.append(
                    SizeMismatch(
                        id=img.id,
                        name=img.name,
                        rel=img.rel or "",
                        expected_bytes=img.size_bytes,
                        actual_bytes=outcome.size_bytes,
                    )
                )
            # Distinct from the size check above: only ever populated for an
            # image that was actually hashed at save time (plan #38).
            if outcome.sha256 is not None and img.sha256 is not None:
                hash_mismatches.append(
                    HashMismatch(
                        id=img.id,
                        name=img.name,
                        rel=img.rel or "",
                        expected_sha256=img.sha256,
                        actual_sha256=outcome.sha256,
                    )
                )

        with self._lock:
            extra_roots = self._state.extra_roots
            # Only remember a folder that actually held something: an
            # accumulating list of wrong guesses would slow every later
            # resolution down for nothing.
            if resolved and str(chosen) not in extra_roots:
                extra_roots = (*extra_roots, str(chosen))
            self._state = replace(
                self._state,
                placeholders=tuple(unresolved),
                extra_roots=extra_roots,
            )
        return Relocation(
            root=str(chosen),
            resolved=tuple(resolved),
            still_unavailable=tuple(unresolved),
            mismatches=tuple(mismatches),
            hash_mismatches=tuple(hash_mismatches),
            rejected=tuple(rejected),
        )


#: Process-wide instance (one open project per running app), mirroring
#: `session.store`.
project = ProjectSession()


def _merge_region_sets(
    previous: tuple[RegionSet, ...],
    arriving: tuple[RegionSet, ...],
    *,
    origins: dict[tuple[str, str], str],
    source: str,
) -> tuple[tuple[RegionSet, ...], dict[tuple[str, str], str]]:
    """Append arriving sets, deduping only what is genuinely already here.

    Deduping by id alone — the rule images and results use — is wrong for
    region sets, because their ids are the USER's. Two projects both
    naming a set "grains" is ordinary, not a collision to resolve by
    dropping one: that would silently discard the second project's
    regions while appending its images, and the next save would make the
    loss permanent. So a genuine collision is KEPT under a free id.

    Renaming then creates its own trap, which is why `origins` exists. A
    set from `two.fvp` stored as `s1~2` no longer answers to `s1`, so a
    second append of `two.fvp` would look up `s1`, find the FIRST
    project's different set, and allocate `s1~3` — growing the session by
    another copy on every reload. Recording `(source, original id)` is
    what lets a file recognise the set it already contributed, whatever
    it ended up called.

    Value comparison still covers the other case: the same set arriving
    from a different path (a copy of the project) is skipped rather than
    renamed, since it is the same data under the same id. Both rules are
    needed and neither subsumes the other.
    """
    merged = list(previous)
    taken = {group.id for group in previous}
    by_id = {group.id: group for group in previous}
    updated = dict(origins)
    for group in arriving:
        key = (source, group.id)
        already = updated.get(key)
        if already is not None and already in taken:
            continue
        existing = by_id.get(group.id)
        if existing is not None and same_region_set(existing, group):
            updated[key] = group.id
            continue
        if existing is not None:
            group = replace(group, id=free_set_id(group.id, taken))
        taken.add(group.id)
        by_id[group.id] = group
        updated[key] = group.id
        merged.append(group)
    return tuple(merged), updated
