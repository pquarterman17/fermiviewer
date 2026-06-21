"""Shared HDF5 helpers for the interchange-format readers (Data-Formats #1).

EMD, DM5, NeXus, and ``.hspy`` are all HDF5 containers, so they share one
``h5py`` dependency and this small toolbox: a magic-byte sniffer, a recursive
dataset walker, attribute decoding, a "largest plottable array" picker for the
generic fallback, and the offset/scale → fermiviewer-`AxisCal` conversion.

Pure-library module: ``h5py`` / numpy / stdlib only (layering guard applies).
All callers open the file themselves (``with h5py.File(path) as f:``) and pass
groups in — this module never touches the route/server stack.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import h5py
import numpy as np

from fermiviewer.datastruct import AxisCal

__all__ = [
    "HDF5_MAGIC",
    "attr_float",
    "attr_str",
    "axiscal_from_offset_scale",
    "is_hdf5",
    "iter_datasets",
    "largest_dataset",
]

# HDF5 superblock signature (first 8 bytes of every HDF5 file)
HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"


def is_hdf5(head: bytes) -> bool:
    """True if a byte head begins with the HDF5 signature."""
    return head[: len(HDF5_MAGIC)] == HDF5_MAGIC


def _decode(v: Any) -> Any:
    """Decode an h5py attribute/scalar: bytes → str, 0-d/1-elem arrays →
    their scalar, leaving everything else untouched."""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, np.ndarray):
        if v.shape == ():
            return _decode(v[()])
        if v.size == 1:
            return _decode(v.reshape(-1)[0])
    if isinstance(v, np.generic):
        return v.item()
    return v


def attr_str(obj: h5py.HLObject, key: str, default: str = "") -> str:
    """Read an attribute as a clean str (decoding bytes); default if absent."""
    if key not in obj.attrs:
        return default
    val = _decode(obj.attrs[key])
    return str(val) if val is not None else default


def attr_float(obj: h5py.HLObject, key: str, default: float = float("nan")) -> float:
    """Read an attribute as a float; default (NaN) if absent/unparseable."""
    if key not in obj.attrs:
        return default
    try:
        return float(_decode(obj.attrs[key]))
    except (TypeError, ValueError):
        return default


def iter_datasets(
    node: h5py.Group, prefix: str = ""
) -> Iterator[tuple[str, h5py.Dataset]]:
    """Recursively yield ``(path, dataset)`` for every dataset under a group.

    Paths are POSIX-style ('/a/b/data'). Soft/external links that fail to
    resolve are skipped rather than raising, so a partially-broken file still
    yields its readable datasets."""
    for key in node:
        try:
            item = node[key]
        except (KeyError, OSError):
            continue  # dangling link
        path = f"{prefix}/{key}"
        if isinstance(item, h5py.Group):
            yield from iter_datasets(item, path)
        elif isinstance(item, h5py.Dataset):
            yield path, item


def largest_dataset(
    node: h5py.Group, min_ndim: int = 1, max_ndim: int = 3
) -> tuple[str, h5py.Dataset] | None:
    """The numeric dataset with the most elements whose ndim is in
    [min_ndim, max_ndim] — the generic "open anything HDF5" fallback. Ignores
    non-numeric (string/compound) datasets. Returns None if nothing qualifies."""
    best: tuple[str, h5py.Dataset] | None = None
    best_size = -1
    for path, ds in iter_datasets(node):
        if ds.dtype.kind not in "fiu":  # float / signed / unsigned int only
            continue
        if not (min_ndim <= ds.ndim <= max_ndim):
            continue
        if ds.size > best_size:
            best_size = ds.size
            best = (path, ds)
    return best


def axiscal_from_offset_scale(
    offset: float, scale: float, units: str
) -> AxisCal:
    """Convert an HDF5 ``value = index*scale + offset`` axis to fermiviewer's
    ``value = (index − origin) × scale`` convention (origin = −offset/scale).

    A zero/NaN scale yields an uncalibrated axis (scale 1, no units)."""
    if not np.isfinite(scale) or scale == 0:
        return AxisCal(scale=1.0, origin=0.0, units="")
    origin = -offset / scale if np.isfinite(offset) else 0.0
    return AxisCal(scale=float(scale), origin=float(origin), units=units or "")
