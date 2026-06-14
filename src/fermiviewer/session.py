"""Session store — decoded DataStructs held server-side, keyed by id.

The handoff's session model: /session/open decodes files once; every
later request references images by id. Derived images (FFT, filter
results) register here too, with lineage recorded in their metadata.

No FastAPI/Pydantic here — routes adapt. Thread-safe for the single-
process uvicorn deployment (Tauri sidecar / `uv run fv`).
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.registry import load_auto

__all__ = ["SessionStore", "UnknownImageError", "store"]


class UnknownImageError(KeyError):
    pass


class SessionStore:
    def __init__(self) -> None:
        self._images: dict[str, DataStruct] = {}
        self._names: dict[str, str] = {}
        # full on-disk source path, for images opened from disk (used by the
        # user-metadata sidecar); absent for uploads / derived images
        self._paths: dict[str, str] = {}
        self._lock = threading.Lock()

    def open_paths(self, paths: list[str]) -> list[tuple[str, DataStruct]]:
        """Decode files and register them. Returns (id, data) pairs.

        Raises on the FIRST failing file — callers decide whether to
        pre-validate. Files that parsed before the failure are not
        registered (all-or-nothing per call).
        """
        decoded = [(Path(p), load_auto(p)) for p in paths]
        out = []
        with self._lock:
            for path, ds in decoded:
                img_id = uuid.uuid4().hex[:12]
                self._images[img_id] = ds
                self._names[img_id] = path.name
                self._paths[img_id] = str(path)
                out.append((img_id, ds))
        return out

    def add_parsed(self, ds: DataStruct, name: str) -> str:
        """Register an already-decoded DataStruct (e.g. browser upload)."""
        img_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._images[img_id] = ds
            self._names[img_id] = name
        return img_id

    def add_derived(self, ds: DataStruct, name: str, parent_id: str) -> str:
        """Register a computed image (FFT/filter result) with lineage."""
        img_id = uuid.uuid4().hex[:12]
        ds.metadata["derived_from"] = parent_id
        with self._lock:
            self._images[img_id] = ds
            self._names[img_id] = name
        return img_id

    def restore(self, img_id: str, ds: DataStruct, name: str) -> str:
        """Re-register a persisted image, preserving its saved id so
        client-side state keyed by id (views, measures) survives the
        round-trip. On collision a fresh id is generated."""
        with self._lock:
            if img_id in self._images:
                img_id = uuid.uuid4().hex[:12]
            self._images[img_id] = ds
            self._names[img_id] = name
        return img_id

    def replace(self, img_id: str, ds: DataStruct) -> None:
        """Swap an image's DataStruct in place (e.g. recalibration)."""
        with self._lock:
            if img_id not in self._images:
                raise UnknownImageError(img_id)
            self._images[img_id] = ds

    def get(self, img_id: str) -> DataStruct:
        try:
            return self._images[img_id]
        except KeyError:
            raise UnknownImageError(img_id) from None

    def name(self, img_id: str) -> str:
        return self._names.get(img_id, img_id)

    def source_path(self, img_id: str) -> str | None:
        """On-disk path for a disk-opened image, else None (uploads/derived)."""
        return self._paths.get(img_id)

    def rename(self, img_id: str, name: str) -> None:
        with self._lock:
            if img_id not in self._images:
                raise UnknownImageError(img_id)
            self._names[img_id] = name

    def ids(self) -> list[str]:
        return list(self._images)

    def close(self, img_id: str) -> None:
        with self._lock:
            self._images.pop(img_id, None)
            self._names.pop(img_id, None)
            self._paths.pop(img_id, None)

    def clear(self) -> None:
        with self._lock:
            self._images.clear()
            self._names.clear()
            self._paths.clear()


store = SessionStore()
"""Process-wide default store (one desktop session per server process)."""
