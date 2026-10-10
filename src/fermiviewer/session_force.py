"""Session store for opened force-curve files (io/force.py).

Force files are small and read whole, so unlike the 4D store nothing here
holds a file open or owns an upload directory.
"""

from __future__ import annotations

import itertools
import threading

from fermiviewer.io.force_common import ForceFile

__all__ = ["ForceStore", "UnknownForceError", "force_store"]


class UnknownForceError(KeyError):
    """No open force file with that id."""


class ForceStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, tuple[str, ForceFile]] = {}
        self._ids = itertools.count(1)

    def add(self, f: ForceFile, name: str) -> str:
        with self._lock:
            force_id = f"force{next(self._ids)}"
            self._files[force_id] = (name, f)
            return force_id

    def get(self, force_id: str) -> ForceFile:
        try:
            return self._files[force_id][1]
        except KeyError:
            raise UnknownForceError(force_id) from None

    def name(self, force_id: str) -> str:
        try:
            return self._files[force_id][0]
        except KeyError:
            raise UnknownForceError(force_id) from None

    def ids(self) -> list[str]:
        return list(self._files)

    def close(self, force_id: str) -> None:
        with self._lock:
            if self._files.pop(force_id, None) is None:
                raise UnknownForceError(force_id)

    def clear(self) -> None:
        with self._lock:
            self._files.clear()


force_store = ForceStore()
