"""Synthetic TIA SER file generators for tests.

Writes minimal but valid SER files exercising both TIA element kinds — 0x4120
1-D spectra (a single spectrum and a scanned spectrum image) and 0x4122 2-D
images — with analytically checkable data and energy calibration. Mirrors the
nanoscope / minidm4 fixture pattern. Supports both the narrow (version
< 0x0220, 4-byte offsets) and wide (>= 0x0220, 8-byte offsets) header layouts.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np

# SER integer DataType → numpy dtype (see fermiviewer.io.ser._DTYPES)
_U4 = 3  # uint32
_DTYPE_ITEMSIZE = {1: 1, 2: 2, 3: 4, 4: 1, 5: 2, 6: 4, 7: 4, 8: 8}
_DTYPE_NUMPY = {1: "u1", 2: "u2", 3: "u4", 4: "i1", 5: "i2", 6: "i4", 7: "f4", 8: "f8"}


def _offsize(version: int) -> tuple[bool, str]:
    wide = version >= 0x0220
    return wide, "Q" if wide else "I"


def _spectrum_element(cal_offset: float, cal_delta: float, cal_element: int,
                      values: list[int], dtype_code: int = _U4) -> bytes:
    body = struct.pack("<ddi", cal_offset, cal_delta, cal_element)
    body += struct.pack("<h", dtype_code)       # DataType i16
    body += struct.pack("<i", len(values))      # ArrayLength i32
    body += b"".join(struct.pack("<I", v) for v in values)
    return body


def write_ser_spectra(path: Path, *, scan_dims: list[int], n_channels: int,
                      cal_offset: float = -20.0, cal_delta: float = 0.2,
                      cal_element: int = 0, version: int = 0x0210,
                      valid_elements: int | None = None,
                      channel_dtype_code: int = _U4) -> dict[str, Any]:
    """Write a 0x4120 SER. scan_dims=[] → single spectrum; [n] → line profile;
    [ny, nx] → 2-D spectrum image. Channel c of element k holds value k*100+c,
    so per-element and total sums are analytically known.

    `version` >= 0x0220 selects the wide (8-byte) offset-array layout.
    `valid_elements` overrides the header's ValidElements field independent
    of the actual element count written (for the no-valid-elements guard).
    `channel_dtype_code` overrides the per-element DataType code (for the
    unsupported-dtype guard)."""
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
    wide, fmt = _offsize(version)
    osize = 8 if wide else 4
    header_len = 26 + osize + len(dim_bytes)  # fixed header + dimension array
    off_arr = header_len
    offarr_len = n_elem * osize * 2  # data offsets + tag offsets
    data_start = off_arr + offarr_len

    elements = []
    values_per_elem = []
    cur = data_start
    data_offsets = []
    for k in range(n_elem):
        vals = [k * 100 + c for c in range(n_channels)]
        values_per_elem.append(vals)
        el = _spectrum_element(cal_offset, cal_delta, cal_element, vals, channel_dtype_code)
        elements.append(el)
        data_offsets.append(cur)
        cur += len(el)

    # ── fixed header ──
    head = struct.pack("<HH", 0x4949, 0x0197)   # ByteOrder, SeriesID
    head += struct.pack("<H", version)          # Version
    head += struct.pack("<I", 0x4120)           # DataTypeID (1-D spectrum)
    head += struct.pack("<I", 0)                # TagTypeID
    head += struct.pack("<I", n_elem)           # TotalElements
    ve = n_elem if valid_elements is None else valid_elements
    head += struct.pack("<I", ve)               # ValidElements
    head += struct.pack(f"<{fmt}", off_arr)     # OffsetArrayOffset
    head += struct.pack("<I", ndim)             # NumberDimensions
    head += dim_bytes

    offarr = b"".join(struct.pack(f"<{fmt}", o) for o in data_offsets)
    offarr += b"".join(struct.pack(f"<{fmt}", 0) for _ in range(n_elem))  # tag offsets
    path.write_bytes(head + offarr + b"".join(elements))

    total = sum(sum(v) for v in values_per_elem)
    # AxisCal origin so that (i − origin)·delta == offset + (i − element)·delta
    origin = cal_element - cal_offset / cal_delta if cal_delta else 0.0
    return {
        "n_elem": n_elem,
        "n_channels": n_channels,
        "scan_dims": scan_dims,
        "total": total,
        "energy_scale": cal_delta,
        "energy_origin": origin,
        "energy0": (0 - origin) * cal_delta,  # == cal_offset
        "values_per_elem": values_per_elem,
        "version": version,
    }


def write_ser_image(path: Path, *, width: int, height: int,
                    values: list[int] | None = None,
                    cal_delta_x: float = 1e-9, dtype_code: int = 2,
                    version: int = 0x0210, n_elem: int = 1,
                    valid_elements: int | None = None) -> dict[str, Any]:
    """Write a 0x4122 SER (image) file. `width`/`height` may be <= 0 to
    exercise the invalid-dimensions guard. `values` defaults to 1..N (never
    zero) so zero-padding from a truncated read is distinguishable from real
    data. `valid_elements` overrides ValidElements independent of `n_elem`
    (for the no-valid-elements guard); `dtype_code` an unsupported SER
    DataType exercises the unsupported-dtype guard."""
    n = max(width, 0) * max(height, 0)
    if values is None:
        values = list(range(1, n + 1))
    itemsize = _DTYPE_ITEMSIZE.get(dtype_code, 4)
    npdt = _DTYPE_NUMPY.get(dtype_code, "u4")
    payload = np.asarray(values[:n], dtype=f"<{npdt}").tobytes() if n > 0 else b""

    elem = struct.pack("<ddi", 0.0, cal_delta_x, 0)   # X: offset, delta, element
    elem += struct.pack("<ddi", 0.0, 1.0, 0)            # Y: offset, delta, element
    elem += struct.pack("<h", dtype_code)               # DataType i16
    elem += struct.pack("<ii", width, height)           # ArraySizeX, ArraySizeY
    elem += payload

    wide, fmt = _offsize(version)
    osize = 8 if wide else 4
    header_len = 26 + osize  # no dimension array (0 nav dims — plain image)
    off_arr = header_len
    offarr_len = n_elem * osize * 2
    data_start = off_arr + offarr_len

    data_offsets = [data_start + k * len(elem) for k in range(n_elem)]

    head = struct.pack("<HH", 0x4949, 0x0197)
    head += struct.pack("<H", version)
    head += struct.pack("<I", 0x4122)           # DataTypeID (2-D image)
    head += struct.pack("<I", 0)                # TagTypeID
    head += struct.pack("<I", n_elem)           # TotalElements
    ve = n_elem if valid_elements is None else valid_elements
    head += struct.pack("<I", ve)               # ValidElements
    head += struct.pack(f"<{fmt}", off_arr)     # OffsetArrayOffset
    head += struct.pack("<I", 0)                # NumberDimensions

    offarr = b"".join(struct.pack(f"<{fmt}", o) for o in data_offsets)
    offarr += b"".join(struct.pack(f"<{fmt}", 0) for _ in range(n_elem))

    path.write_bytes(head + offarr + elem * n_elem)
    return {"width": width, "height": height, "n_elem": n_elem, "itemsize": itemsize}
