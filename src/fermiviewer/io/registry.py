"""Parser registry — single-registration extension dispatch.

One map, one registration per parser (the deliberate improvement over the
MATLAB dual-registration). Ambiguous extensions get content sniffers when
they arrive (e.g. .dat).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fermiviewer.calc.fourd.dataset import FourDDataset
from fermiviewer.datastruct import DataStruct
from fermiviewer.io.bcf import load_bcf
from fermiviewer.io.dm import load_dm
from fermiviewer.io.dm5 import load_dm5
from fermiviewer.io.emd import load_emd
from fermiviewer.io.fourd.mib import load_mib
from fermiviewer.io.hspy import load_hspy
from fermiviewer.io.images import load_image, load_tiff
from fermiviewer.io.jeol import load_jeol_img, load_jeol_map, load_jeol_pts
from fermiviewer.io.mrc import load_mrc
from fermiviewer.io.msa import load_msa
from fermiviewer.io.nanoscope import is_nanoscope, load_nanoscope
from fermiviewer.io.nexus import load_hdf5_auto
from fermiviewer.io.rpl import load_rpl
from fermiviewer.io.ser import load_ser
from fermiviewer.io.spc_edax import load_spc_edax

__all__ = [
    "UnsupportedFormatError",
    "is_fourd_path",
    "load_auto",
    "load_fourd_auto",
    "supported_extensions",
]


class UnsupportedFormatError(ValueError):
    pass


_LOADERS: dict[str, Callable[[Path], DataStruct]] = {
    ".dm3": load_dm,
    ".dm4": load_dm,
    ".dm5": load_dm5,  # GMS 3.5+ HDF5 successor to DM3/DM4
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
    ".rpl": load_rpl,  # Lispix raw-parameter-list header; reads sibling .raw
    ".spc": load_spc_edax,  # EDAX EDS spectrum (not GRAMS/Thermo Galactic .spc)
    ".tif": load_tiff,
    ".tiff": load_tiff,
    # JEOL Analysis Station — nothing else in the registry claims .img/.pts;
    # .map is JEOL-owned here too (not the unrelated Python .map() builtin).
    ".img": load_jeol_img,
    ".map": load_jeol_map,
    ".pts": load_jeol_pts,
    ".png": load_image,
    ".jpg": load_image,
    ".jpeg": load_image,
    ".bmp": load_image,
    ".gif": load_image,
    # .raw/.bin need explicit geometry — use io.images.load_raw directly.
    # A bare .raw is NEVER registered here even though load_rpl consumes one:
    # the .raw alone carries no width/height/depth/dtype, only its .rpl
    # sibling does — load_auto(".raw") would have nothing to go on.
    #
    # .mib is deliberately NOT registered here: a Merlin 4D-STEM acquisition
    # can never be a DataStruct (3D-capped, whole-buffer-frozen — see
    # docs/adr/0001-fourd-data-model.md), so load_auto(".mib") correctly
    # falls through to UnsupportedFormatError below. Use load_fourd_auto.
}

# 4D-STEM dispatch — a PARALLEL table, never merged into _LOADERS: these
# loaders return FourDDataset, not DataStruct, so load_auto (above) must
# never route to them. .mib is unambiguous; the shared HDF5 extensions
# above are content-sniffed (is_fourd_hdf5) since a plain <=3D file with
# the same extension is already claimed by _LOADERS.
_FOURD_LOADERS: dict[str, Callable[[Path], FourDDataset]] = {
    ".mib": load_mib,
}
_FOURD_SNIFF_EXTS = (".hspy", ".h5", ".hdf5", ".nxs", ".nx5")


def is_fourd_path(path: str | Path) -> bool:
    """True if `path` should be opened via `load_fourd_auto`, not `load_auto`.

    Checked by the /session/open route to decide which store (fourd vs
    normal image) a requested path belongs in, before either loader runs.
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext in _FOURD_LOADERS:
        return True
    if ext in _FOURD_SNIFF_EXTS:
        from fermiviewer.io.fourd.hspy4d import is_fourd_hdf5

        return is_fourd_hdf5(p)
    return False


def load_fourd_auto(path: str | Path) -> FourDDataset:
    """Load a 4D-STEM file (PLAN_4DSTEM). Distinct from `load_auto`, which
    stays DataStruct-only — never route a FourDDataset through it."""
    p = Path(path)
    ext = p.suffix.lower()
    loader = _FOURD_LOADERS.get(ext)
    if loader is not None:
        return loader(p)
    if ext in _FOURD_SNIFF_EXTS:
        from fermiviewer.io.fourd.hspy4d import is_fourd_hdf5, load_hspy4d

        if is_fourd_hdf5(p):
            return load_hspy4d(p)
        raise UnsupportedFormatError(f"'{p.name}' is not a 4D-STEM dataset")
    raise UnsupportedFormatError(
        f"no 4D-STEM parser for '{p.suffix}' "
        f"(supported: .mib, {', '.join(_FOURD_SNIFF_EXTS)} when 4D)"
    )


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
