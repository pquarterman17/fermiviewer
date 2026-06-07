"""Minimal synthetic SFS/BCF container — port of writeMiniSfsBcf.m.

Exercises the fragile parts of the format: small ChunkSize forcing
multi-chunk pointer tables (chained through chunk headers), shuffled
data-chunk placement, and chunk 0 reserved (its region overlaps the SFS
header fields at 0x128–0x147 — real Esprit files leave it to the header).
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["write_mini_sfs_bcf"]


def write_mini_sfs_bcf(
    path: str | Path,
    xml_bytes: bytes,
    chunk_size: int = 512,
    shuffle: bool = True,
    break_table_at: int = 0,
) -> Path:
    usable = chunk_size - 32
    file_size = len(xml_bytes)

    n_data = -(-file_size // usable)
    n_tab = -(-n_data * 4 // usable)
    first_tab = n_data + 1
    tree_chunk = n_data + n_tab + 1

    if shuffle and n_data > 1:
        data_idx = list(range(1, n_data + 1, 2)) + list(range(2, n_data + 1, 2))
    else:
        data_idx = list(range(1, n_data + 1))

    total = 280 + tree_chunk * chunk_size + 32 + 512
    buf = bytearray(total)

    buf[0:8] = b"AAMVHFSS"
    buf[0x128:0x12C] = chunk_size.to_bytes(4, "little")
    buf[0x140:0x144] = tree_chunk.to_bytes(4, "little")
    buf[0x144:0x148] = (1).to_bytes(4, "little")

    # data chunks (header next-pointer unused for data chunks)
    for k, c_idx in enumerate(data_idx):
        base = 280 + c_idx * chunk_size
        buf[base : base + 4] = b"\xff\xff\xff\xff"
        lo = k * usable
        sl = xml_bytes[lo : lo + usable]
        buf[base + 32 : base + 32 + len(sl)] = sl

    # pointer table, chained through table-chunk headers
    ptr_bytes = b"".join(i.to_bytes(4, "little") for i in data_idx)
    for t in range(n_tab):
        c_idx = first_tab + t
        base = 280 + c_idx * chunk_size
        nxt = 1_000_000 if break_table_at == t + 1 else (
            c_idx + 1 if t < n_tab - 1 else 0xFFFFFFFF
        )
        buf[base : base + 4] = nxt.to_bytes(4, "little")
        sl = ptr_bytes[t * usable : (t + 1) * usable]
        buf[base + 32 : base + 32 + len(sl)] = sl

    # tree: one 512-byte entry (last region in the file, read contiguously)
    t_base = 280 + tree_chunk * chunk_size
    buf[t_base : t_base + 4] = b"\xff\xff\xff\xff"
    e = t_base + 32
    buf[e : e + 4] = first_tab.to_bytes(4, "little", signed=True)
    buf[e + 4 : e + 12] = file_size.to_bytes(8, "little")
    buf[e + 220] = 0
    name = b"EDSDatabase/HeaderData"
    buf[e + 224 : e + 224 + len(name)] = name

    out = Path(path)
    out.write_bytes(bytes(buf))
    return out
