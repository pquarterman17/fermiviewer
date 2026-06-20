"""Launch context — the working directory the app was started from.

When the user runs `fermiviewer` (or `fv`) from a folder of images, the
in-app Open dialog defaults there. The OS-native file picker can't be
pointed at a directory by the page (a browser security boundary), so the
launch dir is exposed via /api/session/launch-dir and the SPA offers a
small server-side folder picker pre-pointed at it.

Set once by server.main(); read by the launch-dir route. Kept separate
from server.py so routes don't import the server module (no cycle).
"""

from __future__ import annotations

import os
from pathlib import Path

_launch_dir: Path | None = None


def set_launch_dir(path: str | os.PathLike[str] | None) -> None:
    """Record the directory the app was launched from (None to clear)."""
    global _launch_dir
    if path is None:
        _launch_dir = None
        return
    try:
        _launch_dir = Path(path).resolve()
    except OSError:  # pragma: no cover — pathological cwd
        _launch_dir = None


def launch_dir() -> Path | None:
    """The launch directory, or None when not set / not launched from one."""
    return _launch_dir
