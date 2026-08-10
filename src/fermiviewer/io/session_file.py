"""v1 workspace reader — READ-ONLY LEGACY (plan #21, retired by plan #32).

Format v1 was a JSON manifest beside an NPZ pixel sidecar: `<stem>.json`
holds names, kinds, axis calibrations, JSON-safe metadata and one opaque
`client_state` blob; `<stem>.npz` holds every image's raw array (original
dtype) keyed by image id.

**Nothing writes this format any more.** ADR 0002 supersedes it with the
single-file, schema-validated `.fvp` v2 container (`io/project_file.py`), and
the writer — with its manifest-last commit ordering, which existed only
because two files had to agree — was deleted when v2's `save_project` took
over. What remains here is the reader, kept so existing v1 workspaces still
open: `io/project_v1.py` upgrades one in memory and the next save writes a
`.fvp`.

Pure file I/O on plain structures (no session-store / FastAPI imports). The
pairing tag is the one v1 integrity check worth keeping: a manifest whose
`generation` disagrees with its sidecar's is a pair that was separated in
transfer, which is exactly the failure v2's single container retires.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

__all__ = ["GENERATION_KEY", "V1_VERSION", "load_session"]

#: The only version this reader accepts, and the NPZ key pairing a sidecar
#: with its manifest. Public because the v1 test fixture writer must use the
#: reader's own constants rather than transcribing them — a generator with a
#: private copy of the contract drifts silently.
V1_VERSION = 1
GENERATION_KEY = "__fv_generation__"


def _paths(path: str | Path) -> tuple[Path, Path]:
    """The pair for a path, whichever half of it was named."""
    p = Path(path)
    if p.suffix.lower() != ".json":
        p = p.with_suffix(".json")
    return p, p.with_suffix(".npz")


def load_session(
    path: str | Path,
) -> tuple[list[tuple[str, str, DataStruct]], dict[str, Any] | None]:
    """Read a v1 session back; returns (entries, client_state)."""
    json_path, npz_path = _paths(path)
    if not json_path.is_file():
        raise FileNotFoundError(f"session manifest not found: {json_path}")
    if not npz_path.is_file():
        raise FileNotFoundError(f"session data sidecar not found: {npz_path}")

    manifest = json.loads(json_path.read_text(encoding="utf-8"))
    version = manifest.get("version")
    if version != V1_VERSION:
        raise ValueError(f"unsupported session version: {version!r}")

    entries: list[tuple[str, str, DataStruct]] = []
    with np.load(npz_path) as arrays:
        manifest_generation = manifest.get("generation")
        sidecar_generation = (
            str(np.asarray(arrays[GENERATION_KEY]).item())
            if GENERATION_KEY in arrays
            else None
        )
        if manifest_generation is not None or sidecar_generation is not None:
            if manifest_generation != sidecar_generation:
                raise ValueError("session manifest and data sidecar do not match")
        for img in manifest["images"]:
            img_id = img["id"]
            if img_id not in arrays:
                raise ValueError(f"sidecar missing pixels for image {img_id}")
            axes = tuple(
                AxisCal(scale=ax["scale"], origin=ax["origin"], units=ax["units"])
                for ax in img["axes"]
            )
            ds = DataStruct(
                data=np.ascontiguousarray(arrays[img_id]),
                kind=DataKind(img["kind"]),
                axes=axes,
                metadata=dict(img.get("metadata") or {}),
            )
            entries.append((img_id, img["name"], ds))

    return entries, manifest.get("client_state")
