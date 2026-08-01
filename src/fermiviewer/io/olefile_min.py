"""Minimal read-only Compound File Binary (CFB) container reader.

Hand-rolled, dependency-free implementation of just enough of [MS-CFB]
(Microsoft's "Compound File Binary File Format" spec) to open legacy
OLE2-structured-storage files such as FEI/TIA's `.emi` experiment files:
header parsing, FAT sector-chain walking, directory-entry enumeration, and
stream extraction (both regular-FAT streams and the small-stream MiniFAT
path). Read-only — no write/modify support, no compression.

Not a general-purpose OLE library: no CLSID/property-set decoding, no
red-black-tree-ordered name lookup (directory sectors are scanned linearly
instead — every allocated entry occupies a slot there regardless of the
tree's sibling/child pointers, so a linear scan finds every stream just as
completely as a tree walk would). Good enough for "does this container hold
a stream with such-and-such bytes in it", which is the only thing
`io.emi` needs.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["OleError", "OleFile", "OleStreamEntry", "is_ole"]

MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_FREESECT = 0xFFFFFFFF
_ENDOFCHAIN = 0xFFFFFFFE
_FATSECT = 0xFFFFFFFD
_DIFSECT = 0xFFFFFFFC
_NOSTREAM = 0xFFFFFFFF

TYPE_UNKNOWN = 0
TYPE_STORAGE = 1
TYPE_STREAM = 2
TYPE_ROOT = 5

_HEADER_SIZE = 512
_DIR_ENTRY_SIZE = 128
_DIFAT_HEADER_ENTRIES = 109


class OleError(ValueError):
    pass


def is_ole(buf: bytes) -> bool:
    """True if `buf` starts with the CFB magic (a cheap, non-throwing probe)."""
    return len(buf) >= 8 and buf[:8] == MAGIC


def _u16(b: bytes, o: int) -> int:
    return int.from_bytes(b[o : o + 2], "little")


def _u32(b: bytes, o: int) -> int:
    return int.from_bytes(b[o : o + 4], "little")


def _u64(b: bytes, o: int) -> int:
    return int.from_bytes(b[o : o + 8], "little")


@dataclass(frozen=True)
class OleStreamEntry:
    """One parsed 128-byte directory entry (storage, stream, or root)."""

    name: str
    obj_type: int
    start_sector: int
    size: int


class OleFile:
    """Whole-file in-memory CFB reader (paired `.emi` files are small)."""

    def __init__(self, buf: bytes, source: str = "<bytes>") -> None:
        if not is_ole(buf):
            raise OleError(f"not a Compound File Binary container: {source}")
        if len(buf) < _HEADER_SIZE:
            raise OleError(f"CFB header truncated: {source}")
        self.buf = buf
        self.source = source

        sector_shift = _u16(buf, 30)
        mini_sector_shift = _u16(buf, 32)
        if not (0 < sector_shift < 31) or not (0 < mini_sector_shift < 31):
            raise OleError(f"implausible CFB sector shift: {source}")
        self.sector_size = 1 << sector_shift
        self.mini_sector_size = 1 << mini_sector_shift

        num_fat_sectors = _u32(buf, 44)
        first_dir_sector = _u32(buf, 48)
        self.mini_cutoff = _u32(buf, 56)
        first_minifat_sector = _u32(buf, 60)
        num_minifat_sectors = _u32(buf, 64)
        first_difat_sector = _u32(buf, 68)
        num_difat_sectors = _u32(buf, 72)

        self._fat = self._read_fat(
            first_difat_sector, num_difat_sectors, num_fat_sectors
        )
        dir_bytes = self._read_chain(first_dir_sector)
        self.entries: list[OleStreamEntry] = self._parse_directory(dir_bytes)
        self._root = self.entries[0] if self.entries else None

        self._minifat = (
            self._read_minifat(first_minifat_sector, num_minifat_sectors)
            if num_minifat_sectors
            else []
        )
        self._ministream = (
            self._read_chain(self._root.start_sector, self._root.size)
            if self._root and self._root.size
            else b""
        )

    # ── sector-level plumbing ───────────────────────────────────────────

    def _sector_offset(self, sector_id: int) -> int:
        # The header always occupies exactly one sector-sized block
        # (padded for 4096-byte-sector files), so sector 0 starts right
        # after it: offset = (id + 1) * sector_size.
        return (sector_id + 1) * self.sector_size

    def _sector(self, sector_id: int) -> bytes:
        off = self._sector_offset(sector_id)
        data = self.buf[off : off + self.sector_size]
        if len(data) < self.sector_size:  # tolerate a truncated final sector
            data = data + b"\x00" * (self.sector_size - len(data))
        return data

    def _read_fat(
        self, first_difat_sector: int, num_difat_sectors: int, num_fat_sectors: int
    ) -> list[int]:
        buf = self.buf
        difat = [_u32(buf, 76 + 4 * i) for i in range(_DIFAT_HEADER_ENTRIES)]
        sector = first_difat_sector
        seen: set[int] = set()
        entries_per_difat_sector = self.sector_size // 4 - 1
        for _ in range(num_difat_sectors):
            if sector in (_FREESECT, _ENDOFCHAIN) or sector in seen:
                break
            seen.add(sector)
            data = self._sector(sector)
            difat.extend(_u32(data, 4 * i) for i in range(entries_per_difat_sector))
            sector = _u32(data, entries_per_difat_sector * 4)

        fat: list[int] = []
        entries_per_fat_sector = self.sector_size // 4
        for i in range(min(num_fat_sectors, len(difat))):
            fat_sector = difat[i]
            if fat_sector in (_FREESECT, _ENDOFCHAIN):
                break
            data = self._sector(fat_sector)
            fat.extend(_u32(data, 4 * j) for j in range(entries_per_fat_sector))
        return fat

    def _read_chain(self, start_sector: int, size: int | None = None) -> bytes:
        """Regular-FAT sector chain → concatenated bytes (truncated to `size`)."""
        if start_sector in (_ENDOFCHAIN, _FREESECT, _NOSTREAM):
            return b""
        out = bytearray()
        sector = start_sector
        seen: set[int] = set()
        while sector not in (_ENDOFCHAIN, _FREESECT) and sector not in seen:
            seen.add(sector)
            out += self._sector(sector)
            if size is not None and len(out) >= size:
                break
            if sector >= len(self._fat):
                raise OleError(f"FAT chain runs past end of FAT: {self.source}")
            sector = self._fat[sector]
        return bytes(out[:size]) if size is not None else bytes(out)

    def _read_minifat(self, first_sector: int, num_sectors: int) -> list[int]:
        raw = bytearray()
        sector = first_sector
        seen: set[int] = set()
        for _ in range(num_sectors):
            if sector in (_ENDOFCHAIN, _FREESECT) or sector in seen:
                break
            seen.add(sector)
            raw += self._sector(sector)
            if sector >= len(self._fat):
                raise OleError(f"MiniFAT chain runs past end of FAT: {self.source}")
            sector = self._fat[sector]
        return [_u32(bytes(raw), 4 * i) for i in range(len(raw) // 4)]

    def _parse_directory(self, dir_bytes: bytes) -> list[OleStreamEntry]:
        entries = []
        n = len(dir_bytes) // _DIR_ENTRY_SIZE
        for k in range(n):
            base = k * _DIR_ENTRY_SIZE
            rec = dir_bytes[base : base + _DIR_ENTRY_SIZE]
            obj_type = rec[66]
            if obj_type == TYPE_UNKNOWN:
                continue  # unallocated directory slot
            name_len = _u16(rec, 64)
            name = rec[: max(name_len - 2, 0)].decode("utf-16-le", errors="replace")
            entries.append(
                OleStreamEntry(
                    name=name,
                    obj_type=obj_type,
                    start_sector=_u32(rec, 116),
                    size=_u64(rec, 120),
                )
            )
        return entries

    # ── public API ───────────────────────────────────────────────────────

    def read_stream(self, entry: OleStreamEntry) -> bytes:
        """Full contents of a stream (or root) directory entry."""
        if entry.obj_type == TYPE_ROOT:
            return self._ministream[: entry.size]
        if entry.size <= 0:
            return b""
        if entry.size < self.mini_cutoff:
            return self._read_mini_chain(entry.start_sector, entry.size)
        return self._read_chain(entry.start_sector, entry.size)

    def _read_mini_chain(self, start_mini_sector: int, size: int) -> bytes:
        out = bytearray()
        mini = start_mini_sector
        seen: set[int] = set()
        mss = self.mini_sector_size
        while mini not in (_ENDOFCHAIN, _FREESECT) and mini not in seen:
            seen.add(mini)
            off = mini * mss
            out += self._ministream[off : off + mss]
            if len(out) >= size:
                break
            if mini >= len(self._minifat):
                raise OleError(f"MiniFAT chain runs past end of table: {self.source}")
            mini = self._minifat[mini]
        return bytes(out[:size])

    def streams(self) -> list[OleStreamEntry]:
        return [e for e in self.entries if e.obj_type == TYPE_STREAM]
