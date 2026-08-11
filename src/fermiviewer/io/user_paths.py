"""The trust boundary for filesystem paths that arrive over the API.

FermiViewer is a desktop app, so `/session/open`, `/project/save` and their
neighbours take *server-side* paths on purpose: the user picks a file in a
native OS dialog and the SPA hands the resulting path back. "This request
names a path anywhere on the machine" is therefore the product, not a bug,
and this module does not try to take that away. What it adds is the single
place where that decision is made deliberately instead of accidentally —
every request-supplied path is canonicalised once, checked against the roots
this install is allowed to touch, and kept out of the app's own private
state.

Two policies, because the API carries two different kinds of path:

* `safe_data_path` — a file or folder the **user named**. Allowed anywhere
  under `data_roots()`, which is the whole volume by default (see that
  function for the shared-machine lockdown switch), but never inside the
  config dir: workspaces, the calibration DB and the workspace index are
  reached through their own endpoints, and the generic open/save surface
  must not become a second, unguarded way to read or overwrite them.

* `safe_config_path` — a path this app **derives** from a user-supplied name,
  i.e. a workspace slug. Confined to the directory it belongs in, so a slug
  that ever escaped `workspaces.slugify` / `session_io._valid_slug` still
  could not escape the tree those two are guarding.

Both canonicalise with `os.path.realpath` *before* deciding, so the answer
accounts for `..`, symlinks and Windows short names, and so every later
`is_file()` / `open()` in the call chain sees the same path this module
approved rather than re-resolving a string that could mean something else by
then.

Why a boundary at all, given SECURITY.md puts "issues that require an
already-compromised local machine" out of scope: the server is reachable by
any local process, and these endpoints are the ones that read and write
files. Canonicalising at the edge is what makes the parser layer's own
guarantees (`io.project_manifest.safe_posix_rel`, `safe_image_id`) rest on a
path that has already been pinned down, and `FV_DATA_ROOTS` gives a shared
lab machine a real way to narrow the surface without a code change.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "PathPolicyError",
    "data_roots",
    "safe_config_path",
    "safe_data_path",
    "safe_data_paths",
]

#: os.pathsep-separated list of roots the API may read and write under.
#: Unset (the default) means "the whole volume" — see `data_roots`.
ROOTS_ENV = "FV_DATA_ROOTS"


class PathPolicyError(ValueError):
    """A request-supplied path this install refuses to touch.

    A `ValueError` so the routes that already map `ValueError` to HTTP 422
    keep doing the right thing without a second except-clause; the ones that
    don't go through `routes._paths`.
    """


def data_roots() -> tuple[str, ...]:
    """Roots a request-supplied path is allowed to resolve inside.

    Empty by default, which `safe_data_path` reads as "the volume the path
    is on" — every absolute path passes, because opening a file the user
    just picked in an OS dialog is what this application is for.

    Setting `FV_DATA_ROOTS` (os.pathsep-separated, like PATH) narrows that
    to the listed trees. This is the switch for a shared or unattended
    machine — a lab workstation where the instrument corpus lives under one
    directory and nothing else should be reachable through the local API.
    """
    configured = os.environ.get(ROOTS_ENV, "")
    roots = [
        os.path.realpath(os.path.expanduser(entry))
        for entry in configured.split(os.pathsep)
        if entry.strip()
    ]
    return tuple(roots)


def _config_root() -> str:
    """The app's own state directory, canonicalised. Never user data."""
    from fermiviewer.usermeta import config_dir

    return os.path.realpath(config_dir())


def _under(path: str, root: str) -> bool:
    """True when `path` is `root` or sits beneath it, comparing whole path
    components — so `/data` never claims `/database`."""
    if path == root:
        return True
    return path.startswith(root.rstrip(os.sep) + os.sep)


def _candidate_root(real: str) -> str:
    """The configured root that best matches `real`.

    Only picks the candidate — `safe_data_path` makes the actual decision —
    so that the containment test stays one visible comparison rather than
    being buried in here.
    """
    best = ""
    for root in data_roots():
        if _under(real, root) and len(root) > len(best):
            best = root
    if best:
        return best
    configured = data_roots()
    if configured:
        # Nothing claimed it; hand back a real root so the caller's check
        # fails against something meaningful rather than against "".
        return configured[0]
    # Unconfined (the default): the volume `real` itself sits on.
    drive, _ = os.path.splitdrive(real)
    return drive + os.sep


def safe_data_path(raw: str | os.PathLike[str], *, where: str) -> str:
    """Canonicalise a user-named path, or raise `PathPolicyError`.

    `where` names the field being checked (`"paths[0]"`, `"dir"`) so the 422
    tells the user which one of several inputs was refused.

    Returns the canonical path as a `str`; callers pass that on rather than
    the original, so the path that was checked is the path that is opened.
    """
    text = os.fspath(raw)
    if not text.strip():
        raise PathPolicyError(f"{where}: path must not be empty")
    if "\x00" in text:
        raise PathPolicyError(f"{where}: path must not contain a NUL byte")

    # A relative path resolves against the server process's working
    # directory. That is a deliberate, tested contract (see
    # tests/test_watch.py::test_watch_start_accepts_a_relative_directory) —
    # `realpath` makes it explicit and absolute here rather than leaving each
    # sink to resolve the string again later, possibly to something else.
    real = os.path.realpath(os.path.expanduser(text))
    root = _candidate_root(real)
    if not real.startswith(root):
        raise PathPolicyError(
            f"{where}: {text!r} is outside the roots this install may use "
            f"(see {ROOTS_ENV})"
        )
    if not _under(real, root):  # component-wise: /data must not claim /database
        raise PathPolicyError(
            f"{where}: {text!r} is outside the roots this install may use "
            f"(see {ROOTS_ENV})"
        )
    if _under(real, _config_root()):
        raise PathPolicyError(
            f"{where}: {text!r} is inside FermiViewer's own config directory; "
            f"use the workspace endpoints to reach saved workspaces"
        )
    return real


def safe_data_paths(
    raws: list[str] | tuple[str, ...], *, where: str
) -> list[str]:
    """`safe_data_path` over a list, naming the offending index on failure."""
    return [
        safe_data_path(raw, where=f"{where}[{index}]")
        for index, raw in enumerate(raws)
    ]


def safe_config_path(
    name: str, root: str | os.PathLike[str], *, where: str
) -> Path:
    """Join a derived `name` onto `root` without letting it escape.

    For paths this app builds from user-supplied text — a workspace slug and
    its suffix. The slug is already restricted to `[a-z0-9-]` upstream; this
    is the containment that still holds if that restriction is ever loosened
    or bypassed, which is the whole point of putting it here as well.
    """
    base = os.path.realpath(root)
    prefix = base.rstrip(os.sep) + os.sep
    real = os.path.realpath(os.path.join(base, name))
    if not real.startswith(prefix):
        raise PathPolicyError(
            f"{where}: {name!r} does not stay inside {base!r}"
        )
    return Path(real)
