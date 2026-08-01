"""Minimal synthetic DM5 (GMS 3.5+ HDF5) writer for parser tests.

h5py makes this tiny — no hand-rolled binary tag tree like minidm4.py needs
for the packed DM3/DM4 format. This fixture pins the structural mapping
``io/dm5.py`` documents (and, where undocumented, ASSUMES) for a real DM5
file: ``ImageList/<n>/ImageData/{Data, Calibrations/...}``, optional
``ImageTags``/``ImageDisplayInfo``.

``write_dm5`` takes ``data`` and ``cal`` in the same convention as
``fixtures.minidm4.write_mini_dm4``: ``cal[d]`` calibrates DM dimension
``d`` (dimension 0 fastest). Per ``io/dm5.py``'s ASSUMPTION 1, the HDF5
``Data`` dataset stores that dimension order REVERSED — so for rank >= 2,
`data` must already be shaped with DM dimension ``d`` at array axis
``(ndim − 1 − d)``, exactly like ``io/dm.py``'s post-reshape ``arr``
(``arr = px.reshape(dims[2], dims[1], dims[0])``). The
``write_dm5_spectrum_image`` helper below builds that array from a cube in
fermiviewer's canonical ``(y, x, energy)`` order so tests can reason in
canonical terms instead of DM's reversed storage order.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import h5py
import numpy as np

__all__ = ["write_dm5", "write_dm5_spectrum_image"]


def write_dm5(
    path: str | Path,
    data: np.ndarray,
    cal: list[dict[str, Any]] | None = None,
    *,
    index: int = 0,
    image_tags: dict[str, Any] | None = None,
    brightness: dict[str, Any] | None = None,
    display: dict[str, float] | None = None,
    extra_images: list[np.ndarray] | None = None,
) -> Path:
    """Write a minimal DM5 file with one ImageList entry.

    `data`: the array as it lands in the HDF5 `Data` dataset (DM-dimension-
    reversed order for rank >= 2 — see module docstring). `cal`: per-DM-
    dimension-index dicts with scale/origin/units (index 0 = fastest DM
    dimension). `extra_images` writes additional numeric ImageList entries
    (for the extra-images warning test).
    """
    out = Path(path)
    arr = np.asarray(data)
    with h5py.File(out, "w") as f:
        image_list = f.create_group("ImageList")
        entry = image_list.create_group(str(index))
        image_data = entry.create_group("ImageData")
        image_data.create_dataset("Data", data=arr)

        cal_grp = image_data.create_group("Calibrations")
        if cal:
            dim_grp = cal_grp.create_group("Dimension")
            for d, c in enumerate(cal):
                g = dim_grp.create_group(str(d))
                g.attrs["Scale"] = float(c.get("scale", 1.0))
                g.attrs["Origin"] = float(c.get("origin", 0.0))
                g.attrs["Units"] = str(c.get("units", ""))
        if brightness:
            bg = cal_grp.create_group("Brightness")
            bg.attrs["Origin"] = float(brightness.get("origin", 0.0))
            bg.attrs["Scale"] = float(brightness.get("scale", 1.0))
            bg.attrs["Units"] = str(brightness.get("units", ""))

        if image_tags:
            _write_tags(entry.create_group("ImageTags"), image_tags)
        if display:
            disp = entry.create_group("ImageDisplayInfo")
            for k, v in display.items():
                disp.attrs[k] = v

        for offset, extra in enumerate(extra_images or [], start=1):
            xentry = image_list.create_group(str(index + offset))
            xdata = xentry.create_group("ImageData")
            xdata.create_dataset("Data", data=np.asarray(extra))
    return out


def _write_tags(grp: h5py.Group, tags: dict[str, Any]) -> None:
    for k, v in tags.items():
        if isinstance(v, dict):
            _write_tags(grp.create_group(k), v)
        else:
            grp.attrs[k] = v


def write_dm5_spectrum_image(
    path: str | Path,
    cube: np.ndarray,
    y_cal: dict[str, Any],
    x_cal: dict[str, Any],
    e_cal: dict[str, Any],
    *,
    e_dm_index: int = 2,
    **kwargs: Any,
) -> Path:
    """Write a 3D DM5 spectrum-image from a cube already in fermiviewer's
    canonical (y, x, energy) order, placing the energy DM dimension at
    `e_dm_index` (0/1/2) rather than always last — exercises `_energy_dim`'s
    units-based detection when e_dm_index != 2.

    Internally reverses to the DM-dimension storage order `io/dm5.py`
    (ASSUMPTION 1) and `io/dm.py` share: DM dimension `d` -> array axis
    `(2 − d)`.
    """
    remaining = sorted({0, 1, 2} - {e_dm_index})
    x_dm_index, y_dm_index = remaining[0], remaining[1]  # faster spatial dim = x
    # cube's own axis (0=y, 1=x, 2=energy) holding each DM dimension's data
    cube_axis_of_dm_dim = {y_dm_index: 0, x_dm_index: 1, e_dm_index: 2}
    arr = np.ascontiguousarray(
        cube.transpose(
            cube_axis_of_dm_dim[2], cube_axis_of_dm_dim[1], cube_axis_of_dm_dim[0]
        )
    )
    cal_by_dm_index: list[dict[str, Any]] = [{}, {}, {}]
    cal_by_dm_index[y_dm_index] = y_cal
    cal_by_dm_index[x_dm_index] = x_cal
    cal_by_dm_index[e_dm_index] = e_cal
    return write_dm5(path, arr, cal_by_dm_index, **kwargs)
