"""Nanosurf .nid files (Easyscan 2, FlexAFM, CoreAFM, DriveAFM …).

An INI-style text header, then ``#!`` and the binary channel blocks.
``[DataSet]`` lists the groups (``Gr0-Name=Scan forward``) and, per group,
its channels as ``Gr<g>-Ch<c>=DataSet-<g>:<c>``; the blocks follow in that
order, group by group and channel index by channel index. Each channel
section gives ``Points``/``Lines``, ``Dim0Range``/``Dim1Range`` (lateral
size), ``Dim2Name``/``Dim2Unit``/``Dim2Min``/``Dim2Range`` (the value axis)
and ``SaveBits`` (signed little-endian integers).

Scaling and orientation follow Gwyddion's ``ezdfile`` module: a raw value
r of n bits maps to ``Dim2Min + Dim2Range · (r + 2ⁿ⁻¹) / 2ⁿ``, and lines
are stored bottom to top. Every listed channel has a block, as Nanosurf's
NSFopen reads them; one-line blocks (spectroscopy) are stepped over, not
opened. (Gwyddion skips them without advancing — marked FIXME there —
which would misread any image that follows one.) Spectroscopy blocks —
one force curve per line, its length in ``LineDim<n>Points`` — are left
to io/force_nid.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import numpy as np

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.spm_common import (
    length_to_nm_factor,
    primary_channel,
    spm_channel,
    unique_labels,
)

__all__ = ["NidBlock", "NidError", "load_nid", "load_nid_all", "read_nid"]

_MAGIC = b"#!"


class NidError(ValueError):
    """Not a readable Nanosurf .nid image."""


def _sections(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    cur: dict[str, str] | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            cur = out.setdefault(line[1:-1], {})
        elif cur is not None and "=" in line:
            key, _, val = line.partition("=")
            cur[key.strip()] = val.strip()
    return out


def _f(sec: dict[str, str], key: str) -> float:
    try:
        return float(sec[key])
    except (KeyError, ValueError):
        return float("nan")


class NidBlock(NamedTuple):
    group: str                  # e.g. "Scan forward", "Spec backward"
    section: dict[str, str]     # the channel's header section
    raw: np.ndarray             # Lines × Points raw integers, file order

    def scaled(self) -> np.ndarray:
        """Raw → value: ``Dim2Min + Dim2Range · (r + 2ⁿ⁻¹) / 2ⁿ``."""
        q = 2.0 ** (self.raw.dtype.itemsize * 8)
        frac = (self.raw.astype(np.float64) + q / 2) / q
        return frac * _f(self.section, "Dim2Range") + _f(self.section, "Dim2Min")

    @property
    def is_spectroscopy(self) -> bool:
        """Spectroscopy blocks: one curve per line (``LineDim<n>Points``)."""
        return "LineDim0Points" in self.section or self.raw.shape[0] < 2


def read_nid(path: str | Path) -> tuple[dict[str, dict[str, str]], list[NidBlock]]:
    """The header sections and every listed channel block, in file order."""
    buf = Path(path).read_bytes()
    start = buf.find(_MAGIC)
    if start < 0 or b"[DataSet]" not in buf[:start]:
        raise NidError("not a Nanosurf .nid file")
    secs = _sections(buf[:start].decode("latin-1"))
    ds = secs.get("DataSet", {})
    try:
        n_groups = int(ds["GroupCount"])
    except (KeyError, ValueError):
        raise NidError("[DataSet] has no GroupCount") from None
    pos = start + len(_MAGIC)
    blocks = []
    for g in range(n_groups):
        group = ds.get(f"Gr{g}-Name", f"Group {g}")
        keys = sorted((int(m.group(1)), v) for k, v in ds.items()
                      if (m := re.fullmatch(rf"Gr{g}-Ch(\d+)", k)))
        for _, name in keys:
            sec = secs.get(name)
            if sec is None:
                continue
            try:
                nx, ny, bits = int(sec["Points"]), int(sec["Lines"]), int(sec.get("SaveBits", 32))
            except (KeyError, ValueError):
                raise NidError(f"{name}: image size missing") from None
            if bits not in (8, 16, 32):
                raise NidError(f"{name}: unsupported {bits}-bit data")
            size = nx * ny * bits // 8
            if pos + size > len(buf):
                raise NidError(f"{name}: data runs past the end of the file")
            raw = np.frombuffer(buf, dtype=f"<i{bits // 8}", count=nx * ny, offset=pos)
            pos += size                         # every listed channel has a block
            blocks.append(NidBlock(group, sec, raw.reshape(ny, nx)))
    return secs, blocks


def load_nid_all(path: str | Path) -> list[DataStruct]:
    """Every image channel of every group (forward/backward scan)."""
    _, blocks = read_nid(path)
    out = []
    for b in blocks:
        if b.is_spectroscopy:
            continue                            # force curves: io/force_nid.py
        sec, group = b.section, b.group
        ny, nx = b.raw.shape
        direction = {"scan forward": "trace", "scan backward": "retrace"}.get(group.lower(), "")
        data = np.flipud(b.scaled())
        channel = sec.get("Dim2Name", "Channel")
        lat_x = length_to_nm_factor(sec.get("Dim0Unit", "m")) or float("nan")
        lat_y = length_to_nm_factor(sec.get("Dim1Unit", "m")) or float("nan")
        out.append(spm_channel(
            data, parser="nanosurf", channel=channel,
            label=f"{channel} ({direction})" if direction else f"{channel} ({group})",
            value_unit=sec.get("Dim2Unit", ""),
            dy_nm=_f(sec, "Dim1Range") * lat_y / ny, dx_nm=_f(sec, "Dim0Range") * lat_x / nx,
            line_direction=direction or None, nid_group=group,
        ))
    if not out:
        raise NidError("the file holds no image channels (spectroscopy only?)")
    return unique_labels(out)


def load_nid(path: str | Path) -> DataStruct:
    """The topography channel (Z-Axis forward, or the first one)."""
    return primary_channel(load_nid_all(path))
