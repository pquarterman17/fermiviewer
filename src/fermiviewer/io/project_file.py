"""Project persistence — the single-file `.fvp` v2 container (plan #30/#31).

Spec: `docs/adr/0002-project-file-format.md`; contract:
`docs/schema/fvp-v2.schema.json`. Supersedes the v1 two-file workspace in
`session_file.py`, which stays for v1 reads only.

    project.fvp                 ZIP, DEFLATE
    ├── manifest.json           schema-validated on every load
    └── pixels/<image-id>.npy   one entry per image with embedded: true

One container cannot be separated in transfer, and it makes the save
**atomic by construction**: staged sibling → flush + fsync → a single
`os.replace`. That retires v1's manifest-last commit ordering, which
existed only because two files had to agree.

Two payload modes, one reader:

* ``light`` — everyday Save Project. Source pixels are *referenced* by a
  POSIX path relative to one declared data root; derived images, and any
  image whose reference cannot be computed, are embedded, because a
  reference-only save would silently discard work that has no file.
* ``bundle`` — Export Project Bundle. Every image is embedded, and
  references are still recorded, so a bundle can be re-saved as a light
  project without losing them.

Structures and validation live in `project_manifest.py`, data-root and
reference maths in `project_paths.py`.

Pure layer: plain values in and out, numpy + jsonschema only. Untrusted
input is assumed throughout — a `rel` is rejected before it can reach the
filesystem, and `.npy` payloads are read with ``allow_pickle=False``.
"""

from __future__ import annotations

import datetime
import json
import os
import uuid
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer import __version__
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.io.project_manifest import (
    FORMAT_MAGIC,
    IMAGE_KEYS,
    MANIFEST_KEYS,
    MANIFEST_NAME,
    PIXELS_DIR,
    VERSION,
    LoadedProject,
    PayloadMode,
    ProjectFormatError,
    ProjectImage,
    axes_from_manifest,
    axes_to_manifest,
    extra_keys,
    image_from_entry,
    json_safe,
    merge_extra,
    safe_image_id,
    safe_posix_rel,
    validate_manifest,
)
from fermiviewer.io.project_v1 import V1_SUFFIXES, load_v1_as_project

# Imported as modules, not by name: `data_root` and `resolve` are also public
# names in this module's own signature space, and shadowing either helper with
# one would be silent.
from fermiviewer.io import project_paths as paths  # isort: skip
from fermiviewer.io import project_resolve as resolving  # isort: skip

__all__ = [
    "PROJECT_SUFFIX",
    "LoadedProject",
    "ProjectEntry",
    "ProjectFormatError",
    "ProjectImage",
    "load_project",
    "save_project",
]

PROJECT_SUFFIX = ".fvp"

#: What `save_project` accepts per image: either the session store's
#: ``(id, name, DataStruct)`` triple, or a `ProjectImage` straight back from
#: `load_project` — the latter is how an unavailable placeholder keeps its
#: reference through a re-save.
ProjectEntry = tuple[str, str, DataStruct] | ProjectImage


# ── save ─────────────────────────────────────────────────────────────


def save_project(
    path: str | Path,
    entries: Sequence[ProjectEntry],
    *,
    mode: PayloadMode = "light",
    samples: Sequence[Mapping[str, Any]] | None = None,
    measures: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    ui_state: Mapping[str, Any] | None = None,
    data_root: str | Path | None = None,
    primary_param: str | None = None,
    name: str | None = None,
    unknown_keys: Mapping[str, Any] | None = None,
) -> Path:
    """Write a `.fvp` project; returns the path actually written.

    `entries` mixes freely: ``(id, name, DataStruct)`` triples for open
    images and `ProjectImage` values for anything carried over from a load —
    notably unavailable placeholders, whose references are preserved
    verbatim (ADR 0002 §4).

    `data_root` declares the root references are relative to. Omitted,
    it is derived from the common parent of the source files that exist on
    this machine; when neither yields a usable absolute root, no reference
    can be computed and light mode embeds those images rather than dropping
    them. `unknown_keys` is `LoadedProject.unknown_keys` fed back, so a
    manifest written by a newer build survives a save by this one.

    The manifest is schema-validated *before* the container is committed: a
    file no reader could load back is not worth putting on disk.
    """
    target = _project_path(path)
    images = [_as_project_image(entry) for entry in entries]
    _check_ids(images)
    root = paths.data_root(data_root, images)
    generation = uuid.uuid4().hex
    records = [
        (img, _image_entry(img, index, root=root, mode=mode))
        for index, img in enumerate(images)
    ]

    manifest: dict[str, Any] = {
        "format": FORMAT_MAGIC,
        "version": VERSION,
        "generation": generation,
        "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "app_version": __version__,
        "name": name,
        "payload_mode": mode,
        "data_root_hint": paths.data_root_hint(data_root, root),
        "primary_param": primary_param,
        "images": [entry for _, entry in records],
        "samples": [dict(sample) for sample in samples or ()],
        "measures": {
            str(k): [dict(m) for m in v] for k, v in (measures or {}).items()
        },
        "ui_state": dict(ui_state or {}),
    }
    merge_extra(manifest, unknown_keys or {}, MANIFEST_KEYS)
    validate_manifest(manifest)
    _write_container(target, generation, manifest, records)
    return target


def _project_path(path: str | Path) -> Path:
    p = Path(path)
    return p if p.suffix.lower() == PROJECT_SUFFIX else p.with_suffix(PROJECT_SUFFIX)


def _check_ids(images: Sequence[ProjectImage]) -> None:
    """Ids must be unique and usable as an entry name.

    Uniqueness is load-bearing, not tidiness: the id IS the `pixels/<id>.npy`
    name, so a repeat would write a duplicate ZIP entry and the second image
    would silently read back the first one's pixels.
    """
    seen: set[str] = set()
    for index, img in enumerate(images):
        img_id = safe_image_id(img.id, where=f"images[{index}].id")
        if img_id in seen:
            raise ProjectFormatError(
                f"images[{index}].id: duplicate image id {img_id!r} — ids key "
                f"the pixel entries and must be unique within a project"
            )
        seen.add(img_id)


def _as_project_image(entry: ProjectEntry) -> ProjectImage:
    """Normalise a session-store triple into the manifest's per-image shape."""
    if isinstance(entry, ProjectImage):
        return entry
    return image_from_entry(*entry)


def _image_entry(
    img: ProjectImage, index: int, *, root: Path | None, mode: PayloadMode
) -> dict[str, Any]:
    """One `images[]` manifest entry, deciding embedded vs referenced."""
    rel, size = (None, None) if img.derived else paths.reference(img, index, root)
    placeholder = img.data is None
    if placeholder:
        embedded = False  # nothing to embed; the reference is all there is
    elif mode == "bundle":
        embedded = True
    else:
        embedded = img.derived or rel is None
    entry: dict[str, Any] = {
        "id": img.id,
        "name": img.name,
        "kind": img.kind.value,
        "axes": axes_to_manifest(img.axes),
        "metadata": json_safe(img.metadata) or {},
        "embedded": embedded,
        "rel": rel,
        "source": img.source,
        "size_bytes": size,
        "derived_from": img.derived_from,
        "unavailable": placeholder,
    }
    return merge_extra(entry, img.extra, IMAGE_KEYS)


def _write_container(
    target: Path,
    generation: str,
    manifest: Mapping[str, Any],
    records: Sequence[tuple[ProjectImage, Mapping[str, Any]]],
) -> None:
    """Stage the whole container, fsync it, then commit with one replace.

    Nothing touches `target` until that replace, so an interruption at any
    point leaves the previous project exactly as it was — and because there
    is only one file, no commit *ordering* has to be got right.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f".{target.name}.{generation}.tmp")
    try:
        with staged.open("wb") as fh:
            with zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=1))
                for img, entry in records:
                    data = img.data
                    if not entry["embedded"] or data is None:
                        continue
                    # Stream into the archive: a bundled spectrum-image cube
                    # runs to gigabytes and must not be buffered whole.
                    # force_zip64 because that size is unknown up front.
                    with zf.open(
                        f"{PIXELS_DIR}/{img.id}.npy", "w", force_zip64=True
                    ) as dest:
                        np.save(dest, data, allow_pickle=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(staged, target)
    except BaseException:
        _cleanup(staged)
        raise


def _cleanup(path: Path) -> None:
    """Best-effort: a failed save must not also fail on its own tidy-up."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


# ── load ─────────────────────────────────────────────────────────────


def load_project(path: str | Path) -> LoadedProject:
    """Read a project: validates the manifest, then resolves references.

    Resolution per referenced image (ADR 0002 §3): `data_root_hint` + `rel`,
    then the directory containing the `.fvp` + `rel`. An image that does not
    resolve — or whose source no longer parses as what the manifest
    describes — comes back as an **unavailable placeholder** keeping its
    identity, calibration, metadata and reference. It is never dropped, and
    `save_project` writes the reference back.

    A **v1 workspace** (`<stem>.json` + `<stem>.npz`) is accepted too and
    upgraded in memory (plan #32), so every caller gets migration for free and
    the next `save_project` writes a `.fvp`. v1 is read-only legacy: nothing
    writes it any more.
    """
    project = Path(path)
    if project.suffix.lower() in V1_SUFFIXES:
        return load_v1_as_project(project)
    if not project.is_file():
        raise FileNotFoundError(f"project file not found: {project}")
    try:
        with zipfile.ZipFile(project) as zf:
            manifest = _read_manifest(zf, project)
            raw_images: list[Mapping[str, Any]] = list(manifest["images"])
            # Path safety BEFORE any filesystem access: a .fvp is a file a
            # stranger can send, so one hostile rel invalidates the manifest
            # rather than being skipped image-by-image mid-resolution.
            for index, raw in enumerate(raw_images):
                safe_image_id(str(raw["id"]), where=f"images[{index}].id")
            rels = {
                index: safe_posix_rel(raw["rel"], where=f"images[{index}].rel")
                for index, raw in enumerate(raw_images)
                if raw.get("rel")
            }
            roots = paths.search_roots(manifest.get("data_root_hint"), project.parent)
            images = tuple(
                _load_image(zf, raw, index, rels.get(index), roots)
                for index, raw in enumerate(raw_images)
            )
    except zipfile.BadZipFile as exc:
        raise ProjectFormatError(
            f"{project.name} is not a readable .fvp ZIP container: {exc}"
        ) from None

    return LoadedProject(
        images=images,
        samples=tuple(dict(s) for s in manifest.get("samples") or ()),
        measures={
            str(k): [dict(m) for m in v]
            for k, v in (manifest.get("measures") or {}).items()
        },
        ui_state=dict(manifest.get("ui_state") or {}),
        payload_mode=str(manifest["payload_mode"]),
        data_root_hint=manifest.get("data_root_hint"),
        primary_param=manifest.get("primary_param"),
        name=manifest.get("name"),
        generation=str(manifest["generation"]),
        unknown_keys=extra_keys(manifest, MANIFEST_KEYS),
    )


def _read_manifest(zf: zipfile.ZipFile, project: Path) -> dict[str, Any]:
    """Parse and schema-validate `manifest.json`.

    Magic and version are checked first, so an unrelated JSON file or a v1
    workspace gets a message about what it actually is instead of a schema
    complaint about a missing property.
    """
    try:
        raw = zf.read(MANIFEST_NAME)
    except KeyError:
        raise ProjectFormatError(
            f"{project.name} contains no {MANIFEST_NAME} — not a .fvp project"
        ) from None
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectFormatError(f"{MANIFEST_NAME} is not valid JSON: {exc}") from None
    if not isinstance(manifest, dict):
        raise ProjectFormatError(f"{MANIFEST_NAME} must be a JSON object")
    if manifest.get("format") != FORMAT_MAGIC:
        raise ProjectFormatError(
            f"{MANIFEST_NAME} is not a FermiViewer project manifest "
            f"(format={manifest.get('format')!r})"
        )
    if manifest.get("version") != VERSION:
        raise ProjectFormatError(
            f"unsupported project version {manifest.get('version')!r}; this "
            f"build reads version {VERSION} (v1 workspaces load via "
            f"fermiviewer.io.session_file)"
        )
    validate_manifest(manifest)
    return manifest


def _load_image(
    zf: zipfile.ZipFile,
    raw: Mapping[str, Any],
    index: int,
    rel: str | None,
    roots: Sequence[Path],
) -> ProjectImage:
    img_id = str(raw["id"])
    kind = DataKind(str(raw["kind"]))
    axes = axes_from_manifest(raw["axes"])
    fields: dict[str, Any] = {
        "id": img_id,
        "name": str(raw["name"]),
        "kind": kind,
        "axes": axes,
        "metadata": dict(raw.get("metadata") or {}),
        "rel": rel,
        "source": raw.get("source"),
        "size_bytes": raw.get("size_bytes"),
        "derived_from": raw.get("derived_from"),
        "extra": extra_keys(raw, IMAGE_KEYS),
    }
    if raw["embedded"]:
        data = _read_pixels(zf, img_id, index)
        if not resolving.fits(data, kind, axes):
            raise ProjectFormatError(
                f"images[{index}] ({img_id}): embedded pixels are {data.ndim}D "
                f"with {len(axes)} axes, which does not describe a {kind.value}"
            )
        return ProjectImage(**fields, data=data, embedded=True)
    # Start from the placeholder that keeps everything except the pixels, so
    # an unresolved image is the *default* rather than a fallback path.
    placeholder = ProjectImage(**fields, data=None, embedded=False, unavailable=True)
    return resolving.resolve(placeholder, roots).image or placeholder


def _read_pixels(zf: zipfile.ZipFile, img_id: str, index: int) -> np.ndarray:
    name = f"{PIXELS_DIR}/{img_id}.npy"
    try:
        with zf.open(name) as fh:
            # allow_pickle=False: an object-array payload in a file a stranger
            # sent is arbitrary code execution, not an image.
            array: np.ndarray = np.load(fh, allow_pickle=False)
    except KeyError:
        raise ProjectFormatError(
            f"images[{index}] ({img_id}) is marked embedded but {name} is missing"
        ) from None
    except (OSError, ValueError, EOFError) as exc:
        raise ProjectFormatError(
            f"images[{index}] ({img_id}): unreadable pixel payload: {exc}"
        ) from None
    return array
