"""MRC2014 parser (first section of the volume).

Port of fermi-viewer's importMRC.m. Calibration is CELLA / MX in Ångströms
per pixel — the grid sampling, not the image width the MATLAB original
divided by. rosettasciio uses MX too (`Xlen / MX`, guarded on MX != 0), and
MRC2014 is explicit that the two need not agree. They do agree for a map
covering exactly one cell — every file in this project's corpus — and
diverge by the crop factor for anything that does not.
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


def _axis_cal(cell_len: float, sampling: int, n_px: int) -> AxisCal:
    """Å per pixel for one axis: CELLA / MX, per MRC2014.

    The divisor is the grid sampling MX, not the image width NX. The spec is
    explicit that MX "need not be the same as NX ... if the map doesn't cover
    exactly a single unit cell", so a cropped sub-volume calibrated by NX
    comes out wrong by exactly the crop factor. Writers that leave MX at 0
    fall back to NX, which is the only number left to divide by.
    """
    divisor = int(sampling) if int(sampling) > 0 else int(n_px)
    if not (float(cell_len) > 0 and divisor > 0):
        return AxisCal()
    return AxisCal(scale=float(cell_len) / divisor, units="A")


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

    # MX/MY/MZ (words 8-10) is the grid sampling the cell is divided into;
    # CELLA (words 11-13) is that cell's size in Ångströms.
    mxyz = np.frombuffer(buf, dtype=f"{bo}i4", count=3, offset=28)
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

    x_cal = _axis_cal(cella[0], mxyz[0], nx)
    y_cal = _axis_cal(cella[1], mxyz[1], ny)
    if not y_cal.calibrated:
        y_cal = x_cal  # square pixels — CELLA_Y is often left at 0

    return DataStruct(
        data=px.reshape(int(ny), int(nx)),
        kind=DataKind.IMAGE,
        axes=(y_cal, x_cal),
        metadata={
            "source": str(path),
            "parser": "mrc",
            "bit_depth": np.dtype(dt).itemsize * 8,
            "mrc_mode": int(mode),
            "mrc_byte_order": "big" if bo == ">" else "little",
            "n_sections": nz,
            "cella": [float(c) for c in cella],
            "mxyz": [int(m) for m in mxyz],
        },
    )
