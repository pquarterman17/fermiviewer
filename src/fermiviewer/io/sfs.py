"""Bruker SFS (Single File System) container reader.

Port of the SFS plumbing in fermi-viewer's importBCF.m (chunk-chain fix
2026-06-06). Layout: 32-byte chunk headers whose first uint32 chains
pointer-table chunks; chunk i starts at 0x118 + i·chunkSize; data at +32.
Internal files over ~chunkSize/4 chunks span MULTIPLE table chunks — the
chain must be walked, never read contiguously (real Esprit maps crash
otherwise). AACS-compressed internal files are zlib blocks.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np

__all__ = ["SFSError", "SfsEntry", "SfsFile"]

MAGIC = b"AAMVHFSS"
CHUNK_BASE = 0x118  # 280
ENTRY_SIZE = 512


class SFSError(ValueError):
    pass


@dataclass(frozen=True)
class SfsEntry:
    name: str
    ptr_table: int
    file_size: int
    is_dir: bool


class SfsFile:
    """Whole-file in-memory SFS reader (committed corpora are ≤ tens of MB)."""

    def __init__(self, raw: bytes, source: str = "<bytes>") -> None:
        if len(raw) < 336 or raw[:8] != MAGIC:
            raise SFSError(f"not a Bruker SFS/BCF file: {source}")
        self.raw = raw
        self.source = source
        self.chunk_size = int.from_bytes(raw[0x128:0x12C], "little")
        self.usable = self.chunk_size - 32
        tree_addr = int.from_bytes(raw[0x140:0x144], "little")
        item_count = int.from_bytes(raw[0x144:0x148], "little")

        tree_base = tree_addr * self.chunk_size + CHUNK_BASE + 32
        tree_end = tree_base + item_count * ENTRY_SIZE
        if tree_end > len(raw):
            raise SFSError(f"SFS file tree truncated: {source}")

        self.entries: list[SfsEntry] = []
        for k in range(item_count):
            base = tree_base + k * ENTRY_SIZE
            name = raw[base + 224 : base + 224 + 256].split(b"\x00", 1)[0]
            self.entries.append(
                SfsEntry(
                    name=name.decode("latin-1"),
                    ptr_table=int.from_bytes(raw[base : base + 4], "little", signed=True),
                    file_size=int.from_bytes(raw[base + 4 : base + 12], "little"),
                    is_dir=raw[base + 220] != 0,
                )
            )

    def find(self, target: str) -> SfsEntry | None:
        """Case-insensitive match on full path or trailing component."""
        t = target.strip().lower()
        t_short = t.rsplit("/", 1)[-1]
        for e in self.entries:
            if e.is_dir:
                continue
            n = e.name.strip().lower()
            if n == t or n.rsplit("/", 1)[-1] == t_short:
                return e
        return None

    def read(self, entry: SfsEntry) -> bytes:
        """Assemble an internal file from its (possibly multi-chunk) table."""
        size = entry.file_size
        if size <= 0:
            return b""
        n_chunks = -(-size // self.usable)          # ceil
        n_table = -(-n_chunks * 4 // self.usable)

        ptr_bytes = bytearray()
        tab = entry.ptr_table
        for t in range(n_table):
            base = tab * self.chunk_size + CHUNK_BASE
            if base < 0 or base + self.chunk_size > len(self.raw):
                raise SFSError(
                    f"SFS pointer-table chunk {t + 1}/{n_table} out of bounds "
                    f"(chunk {tab}) in {self.source}"
                )
            tab = int.from_bytes(self.raw[base : base + 4], "little")
            ptr_bytes += self.raw[base + 32 : base + self.chunk_size]

        table = np.frombuffer(bytes(ptr_bytes[: n_chunks * 4]), dtype="<u4")

        out = bytearray()
        remaining = size
        for hc, chunk in enumerate(table):
            start = int(chunk) * self.chunk_size + CHUNK_BASE + 32
            take = min(remaining, self.usable)
            if start + take > len(self.raw):
                raise SFSError(
                    f"SFS data chunk {hc + 1}/{n_chunks} out of bounds "
                    f"(chunk {int(chunk)}) in {self.source}"
                )
            out += self.raw[start : start + take]
            remaining -= take
        return bytes(out)


def decompress_if_aacs(data: bytes) -> bytes:
    """Inflate AACS-block-compressed data (passthrough otherwise)."""
    if len(data) < 128 or data[:4] != b"AACS":
        return data
    n_blocks = int.from_bytes(data[12:16], "little")
    out = bytearray()
    pos = 128
    for _ in range(n_blocks):
        if pos + 4 > len(data):
            break
        comp_size = int.from_bytes(data[pos : pos + 4], "little")
        pos += 16  # 4-byte size + 12 padding
        if comp_size == 0 or pos + comp_size > len(data):
            break
        out += zlib.decompress(data[pos : pos + comp_size])
        pos += comp_size
    return bytes(out)
