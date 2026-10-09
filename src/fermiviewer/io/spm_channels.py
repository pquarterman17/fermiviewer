"""Every channel of a scanning-probe file, whichever format wrote it.

The AFM "Open Other Channels" action and the upload stash call this, so a
new SPM reader only has to add its ``load_<fmt>_all`` here (and its
primary-channel loader to ``io/registry.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.gwy import load_gwy_all
from fermiviewer.io.ibw import load_ibw_all
from fermiviewer.io.jpk import load_jpk_all
from fermiviewer.io.nanoscope import is_nanoscope, load_nanoscope_all
from fermiviewer.io.wsxm import load_wsxm_all

__all__ = ["SPM_PARSERS", "load_spm_channels"]

#: the `parser` metadata of images whose files hold several channels
SPM_PARSERS = frozenset({"nanoscope", "gwyddion", "asylum", "jpk", "wsxm"})

_BY_EXT: dict[str, Callable[[Path], list[DataStruct]]] = {
    ".gwy": load_gwy_all,
    ".ibw": load_ibw_all,
    ".jpk": load_jpk_all,
    ".jpk-qi-image": load_jpk_all,
    ".top": load_wsxm_all,
    ".stp": load_wsxm_all,
}


def load_spm_channels(path: str | Path) -> list[DataStruct]:
    """All image channels of an SPM file (ValueError if it is not one)."""
    p = Path(path)
    loader = _BY_EXT.get(p.suffix.lower())
    if loader is not None:
        return loader(p)
    with open(p, "rb") as fh:
        head = fh.read(20)
    if is_nanoscope(head):
        return load_nanoscope_all(p)
    raise ValueError(f"'{p.name}' is not a multi-channel SPM file")
