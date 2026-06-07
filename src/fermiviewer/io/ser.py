"""FEI/ThermoFisher TIA SER parser (2D images, DataTypeID 0x4122).

Port of fermi-viewer's importSER.m. Little-endian; version ≥ 0x0220 uses
64-bit offsets. Calibration delta is in metres.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

__all__ = ["load_ser"]

_DTYPES = {1: "u1", 2: "u2", 3: "u4", 4: "i1", 5: "i2", 6: "i4", 7: "f4", 8: "f8"}


def load_ser(path: str | Path) -> DataStruct:
    path = Path(path)
    buf = path.read_bytes()
    if len(buf) < 30:
        raise ValueError(f"empty or truncated SER file: {path}")

    def u16(o: int) -> int:
        return int.from_bytes(buf[o : o + 2], "little")

    def u32(o: int) -> int:
        return int.from_bytes(buf[o : o + 4], "little")

    byte_order, series_id, version = u16(0), u16(2), u16(4)
    data_type_id = u32(6)
    if byte_order != 0x4949 or series_id != 0x0197:
        raise ValueError(f"not a TIA SER file (magic mismatch): {path}")
    if data_type_id != 0x4122:
        raise ValueError(
            f"unsupported SER DataTypeID 0x{data_type_id:04X} "
            f"(only 2D images 0x4122): {path}"
        )
    valid_elements = u32(18)
    if valid_elements < 1:
        raise ValueError(f"no valid data elements in {path}")

    wide = version >= 0x0220
    off_arr = int.from_bytes(buf[22 : 30 if wide else 26], "little")
    data_off = int.from_bytes(
        buf[off_arr : off_arr + (8 if wide else 4)], "little"
    )

    # element header: X cal (f64 offset, f64 delta, i32 element), Y cal same,
    # then i16 dtype, i32 sizeX, i32 sizeY
    hdr = np.frombuffer(buf, dtype="<f8", count=2, offset=data_off)
    cal_delta_x = float(hdr[1])
    p = data_off + 2 * 8 + 4 + 2 * 8 + 4
    arr_dtype = int.from_bytes(buf[p : p + 2], "little", signed=True)
    w = int.from_bytes(buf[p + 2 : p + 6], "little", signed=True)
    h = int.from_bytes(buf[p + 6 : p + 10], "little", signed=True)
    if w <= 0 or h <= 0:
        raise ValueError(f"invalid SER dimensions {w}x{h}: {path}")
    if arr_dtype not in _DTYPES:
        raise ValueError(f"unsupported SER DataType {arr_dtype}: {path}")
    dt = _DTYPES[arr_dtype]

    n = w * h
    avail = (len(buf) - p - 10) // np.dtype(dt).itemsize
    px = np.frombuffer(buf, dtype=f"<{dt}", count=min(n, max(avail, 0)), offset=p + 10)
    if px.size < n:
        import warnings

        warnings.warn(f"{path.name}: short read, zero-padding", stacklevel=2)
        px = np.concatenate([px, np.zeros(n - px.size, dtype=px.dtype)])

    cal = AxisCal(scale=abs(cal_delta_x), units="m") if cal_delta_x != 0 else AxisCal()
    return DataStruct(
        data=px[:n].reshape(h, w),
        kind=DataKind.IMAGE,
        axes=(cal, cal),
        metadata={
            "source": str(path),
            "parser": "ser",
            "bit_depth": np.dtype(dt).itemsize * 8,
            "ser_version": version,
            "ser_data_type": arr_dtype,
        },
    )
