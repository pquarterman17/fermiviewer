"""JEOL Analysis Station ``.img`` / ``.map`` / ``.pts`` parser (Data-Formats
#4b).

``.ASW`` *project* files are NOT loaded directly here — they are a small XML
catalogue that references a ``Sample/<view>/`` directory of raw ``.img`` /
``.map`` / ``.pts`` (and ``.eds``) files by relative path. Point this module
at those raw files directly; a future ``.ASW`` loader could expand a project
into its member files and call this module per-entry, but that is out of
scope here.

``.eds`` (single spectrum) is NOT implemented: probing ``met03.EDS`` shows it
does **not** use the self-describing dict format below — no ``JED-2200:``/
``PTTDFILE`` magic, and known field names (``Live Time``, detector name) sit
at fixed byte offsets with no length-prefixed key framing. It is a distinct,
older Analysis Station format that needs its own reverse-engineering pass;
left for future work rather than guessed at here.

LICENSE NOTE: rosettasciio ships a GPL-licensed JEOL reader. Everything below
was derived from scratch by hex-editing real ``.img``/``.map``/``.pts`` files
(see the empirically-derived-assumptions list below) and cross-checking the
*numeric output* of this module against rosettasciio's reader as a black-box
oracle (``tests/test_jeol.py``'s ``oracle`` marker) — never by reading its
source. No code or design was copied from it.

Container format (``.img``/``.map``, both share one on-disk layout):
    A fixed preamble — 4-byte length, an ASCII tag ("JED-2200:LibJxImageForm"
    for both extensions; nothing in it distinguishes .img from .map), a few
    reserved u32 fields, zero-padded — precedes a **self-describing dict
    tree** (below). Real files store the tree **twice back to back**: a
    small "preview" copy (an ``Image`` dict with only a ``Thumbnail`` blob)
    immediately followed, after zero padding, by a full copy whose ``Image``
    dict carries the real ``Size``/``Bits`` pixel array. ``_pick_image_record``
    picks whichever copy actually has ``Bits``.

Self-describing entry format (the recurring building block, used by
``.img``/``.map`` headers and by the ``.pts`` header up to (but NOT
including — see ``jeol_pts.py``) the raw event stream):
    ``[0x01][key_len: u32][key: key_len bytes, NUL-terminated]``
    ``[dtype: u32][size: u32][value: size bytes]``
    dtype 0 (size 0) means "this entry is a dict" — children follow
    recursively until a bare ``0xFF`` byte, which closes the dict. Otherwise
    ``value`` is ``size`` raw bytes decoded per dtype: 1-5 = scalar
    int8/int16/int32/float32/float64, 6-10 = the same 5 base types as a
    packed array (dtype = base + 5), 12 = NUL-terminated ASCII string.
    A scalar/array entry is followed by a single ``0xFF`` terminator *most*
    of the time but not always (empirically, some int16/int32 fields inside
    ``.pts``'s ``EDS Data`` block — e.g. ``CountRate``, ``DeadTime`` — have
    no terminator at all and are followed immediately by the next sibling's
    ``0x01``); ``_parse_entry`` treats it as optional (peek-and-consume) to
    tolerate this. That optional terminator is safe everywhere actually
    exercised here (``.img``/``.map``'s full tree; ``.pts``'s ``EDS Data``
    and its listed siblings) but is NOT safe over ``.pts``'s ``PTTD
    Cond``/``PTTD Param`` sections, which serialise a UI settings/combo-box
    form in a visibly different sub-encoding — this module never recurses
    into those two keys; the handful of scalars it needs from ``.pts`` are
    read via direct anchored lookups instead (``_find_entry``).

``.pts`` header, additionally:
    A distinct fixed 64-byte preamble (magic ``PTTDFILE`` at offset 4) gives
    the raw event stream's byte range directly: ``u32 @ offset 28`` = stream
    start offset, ``u32 @ offset 32`` = stream byte length. Both are read
    directly rather than located by scanning — this is also how a truncated
    acquisition is detected (``offset + length`` running past EOF; see
    ``InvalidFrame`` in the real corpus, where a JEOL_eds readme confirms the
    files are deliberately-interrupted acquisitions).

Energy calibration for the ``.pts`` cube: ``EDS Data.CoefA``/``CoefB`` give
``energy(raw_channel) = CoefA * raw_channel + CoefB`` in keV, but the raw
event stream's channel field (``jeol_pts.decode_pts_stream``) is NOT
``raw_channel`` directly — empirically, on the one real ``.pts`` file this
was verified against, ``energy(cube_index) = CoefA * (cube_index − 96) +
CoefB`` reproduces rosettasciio's reported axis offset to 6 significant
figures. The 96-channel shift is treated here as a fixed constant of the
format (its physical origin — a pulser/zero-peak blanking region on this
detector? a fixed hardware pre-roll? — was not identified); it has only been
verified on a single sample and could in principle vary by detector model.

Pixel calibration for both ``.img``/``.map`` and ``.pts``: real files store
a field-of-view width ``ScanSize`` (µm) and a raster subdivision constant
that empirically comes out to exactly 40 (``pixel_size_um = ScanSize / (
width_px * 40)``) — reproduces rosettasciio's 0.00869140625 µm/px on the
development sample exactly (178.0 / (512 * 40)). Not derived from any known
hardware spec; treated as an empirical constant of this instrument family.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.hdf5_common import axiscal_from_offset_scale
from fermiviewer.io.jeol_pts import decode_pts_stream

__all__ = ["JeolFormatError", "load_jeol_img", "load_jeol_map", "load_jeol_pts"]


class JeolFormatError(ValueError):
    """Raised for unreadable, unrecognised, or truncated JEOL files."""


# ── self-describing entry decoder (see module docstring) ────────────

_SCALAR_FMT = {1: "b", 2: "h", 3: "i", 4: "f", 5: "d"}
# dtype 6 (array of the base-1 type) is used exclusively for pixel/count
# byte arrays (Image.Bits, Palette.RGBQUAD's u1 siblings) in every file
# probed — unsigned (0-255), matching rosettasciio's uint8 (never observed
# a *scalar* dtype 1, so _SCALAR_FMT's signed guess there is unconfirmed).
_ARRAY_DTYPE = {6: "<u1", 7: "<i2", 8: "<i4", 9: "<f4", 10: "<f8"}
_MAX_DEPTH = 32


def _decode_value(dtype: int, val: bytes) -> Any:
    if dtype == 12:
        return val.split(b"\x00", 1)[0].decode("latin-1", "replace")
    fmt = _SCALAR_FMT.get(dtype)
    if fmt is not None and len(val) == struct.calcsize(fmt):
        return struct.unpack(f"<{fmt}", val)[0]
    np_dt = _ARRAY_DTYPE.get(dtype)
    if np_dt is not None:
        itemsize = np.dtype(np_dt).itemsize
        if itemsize and len(val) % itemsize == 0:
            return np.frombuffer(val, dtype=np_dt)
    return val  # unrecognised dtype: hand back the raw bytes


def _parse_entry(buf: bytes, pos: int, depth: int = 0) -> tuple[str, Any, int]:
    if depth > _MAX_DEPTH:
        raise JeolFormatError("JEOL header nesting too deep (misaligned parse?)")
    if buf[pos] != 0x01:
        raise JeolFormatError(f"expected entry tag 0x01 at byte {pos}, got 0x{buf[pos]:02x}")
    (key_len,) = struct.unpack_from("<I", buf, pos + 1)
    key_start = pos + 5
    key = buf[key_start : key_start + key_len].rstrip(b"\x00").decode("latin-1", "replace")
    pos = key_start + key_len
    dtype, size = struct.unpack_from("<2I", buf, pos)
    pos += 8
    if dtype == 0 and size == 0:
        children: dict[str, Any] = {}
        while buf[pos] != 0xFF:
            ckey, cval, pos = _parse_entry(buf, pos, depth + 1)
            children[ckey] = cval
        return key, children, pos + 1
    val = buf[pos : pos + size]
    pos += size
    if pos < len(buf) and buf[pos] == 0xFF:  # optional — see module docstring
        pos += 1
    return key, _decode_value(dtype, val), pos


def _find_entry(buf: bytes, key: str, start: int = 0) -> tuple[Any, int] | None:
    """Locate a top-level ``key`` entry by its exact byte pattern and decode
    it (recursing into children if it's a dict). Used for the handful of
    ``.pts`` scalars that live outside the safely-recursible sections."""
    kb = key.encode("latin-1") + b"\x00"
    anchor = b"\x01" + struct.pack("<I", len(kb)) + kb
    idx = buf.find(anchor, start)
    if idx < 0:
        return None
    _, val, end = _parse_entry(buf, idx)
    return val, end


# ── .img / .map ───────────────────────────────────────────────────────

def _find_root_offset(buf: bytes) -> int:
    """Scan past the fixed preamble for the first plausible entry header
    (rather than hardcoding its length — verified at byte 76 on the real
    corpus, but the preamble's exact length is not independently known)."""
    limit = min(len(buf) - 5, 1024)
    for pos in range(16, limit):
        if buf[pos] != 0x01:
            continue
        (klen,) = struct.unpack_from("<I", buf, pos + 1)
        if not (1 <= klen <= 64):
            continue
        key_end = pos + 5 + klen
        if key_end > len(buf) or buf[key_end - 1] != 0:
            continue
        key = buf[pos + 5 : key_end - 1]
        if key and all(0x20 <= b < 0x7F for b in key):
            return pos
    raise JeolFormatError("could not locate the JEOL header's entry tree")


def _parse_top_level_records(buf: bytes, start: int) -> list[dict[str, Any]]:
    """.img/.map store the entry tree twice back-to-back, zero-padded
    between copies (see module docstring)."""
    pos = start
    records = []
    while pos < len(buf):
        while pos < len(buf) and buf[pos] == 0:
            pos += 1
        if pos >= len(buf) or buf[pos] != 0x01:
            break
        rec: dict[str, Any] = {}
        while pos < len(buf) and buf[pos] == 0x01:
            key, val, pos = _parse_entry(buf, pos)
            rec[key] = val
        if pos < len(buf) and buf[pos] == 0xFF:
            pos += 1  # the envelope's own closing sentinel
        records.append(rec)
    return records


def _pick_image_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    for rec in reversed(records):  # the full copy (with Bits) comes last
        if isinstance(rec.get("Image"), dict) and "Bits" in rec["Image"]:
            return rec
    for rec in records:
        if isinstance(rec.get("Image"), dict):
            return rec
    raise JeolFormatError("no Image record found in JEOL file")


def _scan_pixel_cal(scan_size: Any, width_px: int) -> AxisCal:
    """Field-of-view width (µm) / (pixel count x 40) — see module docstring."""
    if (
        isinstance(scan_size, (int, float))
        and np.isfinite(scan_size)
        and scan_size > 0
        and width_px > 0
    ):
        return AxisCal(scale=float(scan_size) / (width_px * 40.0), units="um")
    return AxisCal()


def _load_img_or_map(path: str | Path, subtype: str) -> DataStruct:
    path = Path(path)
    buf = path.read_bytes()
    if buf[4:12] != b"JED-2200":
        raise JeolFormatError(f"{path.name}: not a JEOL 'JED-2200' image/map file")

    root = _find_root_offset(buf)
    records = _parse_top_level_records(buf, root)
    if not records:
        raise JeolFormatError(f"{path.name}: no readable header entries")
    rec = _pick_image_record(records)

    image = rec.get("Image", {})
    bits = image.get("Bits")
    size = image.get("Size")
    if not isinstance(bits, np.ndarray) or not isinstance(size, np.ndarray) or len(size) != 2:
        raise JeolFormatError(f"{path.name}: Image record has no usable pixel data")
    height, width = int(size[1]), int(size[0])
    if height * width != bits.size:
        raise JeolFormatError(
            f"{path.name}: declared size {width}x{height} != pixel data length {bits.size}"
        )
    pixels = bits.astype(np.uint8).reshape(height, width)

    instrument = rec.get("Instrument", {})
    cal = _scan_pixel_cal(instrument.get("ScanSize"), width)

    metadata: dict[str, Any] = {
        "source": str(path),
        "parser": "jeol",
        "jeol_subtype": subtype,
        "instrument_name": instrument.get("Name", ""),
        "beam_kv": instrument.get("AccV"),
        "magnification": instrument.get("Mag"),
        "working_distance_mm": instrument.get("WorkD"),
        "scan_rotation_deg": instrument.get("ScanR"),
        "title": image.get("Title", ""),
        "group_name": image.get("GroupName", ""),
    }
    map_info = rec.get("Map")
    if isinstance(map_info, dict):
        metadata["map_element"] = map_info.get("Title", "")
        metadata["map_type"] = map_info.get("MapType")
        metadata["sweep_count"] = map_info.get("SweepCount")
        metadata["dwell_time_ms"] = map_info.get("DwellTime")
        metadata["roi_channels"] = [map_info.get("StartRoi"), map_info.get("EndRoi")]

    return DataStruct(data=pixels, kind=DataKind.IMAGE, axes=(cal, cal), metadata=metadata)


def load_jeol_img(path: str | Path) -> DataStruct:
    """Load a JEOL Analysis Station ``.img`` SEM/STEM survey image."""
    return _load_img_or_map(path, "img")


def load_jeol_map(path: str | Path) -> DataStruct:
    """Load a JEOL Analysis Station ``.map`` elemental intensity map."""
    return _load_img_or_map(path, "map")


# ── .pts ────────────────────────────────────────────────────────────

_PTS_N_CHANNELS = 4096
_PTS_ENERGY_CHANNEL_SHIFT = 96.0  # see module docstring


def _pts_stream_range(buf: bytes, path: Path) -> tuple[int, int]:
    if len(buf) < 36 or buf[4:12] != b"PTTDFILE":
        raise JeolFormatError(f"{path.name}: not a JEOL 'PTTDFILE' spectrum-image file")
    data_offset, data_size = struct.unpack_from("<2I", buf, 28)
    if data_offset >= len(buf) or data_size == 0:
        raise JeolFormatError(f"{path.name}: no event-stream data recorded")
    if data_offset + data_size > len(buf):
        raise JeolFormatError(
            f"{path.name}: truncated acquisition — header declares "
            f"{data_size} bytes of event data at offset {data_offset} "
            f"({data_offset + data_size} total), but the file is only "
            f"{len(buf)} bytes (interrupted measurement?)"
        )
    return data_offset, data_offset + data_size


def _pts_header_fields(buf: bytes, path: Path) -> dict[str, Any]:
    """Walk the safely-recursible tail of the header, starting at 'EDS
    Data' and continuing through its top-level siblings ('Meas Cond',
    'MeasCond', 'Data') — never 'PTTD Cond'/'PTTD Param' (see module
    docstring)."""
    kb = b"EDS Data\x00"
    anchor = b"\x01" + struct.pack("<I", len(kb)) + kb
    pos = buf.find(anchor)
    if pos < 0:
        raise JeolFormatError(f"{path.name}: no 'EDS Data' section in header")
    out: dict[str, Any] = {}
    while pos < len(buf) and buf[pos] == 0x01:
        key, val, pos = _parse_entry(buf, pos)
        out[key] = val
    return out


def load_jeol_pts(path: str | Path) -> DataStruct:
    """Load a JEOL Analysis Station ``.pts`` EDS spectrum-image event
    stream into a binned ``(y, x, energy)`` cube."""
    path = Path(path)
    buf = path.read_bytes()
    start, end = _pts_stream_range(buf, path)

    tail = _pts_header_fields(buf, path)
    eds = tail.get("EDS Data", {})
    coef_a = eds.get("CoefA")
    coef_b = eds.get("CoefB")
    if not (isinstance(coef_a, (int, float)) and isinstance(coef_b, (int, float))):
        raise JeolFormatError(f"{path.name}: no CoefA/CoefB energy calibration in header")

    meas_cond = tail.get("Meas Cond", {})
    pixels_str = str(meas_cond.get("Pixels", ""))
    if "x" not in pixels_str:
        raise JeolFormatError(f"{path.name}: no Pixels (image size) field in header")
    width_str, height_str = pixels_str.lower().split("x", 1)
    width, height = int(width_str), int(height_str)

    scan_size_found = _find_entry(buf, "ScanSize")
    scan_size = scan_size_found[0] if scan_size_found else None
    spatial = _scan_pixel_cal(scan_size, width)

    energy = axiscal_from_offset_scale(
        offset=float(coef_b) - _PTS_ENERGY_CHANNEL_SHIFT * float(coef_a),
        scale=float(coef_a),
        units="keV",
    )

    cube, n_hits = decode_pts_stream(buf, start, end, width, height, _PTS_N_CHANNELS)

    doc = eds.get("AnalyzableMap MeasData", {}).get("Doc", {})
    dead_time = eds.get("AnalyzableMap MeasData", {}).get("DeadTime")
    meas_cond2 = tail.get("MeasCond", {})

    metadata: dict[str, Any] = {
        "source": str(path),
        "parser": "jeol",
        "jeol_subtype": "pts",
        "n_hits": n_hits,
        "sweep_count": eds.get("Sweep"),
        "dwell_time_ms": eds.get("DwellTime(msec)"),
        "live_time_s": doc.get("LiveTime"),
        "real_time_s": doc.get("RealTime"),
        "count_rate_cps": doc.get("CountRate"),
        "dead_time_pct": dead_time,
        "beam_kv": meas_cond2.get("AccKV"),
        "coef_a": coef_a,
        "coef_b": coef_b,
    }
    return DataStruct(
        data=cube,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(spatial, spatial, energy),
        metadata=metadata,
    )
