"""Minimal synthetic Lispix .rpl + .raw pair writer for tests.

Takes `data` already in fermiviewer's own canonical output shape — 1D
(depth,) for a spectrum, 2D (height, width) for an image, 3D
(height, width, depth) for a spectrum image — and writes the ON-DISK bytes
in whichever order `record_by` implies ("image" = plane-ordered, depth
first; "vector"/"dont-care" = spectrum-ordered, depth last already). A
round trip through `load_rpl` should hand back exactly `data`, regardless of
`record_by` or `byte_order`. Mirrors the minimrc/minispc fixture pattern.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["write_mini_rpl"]

_DATA_TYPE_NAME = {"i": "signed", "u": "unsigned", "f": "float"}
_BYTE_ORDER_SYMBOL = {"dont-care": "=", "little-endian": "<", "big-endian": ">"}


def write_mini_rpl(
    dir_path: str | Path,
    stem: str,
    data,
    *,
    record_by: str = "vector",
    byte_order: str = "dont-care",
    offset_bytes: int = 0,
    axis_cal: dict[str, dict[str, Any]] | None = None,
    extra_header: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    data = np.asarray(data)
    data_type = _DATA_TYPE_NAME.get(data.dtype.kind)
    if data_type is None:
        raise ValueError(f"unsupported test dtype {data.dtype}")
    data_length = data.dtype.itemsize

    if data.ndim == 1:
        width, height, depth = 1, 1, int(data.shape[0])
        on_disk = data
    elif data.ndim == 2:
        height, width = (int(s) for s in data.shape)
        depth = 1
        on_disk = data
    elif data.ndim == 3:
        height, width, depth = (int(s) for s in data.shape)
        on_disk = np.moveaxis(data, -1, 0) if record_by == "image" else data
    else:
        raise ValueError("data must be 1D, 2D, or 3D")

    bo = _BYTE_ORDER_SYMBOL[byte_order]
    payload = np.ascontiguousarray(on_disk).astype(f"{bo}{data.dtype.kind}{data_length}")
    raw_bytes = (b"\x00" * offset_bytes) + payload.tobytes()

    lines = [
        ";test fixture",
        "key\tvalue",
        f"width\t{width}",
        f"height\t{height}",
        f"depth\t{depth}",
        f"offset\t{offset_bytes}",
        f"data-length\t{data_length}",
        f"data-type\t{data_type}",
        f"byte-order\t{byte_order}",
        f"record-by\t{record_by}",
    ]
    for axis, cal in (axis_cal or {}).items():
        for key, val in cal.items():
            lines.append(f"{axis}-{key}\t{val}")
    for key, val in (extra_header or {}).items():
        lines.append(f"{key}\t{val}")

    rpl_path = Path(dir_path) / f"{stem}.rpl"
    raw_path = Path(dir_path) / f"{stem}.raw"
    rpl_path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    raw_path.write_bytes(raw_bytes)
    return rpl_path, raw_path
