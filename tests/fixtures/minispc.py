"""Minimal synthetic EDAX .spc header + counts writer for tests.

No synthetic fixture existed before this — only the real committed corpus
(see the `edax_examples` conftest fixture) — so header edge cases (short
files, bad geometry, the GRAMS-collision guard) had no CI-runnable coverage
without the private test-data corpus present. Mirrors the minimrc/ser
fixture pattern: hand-rolled bytes, no dependency on the parser under test.

`fversn_byte`, when given, overwrites byte 1 of the file — the exact byte
position GRAMS/Thermo Galactic .spc uses for its own format marker — letting
tests synthesize the extension collision without a real GRAMS file.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

__all__ = ["write_mini_spc_edax"]

_HEADER = 736  # end of the last decoded field (numElem @ 638, 2 bytes)


def write_mini_spc_edax(
    path: str | Path,
    counts,
    *,
    version: float = 0.70,
    ev_per_chan: int = 10,
    start_energy: float = 0.0,
    end_energy: float | None = None,
    live_time: float = 50.0,
    tilt: float = 0.0,
    det_reso: float = 130.0,
    azimuth: float = 0.0,
    elevation: float = 35.0,
    kv: float = 20.0,
    n_elem: int = 0,
    data_start: int | None = None,
    fversn_byte: int | None = None,
) -> Path:
    counts_arr = np.asarray(counts, dtype="<u4")
    n_pts = counts_arr.size
    data_start = _HEADER if data_start is None else data_start
    if data_start < _HEADER:
        raise ValueError(f"data_start must be >= {_HEADER} (end of decoded fields)")

    buf = bytearray(data_start)
    struct.pack_into("<f", buf, 0, version)
    struct.pack_into("<i", buf, 28, data_start)
    struct.pack_into("<h", buf, 32, n_pts)
    struct.pack_into("<i", buf, 384, ev_per_chan)
    end_e = (
        end_energy
        if end_energy is not None
        else start_energy + max(n_pts - 1, 0) * ev_per_chan / 1000.0
    )
    struct.pack_into("<f", buf, 448, start_energy)
    struct.pack_into("<f", buf, 452, end_e)
    struct.pack_into("<f", buf, 456, live_time)
    struct.pack_into("<f", buf, 460, tilt)
    struct.pack_into("<f", buf, 472, det_reso)
    struct.pack_into("<f", buf, 508, azimuth)
    struct.pack_into("<f", buf, 512, elevation)
    struct.pack_into("<f", buf, 532, kv)
    struct.pack_into("<h", buf, 638, n_elem)

    if fversn_byte is not None:
        buf[1] = fversn_byte

    out = Path(path)
    out.write_bytes(bytes(buf) + counts_arr.tobytes())
    return out
