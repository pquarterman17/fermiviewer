"""Minimal synthetic MRC2014 writer.

No synthetic MRC fixture existed before this — only small real-instrument
corpus files (16x16, golden-pinned) — so the endianness bug (mrc.py hardcoded
little-endian and never read the machine stamp) had no CI-runnable coverage.
Mirrors the minidm4/ser fixture pattern: hand-rolled bytes, no dependency on
the parser under test.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

__all__ = ["write_mini_mrc"]

_HEADER = 1024
# MRC2014 machine stamp: 0x44 0x44 = little-endian, 0x11 0x11 = big-endian.
_MACHST = {"little": b"\x44\x44\x00\x00", "big": b"\x11\x11\x00\x00"}
_MODE_DTYPE = {0: "i1", 1: "i2", 2: "f4", 6: "u2"}


def write_mini_mrc(
    path: str | Path,
    data: np.ndarray,
    *,
    mode: int = 6,
    endian: str = "little",
    nsymbt: int = 0,
    cella_x: float = 0.0,
    machst: bytes | None = None,
    nx: int | None = None,
    ny: int | None = None,
    header_mode: int | None = None,
) -> Path:
    """Write a minimal MRC2014 file. `data` is (ny, nx) (NX fastest on disk,
    matching load_mrc's final reshape). `endian` picks the byte order for
    every header integer/float AND the pixel data, plus the matching machine
    stamp; pass `machst=` to override it (e.g. junk bytes to test the
    unrecognised-stamp default-to-little-endian fallback).

    `nx`/`ny` override the header's NX/NY fields independent of `data.shape`
    (for the invalid-dims test); `header_mode` overrides only the header's
    MODE field, independent of `mode` — which still selects the dtype used
    to encode the actual pixel payload (for the unsupported-MODE test, where
    the parser must raise before ever reading pixels).
    """
    data = np.asarray(data)
    dy, dx = data.shape
    nx = dx if nx is None else nx
    ny = dy if ny is None else ny
    bo = "<" if endian == "little" else ">"
    dt = _MODE_DTYPE[mode]
    stored_mode = mode if header_mode is None else header_mode

    header = bytearray(_HEADER)
    header[0:4] = struct.pack(f"{bo}i", nx)
    header[4:8] = struct.pack(f"{bo}i", ny)
    header[8:12] = struct.pack(f"{bo}i", 1)  # NZ
    header[12:16] = struct.pack(f"{bo}i", stored_mode)
    header[40:52] = struct.pack(f"{bo}fff", cella_x, cella_x, cella_x)
    header[92:96] = struct.pack(f"{bo}i", nsymbt)
    header[208:212] = b"MAP "
    header[212:216] = machst if machst is not None else _MACHST[endian]

    ext_header = bytes(max(nsymbt, 0))
    payload = data.astype(f"{bo}{dt}").tobytes()

    out = Path(path)
    out.write_bytes(bytes(header) + ext_header + payload)
    return out
