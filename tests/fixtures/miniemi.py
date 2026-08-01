"""Minimal synthetic FEI/TIA `.emi` generators for tests.

Two flavours, both observed to matter in practice:

* `write_mini_emi_cfb` — a genuinely spec-valid Compound File Binary
  ([MS-CFB]) container, exercising `fermiviewer.io.olefile_min`'s header/
  FAT/MiniFAT/directory-entry machinery end to end. Handles streams on
  either side of the mini-stream cutoff (regular-FAT vs MiniFAT paths), and
  can spread the payload across multiple directory entries.
* `write_raw_emi` — no OLE wrapper at all, just the `<ObjectInfo>...
  </ObjectInfo>` block (optionally surrounded by binary filler) written
  directly to a `.emi` file. This mirrors every real `.emi` file in the
  project's `fei/microscopy` corpus: none of them are actual CFB
  containers (confirmed by grepping for the `D0CF11E0A1B11AE1` signature),
  so `io.emi.load_emi_metadata` must degrade gracefully to a raw byte-range
  search when the CFB magic is absent.
"""

from __future__ import annotations

import struct
from pathlib import Path

__all__ = ["write_mini_emi_cfb", "write_raw_emi"]

_FREESECT = 0xFFFFFFFF
_ENDOFCHAIN = 0xFFFFFFFE
_FATSECT = 0xFFFFFFFD
_NOSTREAM = 0xFFFFFFFF
_SECTOR = 512
_MINI_SECTOR = 64


def _name_field(name: str) -> bytes:
    raw = name.encode("utf-16-le") + b"\x00\x00"
    if len(raw) > 64:
        raise ValueError(f"CFB entry name too long: {name!r}")
    return raw + b"\x00" * (64 - len(raw))


class _SectorAllocator:
    """Hands out regular-FAT sector runs and records their chain in `fat`."""

    def __init__(self) -> None:
        self.fat: dict[int, int] = {}
        self.cursor = 0

    def alloc(self, n_bytes: int) -> tuple[int, int]:
        """Reserve ceil(n_bytes/512) sectors chained end-to-end; (start, count)."""
        if n_bytes <= 0:
            return _ENDOFCHAIN, 0
        n_sec = -(-n_bytes // _SECTOR)
        start = self.cursor
        for i in range(n_sec):
            self.fat[self.cursor + i] = (
                (self.cursor + i + 1) if i < n_sec - 1 else _ENDOFCHAIN
            )
        self.cursor += n_sec
        return start, n_sec


def _build_ministream(
    small: dict[str, bytes],
) -> tuple[dict[str, tuple[int, int]], bytes, dict[int, int]]:
    """Concatenate small-stream payloads (each padded to a 64-byte mini-
    sector boundary) into one blob, chained through a MiniFAT map."""
    layout: dict[str, tuple[int, int]] = {}
    blob = bytearray()
    minifat: dict[int, int] = {}
    mini_cursor = 0
    for name, data in small.items():
        n_mini = -(-len(data) // _MINI_SECTOR) if data else 0
        if n_mini == 0:
            layout[name] = (_ENDOFCHAIN, 0)
            continue
        start_mini = mini_cursor
        for i in range(n_mini):
            minifat[mini_cursor + i] = (
                (mini_cursor + i + 1) if i < n_mini - 1 else _ENDOFCHAIN
            )
        blob += data + b"\x00" * (n_mini * _MINI_SECTOR - len(data))
        layout[name] = (start_mini, len(data))
        mini_cursor += n_mini
    return layout, bytes(blob), minifat


def _root_entry_bytes(root_start: int, root_size: int, has_children: bool) -> bytes:
    rec = bytearray(128)
    rec[0:64] = _name_field("Root Entry")
    struct.pack_into("<H", rec, 64, (len("Root Entry") + 1) * 2)
    rec[66] = 5  # storage type: root
    struct.pack_into("<I", rec, 68, _NOSTREAM)
    struct.pack_into("<I", rec, 72, _NOSTREAM)
    struct.pack_into("<I", rec, 76, 1 if has_children else _NOSTREAM)
    struct.pack_into("<I", rec, 116, root_start)
    struct.pack_into("<Q", rec, 120, root_size)
    return bytes(rec)


def _stream_entry_bytes(name: str, next_sibling: int, start: int, size: int) -> bytes:
    rec = bytearray(128)
    rec[0:64] = _name_field(name)
    struct.pack_into("<H", rec, 64, (len(name) + 1) * 2)
    rec[66] = 2  # storage type: stream
    struct.pack_into("<I", rec, 68, _NOSTREAM)
    struct.pack_into("<I", rec, 72, next_sibling)  # right-linked sibling chain
    struct.pack_into("<I", rec, 76, _NOSTREAM)
    struct.pack_into("<I", rec, 116, start)
    struct.pack_into("<Q", rec, 120, size)
    return bytes(rec)


def _build_directory(
    names: list[str],
    big_layout: dict[str, tuple[int, int]],
    mini_layout: dict[str, tuple[int, int]],
    root_start: int,
    ministream_total: int,
) -> bytes:
    records = [_root_entry_bytes(root_start, ministream_total, bool(names))]
    for idx, name in enumerate(names):
        nxt = idx + 2 if idx + 1 < len(names) else _NOSTREAM
        start, size = big_layout.get(name) or mini_layout[name]
        records.append(_stream_entry_bytes(name, nxt, start, size))
    return b"".join(records)


def _pad_to_sectors(data: bytes, n_sectors: int) -> bytes:
    return data + b"\x00" * (n_sectors * _SECTOR - len(data))


def _assemble_body(
    total_sectors: int,
    *,
    big_layout: dict[str, tuple[int, int]],
    streams: dict[str, bytes],
    ministream_start: int,
    mini_blob: bytes,
    minifat_start: int,
    minifat_bytes: bytes,
    num_minifat_sectors: int,
    dir_start: int,
    dir_bytes: bytes,
    n_dir_sectors: int,
    fat_start: int,
    fat: dict[int, int],
) -> bytearray:
    body = bytearray(total_sectors * _SECTOR)

    def put(idx: int, data: bytes) -> None:
        off = idx * _SECTOR
        body[off : off + len(data)] = data

    for name, (start, size) in big_layout.items():
        n_sec = -(-size // _SECTOR)
        padded = _pad_to_sectors(streams[name], n_sec)
        for i in range(n_sec):
            put(start + i, padded[i * _SECTOR : (i + 1) * _SECTOR])

    if mini_blob:
        n_sec = -(-len(mini_blob) // _SECTOR)
        padded = _pad_to_sectors(mini_blob, n_sec)
        for i in range(n_sec):
            put(ministream_start + i, padded[i * _SECTOR : (i + 1) * _SECTOR])

    if minifat_bytes:
        padded = _pad_to_sectors(minifat_bytes, num_minifat_sectors)
        for i in range(num_minifat_sectors):
            put(minifat_start + i, padded[i * _SECTOR : (i + 1) * _SECTOR])

    for i in range(n_dir_sectors):
        put(dir_start + i, dir_bytes[i * _SECTOR : (i + 1) * _SECTOR])

    fat_bytes = b"".join(struct.pack("<I", fat.get(i, _FREESECT)) for i in range(128))
    put(fat_start, fat_bytes)
    return body


def _build_header(
    *, dir_start: int, mini_cutoff: int, minifat_start: int, num_minifat_sectors: int,
    fat_start: int,
) -> bytes:
    header = bytearray(512)
    header[0:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<H", header, 24, 0x003E)  # minor version
    struct.pack_into("<H", header, 26, 3)  # major version: 512-byte sectors
    struct.pack_into("<H", header, 28, 0xFFFE)  # byte order
    struct.pack_into("<H", header, 30, 9)  # sector shift -> 512
    struct.pack_into("<H", header, 32, 6)  # mini sector shift -> 64
    struct.pack_into("<I", header, 40, 0)  # num directory sectors (0 for v3)
    struct.pack_into("<I", header, 44, 1)  # num FAT sectors
    struct.pack_into("<I", header, 48, dir_start)
    struct.pack_into("<I", header, 56, mini_cutoff)
    struct.pack_into(
        "<I", header, 60, minifat_start if num_minifat_sectors else _ENDOFCHAIN
    )
    struct.pack_into("<I", header, 64, num_minifat_sectors)
    struct.pack_into("<I", header, 68, _ENDOFCHAIN)  # first DIFAT sector
    struct.pack_into("<I", header, 72, 0)  # num DIFAT sectors
    for i in range(109):
        struct.pack_into("<I", header, 76 + 4 * i, fat_start if i == 0 else _FREESECT)
    return bytes(header)


def write_mini_emi_cfb(
    path: str | Path,
    xml_bytes: bytes,
    *,
    stream_name: str = "ObjectInfo",
    extra_streams: dict[str, bytes] | None = None,
    mini_cutoff: int = 4096,
) -> Path:
    """Write a minimal valid CFB v3 (512-byte sector) container.

    `xml_bytes` is stored as the stream named `stream_name` (default
    "ObjectInfo" — real TIA streams aren't named this predictably, which is
    exactly why `io.emi` searches every stream's content rather than
    looking up a stream by name). `extra_streams` adds sibling streams
    (e.g. to prove the reader doesn't stop at the first one). Streams
    shorter than `mini_cutoff` route through the MiniFAT/mini-stream path;
    longer ones through the regular FAT — pass a small `mini_cutoff` to
    force even a short payload through the regular-FAT path.
    """
    streams: dict[str, bytes] = {stream_name: xml_bytes}
    if extra_streams:
        streams.update(extra_streams)
    names = list(streams.keys())

    big = {n: d for n, d in streams.items() if len(d) >= mini_cutoff}
    small = {n: d for n, d in streams.items() if len(d) < mini_cutoff}

    alloc = _SectorAllocator()
    big_layout: dict[str, tuple[int, int]] = {}
    for name, data in big.items():
        start, _n_sec = alloc.alloc(len(data))
        big_layout[name] = (start, len(data))

    mini_layout, mini_blob, minifat = _build_ministream(small)
    ministream_start, _n_sec = alloc.alloc(len(mini_blob))

    minifat_bytes = b"".join(
        struct.pack("<I", minifat.get(i, _FREESECT))
        for i in range(len(mini_blob) // _MINI_SECTOR)
    )
    minifat_start, num_minifat_sectors = alloc.alloc(len(minifat_bytes))

    dir_start, n_dir_sectors = alloc.alloc((1 + len(names)) * 128)
    dir_bytes = _pad_to_sectors(
        _build_directory(names, big_layout, mini_layout, ministream_start, len(mini_blob)),
        n_dir_sectors,
    )

    fat_start = alloc.cursor
    alloc.fat[fat_start] = _FATSECT
    alloc.cursor += 1

    if alloc.cursor > 128:
        raise ValueError(
            f"fixture too large for a single FAT sector ({alloc.cursor} sectors) "
            "— split into a bigger fixture generator if this is ever needed"
        )

    body = _assemble_body(
        alloc.cursor,
        big_layout=big_layout,
        streams=streams,
        ministream_start=ministream_start,
        mini_blob=mini_blob,
        minifat_start=minifat_start,
        minifat_bytes=minifat_bytes,
        num_minifat_sectors=num_minifat_sectors,
        dir_start=dir_start,
        dir_bytes=dir_bytes,
        n_dir_sectors=n_dir_sectors,
        fat_start=fat_start,
        fat=alloc.fat,
    )
    header = _build_header(
        dir_start=dir_start,
        mini_cutoff=mini_cutoff,
        minifat_start=minifat_start,
        num_minifat_sectors=num_minifat_sectors,
        fat_start=fat_start,
    )

    out = Path(path)
    out.write_bytes(header + bytes(body))
    return out


def write_raw_emi(
    path: str | Path, xml_bytes: bytes, *, prefix: bytes = b"", suffix: bytes = b""
) -> Path:
    """Write `.emi` content with NO CFB wrapper — matches every real file in
    the fei/microscopy corpus. `prefix`/`suffix` simulate the binary tag
    bytes real TIA exports carry around the `<ObjectInfo>` block."""
    out = Path(path)
    out.write_bytes(prefix + xml_bytes + suffix)
    return out
