"""HyperSpy ``.hspy`` reader (read-only) — Data-Formats #6.

``.hspy`` is HDF5 with a HyperSpy layout: ``Experiments/<name>/`` holding a
``data`` array plus ``axis-0..N`` groups (each with ``size``/``scale``/
``offset``/``units``/``name``/``navigate`` attrs). HyperSpy's ``navigate=True``
axes are spatial; the signal axis with energy units is the spectral axis.

Maps to a canonical ``DataStruct``: 2D image / 1D spectrum / 3D
``(y, x, energy)`` SI. 4D (a 4D-STEM signal) raises a clear PLAN_4DSTEM error.
Pure ``io/`` layer (h5py/numpy/stdlib). Read-only — no HyperSpy dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import h5py
import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.hdf5_common import (
    attr_float,
    attr_str,
    axiscal_from_offset_scale,
    is_hdf5,
)

__all__ = ["HspyFormatError", "load_hspy"]

ENERGY_UNITS = {"ev", "kev", "mev"}


class HspyFormatError(ValueError):
    """Raised for unreadable / non-HyperSpy ``.hspy`` files."""


def _axis_meta(grp: h5py.Group) -> dict[int, dict[str, Any]]:
    """Read every ``axis-<i>`` sub-group's HyperSpy attributes."""
    axes: dict[int, dict[str, Any]] = {}
    for key in grp:
        if not key.startswith("axis-"):
            continue
        try:
            idx = int(key.split("-", 1)[1])
        except ValueError:
            continue
        a = grp[key]
        axes[idx] = {
            "scale": attr_float(a, "scale", 1.0),
            "offset": attr_float(a, "offset", 0.0),
            "units": attr_str(a, "units"),
            "name": attr_str(a, "name"),
            "navigate": bool(np.asarray(a.attrs.get("navigate", False)).ravel()[0])
            if "navigate" in a.attrs
            else False,
        }
    return axes


def _is_energy(a: dict[str, Any]) -> bool:
    return a["units"].strip().lower() in ENERGY_UNITS or a["name"].strip().lower() in {
        "energy",
        "energy loss",
    }


def _cal(a: dict[str, Any]) -> AxisCal:
    return axiscal_from_offset_scale(a["offset"], a["scale"], a["units"])


def _first_experiment(f: h5py.File) -> h5py.Group:
    if "Experiments" not in f or not isinstance(f["Experiments"], h5py.Group):
        raise HspyFormatError("no /Experiments group — not a .hspy file")
    exps = f["Experiments"]
    for key in exps:
        node = exps[key]
        if isinstance(node, h5py.Group) and "data" in node:
            return node
    raise HspyFormatError("no experiment with a data array")


def load_hspy(path: str | Path) -> DataStruct:
    """Parse a HyperSpy ``.hspy`` file into a ``DataStruct``."""
    path = Path(path)
    with open(path, "rb") as fh:
        if not is_hdf5(fh.read(8)):
            raise HspyFormatError(f"not an HDF5/.hspy file: {path}")

    with h5py.File(path, "r") as f:
        exp = _first_experiment(f)
        data = np.asarray(exp["data"][()])
        axes = _axis_meta(exp)
        meta: dict[str, Any] = {
            "source": str(path),
            "parser": "hspy",
            "hspy_experiment": exp.name.rsplit("/", 1)[-1],
        }
        ndim = data.ndim
        if ndim >= 4:
            raise HspyFormatError(
                f"{path.name}: {ndim}-D signal {data.shape} — 4D-STEM is not "
                f"supported by the 3D pipeline (see PLAN_4DSTEM)."
            )

        # axis-<i> maps to data axis i (HyperSpy stores them in array order)
        blank = {"scale": 1.0, "offset": 0.0, "units": "", "name": ""}
        cals = [_cal(axes.get(i, blank)) for i in range(ndim)]

        if ndim == 1:
            return DataStruct(
                data=data.astype(np.float64, copy=False),
                kind=DataKind.SPECTRUM,
                axes=(cals[0],),
                metadata=meta,
            )
        if ndim == 2:
            return DataStruct(
                data=data,
                kind=DataKind.IMAGE,
                axes=(cals[0], cals[1]),
                metadata=meta,
            )
        # 3D: the energy axis is the signal axis with energy units; move last
        e_dim = next(
            (i for i in range(3) if i in axes and _is_energy(axes[i])), 2
        )
        y_dim, x_dim = sorted(set(range(3)) - {e_dim})
        cube = np.ascontiguousarray(
            np.moveaxis(data, (y_dim, x_dim, e_dim), (0, 1, 2))
        )
        return DataStruct(
            data=cube,
            kind=DataKind.SPECTRUM_IMAGE,
            axes=(cals[y_dim], cals[x_dim], cals[e_dim]),
            metadata=meta,
        )
