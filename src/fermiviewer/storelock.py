"""Cross-process lock for the JSON stores under the user config dir.

Each store (`io/calibration_db`, `io/profiles_db`, `workspaces`) already
serialises its read/modify/write transactions with a `threading.RLock`,
which is enough for FastAPI's threadpool but stops at the process
boundary. Two FermiViewer servers can share one `~/.fermiviewer/`: the
launcher only adopts a running sibling when `/api/health` answers within
its probe window (`server._await_health`, 0.5 s for the browser CLI), so a
sibling that has bound the port but is still importing numpy reads as
"another app" and the second launch floats to the next free port
(`server.py`) instead of reusing it. Both processes then hold their own
`RLock` and neither sees the other, so a concurrent create/update is a
lost update: both load the same JSON, both write their own copy back, and
the second `os.replace` wins whole.

`StoreLock` closes that. It is a drop-in for `threading.RLock` — same
`with` protocol, still re-entrant per thread — that additionally takes an
OS advisory lock on a sibling `<store>.lock` file for the duration of the
outermost `with`. `flock` on POSIX, `msvcrt.locking` on Windows; the
temp-file-then-`os.replace` write each store already does keeps the store
itself readable at every instant, so a reader that predates this lock
still never sees a half-written file.

Deliberately advisory and best-effort:

* The lock file path is resolved on each acquisition, never cached, so the
  env overrides the stores honour (`FV_CALIB_PATH`, `FV_PROFILES_PATH`,
  `FV_CONFIG_DIR`) keep working — including a test that repoints them
  between transactions.
* A config dir that cannot hold a lock file (read-only home, an exotic
  filesystem with no `flock`) degrades to the thread lock alone rather
  than failing the request. That is the behaviour we already had.
* Waiting is bounded (`_TIMEOUT`). A wedged process must not hang the UI
  forever, so after the timeout we proceed unlocked — back to the old
  race, not to a deadlock.

Lock ordering: `profiles_db.import_legacy_calibrations` is the only
transaction that nests, and it takes profiles → calibrations. Nothing
takes them the other way (`calibration_db` cannot import `profiles_db`
without a cycle), and the workspace index is never held with either, so
there is no ordering under which two processes can deadlock.
"""

from __future__ import annotations

import errno
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType

__all__ = ["StoreLock"]

_log = logging.getLogger(__name__)

#: give up waiting for a peer after this long and proceed thread-locked
#: only — a stuck sibling degrades us to the pre-lock race, never to a
#: hung request
_TIMEOUT = 10.0

#: poll interval while a peer holds the file lock
_POLL = 0.02


class _UnsupportedError(Exception):
    """This filesystem has no usable advisory locking."""


#: errnos that mean "a peer holds the lock, try again" rather than "this
#: filesystem cannot lock". Everything else (ENOLCK, EOPNOTSUPP, EINVAL on
#: some network mounts) means there is nothing to wait for, so we degrade
#: immediately instead of spinning out the full timeout on every write.
_CONTENDED = frozenset({errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK})


def _lock_exclusive(fd: int) -> bool:
    """Try once to take an exclusive OS lock on ``fd``. True on success,
    False if a peer holds it; raises `_UnsupportedError` if this filesystem
    cannot lock at all (the caller then runs thread-locked)."""
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            # EACCES is Windows' "locked by someone else"; anything else
            # (a filesystem that cannot lock) is not worth waiting on
            if exc.errno in _CONTENDED:
                return False
            raise _UnsupportedError(str(exc)) from exc
        return True

    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in _CONTENDED:
            return False
        raise _UnsupportedError(str(exc)) from exc
    return True


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return

    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


class StoreLock:
    """Re-entrant lock guarding one JSON store across threads *and*
    processes.

    ``path`` is a callable returning the store file; the lock file is its
    sibling ``<name>.lock``. It is a callable rather than a `Path` because
    every store resolves its own location lazily from the environment.
    """

    def __init__(self, path: Callable[[], Path]) -> None:
        self._path = path
        self._thread = threading.RLock()
        self._depth = 0
        self._fd: int | None = None

    def _lock_path(self) -> Path:
        p = self._path()
        return p.with_name(f"{p.name}.lock")

    def _acquire_file(self) -> None:
        """Take the OS lock for the outermost `with`. Any failure leaves
        ``self._fd`` None, i.e. thread-locked only."""
        try:
            lock_path = self._lock_path()
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
            fd = os.open(lock_path, flags, 0o644)
        except OSError as exc:  # read-only config dir, bad path, …
            _log.debug("store lock unavailable (%s); thread lock only", exc)
            return
        try:
            # `msvcrt.locking` locks a byte RANGE from the current offset,
            # so the file must have a byte to lock; `flock` does not care.
            # Racing writers both put the same \0 at offset 0, so there is
            # nothing to lose. Best-effort: a failure here only costs us
            # the file lock, which the code below already tolerates.
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
        except OSError as exc:
            # Separate from the open above so the descriptor is always
            # closed. A full lock filesystem is exactly the case this
            # degrades for, and _acquire_file runs once per store
            # transaction -- leaking one fd each time would exhaust the
            # process's handles while it looked like a clean fallback.
            _log.debug("store lock unusable (%s); thread lock only", exc)
            os.close(fd)
            return
        deadline = time.monotonic() + _TIMEOUT
        while True:
            try:
                if _lock_exclusive(fd):
                    self._fd = fd
                    return
            except _UnsupportedError as exc:
                _log.debug("file locking unsupported (%s); thread lock only", exc)
                os.close(fd)
                return
            if time.monotonic() >= deadline:
                _log.warning(
                    "timed out after %.0fs waiting for another FermiViewer to "
                    "release %s; proceeding without the cross-process lock",
                    _TIMEOUT,
                    self._lock_path(),
                )
                os.close(fd)
                return
            time.sleep(_POLL)

    def _release_file(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        _unlock(fd)
        try:
            os.close(fd)
        except OSError:
            pass

    def __enter__(self) -> StoreLock:
        self._thread.acquire()
        # mutated only under the thread lock, so the depth count is safe
        self._depth += 1
        if self._depth == 1:
            try:
                self._acquire_file()
            except BaseException:
                self._depth -= 1
                self._thread.release()
                raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._depth -= 1
        if self._depth == 0:
            self._release_file()
        self._thread.release()
