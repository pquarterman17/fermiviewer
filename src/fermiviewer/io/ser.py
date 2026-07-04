"""FEI/ThermoFisher TIA SER parser.

Handles both TIA element kinds:

* **0x4122 — 2D images** (port of fermi-viewer's importSER.m). The first
  valid element is returned as a calibrated image; calibration delta is kept
  in metres, exactly as the MATLAB reference (golden-pinned). When a file
  holds a multi-frame series (valid_elements > 1) only the first frame is
  returned — the DataStruct contract has no image-stack kind — and a warning
  records how many frames were dropped.
* **0x4120 — 1D spectra** (enhancement beyond the MATLAB parser, which
  rejected these). A single element becomes a SPECTRUM; a scanned series
  (line profile or 2-D map) becomes a SPECTRUM_IMAGE with the navigation
  dimensions from the file's dimension array and a per-channel energy axis
  from the element calibration. This is what makes TIA EDS/EELS spectrum
  images and line profiles load.

Little-endian; version ≥ 0x0220 uses 64-bit offsets.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

__all__ = ["load_ser"]

_DTYPES = {1: "u1", 2: "u2", 3: "u4", 4: "i1", 5: "i2", 6: "i4", 7: "f4", 8: "f8"}
_IMAGE_ID = 0x4122
_SPECTRUM_ID = 0x4120


def _int(buf: bytes, off: int, size: int, signed: bool = False) -> int:
    return int.from_bytes(buf[off : off + size], "little", signed=signed)


def _dtype_at(buf: bytes, off: int) -> str:
    code = _int(buf, off, 2, signed=True)
    if code not in _DTYPES:
        raise ValueError(f"unsupported SER DataType {code}")
    return _DTYPES[code]


def _parse_header(buf: bytes) -> dict:
    """Fixed header + variable dimension array → dict of fields."""
    if len(buf) < 30:
        raise ValueError("empty or truncated SER file")
    if _int(buf, 0, 2) != 0x4949 or _int(buf, 2, 2) != 0x0197:
        raise ValueError("not a TIA SER file (magic mismatch)")
    version = _int(buf, 4, 2)
    data_type_id = _int(buf, 6, 4)
    valid_elements = _int(buf, 18, 4)
    wide = version >= 0x0220
    osize = 8 if wide else 4
    off_arr = _int(buf, 22, osize)
    ndim = _int(buf, 22 + osize, 4)

    # dimension array (navigation axes): sizes only; skip the strings
    cur = 22 + osize + 4
    dims: list[int] = []
    for _ in range(ndim):
        dims.append(_int(buf, cur, 4))
        cur += 4 + 8 + 8 + 4  # size, calOffset f64, calDelta f64, calElement i32
        desc_len = _int(buf, cur, 4)
        cur += 4 + desc_len
        unit_len = _int(buf, cur, 4)
        cur += 4 + unit_len

    # data-offset array: the first valid_elements entries point at data
    data_offsets = [
        _int(buf, off_arr + i * osize, osize) for i in range(max(valid_elements, 0))
    ]
    return {
        "version": version,
        "data_type_id": data_type_id,
        "valid_elements": valid_elements,
        "wide": wide,
        "dims": dims,
        "data_offsets": data_offsets,
    }


def _read_image_element(buf: bytes, off: int) -> tuple[np.ndarray, float, int]:
    """One 0x4122 element → (H×W array, |x cal delta| in metres, SER type code)."""
    # X calibration is (offset f64, delta f64, element i32); delta is the 2nd f64
    cal_delta_x = float(np.frombuffer(buf, dtype="<f8", count=2, offset=off)[1])
    p = off + 2 * 8 + 4 + 2 * 8 + 4  # past X cal (f64,f64,i32) + Y cal (f64,f64,i32)
    code = _int(buf, p, 2, signed=True)
    dt = _dtype_at(buf, p)
    w = _int(buf, p + 2, 4, signed=True)
    h = _int(buf, p + 6, 4, signed=True)
    if w <= 0 or h <= 0:
        raise ValueError(f"invalid SER dimensions {w}x{h}")
    n = w * h
    avail = (len(buf) - (p + 10)) // np.dtype(dt).itemsize
    px = np.frombuffer(buf, dtype=f"<{dt}", count=min(n, max(avail, 0)), offset=p + 10)
    if px.size < n:
        warnings.warn("SER image element: short read, zero-padding", stacklevel=2)
        px = np.concatenate([px, np.zeros(n - px.size, dtype=px.dtype)])
    return px[:n].reshape(h, w), cal_delta_x, code


def _read_spectrum_element(buf: bytes, off: int) -> tuple[np.ndarray, float, float, int]:
    """One 0x4120 element → (1-D array, cal offset, cal delta, cal element)."""
    cal_offset, cal_delta = np.frombuffer(buf, dtype="<f8", count=2, offset=off)
    cal_element = _int(buf, off + 16, 4, signed=True)
    p = off + 20
    dt = _dtype_at(buf, p)
    length = _int(buf, p + 2, 4, signed=True)
    if length <= 0:
        raise ValueError(f"invalid SER spectrum length {length}")
    avail = (len(buf) - (p + 6)) // np.dtype(dt).itemsize
    data = np.frombuffer(buf, dtype=f"<{dt}", count=min(length, max(avail, 0)), offset=p + 6)
    if data.size < length:
        warnings.warn("SER spectrum element: short read, zero-padding", stacklevel=2)
        data = np.concatenate([data, np.zeros(length - data.size, dtype=data.dtype)])
    return data[:length], float(cal_offset), float(cal_delta), int(cal_element)


def _energy_axis(cal_offset: float, cal_delta: float, cal_element: int) -> AxisCal:
    """SER 1-D cal (value = offset + (i − element)·delta) → AxisCal
    (value = (i − origin)·scale). Units default to eV (EELS/EDS)."""
    if cal_delta == 0:
        return AxisCal()
    origin = cal_element - cal_offset / cal_delta
    return AxisCal(scale=cal_delta, origin=origin, units="eV")


def _load_images(path: Path, buf: bytes, hdr: dict) -> DataStruct:
    offsets = hdr["data_offsets"]
    if not offsets:
        raise ValueError(f"no valid data elements in {path}")
    data, cal_delta_x, type_code = _read_image_element(buf, offsets[0])
    if len(offsets) > 1:
        warnings.warn(
            f"{path.name}: SER holds {len(offsets)} image frames; only the first "
            "is returned (image stacks are not supported). Use per-frame tools "
            "on the individual .ser files if available.",
            stacklevel=2,
        )
    cal = AxisCal(scale=abs(cal_delta_x), units="m") if cal_delta_x != 0 else AxisCal()
    return DataStruct(
        data=data,
        kind=DataKind.IMAGE,
        axes=(cal, cal),
        metadata={
            "source": str(path),
            "parser": "ser",
            "bit_depth": data.dtype.itemsize * 8,
            "ser_version": hdr["version"],
            "ser_data_type": type_code,
            "ser_frames_total": len(offsets),
        },
    )


def _load_spectra(path: Path, buf: bytes, hdr: dict) -> DataStruct:
    offsets = hdr["data_offsets"]
    if not offsets:
        raise ValueError(f"no valid data elements in {path}")
    first, cal_off, cal_del, cal_el = _read_spectrum_element(buf, offsets[0])
    n_ch = first.size
    energy = _energy_axis(cal_off, cal_del, cal_el)
    dims = [d for d in hdr["dims"] if d > 0]
    n = len(offsets)

    meta = {
        "source": str(path),
        "parser": "ser",
        "bit_depth": first.dtype.itemsize * 8,
        "ser_version": hdr["version"],
        "ser_scan_dims": dims,
        "value_unit": None,
    }

    # single spectrum → SPECTRUM; scanned series → SPECTRUM_IMAGE (Ny, Nx, E)
    if n == 1:
        return DataStruct(data=first.astype(first.dtype), kind=DataKind.SPECTRUM,
                          axes=(energy,), metadata=meta)

    stack = np.empty((n, n_ch), dtype=first.dtype)
    stack[0] = first
    for i, off in enumerate(offsets[1:], start=1):
        spec, *_ = _read_spectrum_element(buf, off)
        stack[i] = spec[:n_ch] if spec.size >= n_ch else np.pad(spec, (0, n_ch - spec.size))

    if len(dims) >= 2 and dims[0] * dims[1] == n:
        ny, nx = dims[0], dims[1]
    elif len(dims) == 1 and dims[0] == n:
        ny, nx = 1, n  # line profile
    else:  # unknown navigation shape — keep it 1-D over the elements
        ny, nx = 1, n
    cube = stack.reshape(ny, nx, n_ch)
    # navigation axes stay uncalibrated here (TIA scan cal is in metres in the
    # dimension array; the energy axis is what analysis needs)
    return DataStruct(
        data=cube,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(), AxisCal(), energy),
        metadata=meta,
    )


def load_ser(path: str | Path) -> DataStruct:
    path = Path(path)
    buf = path.read_bytes()
    hdr = _parse_header(buf)
    tid = hdr["data_type_id"]
    if tid == _IMAGE_ID:
        return _load_images(path, buf, hdr)
    if tid == _SPECTRUM_ID:
        return _load_spectra(path, buf, hdr)
    raise ValueError(
        f"unsupported SER DataTypeID 0x{tid:04X} "
        f"(expected 0x4122 image or 0x4120 spectrum): {path}"
    )
