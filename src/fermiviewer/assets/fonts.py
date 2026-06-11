"""Frozen-aware path resolution for vendored font assets.

JetBrains Mono Regular (OFL-1.1) is vendored as a TTF so PIL can render
scale-bar and measurement labels at the on-screen font size during export.
The OFL.txt license sits alongside the TTF in the same directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def jetbrains_mono_regular() -> Path:
    """Absolute path to JetBrainsMono-Regular.ttf.

    Works in three layouts:
    - dev / editable install: ``src/fermiviewer/assets/fonts/`` relative to repo root
    - wheel install: ``fermiviewer/assets/fonts/`` inside site-packages
    - PyInstaller one-dir: ``<_MEIPASS>/fermiviewer/assets/fonts/``
    """
    # _HERE is src/fermiviewer/assets/ in dev, fermiviewer/assets/ in wheel
    candidate = _HERE / "fonts" / "JetBrainsMono-Regular.ttf"
    if candidate.exists():
        return candidate

    # PyInstaller frozen layout: sys._MEIPASS/_internal/fermiviewer/assets/fonts/
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "fermiviewer" / "assets" / "fonts" / "JetBrainsMono-Regular.ttf"
        if frozen.exists():
            return frozen

    # Last resort: return the expected path even if absent (caller handles missing)
    return candidate
