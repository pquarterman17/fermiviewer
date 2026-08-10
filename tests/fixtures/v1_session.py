"""Minimal v1 workspace writer — the format FermiViewer no longer writes.

`io/session_file.py` is read-only legacy since plan item 32: v2 `.fvp` is the
only write path, so a v1 pair can no longer be produced by the application.
Tests still need one, both to prove the migration is lossless and to keep the
v1 *reader* covered, which is what this writer is for.

It takes its version number and sidecar-pairing key from
`io.session_file`'s own public constants rather than transcribing them, so the
fixture cannot drift away from the reader it feeds. The reader is the oracle:
`load_session` accepting what this writes is the check that it is really v1.

Provenance: the manifest layout below was lifted from `save_session` before
that function was deleted, and verified in the same session by round-tripping
both writers through `load_session` and comparing the results field by field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.session_file import GENERATION_KEY, V1_VERSION

__all__ = ["write_v1_session"]


def write_v1_session(
    path: str | Path,
    entries: list[tuple[str, str, DataStruct]],
    client_state: dict[str, Any] | None = None,
    *,
    generation: str | None = "0123456789abcdef",
) -> tuple[Path, Path]:
    """Write a v1 `<stem>.json` + `<stem>.npz` pair; returns both paths.

    `generation=None` omits the pairing tag entirely, which is the pre-#21
    legacy shape the reader still accepts.
    """
    json_path = Path(path)
    if json_path.suffix.lower() != ".json":
        json_path = json_path.with_suffix(".json")
    npz_path = json_path.with_suffix(".npz")

    manifest: dict[str, Any] = {
        "version": V1_VERSION,
        "generation": generation,
        "images": [
            {
                "id": img_id,
                "name": name,
                "kind": ds.kind.value,
                "axes": [
                    {"scale": ax.scale, "origin": ax.origin, "units": ax.units}
                    for ax in ds.axes
                ],
                "metadata": dict(ds.metadata),
            }
            for img_id, name, ds in entries
        ],
        "client_state": client_state,
    }
    arrays: dict[str, np.ndarray] = {
        img_id: np.asarray(ds.data) for img_id, _, ds in entries
    }
    if generation is not None:
        arrays[GENERATION_KEY] = np.asarray(generation)

    json_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(npz_path, **arrays)  # type: ignore[arg-type]
    json_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return json_path, npz_path
