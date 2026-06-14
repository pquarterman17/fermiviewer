"""Bruker SpectrumData0 hypercube decoder.

Port of fermi-viewer's decodeBcfCube.m (itself pinned to HyperSpy's
py_parse_hypermap). Three per-pixel packings: raw 16-bit channel lists
(flag 0), 12-bit nibble-packed pulse lists (flag 1), and instructive
run-length with gain + deltas (flag > 1). Zero-count channels are
omitted, so every pixel is variable length.

Correctness oracle: cube summed over all pixels == the <Channels> sum
spectrum in the XML header (enforced in tests).
"""

from __future__ import annotations

import numpy as np

__all__ = ["decode_cube"]

_FIRST_LINE_OFFSET = 0x1A0  # 416
_PIXEL_HEADER = 22


def _u16(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off : off + 2], "little")


def _u32(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off : off + 4], "little")


def decode_cube(buf: bytes, max_chan: int) -> np.ndarray | None:
    """Decode to a dense [H, W, max_chan] cube (uint16 when it fits)."""
    n = len(buf)
    if n < 8:
        return None
    height = int.from_bytes(buf[0:4], "little", signed=True)
    width = int.from_bytes(buf[4:8], "little", signed=True)
    if height <= 0 or width <= 0 or height > 1e5 or width > 1e5:
        return None

    max_chan = int(max_chan)
    vfa = np.zeros(height * width * max_chan, dtype=np.uint32)
    a = np.frombuffer(buf, dtype=np.uint8)

    offset = _FIRST_LINE_OFFSET
    for line in range(height):
        if offset + 4 > n:
            break
        line_head = int.from_bytes(buf[offset : offset + 4], "little", signed=True)
        offset += 4
        line_head = max(line_head, 0)

        for _ in range(line_head):
            if offset + _PIXEL_HEADER > n:
                offset = n + 1
                break
            offset = _decode_pixel(a, buf, offset, n, max_chan, width, line, vfa)
        if offset > n:
            break

    cube = vfa.reshape(height, width, max_chan)
    if cube.max(initial=0) <= np.iinfo(np.uint16).max:
        return cube.astype(np.uint16)
    return cube


def _decode_pixel(
    a: np.ndarray, buf: bytes, offset: int, n: int,
    max_chan: int, width: int, line: int, vfa: np.ndarray,
) -> int:
    """Decode one pixel record and scatter it into the flat cube."""
    x_pix = _u32(buf, offset)
    chan1 = _u16(buf, offset + 4)
    chan2 = _u16(buf, offset + 6)
    flag = _u16(buf, offset + 12)
    n_pulses = _u16(buf, offset + 16)
    data_size2 = _u32(buf, offset + 18)
    offset += _PIXEL_HEADER
    if chan1 < 1:
        chan1 = max_chan

    if flag == 0:
        pixel, offset = _decode_raw16(a, offset, data_size2, chan1, n)
    elif flag == 1:
        pixel, offset = _decode_12bit(a, offset, data_size2, n_pulses, chan1, n)
    else:
        pixel, offset = _decode_instructive(
            a, buf, offset, data_size2, chan1, chan2, n_pulses, n
        )

    vlen = min(min(chan1, max_chan), pixel.size)
    if vlen > 0:
        base = max_chan * (x_pix + width * line)
        if 0 <= base and base + vlen <= vfa.size:
            vfa[base : base + vlen] = pixel[:vlen]
    return offset


def _decode_raw16(
    a: np.ndarray, offset: int, size: int, chan1: int, n: int
) -> tuple[np.ndarray, int]:
    if size >= 2 and offset + size <= n:
        idx = a[offset : offset + (size // 2) * 2].view("<u2")
        pixel = np.bincount(idx, minlength=chan1).astype(np.uint32)
    else:
        pixel = np.zeros(chan1, dtype=np.uint32)
    return pixel, offset + size


def _decode_12bit(
    a: np.ndarray, offset: int, size: int, n_pulses: int, chan1: int, n: int
) -> tuple[np.ndarray, int]:
    if n_pulses > 0 and offset + size <= n:
        d = a[offset : offset + size]
        n2 = (d.size // 2) * 2
        swapped = d[:n2].reshape(-1, 2)[:, ::-1].reshape(-1)   # byteswap pairs
        data2 = np.repeat(swapped, 2)
        i0 = np.arange(data2.size)
        masked = data2[(i0 % 6 != 0) & (i0 % 6 != 5)]
        need = 2 * n_pulses
        if masked.size >= need:
            m = masked[:need].astype(np.uint16)
            e16 = (m[0::2] << 8) | m[1::2]                      # big-endian u16
            e16[0::2] >>= 4
            e16 &= 0xFFF
            pixel = np.bincount(e16, minlength=chan1).astype(np.uint32)
        else:
            pixel = np.zeros(chan1, dtype=np.uint32)
    else:
        pixel = np.zeros(chan1, dtype=np.uint32)
    return pixel, offset + size


def _decode_instructive(
    a: np.ndarray, buf: bytes, offset: int, size: int,
    chan1: int, chan2: int, n_pulses: int, n: int,
) -> tuple[np.ndarray, int]:
    pixel = np.zeros(chan1 + 32, dtype=np.int64)
    pp = 0
    the_end = offset + size - 4
    while offset < the_end and offset + 2 <= n:
        size_p = buf[offset]
        channels = buf[offset + 1]
        offset += 2
        if size_p == 0:
            pp += channels
            continue
        if size_p not in (1, 2, 4, 8):
            # BCF only defines gain widths of 1/2/4/8 bytes (→ nibble or
            # 1/2/4-byte deltas); any other value means the instructive
            # stream is corrupt or desynced. Skip to this pixel's boundary
            # to stay aligned rather than crashing on an invalid numpy
            # dtype like "<u3". (rsciio's decoder likewise only handles
            # sizes 1/2/4/8 — verified against unbcf_fast.pyx.)
            offset = the_end
            break
        gain = int.from_bytes(buf[offset : offset + size_p], "little")
        offset += size_p
        if size_p == 1:
            length = -(-channels // 2)                          # ceil
            half = a[offset : offset + length].astype(np.int64)
            g = np.empty(2 * half.size, dtype=np.int64)
            g[0::2] = (half & 15) + gain
            g[1::2] = (half >> 4) + gain
            pixel[pp : pp + channels] = g[:channels]
        else:
            esz = size_p // 2
            length = channels * esz
            vals = a[offset : offset + length].view(f"<u{esz}").astype(np.int64)
            pixel[pp : pp + channels] = vals + gain
        pp += channels
        offset += length

    if pp < chan1 and chan2 < chan1:
        pp = chan1
    pixel = pixel[: max(pp, 0)]

    # additional sparse pulses
    if n_pulses > 0 and offset + 4 <= n:
        add_s = _u32(buf, offset)
        offset += 4
        if add_s >= 2 and offset + add_s <= n:
            pulses = a[offset : offset + (add_s // 2) * 2].view("<u2")
            valid = pulses[pulses < pixel.size]
            if valid.size:
                pixel = pixel + np.bincount(valid, minlength=pixel.size)
        offset += add_s
    else:
        offset += 4

    return np.clip(pixel, 0, None).astype(np.uint32), offset
