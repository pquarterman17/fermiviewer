"""`.fvp` v2 manifest — structures, schema validation, path safety.

The data half of the project container (ADR 0002); `project_file.py` holds
the ZIP read/write. Split so the container logic and the contract it is
checked against stay separately readable, both under the module ceiling.

Three jobs:

1. **Structures.** `ProjectImage` / `LoadedProject` are plain frozen
   dataclasses over plain values — the pure-layer rule means no Pydantic
   here, and routes/ adapts.
2. **Validation.** Every load validates `manifest.json` against the
   *packaged copy* of `docs/schema/fvp-v2.schema.json`, failing with the
   offending JSON path (``images[3].rel``). The copy is asserted
   byte-identical to the docs original by tests/test_project_format.py, so
   the published contract and the enforced one cannot drift.
3. **Path safety.** A `.fvp` is a file a stranger can send. A `rel` that
   is absolute or escapes the data root with `..` is rejected before any
   filesystem access.

Keys this reader does not model — including schema-known but unimplemented
ones (`notes`) and anything a newer build added — are carried verbatim in
`extra` / `unknown_keys` and written back on save, so a round-trip through an
older build is not lossy (ADR 0002 §6).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from jsonschema import Draft202012Validator

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

if TYPE_CHECKING:
    # Import-time would be circular: project_results builds on the helpers
    # and error type defined here. regions_model likewise.
    from fermiviewer.io.project_results import ResultRecord
    from fermiviewer.io.regions_model import RegionClass, RegionSet

__all__ = [
    "FORMAT_MAGIC",
    "IMAGE_KEYS",
    "MANIFEST_KEYS",
    "MANIFEST_NAME",
    "PIXELS_DIR",
    "SCHEMA_NAME",
    "THUMBS_DIR",
    "VERSION",
    "LoadedProject",
    "PayloadMode",
    "ProjectFormatError",
    "ProjectImage",
    "axes_from_manifest",
    "axes_to_manifest",
    "extra_keys",
    "image_from_entry",
    "json_safe",
    "merge_extra",
    "safe_image_id",
    "safe_posix_rel",
    "schema_bytes",
    "validate_manifest",
]

FORMAT_MAGIC = "fermiviewer-project"
VERSION = 2
MANIFEST_NAME = "manifest.json"
PIXELS_DIR = "pixels"
THUMBS_DIR = "thumbs"
SCHEMA_NAME = "fvp-v2.schema.json"
_SCHEMA_PACKAGE = "fermiviewer.io"

# Payload modes are a closed set in the schema; Literal so a typo at a call
# site is a mypy error rather than a container no reader accepts.
PayloadMode = Literal["light", "bundle"]

# Keys this reader writes itself. Everything else in a manifest (or in an
# images[] entry) is unknown-to-us and round-trips verbatim.
MANIFEST_KEYS = frozenset(
    {
        "format",
        "version",
        "generation",
        "saved_at",
        "app_version",
        "name",
        "payload_mode",
        "data_root_hint",
        "primary_param",
        "images",
        "samples",
        "measures",
        "results",
        "regions",
        "ui_state",
    }
)
IMAGE_KEYS = frozenset(
    {
        "id",
        "name",
        "kind",
        "axes",
        "metadata",
        "embedded",
        "rel",
        "source",
        "size_bytes",
        "sha256",
        "derived_from",
        "unavailable",
    }
)


class ProjectFormatError(ValueError):
    """A `.fvp` is not a project we can read (bad ZIP, schema violation,
    unsafe path, or a container missing pixels it claims to embed)."""


# ── structures ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectImage:
    """One `images[]` entry.

    `data is None` marks an **unavailable placeholder**: the manifest
    described a source this machine could not resolve. Such an entry keeps
    its identity, calibration, metadata and `rel`, and saving writes the
    reference back unchanged — opening a project without its data and
    pressing save must not be able to destroy it (ADR 0002 §4).
    """

    id: str
    name: str
    kind: DataKind
    axes: tuple[AxisCal, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    data: np.ndarray | None = None
    embedded: bool = False
    rel: str | None = None
    source: str | None = None
    size_bytes: int | None = None
    #: Optional content hash (plan #38), opt-in at save time — see
    #: `save_project`'s `hash_sources`. None unless a save has computed one
    #: for this image; once present, re-saves and relocations both use it
    #: (recomputed when a fresh source is available, else carried over
    #: unchanged like `rel`/`size_bytes`).
    sha256: str | None = None
    derived_from: str | None = None
    unavailable: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    #: Absolute path this load actually read the pixels from. Load-only —
    #: never written to the manifest, whose `source` stays the original
    #: import path (the schema keeps that as provenance). A re-save computes
    #: its `rel` from here, so a project resolved through the project-dir
    #: fallback on a second machine re-saves with correct references.
    resolved_path: str | None = None
    #: The `thumbs/<id>.png` bytes this load found, if any (plan #37).
    #: Load-only, like `resolved_path`: it is a ZIP entry, not a manifest
    #: key, so `save_project` decides what to write itself — freshly
    #: rendered whenever pixels are available, this carried-over value
    #: otherwise, so an unavailable placeholder's thumbnail survives a
    #: re-save exactly like its `rel` does (ADR 0002 §4).
    thumb: bytes | None = None

    @property
    def derived(self) -> bool:
        """True for an image produced by a filter/crop/analysis rather than
        read from disk. Derived images have no file of their own, so they are
        embedded in BOTH payload modes — a light save that merely referenced
        them would silently discard work (ADR 0002 §2)."""
        if self.derived_from:
            return True
        return self.metadata.get("parser") == "derived"

    @property
    def datastruct(self) -> DataStruct | None:
        """The image as a DataStruct, or None for an unavailable placeholder."""
        if self.data is None:
            return None
        return DataStruct(
            data=self.data,
            kind=self.kind,
            axes=self.axes,
            metadata=dict(self.metadata),
        )


def image_from_entry(img_id: str, name: str, ds: DataStruct) -> ProjectImage:
    """A session-store ``(id, name, DataStruct)`` triple as a `ProjectImage`.

    Shared by `save_project` (open images) and the v1 migration (images that
    arrived from a legacy workspace), so both classify derived-vs-sourced the
    same way — the decision that governs whether a light save may reference an
    image or must embed it.
    """
    metadata = dict(ds.metadata)
    derived_from = metadata.get("derived_from")
    source = metadata.get("source")
    # A derived image reuses metadata["source"] for the operation that made
    # it (e.g. "gaussian"), which is not a path — don't record it as one.
    is_derived = bool(derived_from) or metadata.get("parser") == "derived"
    return ProjectImage(
        id=str(img_id),
        name=str(name),
        kind=ds.kind,
        axes=tuple(ds.axes),
        metadata=metadata,
        data=ds.data,
        source=str(source) if isinstance(source, str) and not is_derived else None,
        derived_from=str(derived_from) if derived_from else None,
    )


@dataclass(frozen=True)
class LoadedProject:
    """Everything a `.fvp` carried, as plain values.

    `unknown_keys` holds top-level manifest keys this build does not model;
    pass it back to `save_project` to keep the round-trip lossless.
    """

    images: tuple[ProjectImage, ...] = ()
    samples: tuple[dict[str, Any], ...] = ()
    measures: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    results: tuple[ResultRecord, ...] = ()
    #: Named region sets and the class vocabulary they draw on (ADR 0006).
    #: Two fields, one manifest section: `regions` carries both, since the
    #: classes are the sets' vocabulary and splitting them across two
    #: top-level keys would double the wiring for no reader's benefit.
    region_sets: tuple[RegionSet, ...] = ()
    region_classes: tuple[RegionClass, ...] = ()
    ui_state: dict[str, Any] = field(default_factory=dict)
    payload_mode: str = "light"
    data_root_hint: str | None = None
    primary_param: str | None = None
    name: str | None = None
    generation: str = ""
    unknown_keys: dict[str, Any] = field(default_factory=dict)

    @property
    def entries(self) -> list[tuple[str, str, DataStruct]]:
        """(id, name, DataStruct) for resolved images only — the shape the
        session store already restores. Placeholders are absent by
        construction (they have no pixels); use `images` to keep them."""
        out: list[tuple[str, str, DataStruct]] = []
        for img in self.images:
            ds = img.datastruct
            if ds is not None:
                out.append((img.id, img.name, ds))
        return out

    @property
    def unavailable_ids(self) -> tuple[str, ...]:
        """Ids that could not be resolved on this machine."""
        return tuple(img.id for img in self.images if img.data is None)


# ── schema validation ────────────────────────────────────────────────


def schema_bytes() -> bytes:
    """The packaged schema, byte-identical to docs/schema/fvp-v2.schema.json.

    Read through importlib.resources so it works from a wheel install and
    from the PyInstaller sidecar, not just a source checkout.
    """
    return resources.files(_SCHEMA_PACKAGE).joinpath(SCHEMA_NAME).read_bytes()


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema: dict[str, Any] = json.loads(schema_bytes())
    return Draft202012Validator(schema)


def _json_path(parts: Iterable[Any]) -> str:
    """Render a jsonschema error path as `images[3].rel`."""
    out = ""
    for part in parts:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out or "<manifest root>"


def validate_manifest(manifest: Any) -> None:
    """Validate against the shipped schema; raise naming the offending path.

    Run on every load, and on save before the container is written — a
    file we could never read back is not worth committing to disk.
    """
    errors = sorted(
        _validator().iter_errors(manifest),
        key=lambda e: ([str(p) for p in e.absolute_path], e.message),
    )
    if not errors:
        return
    first = errors[0]
    detail = f" ({len(errors)} problems)" if len(errors) > 1 else ""
    raise ProjectFormatError(
        f"invalid project manifest at {_json_path(first.absolute_path)}: "
        f"{first.message}{detail}"
    )


# ── path safety ──────────────────────────────────────────────────────


def safe_posix_rel(rel: str, *, where: str) -> str:
    """Normalise a stored reference to POSIX form, rejecting escapes.

    Backslashes become `/` first (ADR 0002 §3: references are written with
    forward slashes and normalised on load), then the result must be
    relative and free of `..` components. Windows drive and UNC forms are
    rejected explicitly, because `PurePosixPath("C:/x")` is *relative* on
    POSIX and would otherwise be joined against the data root.

    Raises ProjectFormatError before any filesystem access.
    """
    posix = rel.replace("\\", "/")
    windows = PureWindowsPath(rel)
    if PurePosixPath(posix).is_absolute() or windows.is_absolute() or windows.drive:
        raise ProjectFormatError(
            f"{where}: source reference must be relative to the data root, "
            f"got {rel!r}"
        )
    if any(part == ".." for part in posix.split("/")):
        raise ProjectFormatError(
            f"{where}: source reference must not escape the data root "
            f"with '..', got {rel!r}"
        )
    return posix


def safe_image_id(img_id: str, *, where: str) -> str:
    """Validate an image id as a single safe path component.

    The id doubles as the `pixels/<id>.npy` entry name, and `unzip
    project.fvp` is an advertised way to inspect a project — so a crafted id
    would plant a zip-slip entry for whoever does that, even though this
    reader never extracts to disk. Separators and `..` are therefore refused
    on both save and load.
    """
    if not img_id:
        raise ProjectFormatError(f"{where}: image id must not be empty")
    if "/" in img_id or "\\" in img_id or "\x00" in img_id:
        raise ProjectFormatError(
            f"{where}: image id must not contain a path separator, got {img_id!r}"
        )
    if img_id in {".", ".."} or PureWindowsPath(img_id).drive:
        raise ProjectFormatError(f"{where}: unusable image id {img_id!r}")
    return img_id


# ── unknown-key plumbing ─────────────────────────────────────────────


def extra_keys(mapping: Mapping[str, Any], known: frozenset[str]) -> dict[str, Any]:
    """The part of `mapping` this build does not model, for verbatim carry."""
    return {k: v for k, v in mapping.items() if k not in known}


def merge_extra(
    entry: dict[str, Any], extra: Mapping[str, Any], known: frozenset[str]
) -> dict[str, Any]:
    """Write carried keys back, never letting them shadow a modelled key."""
    for key, value in extra.items():
        if key not in known:
            entry[key] = value
    return entry


# ── JSON coercion ────────────────────────────────────────────────────


def json_safe(value: Any) -> Any:
    """Recursively keep JSON-representable values; numpy scalars are
    converted. Unsupported values (ndarrays, exotic objects) become None:
    dropped as dict keys, kept as list placeholders (index alignment).

    Same contract as the v1 session serializer's helper — parser metadata
    is arbitrary and must never make a save fail.
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            safe_v = json_safe(v)
            if safe_v is not None or v is None:
                out[str(k)] = safe_v
        return out
    if isinstance(value, (list, tuple)):
        # Unrepresentable elements (e.g. ndarrays) fall through to the None
        # catch-all below rather than being dropped — deliberate, so each
        # element's index stays aligned with the source list.
        return [json_safe(v) for v in value]
    return None


# ── manifest -> structures ───────────────────────────────────────────


def axes_from_manifest(entries: Sequence[Mapping[str, Any]]) -> tuple[AxisCal, ...]:
    """AxisCal per data dimension (schema guarantees the fields exist)."""
    return tuple(
        AxisCal(
            scale=float(ax["scale"]),
            origin=float(ax["origin"]),
            units=str(ax["units"]),
        )
        for ax in entries
    )


def axes_to_manifest(axes: Sequence[AxisCal]) -> list[dict[str, Any]]:
    """AxisCal per data dimension, as schema-valid (strict-JSON) numbers.

    An uncalibrated axis often carries `scale=NaN` (e.g. `io/dm.py`,
    `io/dm5.py` default an unread calibration tag to NaN rather than 1.0),
    and `json.dumps` writes that as the bare token `NaN` — accepted by
    Python's own reader but not strict JSON, which breaks `unzip
    project.fvp` inspection with an external tool (ADR 0002). A non-finite
    `scale`/`origin` is written as `0.0` instead: `AxisCal.calibrated` and
    `.axis()` already treat scale 0 and NaN identically (both mean
    "uncalibrated"), so this is a lossless substitution, not a lossy one.
    """
    return [
        {
            "scale": ax.scale if math.isfinite(ax.scale) else 0.0,
            "origin": ax.origin if math.isfinite(ax.origin) else 0.0,
            "units": ax.units,
        }
        for ax in axes
    ]
