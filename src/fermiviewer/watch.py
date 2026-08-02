"""Directory poller — auto-run a saved recipe on new files (Scripting #7).

``FolderWatcher`` polls a directory with ``os.scandir`` and hands each new,
*stable* file to an injected ``on_file`` callback. A file is debounced: its
``(mtime_ns, size)`` fingerprint must be identical across two *consecutive*
polls before it fires — a file mid-copy keeps changing size (and usually
mtime), so it is simply re-checked next poll instead of being read half-
written. Once a path has fired (or been rejected as not-openable) it is
remembered in ``_processed`` and never reconsidered, so a watcher can poll
indefinitely without redoing work.

PURITY: this module is stdlib + the pure ``io`` layer only (never fastapi/
pydantic/routes/session — enforced for io/calc/ops by
``tests/test_repo_integrity.py``; this module holds itself to the same bar
even though it lives outside those directories). It knows nothing about the
session store, the job queue, or HTTP: the route layer (``routes/watch.py``)
supplies ``on_file`` (load → register → submit a recipe job) and may
override ``is_openable`` (defaults to the io registry's extension map via
``default_is_openable``).

THREADING: a single daemon thread runs the poll loop. ``stop()`` is
synchronous — it signals the loop and ``Thread.join()``s it, so callers
(including the FastAPI lifespan hook in server.py, NEVER atexit — see
jobs.py's shutdown for why that distinction matters) never leave a dangling
thread behind. ``poll_once()`` is exposed publicly so the debounce logic can
be unit-tested deterministically (by interleaving writes and poll calls)
without sleeping through real poll intervals; only call it directly when the
watcher's own thread is not running (started via :meth:`start`), since
``_candidates``/``_processed`` are not lock-protected against concurrent
scanning.

AUTO-SHUTDOWN INTERACTION: this module has no opinion on it — the decision
("an active watch holds the desktop session open") and its wiring live in
``routes/watch.py`` (``is_watch_active``) and ``server.py`` (the grace-check
docstring there explains the reasoning).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fermiviewer.io.registry import supported_extensions

__all__ = ["FolderWatcher", "default_is_openable"]


def default_is_openable(path: Path) -> bool:
    """Suffix-only openability check against the io registry's extension
    map. Content-sniffed formats (e.g. Nanoscope's numeric extensions,
    routed by ``io.registry.load_auto`` on magic bytes rather than suffix)
    are NOT detected here — inject a custom ``is_openable`` for those."""
    return path.suffix.lower() in supported_extensions()


class FolderWatcher:
    """Polls ``directory`` for new, stable, openable files and fires
    ``on_file(path)`` exactly once per path."""

    def __init__(
        self,
        directory: Path,
        on_file: Callable[[Path], None],
        is_openable: Callable[[Path], bool] = default_is_openable,
        interval: float = 1.0,
    ) -> None:
        self.directory = Path(directory)
        self.interval = interval
        self._on_file = on_file
        self._is_openable = is_openable
        # path -> (mtime_ns, size) fingerprint recorded on the PREVIOUS poll;
        # a match on the next poll is what "stable" means.
        self._candidates: dict[str, tuple[int, int]] = {}
        self._processed: set[str] = set()
        self._seen = 0
        self._handled = 0
        self._errors = 0
        self._last_error: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the poll thread. Idempotent: a second start() on an
        already-running watcher is a no-op (call stop() first to restart)."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        thread = threading.Thread(target=self._run, name="fv-watch", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the poll loop to exit and join it. Safe to call repeatedly
        or when never started — never leaves a thread dangling."""
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "dir": str(self.directory),
                "seen": self._seen,
                "processed": self._handled,
                "errors": self._errors,
                "last_error": self._last_error,
            }

    def poll_once(self) -> None:
        """Scan the directory once. See the class/module docstrings for the
        debounce contract and the concurrency caveat with the poll thread."""
        try:
            entries = list(os.scandir(self.directory))
        except OSError as exc:
            with self._lock:
                self._last_error = str(exc)
            return
        # A candidate whose path no longer shows up in this scan (deleted,
        # renamed, or replaced mid-copy before it ever went stable) would
        # otherwise sit in _candidates forever — unlike _processed, which is
        # deliberately unbounded for the life of the watch (a path that DID
        # fire must never be reconsidered), a never-stabilized file has no
        # reason to be remembered once it's gone. Bounds _candidates to the
        # files actually present in any one poll, for a watch that runs
        # indefinitely over a directory that sees a lot of aborted/renamed
        # writes (editor swap files, failed transfers, ...).
        current = {entry.path for entry in entries if entry.is_file()}
        for stale in self._candidates.keys() - current:
            del self._candidates[stale]
        for entry in entries:
            self._consider(entry)

    def _consider(self, entry: os.DirEntry[str]) -> None:
        if not entry.is_file():
            return
        key = entry.path
        if key in self._processed:
            return
        try:
            stat = entry.stat()
        except OSError:
            return  # vanished between scandir and stat — reconsidered next poll
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        if self._candidates.get(key) != fingerprint:
            self._candidates[key] = fingerprint
            return  # not yet stable across two consecutive polls
        del self._candidates[key]
        self._processed.add(key)
        with self._lock:
            self._seen += 1
        path = Path(key)
        if not self._is_openable(path):
            return
        try:
            self._on_file(path)
        except Exception as exc:  # noqa: BLE001 — surfaced via status(), never kills the loop
            with self._lock:
                # last_error alone is a single overwritten string — a burst
                # of failures (e.g. hundreds of files landing at once and
                # tripping the shared job queue's admission bound) would
                # otherwise show only its most recent message, silently
                # losing the count of everything before it. errors is the
                # cumulative counter status() exposes for that.
                self._errors += 1
                self._last_error = f"{path.name}: {exc}"
            return
        with self._lock:
            self._handled += 1

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(self.interval)
