"""Nanonis scan files (.sxm) — STM / AFM images from the Nanonis controller.

An ASCII header of ``:TAG:`` lines each followed by its value lines, ending
``:SCANIT_END:``; the data starts after the ``\\x1a\\x04`` marker as
big-endian float32 already in physical units (unfinished lines are NaN).
``:SCAN_PIXELS:`` gives columns and rows, ``:SCAN_RANGE:`` the scan size
(m), and ``:DATA_INFO:`` a tab-separated table of channels (Name, Unit,
Direction both/forward/backward). Images follow in that table's order,
forward before backward.

Orientation follows Gwyddion's ``nanonis`` module: backward images are
mirrored left–right (they are stored in scan order) and a scan recorded
``up`` is flipped so its last line is on top.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.spm_common import primary_channel, spm_channel, unique_labels

__all__ = ["SxmError", "is_sxm", "load_sxm", "load_sxm_all"]

_MARKER = b"\x1a\x04"


class SxmError(ValueError):
    """Not a readable Nanonis .sxm file."""


def is_sxm(head: bytes) -> bool:
    return head.startswith(b":NANONIS_VERSION:")


def _tags(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    cur: list[str] | None = None
    for line in text.splitlines():
        if line.startswith(":") and line.endswith(":") and len(line) > 2:
            cur = out.setdefault(line[1:-1], [])
        elif cur is not None:
            cur.append(line)
    return out


def _numbers(lines: list[str] | None) -> list[float]:
    try:
        return [float(t) for t in " ".join(lines or []).split()]
    except ValueError:
        return []


def _data_info(lines: list[str]) -> list[tuple[str, str, tuple[str, ...]]]:
    """(name, unit, directions) per channel from the DATA_INFO table."""
    rows = [ln.split("\t") for ln in lines if ln.strip()]
    if not rows:
        raise SxmError("DATA_INFO missing")
    head = [c.strip().lower() for c in rows[0]]
    try:
        i_name, i_unit, i_dir = head.index("name"), head.index("unit"), head.index("direction")
    except ValueError:
        raise SxmError("DATA_INFO lacks Name/Unit/Direction columns") from None
    out = []
    for row in rows[1:]:
        cells = [c.strip() for c in row]
        if len(cells) <= max(i_name, i_unit, i_dir):
            continue
        dirs = {"both": ("trace", "retrace"), "forward": ("trace",),
                "backward": ("retrace",)}.get(cells[i_dir].lower(), ("trace",))
        out.append((cells[i_name].replace("_", " "), cells[i_unit], dirs))
    return out


def load_sxm_all(path: str | Path) -> list[DataStruct]:
    """Every channel and scan direction as a calibrated image."""
    buf = Path(path).read_bytes()
    if not is_sxm(buf):
        raise SxmError("not a Nanonis .sxm file")
    end = buf.find(_MARKER)
    if end < 0:
        raise SxmError("missing the \\x1a\\x04 data marker")
    tags = _tags(buf[:end].decode("latin-1"))
    pixels = _numbers(tags.get("SCAN_PIXELS"))
    rng = _numbers(tags.get("SCAN_RANGE"))
    if len(pixels) < 2:
        raise SxmError("SCAN_PIXELS missing")
    nx, ny = int(pixels[0]), int(pixels[1])
    channels = _data_info(tags.get("DATA_INFO", []))
    up = " ".join(tags.get("SCAN_DIR", [])).strip().lower() == "up"
    dx = rng[0] * 1e9 / nx if len(rng) >= 2 else float("nan")
    dy = rng[1] * 1e9 / ny if len(rng) >= 2 else float("nan")
    pos = end + len(_MARKER)
    n = nx * ny
    out = []
    bias = _numbers(tags.get("BIAS"))
    for name, unit, dirs in channels:
        for direction in dirs:
            if pos + 4 * n > len(buf):
                raise SxmError("image data runs past the end of the file")
            img = np.frombuffer(buf, dtype=">f4", count=n, offset=pos).reshape(ny, nx)
            pos += 4 * n
            img = img.astype(np.float64)
            if direction == "retrace":
                img = img[:, ::-1]
            if up:
                img = img[::-1]
            out.append(spm_channel(
                img, parser="nanonis", channel=name, label=f"{name} ({direction})",
                value_unit=unit, dy_nm=dy, dx_nm=dx, line_direction=direction,
                bias_v=bias[0] if bias else None,
            ))
    if not out:
        raise SxmError("the file holds no image channels")
    return unique_labels(out)


def load_sxm(path: str | Path) -> DataStruct:
    """The topography channel (Z forward, or the first one)."""
    return primary_channel(load_sxm_all(path))
