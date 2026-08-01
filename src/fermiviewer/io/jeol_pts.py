"""JEOL ``.pts`` raw event-stream decoder — the per-pixel pulse list that
follows the ``.pts`` header (see ``jeol.py`` for the header/dict format).

Format (empirically derived — see module docstring in ``jeol.py`` for the
license/derivation policy). The stream is a flat sequence of 16-bit
little-endian words. The top nibble selects the word's meaning; the low 12
bits are its payload:

    0x9xxx  new scan line:      y = payload >> 3   (absolute row index)
    0x8xxx  new column:         x = payload >> 3   (absolute column index)
    0xBxxx  X-ray hit:          channel = payload  (0-4095, cube's last axis)
    0x6xxx / 0x7xxx             clock/dead-time ticks — no payload, ignored
    anything else               unrecognised — ignored (forward compatible)

``x``/``y`` are "current position" registers: a hit event is binned at the
most recently seen (x, y), starting from (0, 0) before the first marker (the
stream always opens with a 0x9/0x8 pair in every real file seen). This
reproduces rosettasciio's ``.pts`` decoder's cube byte-for-byte on the
development corpus (``tests/test_jeol.py``'s oracle test) — verified by
running rsciio as a black-box comparison tool, never by reading its source.
"""

from __future__ import annotations

import numpy as np

__all__ = ["decode_pts_stream"]


def decode_pts_stream(
    buf: bytes,
    start: int,
    end: int,
    width: int,
    height: int,
    n_channels: int = 4096,
) -> tuple[np.ndarray, int]:
    """Decode the raw event stream ``buf[start:end]`` into a dense
    ``(height, width, n_channels)`` hit-count cube.

    Returns ``(cube, n_hits)`` — ``n_hits`` is the total number of 0xB
    (X-ray) events seen, including any dropped for landing outside
    ``[0, width) x [0, height) x [0, n_channels)`` (a malformed/truncated
    stream can carry a stray out-of-range position or channel; those hits
    are counted but not binned rather than raising).
    """
    raw = buf[start:end]
    n16 = len(raw) // 2
    words = np.frombuffer(raw[: n16 * 2], dtype="<u2").astype(np.uint32)
    nib = words >> 12
    payload = words & 0x0FFF

    is_y = nib == 0x9
    is_x = nib == 0x8
    is_hit = nib == 0xB

    # Forward-fill the most recent X/Y marker's value onto every later
    # index (a hit's position is whatever X/Y was last announced before it).
    idx = np.arange(words.size)
    y_source = np.maximum.accumulate(np.where(is_y, idx, -1))
    x_source = np.maximum.accumulate(np.where(is_x, idx, -1))

    y_cur = np.zeros(words.size, dtype=np.int64)
    x_cur = np.zeros(words.size, dtype=np.int64)
    has_y, has_x = y_source >= 0, x_source >= 0
    y_cur[has_y] = payload[y_source[has_y]] >> 3
    x_cur[has_x] = payload[x_source[has_x]] >> 3

    ys, xs, chs = y_cur[is_hit], x_cur[is_hit], payload[is_hit]
    n_hits = int(is_hit.sum())

    valid = (ys < height) & (xs < width) & (chs < n_channels)
    ys, xs, chs = ys[valid], xs[valid], chs[valid]

    cube = np.zeros((height, width, n_channels), dtype=np.uint16)
    np.add.at(cube, (ys, xs, chs), 1)
    return cube, n_hits
