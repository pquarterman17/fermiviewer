"""Every channel of a scanning-probe file, whichever format wrote it.

The AFM "Open Other Channels" action and the upload stash call this, so a
new SPM reader only has to add its ``load_<fmt>_all`` here (and its
primary-channel loader to ``io/registry.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.gwy import load_gsf, load_gwy_all
from fermiviewer.io.ibw import load_ibw_all
from fermiviewer.io.jpk import load_jpk_all
from fermiviewer.io.mdt import is_mdt, load_mdt_all
from fermiviewer.io.nanoscope import is_nanoscope, load_nanoscope_all
from fermiviewer.io.nid import load_nid_all
from fermiviewer.io.sxm import is_sxm, load_sxm_all
from fermiviewer.io.wsxm import is_wsxm, load_wsxm_all

__all__ = ["SPM_PARSERS", "load_spm_channels"]

#: the `parser` metadata of images whose files hold several channels
SPM_PARSERS = frozenset({
    "nanoscope", "gwyddion", "asylum", "jpk", "wsxm", "nanosurf", "ntmdt", "nanonis",
})

_BY_EXT: dict[str, Callable[[Path], list[DataStruct]]] = {
    ".gwy": load_gwy_all,
    ".gsf": lambda p: [load_gsf(p)],
    ".nid": load_nid_all,
    ".mdt": load_mdt_all,
    ".sxm": load_sxm_all,
    ".adh": load_wsxm_all,
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
        head = fh.read(200)
    if is_nanoscope(head):
        return load_nanoscope_all(p)
    if is_wsxm(head):                       # WSxM channels use many extensions
        return load_wsxm_all(p)
    if is_mdt(head):
        return load_mdt_all(p)
    if is_sxm(head):
        return load_sxm_all(p)
    raise ValueError(f"'{p.name}' is not a multi-channel SPM file")
