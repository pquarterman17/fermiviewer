"""NT-MDT (Spectrum Instruments) .mdt files — Nova / Nova Px.

A 33-byte file header (magic ``01 b0 93 ff``, data size, last frame index)
then a chain of frames, each with a 22-byte header (size, type, version,
date, variable-block size). Two frame types hold images:

* type 0, *scanned* (Nova): axis scales (offset, step, unit code) for x, y
  and z, the scan parameters, then a frame-mode block with the image size
  and int16 data; value = z offset + z step · raw.
* type 106, *MDA* (Nova Px): a header of section sizes, the title, an
  XML comment, then dimension and measurand calibrations (name, unit,
  scale, bias, index range, data type); an image is 2 dimensions × 1
  measurand, value = bias + scale · raw.

Text, palette, spectroscopy and curve frames are skipped. Layout, unit
codes and data types follow Gwyddion's ``nt-mdt`` module; images are
stored bottom row first, as Gwyddion reads them.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.spm_common import (
    length_to_nm_factor,
    primary_channel,
    spm_channel,
    unique_labels,
)

__all__ = ["MdtError", "is_mdt", "load_mdt", "load_mdt_all"]

_MAGIC = b"\x01\xb0\x93\xff"
_FRAME_HEADER = 22
_SCANNED, _MDA = 0, 106

# unit codes of scanned frames (Gwyddion mdt_units, codes -10 … 39)
_UNIT_CODES = dict(zip(range(-10, 40), [
    "1/cm", "", "", "", "", "m", "cm", "mm", "µm", "nm", "Å", "nA", "V", "", "kHz", "deg",
    "%", "°C", "V", "s", "ms", "µs", "ns", "", "px", "", "", "", "", "", "A", "mA", "µA",
    "nA", "pA", "V", "mV", "µV", "nV", "pV", "N", "mN", "µN", "nN", "pN", "", "", "", "", "",
], strict=True))
_UNIT_CODES[1170] = "Hz"

# MDA data types (Gwyddion MDADataType)
_MDA_TYPES = {-1: "i1", 1: "u1", -2: "i2", 2: "u2", -4: "i4", 4: "u4", -8: "i8", 8: "u8",
              -(4 + 23 * 256): "f4", -(8 + 52 * 256): "f8"}
_SI_CODES = {0x101: "m", 0x100001: "A", 0xFFFD010200: "V", 0x1000001: "s"}


class MdtError(ValueError):
    """Not a readable NT-MDT file."""


def is_mdt(head: bytes) -> bool:
    return head[:4] == _MAGIC


def _u(fmt: str, buf: bytes, pos: int) -> tuple:
    try:
        return struct.unpack_from("<" + fmt, buf, pos)
    except struct.error:
        raise MdtError("frame runs past the end of the file") from None


def _scanned(buf: bytes, fstart: int, size: int, var: int) -> tuple[np.ndarray, dict] | None:
    p = fstart + _FRAME_HEADER
    (xo, xs, xu, yo, ys, yu, zo, zs, zu) = _u("ffhffhffh", buf, p)
    p = fstart + _FRAME_HEADER + var
    _mode, nx, ny, ndots = _u("4H", buf, p)
    p += 8
    if ndots:
        p += 14 + ndots * 16
    if nx < 2 or ny < 2 or p + 2 * nx * ny > fstart + size:
        return None
    raw = np.frombuffer(buf, dtype="<i2", count=nx * ny, offset=p)
    p += 2 * nx * ny
    title = ""
    if fstart + size - p > 4:
        (n,) = _u("I", buf, p)
        if 0 < n <= fstart + size - p - 4:
            title = buf[p + 4:p + 4 + n].decode("cp1251", "replace")
    zunit = _UNIT_CODES.get(zu, "")
    data = zo + (zs or 1.0) * raw.astype(np.float64)
    return data.reshape(ny, nx), {
        "title": title, "zunit": zunit,
        "dx": abs(xs) or 1.0, "dy": abs(ys) or 1.0, "xyunit": _UNIT_CODES.get(xu, ""),
    }


def _calibration(buf: bytes, p: int) -> tuple[dict, int]:
    tot, struct_len = _u("II", buf, p)
    body = p + 8
    name_len, comment_len, unit_len = _u("III", buf, body)
    si_unit, _acc = _u("Qd", buf, body + 12)
    bias, scale = _u("dd", buf, body + 12 + 16 + 8)
    lo, hi = _u("QQ", buf, body + 12 + 16 + 8 + 16)
    dtype, author_len = _u("iI", buf, body + 12 + 16 + 8 + 32)
    q = body + struct_len
    name = buf[q:q + name_len].decode("cp1251", "replace")
    q += name_len + comment_len
    unit = buf[q:q + unit_len].decode("cp1251", "replace")
    return ({"name": name, "unit": unit or _SI_CODES.get(si_unit, ""), "bias": bias,
             "scale": scale, "n": int(hi - lo + 1), "dtype": dtype}, p + tot)


def _mda(buf: bytes, fstart: int, size: int) -> tuple[np.ndarray, dict] | None:
    rec = fstart + _FRAME_HEADER
    head_size, _tot = _u("II", buf, rec)
    name_size, comm_size, view_size, spec_size, source_size = _u("5I", buf, rec + 8 + 36)
    p = rec + head_size
    title = buf[p:p + name_size].decode("cp1251", "replace")
    p += name_size + comm_size + spec_size + view_size + source_size
    p += 4                                              # total size
    (struct_len,) = _u("I", buf, p)
    sp = p + 4
    _array_size, _cell, n_dim, n_meas = _u("QIII", buf, sp)
    p = sp + struct_len
    if (n_dim, n_meas) != (2, 1):
        return None                                     # spectrum, Raman cube, …
    dims = []
    for _ in range(n_dim):
        cal, p = _calibration(buf, p)
        dims.append(cal)
    z, p = _calibration(buf, p)
    nx, ny = dims[0]["n"], dims[1]["n"]
    dt = _MDA_TYPES.get(z["dtype"])
    if dt is None or nx < 2 or ny < 2:
        return None
    count = nx * ny
    if p + count * np.dtype(dt).itemsize > fstart + size:
        raise MdtError("MDA image runs past the end of its frame")
    raw = np.frombuffer(buf, dtype="<" + dt, count=count, offset=p)
    data = z["bias"] + z["scale"] * raw.astype(np.float64)
    return data.reshape(ny, nx), {
        "title": title or z["name"], "zunit": z["unit"],
        "dx": abs(dims[0]["scale"]) or 1.0, "dy": abs(dims[1]["scale"]) or 1.0,
        "xyunit": dims[0]["unit"],
    }


def load_mdt_all(path: str | Path) -> list[DataStruct]:
    """Every image frame of the file."""
    buf = Path(path).read_bytes()
    if not is_mdt(buf) or len(buf) < 33:
        raise MdtError("not an NT-MDT .mdt file")
    (last,) = _u("H", buf, 12)
    p = 33
    out = []
    for i in range(last + 1):
        size, ftype = _u("IH", buf, p)
        (var,) = _u("H", buf, p + 20)
        if size < _FRAME_HEADER or p + size > len(buf):
            raise MdtError(f"frame {i} runs past the end of the file")
        found = (_scanned(buf, p, size, var) if ftype == _SCANNED
                 else _mda(buf, p, size) if ftype == _MDA else None)
        if found is not None:
            data, info = found
            lat = length_to_nm_factor(info["xyunit"]) or float("nan")
            title = info["title"].strip() or f"Frame {i + 1}"
            out.append(spm_channel(
                np.flipud(data), parser="ntmdt", channel=title, label=title,
                value_unit=info["zunit"], dy_nm=info["dy"] * lat, dx_nm=info["dx"] * lat,
                mdt_frame=i,
            ))
        p += size
    if not out:
        raise MdtError("the file holds no image frames")
    return unique_labels(out)


def load_mdt(path: str | Path) -> DataStruct:
    """The topography frame (Height/Topography, or the first image)."""
    return primary_channel(load_mdt_all(path))
