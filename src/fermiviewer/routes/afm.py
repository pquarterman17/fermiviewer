"""AFM/SPM channel access: open a scan's other channels.

Opening a multi-channel SPM file (Bruker NanoScope, Gwyddion, Asylum
.ibw, JPK, WSxM — see io/spm_channels.py) shows its height channel; the
rest (phase, amplitude, PeakForce modulus/adhesion, …) are opened on request as separate
images named "<file> · <channel (direction)>", so the session is not
flooded with eight images per file. A disk-opened image re-reads its file;
a browser upload has no file left on disk, so its channels are kept in
memory at upload time (``stash_upload_channels``). A scan and its opened
channels form one family, so Open Other Channels works from any of them and
reopens a channel that was closed; the family (and any cached upload) is
dropped when its last image closes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.spm_channels import SPM_PARSERS, load_spm_channels
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

__all__ = ["forget", "reset", "router", "stash_upload_channels"]

router = APIRouter(prefix="/api/afm")


class ChannelInfo(BaseModel):
    """One channel in a multi-channel SPM scan."""

    label: str
    image_id: str | None = None


class OpenChannelsRequest(BaseModel):
    """An omitted label list preserves the legacy open-everything action."""

    labels: list[str] | None = None


@dataclass
class _Family:
    """One scan's channels: where to read them from, and which image
    currently shows each (label → image id)."""

    source: list[DataStruct] | str          # cached upload channels, or a file path
    members: dict[str, str] = field(default_factory=dict)
    # Inventory GETs only need labels. Cache them separately so selecting
    # among channels of a large disk scan does not decode every array again.
    labels: list[str] | None = None
    # held for a whole open (read + register): two overlapping requests —
    # a double-click, or two siblings — must not both see a label as
    # missing and each register it
    opening: threading.Lock = field(default_factory=threading.Lock)


_lock = threading.Lock()
_families: dict[str, _Family] = {}           # family key → family
_member_of: dict[str, str] = {}              # image id → family key
_generation = 0                              # bumped by reset()


def _label(ds: DataStruct) -> str:
    md = ds.metadata
    return str(md.get("channel_label") or md.get("channel") or "channel")


def _join(img_id: str, source: list[DataStruct] | str) -> None:
    """Start a family rooted at `img_id` (caller holds the lock)."""
    labels = [_label(ch) for ch in source] if isinstance(source, list) else None
    _families[img_id] = _Family(
        source, {_label(store.get(img_id)): img_id}, labels=labels,
    )
    _member_of[img_id] = img_id


def stash_upload_channels(img_id: str, staged: Path) -> None:
    """Keep an uploaded SPM file's channels for a later open — the
    staged file is deleted when the upload request ends."""
    try:
        channels = load_spm_channels(staged)
    except (ValueError, OSError):
        return
    if len(channels) > 1:
        with _lock:
            _join(img_id, channels)


def _family(img_id: str) -> tuple[str, _Family]:
    """The family `img_id` belongs to, creating one for a disk-opened scan."""
    with _lock:
        key = _member_of.get(img_id)
        if key is not None and key in _families:
            return key, _families[key]
        _member_of.pop(img_id, None)                 # stale: its family is gone
        path = store.source_path(img_id)
        if path is None:
            raise HTTPException(
                422, "this image has no file to read other channels from "
                     "(derived or restored image) — reopen the scan file")
        _join(img_id, path)
        return img_id, _families[img_id]


def _read(source: list[DataStruct] | str) -> list[DataStruct]:
    if not isinstance(source, str):
        return source
    try:
        return load_spm_channels(source)
    except ValueError as e:
        raise HTTPException(422, f"not a multi-channel AFM scan: {e}") from None
    except OSError as e:
        raise HTTPException(404, f"cannot read {Path(source).name}: {e}") from None


def _require_spm(image_id: str) -> DataStruct:
    try:
        src = store.get(image_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {image_id}") from None
    if src.metadata.get("parser") not in SPM_PARSERS:
        raise HTTPException(422, "only AFM/SPM scans have extra channels")
    return src


@router.get("/{image_id}/channels")
def list_channels(image_id: str) -> list[ChannelInfo]:
    """List a scan's channels without registering closed channels.

    ``image_id`` identifies an already-open member when a channel is open,
    allowing the client selector to navigate without creating duplicates.
    """
    _require_spm(image_id)
    _, fam = _family(image_id)
    with fam.opening:
        if fam.labels is None:
            fam.labels = [_label(ch) for ch in _read(fam.source)]
        live = set(store.ids())
        return [
            ChannelInfo(
                label=label,
                image_id=(iid if (iid := fam.members.get(label)) in live else None),
            )
            for label in fam.labels
        ]


@router.post("/{image_id}/channels")
def open_other_channels(
    image_id: str, request: OpenChannelsRequest | None = None,
) -> list[ImageMeta]:
    """Register every channel of the scan that is not open right now — from
    the scan or any of its channels; a closed channel can be reopened.
    Returns their metas (empty when all are already open)."""
    _require_spm(image_id)
    with _lock:
        generation = _generation
    key, fam = _family(image_id)
    base = Path(store.name(image_id)).name.split(" · ")[0]   # a child is "<file> · <label>"
    metas = []
    with fam.opening:
        channels = _read(fam.source)
        if fam.labels is None:
            fam.labels = [_label(ch) for ch in channels]
        available = {_label(ch) for ch in channels}
        requested = None if request is None else request.labels
        if requested is not None:
            missing = set(requested) - available
            if missing:
                names = ", ".join(sorted(missing))
                raise HTTPException(422, f"unknown channel label: {names}")
            wanted = set(requested)
            channels = [ch for ch in channels if _label(ch) in wanted]
        # The read ran outside _lock, so the family may have changed under
        # it: its last member closed (forget dropped it) or the session was
        # replaced (reset). Check and register in one critical section.
        with _lock:
            if _generation != generation or _families.get(key, fam) is not fam:
                raise HTTPException(409, "the session changed while the channels "
                                         "were being read — try again")
            _families[key] = fam                     # reattach if forget dropped it
            live = set(store.ids())
            for ch in channels:
                if fam.members.get(_label(ch)) in live:
                    continue
                new_id = store.add_parsed(ch, f"{base} · {_label(ch)}")
                fam.members[_label(ch)] = new_id
                _member_of[new_id] = key
                metas.append(ImageMeta.from_datastruct(new_id, store.name(new_id), ch))
    return metas


def forget(img_id: str) -> None:
    """A closed image leaves its family; the family goes with its last member."""
    with _lock:
        key = _member_of.pop(img_id, None)
        if key is None or key not in _families:
            return
        fam = _families[key]
        for lab in [lab for lab, iid in fam.members.items() if iid == img_id]:
            del fam.members[lab]
        if not fam.members:
            del _families[key]


def reset() -> None:
    """Drop every family (the session store was cleared, e.g. a project
    replaced it — restored images keep their ids, so stale entries must go).
    An open already reading channels sees the new generation and aborts."""
    global _generation
    with _lock:
        _generation += 1
        _families.clear()
        _member_of.clear()
