"""Gwyddion native files (.gwy, "GWYP" serialization; Gwyddion 1.x "GWYO").

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

__all__ = ["GwyError", "load_gsf", "load_gwy", "load_gwy_all", "read_gwy_container"]

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
        raw = self.buf[self.pos:end]
        try:
            s = raw.decode("utf-8")
        except UnicodeDecodeError:                  # Gwyddion 1.x wrote Latin-1 (µm)
            s = raw.decode("latin-1")
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
    r = _Reader(buf)
    r.pos = 4
    if buf[:4] == _MAGIC:
        return r.obj()
    if buf[:4] == b"GWYO":
        return _old_container(r)
    raise GwyError("not a Gwyddion .gwy file")


# Gwyddion 1.x ("GWYO") containers store each item as its GType code, key
# and value; the objects inside serialize as in Gwyddion 2.
_OLD_TYPES = {20: ("<I", 4), 12: ("<b", 1), 16: ("<B", 1), 24: ("<i", 4), 28: ("<I", 4),
              40: ("<q", 8), 44: ("<Q", 8), 60: ("<d", 8)}
_G_STRING, _G_OBJECT = 64, 80


def _old_container(r: _Reader) -> dict[str, Any]:
    name = r.cstring()
    if name != "GwyContainer":
        raise GwyError("Gwyddion 1.x file without a container")
    size = r.take("<I", 4)
    end = r.pos + size
    out: dict[str, Any] = {"__type__": name}
    while r.pos < end:
        gtype = r.take("<I", 4)
        key = r.cstring()
        if gtype == _G_STRING:
            out[key] = r.cstring()
        elif gtype == _G_OBJECT:
            out[key] = r.obj()
        elif gtype in _OLD_TYPES:
            out[key] = r.take(*_OLD_TYPES[gtype])
        else:
            raise GwyError(f"Gwyddion 1.x item {key!r} has unknown type {gtype}")
    return out


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


_GSF_MAGIC = b"Gwyddion Simple Field 1.0\n"


def load_gsf(path: str | Path) -> DataStruct:
    """Gwyddion Simple Field (.gsf): ``Key = value`` text lines after the
    magic line, NUL padding to a multiple of 4 bytes, then XRes × YRes
    little-endian float32 values, top row first, in ZUnits."""
    buf = Path(path).read_bytes()
    if not buf.startswith(_GSF_MAGIC):
        raise GwyError("not a Gwyddion Simple Field file")
    end = buf.find(b"\0")
    if end < 0:
        raise GwyError("GSF header is not NUL-terminated")
    meta: dict[str, str] = {}
    for line in buf[len(_GSF_MAGIC):end].decode("utf-8", "replace").splitlines():
        key, sep, val = line.partition("=")
        if sep:
            meta[key.strip()] = val.strip()
    try:
        xres, yres = int(meta["XRes"]), int(meta["YRes"])
    except (KeyError, ValueError):
        raise GwyError("GSF header lacks XRes/YRes") from None
    start = (end // 4 + 1) * 4                         # padding: 1–4 NULs
    if start + 4 * xres * yres > len(buf):
        raise GwyError("GSF data runs past the end of the file")
    data = np.frombuffer(buf, dtype="<f4", count=xres * yres, offset=start)
    lat = length_to_nm_factor(meta.get("XYUnits", "m")) or float("nan")
    title = meta.get("Title", "") or Path(path).stem
    return spm_channel(
        data.reshape(yres, xres), parser="gwyddion", channel=title, label=title,
        value_unit=meta.get("ZUnits", ""),
        dy_nm=float(meta.get("YReal", "nan")) * lat / yres,
        dx_nm=float(meta.get("XReal", "nan")) * lat / xres,
    )
