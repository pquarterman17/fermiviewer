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
import os
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

__all__ = ["load_session", "save_session"]

_VERSION = 1
_GENERATION_KEY = "__fv_generation__"


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


def _transaction_path(path: Path, generation: str, role: str) -> Path:
    """Hidden sibling used while installing a session file pair."""
    return path.with_name(f".{path.name}.{generation}.{role}")


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write and flush a staged manifest before it can become visible."""
    with path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
        fh.flush()
        os.fsync(fh.fileno())


def _write_arrays(path: Path, arrays: dict[str, np.ndarray]) -> None:
    """Write and flush a staged NPZ without numpy changing its filename."""
    with path.open("wb") as fh:
        # numpy stubs type the kwargs as allow_pickle; arrays-as-kwargs is
        # the documented savez API.
        np.savez_compressed(fh, **arrays)  # type: ignore[arg-type]
        fh.flush()
        os.fsync(fh.fileno())


def _cleanup(paths: list[Path]) -> None:
    """Best-effort cleanup; a valid committed pair must not become an error."""
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _commit_pair(
    staged_json: Path,
    staged_npz: Path,
    json_path: Path,
    npz_path: Path,
    generation: str,
) -> None:
    """Install both staged files, restoring the previous pair on failure."""
    backup_json = _transaction_path(json_path, generation, "bak")
    backup_npz = _transaction_path(npz_path, generation, "bak")
    backups = ((json_path, backup_json), (npz_path, backup_npz))
    installed: list[Path] = []
    moved_backups: list[tuple[Path, Path]] = []

    try:
        for final, backup in backups:
            if final.exists():
                os.replace(final, backup)
                moved_backups.append((final, backup))
        # The manifest is the commit marker, so expose the pixel sidecar first.
        os.replace(staged_npz, npz_path)
        installed.append(npz_path)
        os.replace(staged_json, json_path)
        installed.append(json_path)
    except BaseException as exc:
        rollback_errors: list[OSError] = []
        for final in reversed(installed):
            try:
                final.unlink(missing_ok=True)
            except OSError as error:
                rollback_errors.append(error)
        for final, backup in reversed(moved_backups):
            try:
                os.replace(backup, final)
            except OSError as error:
                rollback_errors.append(error)
        _cleanup([staged_json, staged_npz, backup_json, backup_npz])
        if rollback_errors:
            raise OSError(
                "session save failed and the previous files could not be fully restored"
            ) from exc
        raise
    else:
        _cleanup([backup_json, backup_npz])


def save_session(
    path: str | Path,
    entries: list[tuple[str, str, DataStruct]],
    client_state: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """Write (id, name, DataStruct) entries; returns (json, npz) paths."""
    json_path, npz_path = _paths(path)
    generation = uuid.uuid4().hex
    manifest: dict[str, Any] = {
        "version": _VERSION,
        "generation": generation,
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

    arrays[_GENERATION_KEY] = np.asarray(generation)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    staged_json = _transaction_path(json_path, generation, "tmp")
    staged_npz = _transaction_path(npz_path, generation, "tmp")
    try:
        _write_arrays(staged_npz, arrays)
        _write_manifest(staged_json, manifest)
        _commit_pair(
            staged_json, staged_npz, json_path, npz_path, generation
        )
    except BaseException:
        _cleanup([staged_json, staged_npz])
        raise
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
        manifest_generation = manifest.get("generation")
        sidecar_generation = (
            str(np.asarray(arrays[_GENERATION_KEY]).item())
            if _GENERATION_KEY in arrays
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
