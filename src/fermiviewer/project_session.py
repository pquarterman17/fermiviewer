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

__all__ = ["OpenProject", "ProjectSession", "Relocation", "SizeMismatch", "project"]


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
class Relocation:
    """The outcome of one "Locate folder…"."""

    root: str
    resolved: tuple[ProjectImage, ...] = ()
    still_unavailable: tuple[ProjectImage, ...] = ()
    mismatches: tuple[SizeMismatch, ...] = ()
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

    def adopt(
        self, loaded: LoadedProject, path: str | Path, *, merge: bool = False
    ) -> None:
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
                )
                return
            known = {img.id for img in previous.placeholders}
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
                extra_roots=tuple(extra),
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
            rejected=tuple(rejected),
        )


#: Process-wide instance (one open project per running app), mirroring
#: `session.store`.
project = ProjectSession()
