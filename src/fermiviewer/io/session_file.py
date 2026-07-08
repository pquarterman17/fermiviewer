"""Workspace persistence — JSON manifest + npz pixel sidecar (plan #21).

Pure file I/O on plain structures (no session-store / FastAPI imports).
Format v1: `<stem>.json` holds names, kinds, axis calibrations,
JSON-safe metadata and an opaque client-state blob; `<stem>.npz` holds
every image's raw array (original dtype) keyed by image id. Embedding
all pixels makes sessions robust to moved/deleted source files and
preserves derived images that have no file of their own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

__all__ = ["load_session", "save_session"]

_VERSION = 1


def _json_safe(value: Any) -> Any:
    """Recursively keep JSON-representable values; numpy scalars are
    converted. Unsupported values (ndarrays, exotic objects) become None:
    dropped as dict keys, kept as list placeholders (index alignment)."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            safe_v = _json_safe(v)
            if safe_v is not None or v is None:
                out[str(k)] = safe_v
        return out
    if isinstance(value, (list, tuple)):
        # Unrepresentable elements (e.g. ndarrays) fall through to the
        # None catch-all below rather than being dropped — deliberate,
        # so each element's index stays aligned with the source list.
        return [_json_safe(v) for v in value]
    return None


def _paths(path: str | Path) -> tuple[Path, Path]:
    p = Path(path)
    if p.suffix.lower() != ".json":
        p = p.with_suffix(".json")
    return p, p.with_suffix(".npz")


def save_session(
    path: str | Path,
    entries: list[tuple[str, str, DataStruct]],
    client_state: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """Write (id, name, DataStruct) entries; returns (json, npz) paths."""
    json_path, npz_path = _paths(path)
    manifest: dict[str, Any] = {
        "version": _VERSION,
        "images": [],
        "client_state": client_state,
    }
    arrays: dict[str, np.ndarray] = {}
    for img_id, name, ds in entries:
        manifest["images"].append(
            {
                "id": img_id,
                "name": name,
                "kind": ds.kind.value,
                "axes": [
                    {"scale": ax.scale, "origin": ax.origin, "units": ax.units}
                    for ax in ds.axes
                ],
                "metadata": _json_safe(ds.metadata) or {},
            }
        )
        arrays[img_id] = np.asarray(ds.data)

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    # numpy stubs type the kwargs as allow_pickle; arrays-as-kwargs is
    # the documented savez API
    np.savez_compressed(npz_path, **arrays)  # type: ignore[arg-type]
    return json_path, npz_path


def load_session(
    path: str | Path,
) -> tuple[list[tuple[str, str, DataStruct]], dict[str, Any] | None]:
    """Read a session back; returns (entries, client_state)."""
    json_path, npz_path = _paths(path)
    if not json_path.is_file():
        raise FileNotFoundError(f"session manifest not found: {json_path}")
    if not npz_path.is_file():
        raise FileNotFoundError(f"session data sidecar not found: {npz_path}")

    manifest = json.loads(json_path.read_text(encoding="utf-8"))
    version = manifest.get("version")
    if version != _VERSION:
        raise ValueError(f"unsupported session version: {version!r}")

    entries: list[tuple[str, str, DataStruct]] = []
    with np.load(npz_path) as arrays:
        for img in manifest["images"]:
            img_id = img["id"]
            if img_id not in arrays:
                raise ValueError(f"sidecar missing pixels for image {img_id}")
            axes = tuple(
                AxisCal(
                    scale=ax["scale"], origin=ax["origin"], units=ax["units"]
                )
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
