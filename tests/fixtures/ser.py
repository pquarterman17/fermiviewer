"""Synthetic TIA SER file generators for tests.

Writes minimal but valid little-endian SER files exercising the 0x4120
(1-D spectrum) path — a single spectrum and a scanned spectrum image — with
analytically checkable data and energy calibration. Mirrors the nanoscope /
minidm4 fixture pattern. (The 0x4122 image path is covered by the committed
`test_ser.ser` golden.)
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

# SER integer DataType → (struct code, numpy dtype)
_U4 = 3  # uint32


def _spectrum_element(cal_offset: float, cal_delta: float, cal_element: int,
                      values: list[int]) -> bytes:
    body = struct.pack("<ddi", cal_offset, cal_delta, cal_element)
    body += struct.pack("<h", _U4)              # DataType i16
    body += struct.pack("<i", len(values))      # ArrayLength i32
    body += b"".join(struct.pack("<I", v) for v in values)
    return body


def write_ser_spectra(path: Path, *, scan_dims: list[int], n_channels: int,
                      cal_offset: float = -20.0, cal_delta: float = 0.2,
                      cal_element: int = 0) -> dict[str, Any]:
    """Write a 0x4120 SER. scan_dims=[] → single spectrum; [n] → line profile;
    [ny, nx] → 2-D spectrum image. Channel c of element k holds value k*100+c,
    so per-element and total sums are analytically known."""
    n_elem = 1
    for d in scan_dims:
        n_elem *= d

    # ── lay out the byte offsets ──
    ndim = len(scan_dims)
    dim_bytes = b""
    for size in scan_dims:
        dim_bytes += struct.pack("<i", size)                 # DimensionSize
        dim_bytes += struct.pack("<dd", 0.0, 1.0)            # cal offset, delta
        dim_bytes += struct.pack("<i", 0)                    # cal element
        dim_bytes += struct.pack("<i", 0)                    # DescriptionLength
        dim_bytes += struct.pack("<i", 0)                    # UnitsLength
    header_len = 30 + len(dim_bytes)  # fixed header (narrow) + dimension array
    off_arr = header_len
    osize = 4  # narrow (version 0x0210)
    offarr_len = n_elem * osize * 2  # data offsets + tag offsets
    data_start = off_arr + offarr_len

    elements = []
    values_per_elem = []
    cur = data_start
    data_offsets = []
    for k in range(n_elem):
        vals = [k * 100 + c for c in range(n_channels)]
        values_per_elem.append(vals)
        el = _spectrum_element(cal_offset, cal_delta, cal_element, vals)
        elements.append(el)
        data_offsets.append(cur)
        cur += len(el)

    # ── fixed header (narrow, version 0x0210) ──
    head = struct.pack("<HH", 0x4949, 0x0197)   # ByteOrder, SeriesID
    head += struct.pack("<H", 0x0210)           # Version (narrow offsets)
    head += struct.pack("<I", 0x4120)           # DataTypeID (1-D spectrum)
    head += struct.pack("<I", 0)                # TagTypeID
    head += struct.pack("<I", n_elem)           # TotalElements
    head += struct.pack("<I", n_elem)           # ValidElements
    head += struct.pack("<I", off_arr)          # OffsetArrayOffset
    head += struct.pack("<I", ndim)             # NumberDimensions
    head += dim_bytes

    offarr = b"".join(struct.pack("<I", o) for o in data_offsets)
    offarr += b"".join(struct.pack("<I", 0) for _ in range(n_elem))  # tag offsets
    path.write_bytes(head + offarr + b"".join(elements))

    total = sum(sum(v) for v in values_per_elem)
    # AxisCal origin so that (i − origin)·delta == offset + (i − element)·delta
    origin = cal_element - cal_offset / cal_delta
    return {
        "n_elem": n_elem,
        "n_channels": n_channels,
        "scan_dims": scan_dims,
        "total": total,
        "energy_scale": cal_delta,
        "energy_origin": origin,
        "energy0": (0 - origin) * cal_delta,  # == cal_offset
        "values_per_elem": values_per_elem,
    }
