"""Gwyddion native files (.gwy, "GWYP" serialization).

A .gwy file is the magic ``GWYP`` followed by one serialized object, a
``GwyContainer``. An object is its type name (NUL-terminated), a uint32
byte size, then components; a component is its name (NUL-terminated), a
one-character type and the value. Types: ``b`` bool (1 byte), ``c`` char,
``i`` int32, ``q`` int64, ``d`` double, ``s`` string, ``o`` object; upper
case is an array of that type preceded by a uint32 count. All little-endian.

Images are ``GwyDataField`` objects stored under ``/N/data`` with their
title in ``/N/data/title``: ``xres``/``yres`` pixels, ``xreal``/``yreal``
physical size and ``data`` (yres × xres doubles, top row first) in the
SI base units of ``si_unit_xy`` / ``si_unit_z`` (``GwySIUnit.unitstr``).
Since Gwyddion is also the common conversion target, this reader opens
anything that was exported to .gwy.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.spm_common import (
    length_to_nm_factor,
    primary_channel,
    spm_channel,
    unique_labels,
)

__all__ = ["GwyError", "load_gwy", "load_gwy_all", "read_gwy_container"]

_MAGIC = b"GWYP"
_SCALAR = {"b": ("<?", 1), "c": ("<c", 1), "i": ("<i", 4), "q": ("<q", 8), "d": ("<d", 8)}
_ARRAY = {"C": "u1", "I": "<i4", "Q": "<i8", "D": "<f8"}


class GwyError(ValueError):
    """Not a readable Gwyddion file."""


class _Reader:
    def __init__(self, buf: bytes) -> None:
        self.buf = buf
        self.pos = 0

    def cstring(self) -> str:
        end = self.buf.find(b"\0", self.pos)
        if end < 0:
            raise GwyError("truncated string")
        s = self.buf[self.pos:end].decode("utf-8", "replace")
        self.pos = end + 1
        return s

    def take(self, fmt: str, size: int) -> Any:
        if self.pos + size > len(self.buf):
            raise GwyError("file ends inside a value")
        v = struct.unpack_from(fmt, self.buf, self.pos)[0]
        self.pos += size
        return v

    def obj(self) -> dict[str, Any]:
        name = self.cstring()
        size = self.take("<I", 4)
        end = self.pos + size
        if end > len(self.buf):
            raise GwyError(f"object {name} runs past the end of the file")
        out: dict[str, Any] = {"__type__": name}
        while self.pos < end:
            key = self.cstring()
            out[key] = self.value(self.take("<c", 1).decode("ascii", "replace"))
        if self.pos != end:
            raise GwyError(f"object {name} size mismatch")
        return out

    def value(self, t: str) -> Any:
        if t in _SCALAR:
            fmt, size = _SCALAR[t]
            return self.take(fmt, size)
        if t == "s":
            return self.cstring()
        if t == "o":
            return self.obj()
        n = self.take("<I", 4)
        if t in _ARRAY:
            dt = np.dtype(_ARRAY[t])
            nbytes = n * dt.itemsize
            if self.pos + nbytes > len(self.buf):
                raise GwyError("array runs past the end of the file")
            arr = np.frombuffer(self.buf, dtype=dt, count=n, offset=self.pos)
            self.pos += nbytes
            return arr
        if t == "S":
            return [self.cstring() for _ in range(n)]
        if t == "O":
            return [self.obj() for _ in range(n)]
        raise GwyError(f"unknown component type {t!r}")


def read_gwy_container(path: str | Path) -> dict[str, Any]:
    """The top-level ``GwyContainer`` as nested dicts (arrays as numpy)."""
    buf = Path(path).read_bytes()
    if buf[:4] != _MAGIC:
        if buf[:4] == b"GWYO":
            raise GwyError("Gwyddion 1.x files are not supported — re-save in Gwyddion 2")
        raise GwyError("not a Gwyddion .gwy file")
    r = _Reader(buf)
    r.pos = 4
    return r.obj()


def _unit(field: dict[str, Any], key: str) -> str:
    u = field.get(key)
    return str(u.get("unitstr", "")) if isinstance(u, dict) else ""


def load_gwy_all(path: str | Path) -> list[DataStruct]:
    """Every data field (image channel) in the file, in channel order."""
    container = read_gwy_container(path)
    ids = sorted(int(m.group(1)) for k in container
                 if (m := re.fullmatch(r"/(\d+)/data", k)))
    out = []
    for i in ids:
        field = container[f"/{i}/data"]
        if not isinstance(field, dict) or field.get("__type__") != "GwyDataField":
            continue
        xres, yres = int(field.get("xres", 0)), int(field.get("yres", 0))
        data = field.get("data")
        if xres < 1 or yres < 1 or data is None or len(data) != xres * yres:
            raise GwyError(f"channel {i}: data does not match {xres}×{yres}")
        title = str(container.get(f"/{i}/data/title", f"Channel {i}"))
        lat = length_to_nm_factor(_unit(field, "si_unit_xy")) or float("nan")
        out.append(spm_channel(
            np.asarray(data, dtype=np.float64).reshape(yres, xres),
            parser="gwyddion", channel=title, label=title,
            value_unit=_unit(field, "si_unit_z"),
            dy_nm=float(field.get("yreal", np.nan)) * lat / yres,
            dx_nm=float(field.get("xreal", np.nan)) * lat / xres,
            gwy_channel_id=i,
        ))
    if not out:
        raise GwyError("the file holds no image channels")
    return unique_labels(out)


def load_gwy(path: str | Path) -> DataStruct:
    """The topography channel (or the first one)."""
    return primary_channel(load_gwy_all(path))
