"""Nanosurf force spectroscopy in .nid files (single curves and maps).

Spectroscopy groups sit beside the image groups (io/nid.py reads the
blocks): ``Spec forward`` is the approach, ``Spec backward`` the retract.
Each channel block holds one curve per line — ``Lines`` curves of up to
``Points`` samples, curve n keeping its first ``LineDim<n>Points`` — in the
value unit ``Dim2Unit``. Deflection comes as force (N), already through
the cantilever calibration of ``[DataSet\\Calibration\\Cantilever]``
(``Prop0`` = spring constant, N/m), so it is turned back into nm with
that k; Z comes from ``Z-Axis Sensor`` when recorded, else ``Z-Axis``.

``[DataSet\\SpecInfos\\SpecMapTable]`` ``Map0 = x0;x1;y0;y1;nx;ny;…`` (m)
describes a grid of curves. They are recorded row by row from (x0, y0),
serpentine (odd rows right to left), as Nanosurf's NSFopen example
assumes when it builds maps; the curves are reordered into image order
(top row first, y1 at the top).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from fermiviewer.io.force_common import ForceCurve, ForceError, ForceFile, ForceSegment
from fermiviewer.io.nid import NidBlock, NidError, read_nid

__all__ = ["is_nid_force", "load_nid_force", "nid_has_images"]

_SEGMENTS = {"spec forward": "approach", "spec backward": "retract"}


def _spec_blocks(blocks: list[NidBlock]) -> dict[str, dict[str, NidBlock]]:
    out: dict[str, dict[str, NidBlock]] = {}
    for b in blocks:
        kind = _SEGMENTS.get(b.group.lower())
        if kind and b.is_spectroscopy:
            out.setdefault(kind, {})[b.section.get("Dim2Name", "")] = b
    return out


def _header_has_spec(path: str | Path) -> bool:
    head = Path(path).read_bytes()[:1 << 20]
    return b"#!" in head and b"=Spec forward" in head.split(b"#!", 1)[0]


def is_nid_force(path: str | Path) -> bool:
    try:
        return _header_has_spec(path) and "approach" in _spec_blocks(read_nid(path)[1])
    except (NidError, OSError):
        return False


def nid_has_images(path: str | Path) -> bool:
    try:
        return any(not b.is_spectroscopy for b in read_nid(path)[1])
    except (NidError, OSError):
        return False


def _prop(value: str) -> float:
    """``D[2.72436]*[N/m]`` → 2.72436."""
    m = re.match(r"\w\[([^\]]*)\]", value or "")
    try:
        return float(m.group(1)) if m else float("nan")
    except ValueError:
        return float("nan")


def _curves(block: NidBlock) -> list[np.ndarray]:
    data = block.scaled()
    lengths = [int(block.section.get(f"LineDim{i}Points", str(data.shape[1])))
               for i in range(data.shape[0])]
    return [row[:n] for row, n in zip(data, lengths, strict=True)]


def _map(secs: dict[str, dict[str, str]], n: int) -> tuple[list[int], tuple[int, int] | None,
                                                            tuple[float, float] | None,
                                                            list[tuple[float, float] | None]]:
    """(curve order in image raster, grid, pitch (dy, dx) in nm, positions)."""
    table = secs.get("DataSet\\SpecInfos\\SpecMapTable", {})
    fields = table.get("Map0", "").split(";")
    try:
        x0, x1, y0, y1 = (float(v) * 1e9 for v in fields[:4])
        nx, ny = int(fields[4]), int(fields[5])
    except (ValueError, IndexError):
        return list(range(n)), None, None, [None] * n
    if nx * ny != n or nx < 1 or ny < 1:
        return list(range(n)), None, None, [None] * n
    order: list[int] = []
    pos: list[tuple[float, float] | None] = []
    for row in range(ny):                       # image row 0 = the last recorded line
        line = ny - 1 - row
        for col in range(nx):
            rec_col = nx - 1 - col if line % 2 else col
            order.append(line * nx + rec_col)
            pos.append((x0 + (x1 - x0) * col / max(nx - 1, 1),
                        y0 + (y1 - y0) * line / max(ny - 1, 1)))
    pitch = (abs(y1 - y0) / max(ny - 1, 1), abs(x1 - x0) / max(nx - 1, 1))
    return order, (ny, nx), pitch, pos


def load_nid_force(path: str | Path) -> ForceFile:
    try:
        secs, blocks = read_nid(path)
    except NidError as e:
        raise ForceError(str(e)) from None
    spec = _spec_blocks(blocks)
    k = _prop(secs.get("DataSet\\Calibration\\Cantilever", {}).get("Prop0", ""))
    per_kind: dict[str, tuple[list[np.ndarray], list[np.ndarray]]] = {}
    z_source = ""
    for kind, chans in spec.items():
        defl = chans.get("Deflection")
        zb = chans.get("Z-Axis Sensor") or chans.get("Z-Axis")
        if defl is None or zb is None:
            continue
        unit = defl.section.get("Dim2Unit", "")
        if unit == "N":
            if not np.isfinite(k) or k <= 0:
                raise ForceError("deflection recorded as force but no spring constant")
            scale = 1e9 / k
        elif unit == "m":
            scale = 1e9
        else:
            raise ForceError(f"deflection in {unit or 'no unit'} — expected N or m")
        z_source = "Z sensor" if "Z-Axis Sensor" in chans else "Z drive"
        per_kind[kind] = ([c * 1e9 for c in _curves(zb)], [c * scale for c in _curves(defl)])
    if "approach" not in per_kind:
        raise ForceError("no Spec forward deflection and Z channels")
    n = len(per_kind["approach"][0])
    order, grid, pitch, pos = _map(secs, n)
    curves = []
    for rank, i in enumerate(order):
        segs = [ForceSegment(kind, zs[i], ds[i]) for kind, (zs, ds) in per_kind.items()
                if i < len(zs)]
        try:
            curves.append(ForceCurve(segs, label=f"curve {i + 1}", position_nm=pos[rank]))
        except ForceError:
            continue                             # ForceFile drops a grid left incomplete
    return ForceFile(
        curves, parser="nanosurf", deflection_unit="nm", spring_constant=k,
        z_source=z_source, grid=grid, map_pitch_nm=pitch,
    )
