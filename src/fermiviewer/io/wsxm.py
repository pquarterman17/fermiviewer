"""WSxM / Nanotec images (.top, .stp, and other WSxM channel files).

A WSxM image is an ASCII header — it starts ``WSxM file copyright`` and
states ``Image header size: N`` near the top — followed by rows × columns
little-endian values of ``Image Data Type`` (``short``/``integer`` int16,
``float``, ``double``). The header is ``[Section]`` blocks of
``Key: value`` lines; ``Control::X/Y Amplitude`` give the scan size and
``General Info::Z Amplitude`` the height range, both with a unit.

Scaling and orientation follow Gwyddion's ``wsxmfile`` module, the
reference implementation: floating-point data is already in the Z
Amplitude unit; integer data spans the Z Amplitude over its own
minimum-to-maximum; and the pixels are stored last-first, so the image is
rotated by 180°. One file is one channel (WSxM saves each channel to its
own file).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.spm_common import length_to_nm_factor, spm_channel

__all__ = ["WsxmError", "is_wsxm", "load_wsxm", "load_wsxm_all"]

_TYPES = {"short": "<i2", "integer": "<i2", "int": "<i4", "float": "<f4", "double": "<f8"}
_QTY = re.compile(r"\s*([-+0-9.eE]+)\s*(.*)$")


class WsxmError(ValueError):
    """Not a readable WSxM image."""


def is_wsxm(head: bytes) -> bool:
    return head.startswith(b"WSxM file copyright")


def _header(buf: bytes) -> dict[str, str]:
    m = re.search(rb"Image header size:\s*(\d+)", buf[:300])
    if not m:
        raise WsxmError("not a WSxM image (no header size)")
    size = int(m.group(1))
    if size > len(buf):
        raise WsxmError("header runs past the end of the file")
    out: dict[str, str] = {"__size__": str(size)}
    section = ""
    for line in buf[:size].decode("latin-1").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        elif ":" in line and section:
            key, _, val = line.partition(":")
            out[f"{section}::{key.strip()}"] = val.strip()
    return out


def _quantity(text: str | None) -> tuple[float, str]:
    m = _QTY.match(text or "")
    if not m:
        return float("nan"), ""
    return float(m.group(1)), m.group(2).strip()


def load_wsxm_all(path: str | Path) -> list[DataStruct]:
    """The file's one channel, as a list like the other SPM readers."""
    buf = Path(path).read_bytes()
    if not is_wsxm(buf):
        raise WsxmError("not a WSxM image")
    h = _header(buf)
    try:
        cols = int(h["General Info::Number of columns"])
        rows = int(h["General Info::Number of rows"])
    except (KeyError, ValueError):
        raise WsxmError("image size missing from the header") from None
    kind = h.get("General Info::Image Data Type", "short").lower()
    if kind not in _TYPES:
        raise WsxmError(f"unsupported WSxM data type {kind!r}")
    dt = np.dtype(_TYPES[kind])
    start = int(h["__size__"])
    if start + rows * cols * dt.itemsize > len(buf):
        raise WsxmError("image data runs past the end of the file")
    raw = np.frombuffer(buf, dtype=dt, count=rows * cols, offset=start)
    data = raw.reshape(rows, cols)[::-1, ::-1].astype(np.float64)   # stored last pixel first

    zamp, zunit = _quantity(h.get("General Info::Z Amplitude"))
    if zunit == "Pi":                                   # phase in units of π
        zamp, zunit = zamp * np.pi, "rad"
    elif zunit == "a.u.":
        zunit = ""
    if dt.kind == "i" and np.isfinite(zamp):
        span = float(data.max() - data.min())
        data = data * (zamp / span) if span > 0 else data * 0.0
    xamp, xunit = _quantity(h.get("Control::X Amplitude"))
    yamp, yunit = _quantity(h.get("Control::Y Amplitude") or h.get("Control::X Amplitude"))
    xf = length_to_nm_factor(xunit) or float("nan")
    yf = length_to_nm_factor(yunit) or float("nan")
    channel = h.get("General Info::Acquisition channel") or Path(path).suffix.lstrip(".").upper()
    direction = h.get("General Info::X scanning direction", "").lower()
    direction = {"forward": "trace", "backward": "retrace"}.get(direction, "")
    return [spm_channel(
        data, parser="wsxm", channel=channel,
        label=f"{channel} ({direction})" if direction else channel,
        value_unit=zunit, dy_nm=yamp * yf / rows, dx_nm=xamp * xf / cols,
        line_direction=direction or None,
    )]


def load_wsxm(path: str | Path) -> DataStruct:
    return load_wsxm_all(path)[0]
