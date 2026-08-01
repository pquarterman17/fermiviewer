"""EDAX ``.spc`` EDS-spectrum parser (Data-Formats #7 remainder).

The on-disk layout was reverse-engineered from the real EDAX Genesis/TEAM
``.spc`` files in the committed corpus (``spc0_61-ipr333_xrf.spc`` carries
format version 0.61 in its filename and its own header; the others are
version 0.70) — byte offsets were located independently by binary-searching
the raw bytes for known field values (``numPts``, ``evPerChan``, ...) and
then cross-checked field-by-field against the rosettasciio ``edax`` reader
as a dev-time oracle. rosettasciio is GPL and is used ONLY as a test oracle
(see ``tests/test_oracle_rsciio.py``) — nothing here is copied from it.

Fixed little-endian binary layout. The "useful" fields all sit inside the
first 736 bytes; the rest of a much larger reserved header block (up to
``dataStart``) is an opaque per-element table plus padding that this reader
does not attempt to decode:

    offset  size  field         note
    0       4     version       f32 — format version (0.61 / 0.70 seen)
    28      4     dataStart     i32 — byte offset of the uint32 counts array
    32      2     numPts        i16 — channel count
    384     4     evPerChan     i32 — eV per channel
    448     4     startEnergy   f32 — keV at channel 0
    452     4     endEnergy     f32 — keV at the last channel (informational
                                 only; not used for calibration)
    456     4     liveTime      f32 — seconds, dead-time corrected. This
                                 header revision carries no separate "real
                                 time" (elapsed clock time) field.
    460     4     tilt          f32 — degrees
    472     4     detReso       f32 — eV, detector energy resolution
    508     4     azimuth       f32 — degrees
    512     4     elevation     f32 — degrees
    532     4     kV            f32 — beam accelerating voltage
    638     2     numElem       i16 — element-table entry count

followed by ``numPts`` little-endian uint32 counts starting at ``dataStart``.

GRAMS/Thermo Galactic spectroscopy ``.spc`` is a completely different,
unrelated format that happens to share the ``.spc`` extension (see the real
examples under ``test-data/spc/spectroscopy/``). It stores its own format
marker (``fversn``, one of the bytes ``'K'``/``'L'``/``'M'``) at byte 1 —
``is_edax_spc``/``load_spc_edax`` check for that first and raise a friendly,
named error rather than misreading it as EDAX (or vice versa).
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.io.hdf5_common import axiscal_from_offset_scale

__all__ = ["SpcFormatError", "is_edax_spc", "load_spc_edax"]

# Byte 1 of a GRAMS/Thermo Galactic .spc is its `fversn` marker: 'K' (0x4B,
# new format, LSB-first — by far the most common), 'L' (0x4C, new format,
# MSB-first), or 'M' (0x4D, old format). Real EDAX files never land on one of
# these three bytes there (it's the second byte of a small float32 version
# number), so this is checked first as the primary collision guard.
_GRAMS_FVERSN = {0x4B, 0x4C, 0x4D}

# End of the last field this reader decodes (numElem @ 638, 2 bytes). Also
# used as the minimum plausible `dataStart` — the counts array cannot start
# before the header fields that describe it have been read.
_MIN_HEADER = 640

_F32 = struct.Struct("<f")
_I32 = struct.Struct("<i")
_I16 = struct.Struct("<h")


def _f32(buf: bytes, off: int) -> float:
    return float(_F32.unpack_from(buf, off)[0])


def _i32(buf: bytes, off: int) -> int:
    return int(_I32.unpack_from(buf, off)[0])


def _i16(buf: bytes, off: int) -> int:
    return int(_I16.unpack_from(buf, off)[0])


class SpcFormatError(ValueError):
    """Unreadable / unrecognised ``.spc`` header, including GRAMS collisions."""


def is_edax_spc(buf: bytes) -> bool:
    """Cheap structural sniff: not a GRAMS file, plausible version/geometry."""
    if len(buf) < _MIN_HEADER or buf[1] in _GRAMS_FVERSN:
        return False
    try:
        version = _f32(buf, 0)
        data_start = _i32(buf, 28)
        n_pts = _i16(buf, 32)
    except struct.error:
        return False
    if not (np.isfinite(version) and 0.0 < version < 100.0):
        return False
    if n_pts <= 0 or data_start < _MIN_HEADER:
        return False
    return data_start + n_pts * 4 <= len(buf)


def load_spc_edax(path: str | Path) -> DataStruct:
    """Parse an EDAX EDS ``.spc`` spectrum into a ``DataStruct``."""
    path = Path(path)
    buf = path.read_bytes()

    if len(buf) < 2:
        raise SpcFormatError(f"{path.name}: file too small to be a .spc spectrum")
    if buf[1] in _GRAMS_FVERSN:
        raise SpcFormatError(
            f"{path.name}: this looks like a GRAMS/Thermo Galactic spectroscopy "
            ".spc file (fversn marker at byte 1), not an EDAX EDS spectrum — "
            "the two vendors share the .spc extension but use unrelated formats"
        )
    if len(buf) < _MIN_HEADER:
        raise SpcFormatError(f"{path.name}: too short for an EDAX .spc header")

    version = _f32(buf, 0)
    if not (np.isfinite(version) and 0.0 < version < 100.0):
        raise SpcFormatError(
            f"{path.name}: unrecognised .spc header (version field {version!r})"
        )

    data_start = _i32(buf, 28)
    n_pts = _i16(buf, 32)
    if n_pts <= 0 or data_start < _MIN_HEADER or data_start + n_pts * 4 > len(buf):
        raise SpcFormatError(f"{path.name}: unrecognised .spc header (bad geometry)")

    ev_per_chan = _i32(buf, 384)
    start_energy = _f32(buf, 448)
    end_energy = _f32(buf, 452)
    live_time = _f32(buf, 456)
    tilt = _f32(buf, 460)
    det_reso = _f32(buf, 472)
    azimuth = _f32(buf, 508)
    elevation = _f32(buf, 512)
    kv = _f32(buf, 532)
    n_elem = _i16(buf, 638)

    counts = np.frombuffer(buf, dtype="<u4", count=n_pts, offset=data_start).astype(
        np.float64
    )

    # startEnergy/endEnergy are already in keV; evPerChan is eV/channel.
    cal = axiscal_from_offset_scale(start_energy, ev_per_chan / 1000.0, "keV")

    metadata: dict[str, Any] = {
        "source": str(path),
        "parser": "spc_edax",
        "spc_version": version,
        "live_time_s": live_time,
        "detector_resolution_ev": det_reso,
        "beam_kv": kv,
        "azimuth_deg": azimuth,
        "elevation_deg": elevation,
        "tilt_deg": tilt,
        "ev_per_channel": ev_per_chan,
        "start_energy_kev": start_energy,
        "end_energy_kev": end_energy,
        "n_elements": n_elem,
    }
    return DataStruct(data=counts, kind=DataKind.SPECTRUM, axes=(cal,), metadata=metadata)
