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


def _byte_order(buf: bytes) -> str:
    """MRC2014 machine stamp (header bytes 212-215): 0x44 0x44 → little-endian,
    0x11 0x11 → big-endian (the other two bytes are unspecified/ignored). Many
    writers leave this field as zero/junk, so an unrecognised stamp is not an
    error — default to little-endian (the overwhelmingly common case)."""
    stamp = buf[212:214]
    if stamp == b"\x11\x11":
        return ">"
    return "<"


def load_mrc(path: str | Path) -> DataStruct:
    path = Path(path)
    buf = path.read_bytes()
    if len(buf) < _HEADER:
        raise ValueError(f"empty or truncated MRC file: {path}")

    bo = _byte_order(buf)
    nx, ny, nz, mode = np.frombuffer(buf, dtype=f"{bo}i4", count=4)
    if nx <= 0 or ny <= 0:
        raise ValueError(f"invalid MRC dimensions NX={nx} NY={ny}: {path}")
    nz = max(int(nz), 1)
    if int(mode) not in _MODES:
        raise ValueError(f"unsupported MRC MODE {mode}: {path}")
    dt = _MODES[int(mode)]

    cella = np.frombuffer(buf, dtype=f"{bo}f4", count=3, offset=40)
    map_stamp = buf[208:212]
    if map_stamp != b"MAP ":
        warnings.warn(
            f'{path.name}: MAP field is {map_stamp!r} instead of b"MAP " — '
            "file may not be MRC2014 compliant",
            stacklevel=2,
        )
    nsymbt = max(int(np.frombuffer(buf, dtype=f"{bo}i4", count=1, offset=92)[0]), 0)

    n = int(nx) * int(ny)
    data_start = _HEADER + nsymbt
    avail = (len(buf) - data_start) // np.dtype(dt).itemsize
    px = np.frombuffer(buf, dtype=f"{bo}{dt}", count=min(n, max(avail, 0)), offset=data_start)
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
            "mrc_byte_order": "big" if bo == ">" else "little",
            "n_sections": nz,
            "cella": [float(c) for c in cella],
        },
    )
