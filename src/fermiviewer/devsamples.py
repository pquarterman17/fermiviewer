"""Dev-only helper: locate a few sample datasets for the auto-load
testing mode (`uv run fv --dev`).

The frontend opens these on startup when the session is empty so the
common load-then-inspect loop doesn't have to be repeated by hand on
every restart. The files come from the sibling fermi-viewer MATLAB
repo's committed corpus (`../fermi-viewer/+test_datasets/`), which is
per-machine and absent on CI / packaged installs — in which case this
returns an empty list and the auto-load is simply skipped. Nothing here
is reachable from a packaged build (no corpus, and the frontend only
calls the endpoint under Vite dev).
"""

from __future__ import annotations

from pathlib import Path

# git/fermi-viewer/+test_datasets, sibling to this repo — matches the
# conftest ML_ROOT resolution (tests/conftest.py).
_SAMPLE_ROOT = (
    Path(__file__).resolve().parents[3] / "fermi-viewer" / "+test_datasets"
)

# One nice 2D raster per extension so the inspector/measure/transform
# tools all have something to act on. If a preferred file isn't present
# on this machine, fall back to the first match anywhere in the tree.
_PREFERRED: dict[str, str] = {
    ".jpg": "Microscopy/EDW087-1.jpg",
    ".dm3": "Microscopy/EDW087-1.dm3",
    ".tif": "Microscopy/EDW087-1.tif",
    ".dm4": "Microscopy/Fig3c_apatite_HAADF.dm4",
}

# Extensions the testing mode opens, in display order.
DEFAULT_EXTS: tuple[str, ...] = (".jpg", ".dm3", ".dm4", ".tif")


def _first_with_ext(ext: str) -> Path | None:
    preferred = _SAMPLE_ROOT / _PREFERRED.get(ext, "")
    if preferred.is_file():
        return preferred
    return next(iter(sorted(_SAMPLE_ROOT.rglob(f"*{ext}"))), None)


def find_sample_files(exts: tuple[str, ...] = DEFAULT_EXTS) -> list[Path]:
    """Resolve one sample file per extension, in order. Missing
    extensions (or an absent corpus) are skipped — never raises."""
    if not _SAMPLE_ROOT.is_dir():
        return []
    out: list[Path] = []
    for ext in exts:
        p = _first_with_ext(ext)
        if p is not None:
            out.append(p)
    return out
