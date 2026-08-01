"""Minimal synthetic JEOL Analysis Station file writers.

No committed corpus exists for JEOL (it's real-instrument-only, gated behind
``jeol_examples``/``realdata``), so these hand-rolled encoders give the
parser unit tests something CI-runnable to exercise. They implement the
self-describing entry format from scratch (see ``io/jeol.py``'s module
docstring for the derivation) — independent of, and much smaller than, a
real Analysis Station file: just enough fields for ``load_jeol_img`` /
``load_jeol_map`` / ``load_jeol_pts`` to succeed.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

__all__ = ["write_mini_jeol_img", "write_mini_jeol_pts"]


def _entry(key: str, dtype: int, value: bytes, terminate: bool = True) -> bytes:
    kb = key.encode("latin-1") + b"\x00"
    out = bytearray(b"\x01")
    out += struct.pack("<I", len(kb)) + kb
    out += struct.pack("<2I", dtype, len(value)) + value
    if terminate:
        out += b"\xff"
    return bytes(out)


def _dict(key: str, children: bytes) -> bytes:
    kb = key.encode("latin-1") + b"\x00"
    out = bytearray(b"\x01")
    out += struct.pack("<I", len(kb)) + kb
    out += struct.pack("<2I", 0, 0) + children + b"\xff"
    return bytes(out)


def _f64(v: float) -> bytes:
    return struct.pack("<d", v)


def _f32(v: float) -> bytes:
    return struct.pack("<f", v)


def _i32(v: int) -> bytes:
    return struct.pack("<i", v)


def _i16(v: int) -> bytes:
    return struct.pack("<h", v)


def _s(v: str) -> bytes:
    return v.encode("latin-1") + b"\x00"


def write_mini_jeol_img(
    path: str | Path,
    pixels: np.ndarray,
    *,
    scan_size_um: float = 100.0,
    mag: int = 10000,
    acc_v: float = 200.0,
    filetype: str = "JED-2200:IMG",
    map_element: str | None = None,
) -> Path:
    """Write a minimal one-copy ``.img``/``.map`` file (no thumbnail
    duplicate — ``load_jeol_img``/``load_jeol_map`` accept a single record
    just as readily as the two-copy layout real files use)."""
    height, width = pixels.shape
    instrument = (
        _entry("Type", 2, _i16(0))
        + _entry("ScanSize", 4, _f32(scan_size_um))
        + _entry("Name", 12, _s("MiniJEOL"))
        + _entry("AccV", 4, _f32(acc_v))
        + _entry("Mag", 3, _i32(mag))
        + _entry("WorkD", 4, _f32(6.0))
        + _entry("ScanR", 4, _f32(239.0))
    )
    image = (
        _entry("DataType", 3, _i32(1))
        + _entry("Size", 8, _i32(width) + _i32(height))
        + _entry("Title", 12, _s("IMG1"))
        + _entry("Bits", 6, pixels.astype("<u1").tobytes())
    )
    root = _dict("Instrument", instrument) + _entry("FileType", 12, _s(filetype))
    root += _dict("Image", image)
    if map_element is not None:
        map_dict = (
            _entry("Title", 12, _s(map_element))
            + _entry("MapType", 3, _i32(2))
            + _entry("SweepCount", 3, _i32(1))
        )
        root += _dict("Map", map_dict)

    preamble = bytearray(76)
    struct.pack_into("<I", preamble, 0, 0x34)
    tag = b"JED-2200:LibJxImageForm\x00"
    preamble[4 : 4 + len(tag)] = tag

    out = Path(path)
    out.write_bytes(bytes(preamble) + root)
    return out


def write_mini_jeol_pts(
    path: str | Path,
    events: bytes,
    *,
    width: int = 4,
    height: int = 4,
    coef_a: float = 0.01,
    coef_b: float = -0.001,
    scan_size_um: float = 40.0,
) -> Path:
    """Write a minimal ``.pts`` file: a fixed 64-byte preamble (magic +
    data_offset/data_size), a small header carrying only what
    ``load_jeol_pts`` reads (``EDS Data``'s CoefA/CoefB/Doc block, a sibling
    ``Meas Cond`` with ``Pixels``, a sibling ``MeasCond``, and a standalone
    top-level ``ScanSize``), then the raw ``events`` word stream verbatim.
    """
    doc = (
        _entry("LiveTime", 5, _f64(10.0))
        + _entry("RealTime", 5, _f64(12.0))
        + _entry("CountRate", 3, _i32(100))
    )
    analyzable = _dict("Doc", doc) + _entry("DeadTime", 2, _i16(2))
    eds_data = (
        _dict("AnalyzableMap MeasData", analyzable)
        + _entry("DwellTime(msec)", 5, _f64(0.1))
        + _entry("Sweep", 2, _i16(1))
        + _entry("CoefA", 5, _f64(coef_a))
        + _entry("CoefB", 5, _f64(coef_b))
    )
    meas_cond = _entry("Pixels", 12, _s(f"{width}x{height}"))
    meas_cond2 = _entry("AccKV", 4, _f32(200.0))
    header = (
        _entry("ScanSize", 4, _f32(scan_size_um))
        + _dict("EDS Data", eds_data)
        + _dict("Meas Cond", meas_cond)
        + _dict("MeasCond", meas_cond2)
    )

    preamble = bytearray(64)
    preamble[4:12] = b"PTTDFILE"
    data_offset = len(preamble) + len(header)
    struct.pack_into("<I", preamble, 28, data_offset)
    struct.pack_into("<I", preamble, 32, len(events))

    out = Path(path)
    out.write_bytes(bytes(preamble) + header + events)
    return out
