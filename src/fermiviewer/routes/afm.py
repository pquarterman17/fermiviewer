"""AFM/SPM channel access: open a scan's other channels.

Opening a Bruker NanoScope file shows its Height channel; the rest (phase,
amplitude, PeakForce modulus/adhesion, …) are opened on request as separate
images named "<file> · <channel (direction)>", so the session is not
flooded with eight images per file. A disk-opened image re-reads its file;
a browser upload has no file left on disk, so its channels are kept in
memory at upload time (``stash_upload_channels``) until used or closed.
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.nanoscope import NanoscopeError, load_nanoscope_all
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

__all__ = ["router", "stash_upload_channels"]

router = APIRouter(prefix="/api/afm")

_lock = threading.Lock()
_uploads: dict[str, list[DataStruct]] = {}       # image id → all channels
_opened: dict[str, set[str]] = {}                # image id → labels opened


def _label(ds: DataStruct) -> str:
    md = ds.metadata
    return str(md.get("channel_label") or md.get("channel") or "channel")


def stash_upload_channels(img_id: str, staged: Path) -> None:
    """Keep an uploaded NanoScope file's channels for a later open."""
    try:
        channels = load_nanoscope_all(staged)
    except (NanoscopeError, OSError):
        return
    if len(channels) > 1:
        with _lock:
            _uploads[img_id] = channels


def _channels_for(img_id: str) -> list[DataStruct]:
    with _lock:
        if img_id in _uploads:
            return _uploads[img_id]
    path = store.source_path(img_id)
    if path is None:
        raise HTTPException(
            422, "this image has no file to read other channels from "
                 "(derived or restored image) — reopen the scan file")
    try:
        return load_nanoscope_all(path)
    except NanoscopeError as e:
        raise HTTPException(422, f"not a multi-channel AFM scan: {e}") from None
    except OSError as e:
        raise HTTPException(404, f"cannot read {Path(path).name}: {e}") from None


@router.post("/{image_id}/channels")
def open_other_channels(image_id: str) -> list[ImageMeta]:
    """Register every channel of the scan not yet open; returns their metas
    (an empty list when all are already open)."""
    try:
        src = store.get(image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {image_id}") from None
    if src.metadata.get("parser") != "nanoscope":
        raise HTTPException(422, "only Bruker NanoScope scans have extra channels")
    channels = _channels_for(image_id)
    base = Path(store.name(image_id)).name
    with _lock:
        seen = _opened.setdefault(image_id, {_label(src)})
        todo = [c for c in channels if _label(c) not in seen]
        seen.update(_label(c) for c in todo)
    metas = []
    for ch in todo:
        new_id = store.add_parsed(ch, f"{base} · {_label(ch)}")
        metas.append(ImageMeta.from_datastruct(new_id, store.name(new_id), ch))
    return metas


def forget(img_id: str) -> None:
    """Drop cached channels for a closed image."""
    with _lock:
        _uploads.pop(img_id, None)
        _opened.pop(img_id, None)
