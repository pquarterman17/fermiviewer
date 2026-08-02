"""HyperSpy-4D ``.hspy``/``.h5``/``.hdf5`` reader — PLAN_4DSTEM #2.

Reuses the same ``Experiments/<name>/data`` + ``axis-N`` layout that
``io/hspy.py`` already reads for <=3D signals (see that module's docstring
for the full format description) — this module is specifically the ndim==4
branch ``load_hspy`` deliberately rejects (``HspyFormatError`` "4D-STEM is
not supported by the 3D pipeline").

``is_fourd_hdf5`` is the content sniffer ``io/registry.py``'s
``is_fourd_path``/``load_fourd_auto`` use to route an ambiguous HDF5
extension (``.hspy``/``.h5``/``.hdf5``/``.nxs``/``.nx5``) here instead of
the existing <=3D loaders (EMD/HyperSpy-3D/NeXus/generic) — a <=3D or
non-HyperSpy file is left completely alone.

Axis order: HyperSpy always maps ``axis-i`` to data axis ``i``. Both real
corpus files (``twinned_nanowire.hdf5``, ``smallPtychography.hspy``) store
navigation (scan) axes first — ``axis-0``/``axis-1`` with
``navigate=True``, ``axis-2``/``axis-3`` with ``navigate=False`` — matching
HyperSpy's own convention of "navigation axes before signal axes" in the
array. Only that layout is implemented: if a file's ``navigate`` attributes
say otherwise, this raises rather than silently reordering (which would
require materializing the array to permute its axes, defeating the whole
point of staying lazy).

Lazy: keeps the ``h5py.File`` open and hands the ``FourDDataset`` the raw
``h5py.Dataset`` directly as its handle — ``h5py.Dataset`` already supports
the ``ds[y, x]`` / ``ds[row0:row1]`` access patterns ``FourDDataset`` needs,
so no adapter/copy is needed. The array is never read eagerly. Pure ``io/``
layer (h5py/numpy/stdlib).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import h5py
import numpy as np

from fermiviewer.calc.fourd.dataset import FourDDataset
from fermiviewer.datastruct import AxisCal
from fermiviewer.io.hdf5_common import attr_float, attr_str, is_hdf5

__all__ = ["Hspy4DFormatError", "is_fourd_hdf5", "load_hspy4d"]


class Hspy4DFormatError(ValueError):
    """Raised for unreadable / non-4D-HyperSpy files."""


def _any_experiment(f: h5py.File) -> h5py.Group | None:
    """First experiment group with any data array, regardless of ndim.

    Used only as a fallback to build a clear "N-D signal is not 4D-STEM"
    error message when the file has no 4D experiment at all — never to
    decide 4D-ness itself (see `_first_experiment`).
    """
    exps = f.get("Experiments")
    if not isinstance(exps, h5py.Group):
        return None
    for key in exps:
        node = exps[key]
        if isinstance(node, h5py.Group) and isinstance(node.get("data"), h5py.Dataset):
            return node
    return None


def _first_experiment(f: h5py.File) -> h5py.Group | None:
    """First experiment group whose data array is 4D, by iteration order.

    A single ``.hspy``/``.h5`` file can hold more than one HyperSpy signal
    under ``Experiments/``, and nothing requires the 4D-STEM one to be the
    first (or only) one present. Checking ndim HERE — not after picking
    "the first experiment with any data", as an earlier version did — is
    what makes a mixed file (e.g. a <=3D experiment sorted before a 4D one)
    resolve deterministically to its 4D signal instead of silently handing
    the whole file to the <=3D loader and losing the 4D signal entirely.
    Two 4D signals in one file resolve to the first by iteration order
    (h5py's default group ordering is alphabetical by name).
    """
    exps = f.get("Experiments")
    if not isinstance(exps, h5py.Group):
        return None
    for key in exps:
        node = exps[key]
        if isinstance(node, h5py.Group) and isinstance(node.get("data"), h5py.Dataset):
            if node["data"].ndim == 4:
                return node
    return None


def is_fourd_hdf5(path: str | Path) -> bool:
    """True if ``path`` is an HDF5 file holding a 4D HyperSpy signal.

    True as soon as ANY experiment in the file is 4D, regardless of how
    many other (non-4D) experiments it also holds or what order they're
    stored in — see `_first_experiment`. Never raises: an unreadable file,
    or one with no matching layout, is simply "not 4D" (the registry falls
    back to the existing <=3D loaders).
    """
    p = Path(path)
    try:
        with open(p, "rb") as fh:
            if not is_hdf5(fh.read(8)):
                return False
        with h5py.File(p, "r") as f:
            return _first_experiment(f) is not None
    except OSError:
        return False


def _axis_cal(grp: h5py.Group) -> AxisCal:
    scale = attr_float(grp, "scale", 1.0)
    offset = attr_float(grp, "offset", 0.0)
    units = attr_str(grp, "units")
    if not np.isfinite(scale) or scale == 0:
        return AxisCal(scale=1.0, origin=0.0, units="")
    origin = -offset / scale if np.isfinite(offset) else 0.0
    return AxisCal(scale=float(scale), origin=float(origin), units=units or "")


def _navigate_flag(grp: h5py.Group) -> bool:
    if "navigate" not in grp.attrs:
        return False
    return bool(np.asarray(grp.attrs["navigate"]).ravel()[0])


def load_hspy4d(path: str | Path) -> FourDDataset:
    """Open a 4D HyperSpy signal as a lazy ``FourDDataset``.

    Worst-case RAM: none up front — the ``h5py.File`` stays open and only
    the blocks a caller later requests (via ``FourDDataset.pattern`` /
    ``iter_scan_rows``) are ever read.
    """
    p = Path(path)
    with open(p, "rb") as fh:
        if not is_hdf5(fh.read(8)):
            raise Hspy4DFormatError(f"not an HDF5 file: {p}")

    f = h5py.File(p, "r")
    try:
        exp = _first_experiment(f)
        if exp is None:
            # No 4D experiment anywhere in the file — `_any_experiment` picks
            # whichever one DOES exist (if any) purely so the error message
            # can report its actual dimensionality instead of a generic
            # "no data array" that would be misleading for, say, a plain 2D
            # HyperSpy image.
            any_exp = _any_experiment(f)
            if any_exp is None:
                raise Hspy4DFormatError(f"{p.name}: no experiment with a data array")
            data = any_exp["data"]
            raise Hspy4DFormatError(
                f"{p.name}: {data.ndim}-D signal {data.shape} is not 4D-STEM"
            )
        data = exp["data"]  # guaranteed 4D by `_first_experiment`

        axis_groups: dict[int, h5py.Group] = {}
        for key in exp:
            if not key.startswith("axis-"):
                continue
            try:
                idx = int(key.split("-", 1)[1])
            except ValueError:
                continue
            node = exp[key]
            if isinstance(node, h5py.Group):
                axis_groups[idx] = node

        has_navigate_attrs = any("navigate" in g.attrs for g in axis_groups.values())
        if has_navigate_attrs:
            nav_axes = [
                i for i in range(4)
                if i in axis_groups and _navigate_flag(axis_groups[i])
            ]
            if nav_axes != [0, 1]:
                raise Hspy4DFormatError(
                    f"{p.name}: navigation axes {nav_axes} are not the "
                    "leading (0, 1) — only that HyperSpy 4D-STEM layout "
                    "(scan axes first, detector axes last) is implemented"
                )
        # else: no navigate attrs at all — fall back to the HyperSpy
        # convention (navigation axes before signal axes) with no reordering.

        blank = AxisCal()
        cals = [
            _axis_cal(axis_groups[i]) if i in axis_groups else blank
            for i in range(4)
        ]
        scan_axes = (cals[0], cals[1])
        det_axes = (cals[2], cals[3])
        scan_shape = (int(data.shape[0]), int(data.shape[1]))
        det_shape = (int(data.shape[2]), int(data.shape[3]))
        dtype = data.dtype

        meta: dict[str, Any] = {
            "source": str(p),
            "parser": "hspy4d",
            "hspy_experiment": exp.name.rsplit("/", 1)[-1],
        }
    except BaseException:
        f.close()
        raise

    return FourDDataset(
        handle=data,
        scan_shape=scan_shape,
        det_shape=det_shape,
        scan_axes=scan_axes,
        det_axes=det_axes,
        dtype=dtype,
        metadata=meta,
        close_fn=f.close,
    )
