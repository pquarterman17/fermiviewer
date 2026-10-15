"""Session store for opened force-curve files (io/force.py).

Force files are small and read whole, so unlike the 4D store nothing here
holds a file open or owns an upload directory.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable
from typing import TypeVar

from fermiviewer.io.force_common import ForceFile

__all__ = ["ForceStore", "UnknownForceError", "force_store"]

T = TypeVar("T")


class UnknownForceError(KeyError):
    """No open force file with that id."""


class ForceStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, tuple[str, ForceFile]] = {}
        self._ids = itertools.count(1)
        self._generation = 0

    def add(self, f: ForceFile, name: str) -> str:
        with self._lock:
            force_id = f"force{next(self._ids)}"
            self._files[force_id] = (name, f)
            return force_id

    def get(self, force_id: str) -> ForceFile:
        with self._lock:
            try:
                return self._files[force_id][1]
            except KeyError:
                raise UnknownForceError(force_id) from None

    def name(self, force_id: str) -> str:
        with self._lock:
            try:
                return self._files[force_id][0]
            except KeyError:
                raise UnknownForceError(force_id) from None

    def entry(self, force_id: str) -> tuple[ForceFile, str, int]:
        """File, name and replacement generation captured atomically."""
        with self._lock:
            try:
                name, force_file = self._files[force_id]
            except KeyError:
                raise UnknownForceError(force_id) from None
            return force_file, name, self._generation

    def entries(self) -> list[tuple[str, str, ForceFile]]:
        """A consistent snapshot for the list endpoint."""
        with self._lock:
            return [
                (force_id, name, force_file)
                for force_id, (name, force_file) in self._files.items()
            ]

    def if_generation(self, generation: int, action: Callable[[], T]) -> tuple[bool, T | None]:
        """Run a short commit action unless the force session was replaced.

        The lock makes the check and commit indivisible with ``clear``. A
        normal close deliberately does not change the generation: analyses
        already holding that file are allowed to finish.
        """
        with self._lock:
            if generation != self._generation:
                return False, None
            return True, action()

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._files)

    def close(self, force_id: str) -> None:
        with self._lock:
            if self._files.pop(force_id, None) is None:
                raise UnknownForceError(force_id)

    def clear(self) -> None:
        with self._lock:
            self._files.clear()
            self._generation += 1


force_store = ForceStore()
