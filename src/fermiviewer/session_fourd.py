"""4D-STEM session store — lazy FourDDataset handles held server-side.

Mirrors `fermiviewer.session.SessionStore`'s shape (register/get/name/list/
close), but keyed in its OWN id namespace ("4d-<n>") so a 2D-image route
can never be handed a 4D id by accident, and vice versa — the two stores
are never merged. No FastAPI/Pydantic here — routes/fourd.py adapts.
Thread-safe for the single-process uvicorn deployment (Tauri sidecar /
`uv run fv`), matching session.py.
"""

from __future__ import annotations

import itertools
import shutil
import tempfile
import threading
import time
from pathlib import Path

from fermiviewer.calc.fourd.dataset import FourDDataset

__all__ = [
    "UPLOAD_DIR_PREFIX", "FourDStore", "UnknownFourDError", "fourd_store",
    "sweep_stale_upload_dirs",
]

#: temp-dir prefix for browser-uploaded 4D files. The 4D loaders read
#: lazily, so an upload must outlive its request; the store owns the dir
#: and deletes it when the dataset is closed.
UPLOAD_DIR_PREFIX = "fv_upload4d_"


class UnknownFourDError(KeyError):
    pass


class FourDStore:
    def __init__(self) -> None:
        self._datasets: dict[str, FourDDataset] = {}
        self._names: dict[str, str] = {}
        self._paths: dict[str, str] = {}
        # fourd_id -> id of the derived nav image registered in the NORMAL
        # image store (routes/fourd.py's /nav endpoint), so repeat calls
        # don't re-register a fresh derived image every time.
        self._nav_ids: dict[str, str] = {}
        # fourd_id -> temp dir the store owns (uploads), removed on close
        self._owned_dirs: dict[str, Path] = {}
        self._counter = itertools.count(1)
        self._lock = threading.Lock()

    def add(
        self, ds: FourDDataset, name: str, source_path: str | Path | None = None,
        owned_dir: Path | None = None,
    ) -> str:
        """Register `ds`. `owned_dir` (an upload's temp dir) is deleted when
        the dataset is closed, after its file handles are released."""
        with self._lock:
            fourd_id = f"4d-{next(self._counter)}"
            self._datasets[fourd_id] = ds
            self._names[fourd_id] = name
            if source_path is not None:
                self._paths[fourd_id] = str(source_path)
            if owned_dir is not None:
                self._owned_dirs[fourd_id] = owned_dir
        return fourd_id

    def replace(self, fourd_id: str, ds: FourDDataset) -> None:
        """Swap a dataset's handle in place, keeping its id, name and path.

        Used by `/fourd/{id}/reshape`, which re-opens a headerless Merlin file
        under a different raster. Keeping the id is the point: the workshop's
        selection, the probe position and the registered nav image are all
        keyed by it, and a fresh id would silently deselect the dataset the
        user is looking at. The OLD dataset is closed here, releasing its
        memmap — a reshape that leaked one per attempt would make the feature
        unusable exactly for the large files it exists for.
        """
        with self._lock:
            if fourd_id not in self._datasets:
                raise UnknownFourDError(fourd_id)
            previous = self._datasets[fourd_id]
            self._datasets[fourd_id] = ds
            # The nav image was rastered at the OLD scan shape, so it no
            # longer describes this dataset; drop the association and let the
            # next /nav call register a fresh one.
            self._nav_ids.pop(fourd_id, None)
        previous.close()

    def get(self, fourd_id: str) -> FourDDataset:
        try:
            return self._datasets[fourd_id]
        except KeyError:
            raise UnknownFourDError(fourd_id) from None

    def name(self, fourd_id: str) -> str:
        return self._names.get(fourd_id, fourd_id)

    def source_path(self, fourd_id: str) -> str | None:
        return self._paths.get(fourd_id)

    def ids(self) -> list[str]:
        return list(self._datasets)

    def nav_image_id(self, fourd_id: str) -> str | None:
        return self._nav_ids.get(fourd_id)

    def set_nav_image_id(self, fourd_id: str, img_id: str) -> None:
        with self._lock:
            self._nav_ids[fourd_id] = img_id

    def close(self, fourd_id: str) -> None:
        with self._lock:
            ds = self._datasets.pop(fourd_id, None)
            self._names.pop(fourd_id, None)
            self._paths.pop(fourd_id, None)
            self._nav_ids.pop(fourd_id, None)
            owned = self._owned_dirs.pop(fourd_id, None)
        if ds is not None:
            ds.close()
        if owned is not None:
            shutil.rmtree(owned, ignore_errors=True)

    def clear(self) -> None:
        with self._lock:
            datasets = list(self._datasets.values())
            owned = list(self._owned_dirs.values())
            self._datasets.clear()
            self._names.clear()
            self._paths.clear()
            self._nav_ids.clear()
            self._owned_dirs.clear()
        for ds in datasets:
            ds.close()
        for d in owned:
            shutil.rmtree(d, ignore_errors=True)

    def close_uploads(self) -> None:
        """Close every dataset opened from an upload (server shutdown), so
        no upload copy outlives the session."""
        for fourd_id in list(self._owned_dirs):
            self.close(fourd_id)


def sweep_stale_upload_dirs(max_age_s: float = 24 * 3600) -> int:
    """Delete upload dirs left by a session that crashed or was killed
    before shutdown. Only dirs untouched for `max_age_s` go, so a second
    running instance never loses the uploads it is still reading."""
    cutoff = time.time() - max_age_s
    removed = 0
    for d in Path(tempfile.gettempdir()).glob(f"{UPLOAD_DIR_PREFIX}*"):
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


fourd_store = FourDStore()
"""Process-wide default store (mirrors fermiviewer.session.store)."""
