"""NeXus / generic-HDF5 reader + the shared-HDF5 dispatch hub — Data-Formats #5.

``io/nexus.py`` does two jobs:

1. ``load_nexus`` — read a NeXus (``NXentry``→``NXdata``→``@signal``/``@axes``)
   container, or, when no NeXus markers exist, a best-effort "open anything
   HDF5" fallback that loads the largest float/int dataset uncalibrated.
2. ``load_hdf5_auto`` — the one disambiguation hub for the ambiguous HDF5
   extensions (``.h5``/``.hdf5``/``.nxs``): sniff the tree and route to the
   EMD, HyperSpy, or NeXus reader (else the generic fallback).

Pure ``io/`` layer (h5py/numpy/stdlib).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import h5py
import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.hdf5_common import (
    attr_str,
    axiscal_from_offset_scale,
    is_hdf5,
    largest_dataset,
)

__all__ = ["NexusFormatError", "load_hdf5_auto", "load_nexus"]

ENERGY_UNITS = {"ev", "kev", "mev"}


class NexusFormatError(ValueError):
    """Raised for unreadable HDF5 with no plottable dataset."""


def _nx_class(obj: h5py.HLObject) -> str:
    return attr_str(obj, "NX_class")


def _default_child(group: h5py.Group, want_class: str) -> h5py.Group | None:
    """The group's ``@default`` child, else its first child of NX_class
    ``want_class`` (NXentry / NXdata)."""
    default = attr_str(group, "default")
    if default and default in group and isinstance(group[default], h5py.Group):
        return group[default]
    for key in group:
        item = group[key]
        if isinstance(item, h5py.Group) and _nx_class(item) == want_class:
            return item
    return None


def _axis_cal_from_values(ds: h5py.Dataset) -> tuple[AxisCal, bool]:
    """Build an AxisCal from a 1D NeXus axis dataset (its sample spacing)."""
    units = attr_str(ds, "units")
    vals = np.asarray(ds[()], dtype=np.float64).ravel()
    if vals.size >= 2:
        scale, offset = float(vals[1] - vals[0]), float(vals[0])
    elif vals.size == 1:
        scale, offset = 1.0, float(vals[0])
    else:
        scale, offset = 1.0, 0.0
    return axiscal_from_offset_scale(offset, scale, units), (
        units.strip().lower() in ENERGY_UNITS
    )


def _find_nxdata(f: h5py.File) -> h5py.Group | None:
    """Walk root → NXentry → NXdata via the @default chain (NeXus rules)."""
    entry = _default_child(f, "NXentry")
    if entry is None:
        return None
    data = _default_child(entry, "NXdata")
    if data is not None:
        return data
    # NXem nests NXdata deeper — search for any NXdata under the entry
    for _name, obj in entry.items():
        if isinstance(obj, h5py.Group):
            nested = _default_child(obj, "NXdata")
            if nested is not None:
                return nested
    return None


def _build(
    signal: np.ndarray,
    axis_cals: list[tuple[AxisCal, bool]],
    meta: dict[str, Any],
    path: Path,
) -> DataStruct:
    ndim = signal.ndim
    if ndim >= 4:
        raise NexusFormatError(
            f"{path.name}: {ndim}-D signal {signal.shape} — 4D-STEM is not "
            f"supported by the 3D pipeline (see PLAN_4DSTEM)."
        )
    cals = [axis_cals[i][0] if i < len(axis_cals) else AxisCal() for i in range(ndim)]
    if ndim == 1:
        return DataStruct(
            data=signal.astype(np.float64, copy=False),
            kind=DataKind.SPECTRUM,
            axes=(cals[0],),
            metadata=meta,
        )
    if ndim == 2:
        return DataStruct(
            data=signal, kind=DataKind.IMAGE, axes=(cals[0], cals[1]), metadata=meta
        )
    e_dim = next(
        (i for i in range(3) if i < len(axis_cals) and axis_cals[i][1]), 2
    )
    y_dim, x_dim = sorted(set(range(3)) - {e_dim})
    cube = np.ascontiguousarray(np.moveaxis(signal, (y_dim, x_dim, e_dim), (0, 1, 2)))
    return DataStruct(
        data=cube,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(cals[y_dim], cals[x_dim], cals[e_dim]),
        metadata=meta,
    )


def load_nexus(path: str | Path) -> DataStruct:
    """Read a NeXus container, or fall back to the largest HDF5 dataset."""
    path = Path(path)
    with open(path, "rb") as fh:
        if not is_hdf5(fh.read(8)):
            raise NexusFormatError(f"not an HDF5/NeXus file: {path}")

    with h5py.File(path, "r") as f:
        meta: dict[str, Any] = {"source": str(path), "parser": "nexus"}
        nxdata = _find_nxdata(f)
        if nxdata is not None:
            signal_name = attr_str(nxdata, "signal")
            if signal_name and signal_name in nxdata:
                signal = np.asarray(nxdata[signal_name][()])
                axes_attr = nxdata.attrs.get("axes")
                axis_names = _axes_list(axes_attr)
                axis_cals = [
                    _axis_cal_from_values(nxdata[a])
                    if a and a in nxdata and a != "."
                    else (AxisCal(), False)
                    for a in axis_names
                ]
                meta["nexus_signal"] = signal_name
                return _build(signal, axis_cals, meta, path)

        # generic fallback: the largest numeric dataset, uncalibrated
        picked = largest_dataset(f, min_ndim=1, max_ndim=3)
        if picked is None:
            raise NexusFormatError(
                f"{path.name}: no plottable 1–3D dataset found"
            )
        sig_path, ds = picked
        signal = np.asarray(ds[()])
        meta["parser"] = "hdf5"
        meta["calibration"] = "none"
        meta["dataset_path"] = sig_path
        return _build(signal, [], meta, path)


def _axes_list(axes_attr: Any) -> list[str]:
    """Normalise a NeXus ``@axes`` attribute (scalar/bytes/array) to a list."""
    if axes_attr is None:
        return []
    if isinstance(axes_attr, (bytes, str)):
        return [axes_attr.decode() if isinstance(axes_attr, bytes) else axes_attr]
    arr = np.atleast_1d(axes_attr)
    return [a.decode() if isinstance(a, bytes) else str(a) for a in arr]


# ════════════════════════════════════════════════════════════════════
#  Shared-HDF5 dispatch hub
# ════════════════════════════════════════════════════════════════════

def _is_emd(f: h5py.File) -> bool:
    if "Data" in f and isinstance(f["Data"], h5py.Group):
        if {"Image", "Spectrum", "SpectrumStream", "Line"} & set(f["Data"]):
            return True
    has_emd = [False]

    def visit(_name: str, obj: h5py.HLObject) -> None:
        if isinstance(obj, h5py.Group) and "emd_group_type" in obj.attrs:
            has_emd[0] = True

    f.visititems(visit)
    return has_emd[0]


def _is_hspy(f: h5py.File) -> bool:
    if "Experiments" not in f or not isinstance(f["Experiments"], h5py.Group):
        return False
    return any(
        isinstance(f["Experiments"][k], h5py.Group) and "data" in f["Experiments"][k]
        for k in f["Experiments"]
    )


def load_hdf5_auto(path: str | Path) -> DataStruct:
    """Disambiguate a shared HDF5 extension (``.h5``/``.hdf5``/``.nxs``) by
    inspecting the tree, then route to the matching reader. EMD and HyperSpy
    layouts win over NeXus; everything else falls through to ``load_nexus``
    (NeXus rules, then the generic largest-dataset fallback)."""
    # local imports avoid a registry import cycle (registry → nexus → …)
    from fermiviewer.io.emd import load_emd
    from fermiviewer.io.hspy import load_hspy

    path = Path(path)
    with open(path, "rb") as fh:
        if not is_hdf5(fh.read(8)):
            raise NexusFormatError(f"not an HDF5 file: {path}")
    with h5py.File(path, "r") as f:
        if _is_emd(f):
            kind = "emd"
        elif _is_hspy(f):
            kind = "hspy"
        else:
            kind = "nexus"
    if kind == "emd":
        return load_emd(path)
    if kind == "hspy":
        return load_hspy(path)
    return load_nexus(path)
