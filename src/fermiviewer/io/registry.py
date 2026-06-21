"""Parser registry — single-registration extension dispatch.

One map, one registration per parser (the deliberate improvement over the
MATLAB dual-registration). Ambiguous extensions get content sniffers when
they arrive (e.g. .dat).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.bcf import load_bcf
from fermiviewer.io.dm import load_dm
from fermiviewer.io.emd import load_emd
from fermiviewer.io.hspy import load_hspy
from fermiviewer.io.images import load_image, load_tiff
from fermiviewer.io.mrc import load_mrc
from fermiviewer.io.msa import load_msa
from fermiviewer.io.nanoscope import is_nanoscope, load_nanoscope
from fermiviewer.io.nexus import load_hdf5_auto
from fermiviewer.io.ser import load_ser

__all__ = ["UnsupportedFormatError", "load_auto", "supported_extensions"]


class UnsupportedFormatError(ValueError):
    pass


_LOADERS: dict[str, Callable[[Path], DataStruct]] = {
    ".dm3": load_dm,
    ".dm4": load_dm,
    ".emd": load_emd,  # Velox + NCEM EMD (HDF5)
    ".hspy": load_hspy,  # HyperSpy native signal (HDF5)
    # shared HDF5 extensions — the sniffer hub routes EMD/hspy/NeXus/generic
    ".h5": load_hdf5_auto,
    ".hdf5": load_hdf5_auto,
    ".nxs": load_hdf5_auto,
    ".nx5": load_hdf5_auto,
    ".bcf": load_bcf,
    ".ser": load_ser,
    ".msa": load_msa,  # EMSA/MAS single spectrum (EDS/EELS/WDS)
    ".mrc": load_mrc,
    ".tif": load_tiff,
    ".tiff": load_tiff,
    ".png": load_image,
    ".jpg": load_image,
    ".jpeg": load_image,
    ".bmp": load_image,
    ".gif": load_image,
    # .raw/.bin need explicit geometry — use io.images.load_raw directly
}


def supported_extensions() -> tuple[str, ...]:
    # .spm is content-routed (Nanoscope vs Park-TIFF); list it for the picker.
    return tuple(sorted({*_LOADERS, ".spm"}))


def load_auto(path: str | Path) -> DataStruct:
    p = Path(path)
    ext = p.suffix.lower()
    # Bruker Nanoscope AFM: numeric .000–.nnn are unambiguous; .spm is shared
    # with Park (TIFF-based), so content-sniff to route it.
    if ext == ".spm" or (len(ext) > 1 and ext[1:].isdigit()):
        with open(p, "rb") as fh:
            head = fh.read(20)
        if is_nanoscope(head):
            return load_nanoscope(p)
        if ext == ".spm":
            return load_tiff(p)  # Park/JPK .spm is a TIFF variant
        raise UnsupportedFormatError(
            f"'{p.name}' has a numeric extension but is not a Nanoscope file"
        )
    loader = _LOADERS.get(ext)
    if loader is None:
        raise UnsupportedFormatError(
            f"no parser for '{p.suffix}' (supported: {', '.join(supported_extensions())})"
        )
    return loader(p)
