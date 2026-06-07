"""MRC2014 parser (first section of the volume).

Port of fermi-viewer's importMRC.m. Calibration = CELLA_X / NX in
Ångströms per pixel.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

__all__ = ["load_mrc"]

_MODES = {0: "i1", 1: "i2", 2: "f4", 6: "u2"}
_HEADER = 1024


def load_mrc(path: str | Path) -> DataStruct:
    path = Path(path)
    buf = path.read_bytes()
    if len(buf) < _HEADER:
        raise ValueError(f"empty or truncated MRC file: {path}")

    nx, ny, nz, mode = np.frombuffer(buf, dtype="<i4", count=4)
    if nx <= 0 or ny <= 0:
        raise ValueError(f"invalid MRC dimensions NX={nx} NY={ny}: {path}")
    nz = max(int(nz), 1)
    if int(mode) not in _MODES:
        raise ValueError(f"unsupported MRC MODE {mode}: {path}")
    dt = _MODES[int(mode)]

    cella = np.frombuffer(buf, dtype="<f4", count=3, offset=40)
    map_stamp = buf[208:212]
    if map_stamp != b"MAP ":
        warnings.warn(
            f'{path.name}: MAP field is {map_stamp!r} instead of b"MAP " — '
            "file may not be MRC2014 compliant",
            stacklevel=2,
        )
    nsymbt = max(int(np.frombuffer(buf, dtype="<i4", count=1, offset=92)[0]), 0)

    n = int(nx) * int(ny)
    data_start = _HEADER + nsymbt
    avail = (len(buf) - data_start) // np.dtype(dt).itemsize
    px = np.frombuffer(buf, dtype=f"<{dt}", count=min(n, max(avail, 0)), offset=data_start)
    if px.size < n:
        warnings.warn(f"{path.name}: short read, zero-padding", stacklevel=2)
        px = np.concatenate([px, np.zeros(n - px.size, dtype=px.dtype)])

    if cella[0] > 0:
        cal = AxisCal(scale=float(cella[0]) / int(nx), units="A")
    else:
        cal = AxisCal()

    return DataStruct(
        data=px.reshape(int(ny), int(nx)),
        kind=DataKind.IMAGE,
        axes=(cal, cal),
        metadata={
            "source": str(path),
            "parser": "mrc",
            "bit_depth": np.dtype(dt).itemsize * 8,
            "mrc_mode": int(mode),
            "n_sections": nz,
            "cella": [float(c) for c in cella],
        },
    )
