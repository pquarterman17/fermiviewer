"""User-configurable metadata: a YAML schema of free-text fields plus an
optional filename `{field}` template that auto-fills them, and per-file
sidecar persistence (``<name>.fvmeta.yaml`` written beside the image).

Pure utility (file I/O only, no FastAPI) — `routes/usermeta.py` adapts it.
The config lives in an OS-appropriate dir (override with FV_METADATA_CONFIG);
a commented starter is seeded on first read so users have something to edit.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

__all__ = [
    "MetaField",
    "MetaSchema",
    "config_path",
    "load_schema",
    "parse_filename",
    "read_sidecar",
    "resolve_values",
    "sidecar_path",
    "write_sidecar",
]


# ── schema ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MetaField:
    name: str
    type: str = "text"  # reserved for future typed fields / dropdowns
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetaSchema:
    fields: tuple[MetaField, ...] = ()
    patterns: tuple[str, ...] = ()
    path: str = ""


_STARTER = """\
# fermiviewer — custom metadata configuration
#
# Fields you want to fill in for each image, shown in the "Custom
# Metadata" inspector card. A bare name is a free-text field; you can also
# give a {name, type, options} mapping:
#   - name: Wafer
#     type: number          # number | date | text (default)
#   - name: Process
#     options: [A, B, C]    # any field with options renders a dropdown
fields:
  - Design
  - Lot
  - Wafer
  - Reticle

# Optional: auto-fill the fields from the file name. {Field} placeholders
# capture text up to the next literal character. This example parses
#   D1234_L44576_W1234_R13.dm3  ->  Design=1234 Lot=44576 Wafer=1234 Reticle=13
pattern: "D{Design}_L{Lot}_W{Wafer}_R{Reticle}"

# You can give several patterns instead; the first that matches wins:
# patterns:
#   - "D{Design}_L{Lot}_W{Wafer}_R{Reticle}"
#   - "{Lot}-{Wafer}"
"""


def _config_dir() -> Path:
    override = os.environ.get("FV_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "fermiviewer"


def config_path() -> Path:
    """Resolve the metadata config file path (FV_METADATA_CONFIG wins)."""
    override = os.environ.get("FV_METADATA_CONFIG")
    return Path(override) if override else _config_dir() / "metadata.yaml"


def _seed_starter(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_STARTER, encoding="utf-8")
    except OSError:
        pass  # read-only config dir → just return an empty schema


def load_schema() -> MetaSchema:
    """Load the metadata schema, seeding a commented starter if absent.

    `fields` accepts either bare strings or ``{name, type?, options?}``
    mappings (so typed fields/dropdowns can be added later without a
    redesign). `pattern` (str) and/or `patterns` (list) define auto-fill.
    """
    path = config_path()
    if not path.exists():
        _seed_starter(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    fields: list[MetaField] = []
    for f in raw.get("fields") or []:
        if isinstance(f, str) and f.strip():
            fields.append(MetaField(name=f.strip()))
        elif isinstance(f, dict) and str(f.get("name", "")).strip():
            fields.append(
                MetaField(
                    name=str(f["name"]).strip(),
                    type=str(f.get("type", "text")),
                    options=tuple(str(o) for o in (f.get("options") or [])),
                )
            )

    # drop duplicate field names (first wins) so the UI never doubles a row
    seen: set[str] = set()
    deduped: list[MetaField] = []
    for f in fields:
        if f.name not in seen:
            seen.add(f.name)
            deduped.append(f)
    fields = deduped

    patterns: list[str] = []
    if isinstance(raw.get("pattern"), str):
        patterns.append(raw["pattern"])
    raw_patterns = raw.get("patterns")
    if isinstance(raw_patterns, str):
        patterns.append(raw_patterns)  # a bare string, not a list (easy slip)
    else:
        patterns.extend(p for p in raw_patterns or [] if isinstance(p, str))

    return MetaSchema(fields=tuple(fields), patterns=tuple(patterns), path=str(path))


# ── filename templates ────────────────────────────────────────────────

_TOKEN = re.compile(r"\{([A-Za-z_]\w*)\}")


def _template_to_regex(template: str) -> re.Pattern[str] | None:
    """Compile a ``D{Design}_L{Lot}`` template to an anchored regex. Each
    placeholder captures non-empty text up to the next literal (non-greedy,
    except the final placeholder which takes the remainder)."""
    parts = re.split(r"(\{[A-Za-z_]\w*\})", template)
    tokens = [p for p in parts if _TOKEN.fullmatch(p)]
    if not tokens:
        return None
    n = len(tokens)
    seen = 0
    rx = ""
    for p in parts:
        m = _TOKEN.fullmatch(p)
        if m:
            seen += 1
            quant = ".+" if seen == n else ".+?"
            rx += f"(?P<{m.group(1)}>{quant})"
        else:
            rx += re.escape(p)
    try:
        return re.compile("^" + rx + "$")
    except re.error:
        return None


def parse_filename(name: str, patterns: tuple[str, ...]) -> dict[str, str]:
    """Match the file name (extension stripped) against each template; the
    first that matches returns its captured fields. Empty dict if none."""
    stem = Path(name).stem
    for template in patterns:
        rx = _template_to_regex(template)
        if rx is None:
            continue
        m = rx.match(stem)
        if m:
            return {k: v for k, v in m.groupdict().items() if v is not None}
    return {}


# ── sidecar persistence ───────────────────────────────────────────────


def sidecar_path(image_path: str) -> Path:
    """``/data/img.dm3`` → ``/data/img.dm3.fvmeta.yaml`` (kept adjacent so
    it travels with the file and never collides with another extension)."""
    p = Path(image_path)
    return p.with_name(p.name + ".fvmeta.yaml")


def read_sidecar(image_path: str) -> dict[str, str]:
    sp = sidecar_path(image_path)
    if not sp.exists():
        return {}
    try:
        d = yaml.safe_load(sp.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(d, dict):
        return {}
    # a YAML `null` value means "cleared" → empty string, not the text "None"
    return {str(k): ("" if v is None else str(v)) for k, v in d.items()}


def write_sidecar(image_path: str, values: dict[str, str]) -> None:
    sp = sidecar_path(image_path)
    sp.write_text(
        yaml.safe_dump(dict(values), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


# ── value resolution ──────────────────────────────────────────────────


def resolve_values(
    schema: MetaSchema,
    name: str,
    source_path: str | None,
    ds_metadata: dict[str, object],
) -> dict[str, str]:
    """Resolve each schema field's value, precedence (low→high):
    filename auto-fill → saved sidecar → live session edit (ds.metadata).
    Returns every schema field, defaulting to ""."""
    vals: dict[str, str] = dict(parse_filename(name, schema.patterns))
    if source_path:
        vals.update(read_sidecar(source_path))
    for f in schema.fields:
        # a present key (even "" / None) is an explicit session edit and wins
        # over filename/sidecar — so a user can clear a field; absent = unset
        if f.name in ds_metadata:
            cur = ds_metadata[f.name]
            vals[f.name] = "" if cur is None else str(cur)
    return {f.name: vals.get(f.name, "") for f in schema.fields}
