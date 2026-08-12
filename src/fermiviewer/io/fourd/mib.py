"""Quantum Detectors Merlin ``.mib`` RAW reader — PLAN_4DSTEM #2.

From-scratch reader; no GPL code read or copied (LiberTEM's MIT-licensed
docs/source were consulted for background on the raw quad-chip layout, but
the exact byte permutation below was derived empirically against the real
``test-data/4dstem/test_data.mib`` + ``test_data.h5`` ground-truth pair —
see ``tests/test_io_fourd_mib.py``'s realdata tests, which check all 132
frames byte-for-byte).

Container format
    A Merlin acquisition is a flat sequence of frames, each::

        [ASCII header, `header_size` bytes][payload, width*height bytes]

    The header is comma-separated ASCII, e.g.::

        MQ1,000950,00768,04,1024,0256,R64,   2x2,0F,2020-03-16 12:29:14...

    Fields used here (0-indexed): ``[0]`` magic ``"MQ1"``; ``[2]`` header
    size in bytes; ``[3]`` number of chips; ``[4]`` on-disk image width;
    ``[5]`` on-disk image height; ``[6]`` dtype tag; ``[7]`` chip layout
    (e.g. ``"2x2"``, whitespace-padded). Merlin never records the SCAN shape
    in the ``.mib`` itself (that lives in a ``.hdr`` sidecar, which this
    corpus does not have) — callers pass ``scan_shape`` explicitly; absent
    that, every frame is treated as one long line-scan (``(1, n_frames)``).

Only the ``R64`` dtype tag is implemented: RAW acquisitions store one byte
per pixel, but bytes within each consecutive **group of 8** (a 64-bit raw
readout word — hence "R64") are stored in REVERSE order relative to true
pixel order. This is confirmed empirically: the raw payload and the
ground-truth decoded frame are an exact permutation of the same byte
multiset (identical per-value histograms across all 132 test frames), and
signature-matching each raw byte position's 132-frame time series against
each truth pixel's time series resolves a 97%-unique bijection whose
structure is exactly this within-group-of-8 reversal.

For a 2x2-chip acquisition (num_chips == 4, chip_layout == "2x2" — the only
multi-chip layout this corpus exercises and the only one implemented), the
on-disk width splits into 4 contiguous 256-column chip blocks (after the
group-of-8 fix is applied) that assemble into the 512x512 quad frame as::

    chip0 chip1        ->   TL  TR
    chip2 chip3              BL  BR

with chips 0 and 1 (the top row) used as read, and chips 2 and 3 (the
bottom row) each rotated 180 degrees before placement — the bottom-row
sensor tiles are physically mounted upside-down relative to the top row.
Single-chip (``num_chips == 1``) acquisitions skip the quad assembly
entirely (only the group-of-8 fix applies); this path is implemented but
UNTESTED against real data (no single-chip sample exists in the corpus) —
any other chip count/layout raises ``MibFormatError`` rather than guessing.

Lazy: only ``open()``s a ``np.memmap`` over the raw file (never read
eagerly) and descrambles one frame — or one block of scan rows — at a time,
on access. Pure ``io/`` layer (numpy/stdlib only).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.calc.fourd.dataset import FourDDataset
from fermiviewer.datastruct import AxisCal

__all__ = ["MibFormatError", "load_mib"]

# Bytes needed to reach past the comma-separated geometry fields; the real
# header pads with spaces/nulls out to `header_size` (e.g. 768), but every
# field this reader uses appears well within the first 200 bytes.
_HEADER_PROBE_BYTES = 256
_RAW_WORD_BYTES = 8  # "R64" = raw, 64-bit (8-byte) readout word


class MibFormatError(ValueError):
    """Raised for unreadable/unsupported ``.mib`` files."""


@dataclass(frozen=True)
class _MibHeader:
    header_size: int
    num_chips: int
    width: int
    height: int
    dtype_tag: str
    chip_layout: str


def _parse_header(probe: bytes) -> _MibHeader:
    text = probe.decode("ascii", errors="replace")
    fields = text.split(",")
    if len(fields) < 8:
        raise MibFormatError("not a Merlin MQ1 raw header: too few comma fields")
    if fields[0] != "MQ1":
        raise MibFormatError(f"not a Merlin MQ1 raw header: magic={fields[0]!r}")
    try:
        header_size = int(fields[2])
        num_chips = int(fields[3])
        width = int(fields[4])
        height = int(fields[5])
    except ValueError as e:
        raise MibFormatError(f"unparseable MQ1 header field: {e}") from None
    # A negative/zero header_size is int()-parseable (e.g. a corrupted "-0001"
    # field) but is never a valid byte offset — left unchecked, it silently
    # slices with a negative start in `_frame` and only surfaces later as an
    # opaque numpy reshape ValueError when a pattern is first decoded, not a
    # clean MibFormatError at open time. Same reasoning for width/height <= 0
    # (a MIB-specific message here beats FourDDataset's generic "det_shape
    # must be positive" one, and it fires immediately rather than after the
    # frame-size arithmetic below has already run on nonsense inputs).
    if header_size <= 0:
        raise MibFormatError(f"invalid header_size {header_size} (must be positive)")
    if width <= 0 or height <= 0:
        raise MibFormatError(
            f"invalid image dimensions {width}x{height} (must be positive)"
        )
    return _MibHeader(
        header_size=header_size,
        num_chips=num_chips,
        width=width,
        height=height,
        dtype_tag=fields[6].strip(),
        chip_layout=fields[7].strip(),
    )


def _undo_raw_word_order(buf: np.ndarray) -> np.ndarray:
    """Reverse each consecutive group of `_RAW_WORD_BYTES` columns.

    ``buf`` is (height, width) uint8. This is a self-inverse permutation
    (each group is a plain reversal), the raw-readout quirk common to every
    chip regardless of chip count/layout.
    """
    h, w = buf.shape
    if w % _RAW_WORD_BYTES != 0:
        raise MibFormatError(
            f"image width {w} is not a multiple of {_RAW_WORD_BYTES} "
            "(required for the R64 raw word-order fix)"
        )
    grouped = buf.reshape(h, w // _RAW_WORD_BYTES, _RAW_WORD_BYTES)
    return grouped[:, :, ::-1].reshape(h, w)


def _assemble_quad(fixed: np.ndarray, num_chips: int) -> np.ndarray:
    """Split a word-order-fixed (height, width) raw frame into chips and
    assemble the final detector frame (see module docstring for the layout)."""
    if num_chips == 1:
        return fixed
    if num_chips != 4:
        raise MibFormatError(
            f"unsupported chip count {num_chips} (only 1 and 4 are implemented)"
        )
    h, w = fixed.shape
    if w % 4 != 0:
        raise MibFormatError(f"width {w} not divisible by 4 chips")
    chip_w = w // 4
    chips = [fixed[:, i * chip_w : (i + 1) * chip_w] for i in range(4)]
    top = np.concatenate([chips[0], chips[1]], axis=1)
    bot = np.concatenate([np.rot90(chips[2], 2), np.rot90(chips[3], 2)], axis=1)
    return np.concatenate([top, bot], axis=0)


class _MibHandle:
    """Lazy per-frame/per-block accessor over a memmapped .mib file.

    Implements the FourDHandle protocol: ``handle[y, x]`` for one pattern,
    ``handle[row0:row1]`` for a block of scan rows. The memmap covers the
    WHOLE file (header bytes included, sliced off per frame) — nothing here
    ever reads more than the frames actually requested.

    Frame order: since Merlin never records the scan geometry, frame index
    ``k`` is mapped to scan position ``(k // cols, k % cols)`` — a plain
    row-major raster assumption. The single real corpus sample is a 132-
    frame line-scan (``scan_shape=(1, 132)``), which can't distinguish this
    from any other raster convention; treat multi-row ``scan_shape`` as an
    ASSUMPTION, not something validated against real multi-row data.
    """

    def __init__(
        self,
        raw: np.memmap,
        header: _MibHeader,
        scan_shape: tuple[int, int],
    ) -> None:
        self._raw = raw
        self._header = header
        self._rows, self._cols = scan_shape

    def _frame(self, index: int) -> np.ndarray:
        h = self._header
        row_bytes = np.asarray(self._raw[index, h.header_size : h.header_size + h.width * h.height])
        buf = row_bytes.reshape(h.height, h.width)
        fixed = _undo_raw_word_order(buf)
        frame = _assemble_quad(fixed, h.num_chips)
        # Force an owned copy: for a single-chip acquisition whose width is
        # exactly one 8-byte raw word (num_chips == 1, so `_assemble_quad`
        # returns `fixed` unmodified), numpy's `.reshape()` after the
        # word-order reversal can degrade to a VIEW still backed by the
        # memmap (only 1 group means merging the group axis is stride-free).
        # A caller holding onto that "one small pattern" — exactly what this
        # lazy reader exists to make cheap — would then transitively keep the
        # whole file memory-mapped open even after `close()`, which on
        # Windows blocks deleting/replacing the file. Every other path here
        # (multi-chip via np.concatenate, multi-word-group via the
        # unavoidable copying reshape) already returns an owned array; this
        # makes that guarantee unconditional.
        return frame.copy()

    def __getitem__(self, key: Any) -> np.ndarray:
        if isinstance(key, tuple) and len(key) == 2:
            y, x = key
            return self._frame(int(y) * self._cols + int(x))
        if isinstance(key, slice):
            row0, row1, step = key.indices(self._rows)
            if step != 1:
                raise ValueError("FourD row slicing must be contiguous (step=1)")
            first = self._frame(row0 * self._cols) if row0 < row1 else None
            det_shape = first.shape if first is not None else (0, 0)
            out = np.empty((max(row1 - row0, 0), self._cols, *det_shape), dtype=np.uint8)
            for r in range(row0, row1):
                for c in range(self._cols):
                    out[r - row0, c] = self._frame(r * self._cols + c)
            return out
        raise TypeError(f"unsupported FourD handle index: {key!r}")

    def close(self) -> None:
        # np.memmap has no explicit close(); drop the reference so the
        # underlying mmap can be released once nothing else holds it.
        self._raw = None  # type: ignore[assignment]


def load_mib(
    path: str | Path, *, scan_shape: tuple[int, int] | None = None
) -> FourDDataset:
    """Open a Merlin ``.mib`` RAW acquisition as a lazy ``FourDDataset``.

    Parameters
    ----------
    path:
        The ``.mib`` file.
    scan_shape:
        ``(rows, cols)`` of the STEM scan. Merlin never records this in the
        ``.mib`` itself; without a ``.hdr`` sidecar there's nothing to infer
        it from, so the default is a single-row line-scan
        ``(1, n_frames)``. Must satisfy ``rows * cols == n_frames``.

    Worst-case RAM: none beyond the memmap page cache and whatever block the
    caller subsequently requests — this function itself never reads frame
    payloads.
    """
    p = Path(path)
    file_size = p.stat().st_size
    with open(p, "rb") as fh:
        probe = fh.read(_HEADER_PROBE_BYTES)
    header = _parse_header(probe)
    if header.dtype_tag != "R64":
        raise MibFormatError(
            f"{p.name}: unsupported MIB dtype tag {header.dtype_tag!r} "
            "(only the 'R64' raw single-byte format is implemented)"
        )
    payload_size = header.width * header.height  # R64 = 1 byte/pixel
    frame_size = header.header_size + payload_size
    if frame_size <= 0 or file_size % frame_size != 0:
        raise MibFormatError(
            f"{p.name}: file size {file_size} is not a multiple of the "
            f"frame size {frame_size} (header {header.header_size} + "
            f"payload {payload_size})"
        )
    n_frames = file_size // frame_size

    if header.num_chips == 4 and header.chip_layout == "2x2":
        chip_rows_out, chip_cols_out = 2, 2
    elif header.num_chips == 1:
        chip_rows_out, chip_cols_out = 1, 1
    else:
        raise MibFormatError(
            f"{p.name}: unsupported chip layout {header.chip_layout!r} "
            f"with {header.num_chips} chips — only single-chip and 2x2-quad "
            "Merlin raw layouts are implemented"
        )
    if header.width % header.num_chips != 0:
        raise MibFormatError(
            f"{p.name}: width {header.width} not divisible by "
            f"{header.num_chips} chips"
        )
    det_h = header.height * chip_rows_out
    det_w = (header.width // header.num_chips) * chip_cols_out

    if scan_shape is None:
        rows, cols = 1, n_frames
    else:
        rows, cols = scan_shape
    if rows * cols != n_frames:
        raise MibFormatError(
            f"{p.name}: scan_shape ({rows}, {cols}) = {rows * cols} pixels "
            f"does not match {n_frames} frames in the file"
        )

    raw = np.memmap(p, dtype=np.uint8, mode="r", shape=(n_frames, frame_size))
    handle = _MibHandle(raw, header, (rows, cols))
    meta: dict[str, Any] = {
        "source": str(p),
        "parser": "mib",
        "chip_layout": header.chip_layout,
        "num_chips": header.num_chips,
        "dtype_tag": header.dtype_tag,
        "n_frames": n_frames,
        # Merlin records no raster: every (rows, cols) with rows*cols ==
        # n_frames is equally consistent with this file, so the scan shape is
        # a user decision and /fourd/{id}/reshape exists to take it.
        "scan_shape_from_file": False,
    }
    return FourDDataset(
        handle=handle,
        scan_shape=(rows, cols),
        det_shape=(det_h, det_w),
        scan_axes=(AxisCal(), AxisCal()),  # no .hdr sidecar => uncalibrated
        det_axes=(AxisCal(), AxisCal()),
        dtype=np.dtype(np.uint8),
        metadata=meta,
        close_fn=handle.close,
    )
