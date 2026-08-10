"""v1 workspace → v2 project, upgraded in memory (plan #32, ADR 0002 §6).

A v1 workspace is a `<stem>.json` manifest beside a `<stem>.npz` holding every
image's pixels, with all the interesting state inside one opaque
`client_state` blob. `load_project` routes such a pair here, so opening one
yields an ordinary `LoadedProject` and **the next save writes a `.fvp`** —
nothing in the application knows or cares which format a project came from.

v1 is read-only legacy from here: `session_file` no longer has a writer.

Nothing is lost in the upgrade:

* pixels and dtype come from the `.npz`, so a v1 project is self-contained
  exactly as it was — every image arrives embedded;
* `metadata["source"]` (recorded at import) becomes the v2 `source`, so the
  FIRST light save can reference the images whose files still exist instead of
  embedding them forever;
* a derived image keeps its `derived_from`, which is what makes it embed in
  both payload modes rather than being referenced into nothing;
* `client_state` is split by `project_sections`, so groups become validated
  `samples` (with their parameter values and units) and annotations become
  `measures`, and everything presentational rides `ui_state` untouched.
"""

from __future__ import annotations

from pathlib import Path

from fermiviewer.io.project_manifest import LoadedProject, image_from_entry
from fermiviewer.io.project_sections import split_client_state
from fermiviewer.io.session_file import load_session

__all__ = ["V1_SUFFIXES", "load_v1_as_project"]

#: Either half of a v1 pair names the pair (`session_file` normalises to
#: `.json`), so a user who picks the sidecar in a file dialog is not told the
#: project does not exist.
V1_SUFFIXES = frozenset({".json", ".npz"})


def load_v1_as_project(path: str | Path) -> LoadedProject:
    """Read a v1 `.json`/`.npz` pair as a v2 `LoadedProject`.

    Raises what `load_session` raises — FileNotFoundError for a missing half,
    ValueError for a mismatched pair or an unsupported version — so callers
    map errors once for both formats.
    """
    source = Path(path)
    entries, client_state = load_session(source)
    sections = split_client_state(client_state)
    return LoadedProject(
        images=tuple(image_from_entry(*entry) for entry in entries),
        samples=tuple(sections.samples),
        measures=sections.measures,
        ui_state=sections.ui_state,
        # Truthful about what was just read: a v1 file embedded everything.
        # The *next* save picks its own mode; nothing here forces one.
        payload_mode="bundle",
        data_root_hint=None,
        primary_param=None,
        # v1 had no project name, so the filename is the only one there is.
        name=source.stem,
        generation="",
        unknown_keys={},
    )
