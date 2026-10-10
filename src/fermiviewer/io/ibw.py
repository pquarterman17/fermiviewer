"""Igor binary waves (.ibw) as written by Asylum Research AFMs.

Layout (Igor Technical Note 003, version 5): a 64-byte ``BinHeader5``, a
320-byte ``WaveHeader5`` whose last field is the start of the wave data,
then the formula, the wave note, the extended units and the dimension
labels. Byte order is whichever makes ``version`` read as 5 (or 2/3 for
1-D legacy waves, which are not images and are refused).

Asylum stores a scan as one 3-D wave: points per line × lines × channels,
first dimension fastest (Fortran order), lines bottom to top. The channel
names are the labels of dimension 2 (e.g. ``HeightTrace``,
``AmplitudeRetrace``), the pixel sizes are ``sfA[0]``/``sfA[1]`` in
``dimUnits`` (m), and the wave note (``Key: value`` lines) carries the scan
parameters. Igor keeps one data unit per wave, so a channel's unit comes
from its name: heights, amplitudes and deflections are metres, phases
degrees.
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

__all__ = ["IbwError", "load_ibw", "load_ibw_all"]

_BIN5 = "h h i i i i 4i 4i i i i"            # 64 bytes
_WAVE5 = ("4x I I i h h 6x h 32s 4x 4x 4i 4d 4d 4s 16s h h d d "
          "4x 16x 16x 4x 64x h h h b b 4x i h h 4x 4x")   # 320 bytes (wData excluded)
_TYPES = {2: "f4", 4: "f8", 8: "i1", 0x10: "i2", 0x20: "i4",
          0x48: "u1", 0x50: "u2", 0x60: "u4"}
_LABEL = 32                                   # MAX_DIM_LABEL_CHARS + 1 in v5

# Asylum channel name prefix → unit of its values (ZSensor: see _unit_of)
_UNITS = (("height", "m"), ("amplitude", "m"), ("deflection", "m"),
          ("phase", "°"), ("current", "A"), ("potential", "V"), ("frequency", "Hz"))


class IbwError(ValueError):
    """Not a readable Asylum/Igor image wave."""


def _order(buf: bytes) -> str:
    for order in ("<", ">"):
        if struct.unpack_from(order + "h", buf, 0)[0] == 5:
            return order
    raise IbwError("not an Igor binary wave version 5 (only v5 holds AFM images)")


def _note(raw: bytes) -> dict[str, str]:
    out = {}
    for line in raw.decode("latin-1").replace("\r", "\n").split("\n"):
        key, sep, val = line.partition(":")
        if sep and key.strip():
            out[key.strip()] = val.strip()
    return out


def _unit_of(base: str, note: dict[str, str]) -> str:
    """Unit of a channel's values. The note names some (``UserIn0Unit``);
    ZSensor is metres only when the Z LVDT is calibrated (``ZLVDTSens`` >
    0) — otherwise Asylum saved the sensor voltage."""
    if note.get(f"{base}Unit"):
        return note[f"{base}Unit"]
    low = base.lower()
    if low.startswith("zsensor"):
        return "m" if (_float(note.get("ZLVDTSens")) or 0) > 0 else "V"
    return next((u for prefix, u in _UNITS if low.startswith(prefix)), "")


def _direction(name: str) -> tuple[str, str]:
    """('Height', 'trace') from 'HeightTrace' / 'HeightRetrace'."""
    for suffix, d in (("Retrace", "retrace"), ("Trace", "trace")):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)], d
    return name, ""


def load_ibw_all(path: str | Path) -> list[DataStruct]:
    """Every channel (layer) of an Asylum scan as a calibrated image."""
    buf = Path(path).read_bytes()
    if len(buf) < 384:
        raise IbwError("file too short for an Igor wave")
    o = _order(buf)
    (_ver, _ck, _wfm, formula_size, note_size, data_eunits_size, *rest) = struct.unpack_from(
        o + _BIN5.replace(" ", ""), buf, 0)
    dim_eunits_size, dim_labels_size = rest[0:4], rest[4:8]
    wave = struct.unpack_from(o + _WAVE5.replace(" ", ""), buf, 64)
    npnts, wtype = wave[2], wave[3]
    n_dim = [d for d in wave[7:11]]
    sf_a = wave[11:15]
    dim_units = [wave[20][i * 4:(i + 1) * 4].split(b"\0")[0].decode("latin-1") for i in range(4)]
    data_unit = wave[19].split(b"\0")[0].decode("latin-1")
    wave_name = wave[6].split(b"\0")[0].decode("latin-1")
    if wtype & 1:
        raise IbwError("complex waves are not images")
    dtype = _TYPES.get(wtype & ~1)
    if dtype is None:
        raise IbwError(f"unsupported Igor number type {wtype:#x}")
    if n_dim[0] < 2 or n_dim[1] < 2:
        raise IbwError("not an image wave (fewer than two dimensions)")
    if any(u and not length_to_nm_factor(u) for u in dim_units[:2]):
        # e.g. a force curve: time × (deflection, Z, …) columns
        raise IbwError("not an image wave (its axes are not lengths — a curve?)")
    if n_dim[2] > 1 and dim_units[2]:
        # a calibrated third axis (V, s, …) is a spectroscopy grid, not channels
        raise IbwError(f"spectroscopy grid ({n_dim[2]} points in {dim_units[2]}), not an image")
    n_layers = max(n_dim[2], 1)
    count = n_dim[0] * n_dim[1] * n_layers
    if count != npnts:
        raise IbwError("wave point count does not match its dimensions")
    dt = np.dtype(o + dtype)
    start = 64 + 320
    end = start + count * dt.itemsize
    if end > len(buf):
        raise IbwError("wave data runs past the end of the file")
    data = np.frombuffer(buf, dtype=dt, count=count, offset=start)
    cube = data.reshape((n_dim[0], n_dim[1], n_layers), order="F")

    pos = end + formula_size
    note = _note(buf[pos:pos + note_size])
    pos += note_size + data_eunits_size + sum(dim_eunits_size)
    labels: list[str] = []
    for d in range(4):
        size = dim_labels_size[d]
        if d == 2 and size:
            raw = buf[pos:pos + size]
            # label 0 names the dimension itself; then one per layer
            labels = [raw[i:i + _LABEL].split(b"\0")[0].decode("latin-1")
                      for i in range(_LABEL, size, _LABEL)]
        pos += size

    lat = length_to_nm_factor(dim_units[0]) or length_to_nm_factor("m") or 1.0
    dx_nm = abs(sf_a[0]) * lat if sf_a[0] else float("nan")
    dy_nm = abs(sf_a[1]) * lat if sf_a[1] else float("nan")
    out = []
    for k in range(n_layers):
        name = labels[k] if k < len(labels) and labels[k] else (
            wave_name if n_layers == 1 and wave_name else f"Channel {k + 1}")
        base, direction = _direction(name)
        image = np.flipud(cube[:, :, k].T)            # lines bottom-up → top row first
        out.append(spm_channel(
            image, parser="asylum", channel=base,
            label=f"{base} ({direction})" if direction else base,
            value_unit=_unit_of(base, note) or data_unit, dy_nm=dy_nm, dx_nm=dx_nm,
            line_direction=direction or None,
            scan_rate_hz=_float(note.get("ScanRate")),
            imaging_mode=note.get("ImagingMode") or None,
        ))
    return unique_labels(out)


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def load_ibw(path: str | Path) -> DataStruct:
    """The topography channel (height trace, or the first one)."""
    return primary_channel(load_ibw_all(path))
