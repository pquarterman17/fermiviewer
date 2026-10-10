"""Asylum Research force curves saved as Igor binary waves (.ibw).

A force curve is a 2-D wave: time (``dimUnits[0] = "s"``) × channels, the
channels named by the dimension-1 labels — ``Raw`` (Z drive), ``Defl``
(deflection, m), ``ZSnsr`` (Z sensor, m), optionally ``DeflV``, ``LVDT``,
``Amp``, ``Phase`` … The wave note splits time into segments:
``Indexes: 0,224,1232,1260,`` gives the boundaries and ``Direction:
Nan,1,-1,0,`` the direction of the segment ending at each (1 extend, −1
retract, 0 dwell). ``SpringConstant`` (N/m) and ``InvOLS`` (m/V) are the
calibration Asylum applied to ``Defl``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from fermiviewer.io.force_common import ForceCurve, ForceError, ForceFile, ForceSegment
from fermiviewer.io.ibw import IbwError, IgorWave, read_wave

__all__ = ["is_ibw_force", "load_ibw_force"]

_KINDS = {1: "approach", -1: "retract", 0: "dwell"}


def _floats(s: str) -> list[float]:
    out = []
    for tok in s.split(","):
        tok = tok.strip()
        if tok:
            try:
                out.append(float(tok))
            except ValueError:
                out.append(float("nan"))
    return out


def _columns(w: IgorWave) -> dict[str, np.ndarray]:
    if w.data.ndim != 2 or w.dim_units[0] != "s":
        return {}
    names = w.labels[1]
    return {name: w.data[:, i].astype(np.float64)
            for i, name in enumerate(names[: w.data.shape[1]]) if name}


def is_ibw_force(path: str | Path) -> bool:
    try:
        cols = _columns(read_wave(path))
    except (IbwError, OSError):
        return False
    return any(c in cols for c in ("Defl", "DeflV"))


def _segments(n: int, note: dict[str, str], z: np.ndarray) -> list[tuple[str, slice]]:
    idx = [int(v) for v in _floats(note.get("Indexes", "")) if np.isfinite(v)]
    dirs = _floats(note.get("Direction", ""))
    if len(idx) >= 2 and len(dirs) >= len(idx) and idx[-1] < n + 1:
        return [(_KINDS.get(int(dirs[i + 1]), "dwell") if np.isfinite(dirs[i + 1]) else "dwell",
                 slice(idx[i], idx[i + 1] + 1)) for i in range(len(idx) - 1)]
    turn = int(np.argmax(np.abs(z - z[0])))       # no segment table: split at the turn
    return [("approach", slice(0, turn + 1)), ("retract", slice(turn, n))]


def load_ibw_force(path: str | Path) -> ForceFile:
    try:
        w = read_wave(path)
    except IbwError as e:
        raise ForceError(str(e)) from None
    cols = _columns(w)
    note = w.note
    if "Defl" in cols:
        defl, unit = cols["Defl"] * 1e9, "nm"
    elif "DeflV" in cols:
        defl, unit = cols["DeflV"], "V"
    else:
        raise ForceError("not an Asylum force curve (no Defl / DeflV column)")
    zkey = next((k for k in ("ZSnsr", "Raw", "LVDT") if k in cols), None)
    if zkey is None:
        raise ForceError("force curve without a Z column (ZSnsr / Raw)")
    z = cols[zkey] * 1e9
    segs = [ForceSegment(kind, z[sl], defl[sl]) for kind, sl in _segments(len(z), note, z)]

    def num(key: str) -> float:
        v = _floats(note.get(key, ""))
        return v[0] if v else float("nan")

    curve = ForceCurve(segs, label=Path(path).name)
    return ForceFile(
        [curve], parser="asylum", deflection_unit=unit,
        spring_constant=num("SpringConstant"), invols=num("InvOLS") * 1e9,
        z_source="Z sensor" if zkey == "ZSnsr" else "Z drive",
        metadata={"channels": list(cols)},
    )
