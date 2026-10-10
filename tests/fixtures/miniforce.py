"""Tiny synthetic AFM force-curve files (Bruker, Asylum IBW, Nanosurf NID)
written to each vendor's layout, so io/force*.py runs in CI without the
instrument corpus. Each takes curves in physical units (nm) and encodes
them the way the instrument does."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

_DEFL_LSB = 0.000375          # V/LSB of the deflection and Z sensor channels
_DEFL_SENS = 50.0             # nm/V
_Z_SENS = 400.0               # nm/V (ZsensSens)


def write_bruker_force(path: Path, z_app: np.ndarray, d_app: np.ndarray, z_ret: np.ndarray,
                       d_ret: np.ndarray, k: float = 0.5, sensor: bool = True,
                       ramp_nm: float | None = None) -> Path:
    """Approach/retract in time order (nm); stored contact end first."""
    n = z_app.size

    def raw(values: np.ndarray, per_lsb: float) -> bytes:
        return np.round(values / per_lsb).astype("<i2").tobytes()

    defl = raw(np.concatenate([d_app[::-1], d_ret]), _DEFL_LSB * _DEFL_SENS)
    chans = [("DeflectionError", "Deflection Error", "Sens. DeflSens", defl)]
    if sensor:
        zs = raw(np.concatenate([z_app[::-1], z_ret]), _DEFL_LSB * _Z_SENS)
        chans.append(("ZSensor", "Height Sensor", "Sens. ZsensSens", zs))
    ramp_v = (ramp_nm if ramp_nm is not None else float(np.ptp(z_app))) / 20.0
    head = [
        "\\*Force file list", "\\Version: 0x09200000",
        "\\*Scanner list", "\\@Sens. Zsens: V 20.00000 nm/V",
        "\\*Ciao scan list", f"\\@Sens. DeflSens: V {_DEFL_SENS} nm/V",
        f"\\@Sens. ZsensSens: V {_Z_SENS} nm/V",
        "\\*Ciao force list", f"\\Samps/line: {n} {n}",
        f"\\@4:Ramp size Zsweep: V [Sens. Zsens] (0.0047 V/LSB) {ramp_v} V",
    ]
    offset, blocks = 8192, b""
    for ident, label, sens, data in chans:
        head += [
            "\\*Ciao force image list", f"\\Data offset: {offset + len(blocks)}",
            f"\\Data length: {len(data)}", "\\Bytes/pixel: 2", f"\\Samps/line: {n} {n}",
            f"\\Spring Constant: {k}", f'\\@4:Image Data: S [{ident}] "{label}"',
            f"\\@4:Z scale: V [{sens}] ({_DEFL_LSB} V/LSB) 2.5 V",
        ]
        blocks += data
    text = ("\r\n".join([*head, "\\*File list end"]) + "\r\n").encode("latin-1") + b"\x1a"
    path.write_bytes(text.ljust(offset, b"\0") + blocks)
    return path


def write_ibw_force(path: Path, segments: list[tuple[int, np.ndarray, np.ndarray]],
                    k: float = 0.1, invols_m: float = 5e-8, zsensor: bool = True) -> Path:
    """segments: (direction 1/−1/0, Z nm, deflection nm) in time order."""
    z = np.concatenate([s[1] for s in segments]) * 1e-9
    d = np.concatenate([s[2] for s in segments]) * 1e-9
    names = ["Raw", "Defl", "ZSnsr"] if zsensor else ["Raw", "Defl"]
    cols = [z, d, z] if zsensor else [z, d]
    data = np.stack(cols, axis=1).astype("<f4")
    n, m = data.shape
    bounds = np.cumsum([0] + [s[1].size for s in segments])
    bounds[1:] -= 1                               # Asylum: the last index of each segment
    note = (f"SpringConstant: {k}\rInvOLS: {invols_m}\r"
            f"Indexes: {','.join(str(b) for b in bounds)},\r"
            f"Direction: Nan,{','.join(str(s[0]) for s in segments)},\r").encode("latin-1")
    labels = b"".join(x.encode().ljust(32, b"\0") for x in ["", *names])
    raw = data.ravel(order="F").tobytes()
    bin5 = struct.pack("<hhiiii4i4iiii", 5, 0, 320 + len(raw), 0, len(note), 0,
                       0, 0, 0, 0, 0, len(labels), 0, 0, 0, 0, 0)
    wave = struct.pack(
        "<4xIIihh6xh32s4x4x4i4d4d4s16shhdd4x16x16x4x64xhhhbb4xihh4x4x",
        0, 0, data.size, 2, 0, 1, b"force", n, m, 0, 0,
        5e-4, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, b"m",
        b"s\0\0\0" + b"\0" * 12, 0, 0, 0.0, 0.0, 0, 0, 0, 0, 0, 0, 0, 0)
    path.write_bytes(bin5 + wave + raw + note + labels)
    return path


def _nid_block(values: np.ndarray, lo: float, span: float) -> np.ndarray:
    """Value → signed 32-bit raw: v = lo + span · (r + 2³¹) / 2³²."""
    q = 2.0 ** 32
    return np.round((values - lo) / span * q - q / 2).clip(-q / 2, q / 2 - 1)


def write_nid_force(path: Path, curves: list[tuple[np.ndarray, np.ndarray]], k: float,
                    grid: tuple[int, int] | None = None, image: np.ndarray | None = None,
                    extent_m: float = 1e-6) -> Path:
    """curves: (Z nm, deflection nm) approaches, recorded order (serpentine
    on a grid); the retract is the approach reversed. Deflection is stored
    as force (N), Z as Z-Axis Sensor (m)."""
    n = len(curves)
    pts = max(c[0].size for c in curves)
    groups: list[tuple[str, list[tuple[str, str, np.ndarray, list[int]]]]] = []
    for gname, rev in (("Spec forward", False), ("Spec backward", True)):
        zz = np.zeros((n, pts))
        ff = np.zeros((n, pts))
        lens = []
        for i, (z, d) in enumerate(curves):
            z, d = (z[::-1], d[::-1]) if rev else (z, d)
            zz[i, : z.size], ff[i, : z.size] = z * 1e-9, d * 1e-9 * k
            lens.append(z.size)
        groups.append((gname, [("Deflection", "N", ff, lens), ("Z-Axis Sensor", "m", zz, lens)]))
    if image is not None:
        groups.append(("Scan forward", [("Z-Axis", "m", np.flipud(image), [])]))
    head = ["[DataSet]", "Version=2", f"GroupCount={len(groups)}"]
    body, blocks = [], b""
    for g, (gname, chans) in enumerate(groups):
        head += [f"Gr{g}-Name={gname}", f"Gr{g}-Count={len(chans)}"]
        for c, (name, unit, arr, lens) in enumerate(chans):
            head.append(f"Gr{g}-Ch{c}=DataSet-{g}:{c}")
            lo, span = float(arr.min()), float(np.ptp(arr)) or 1.0
            body += ["", f"[DataSet-{g}:{c}]", f"Points={arr.shape[1]}",
                     f"Lines={arr.shape[0]}", "Dim0Unit=m", f"Dim0Range={extent_m}",
                     "Dim1Unit=m", f"Dim1Range={extent_m}", f"Dim2Name={name}",
                     f"Dim2Unit={unit}", f"Dim2Min={lo}", f"Dim2Range={span}", "SaveBits=32"]
            body += [f"LineDim{i}Points={v}" for i, v in enumerate(lens)]
            blocks += _nid_block(arr, lo, span).astype("<i4").tobytes()
    body += ["", "[DataSet\\Calibration\\Cantilever]", f"Prop0=D[{k}]*[N/m]"]
    if grid is not None:
        ny, nx = grid
        body += ["", "[DataSet\\SpecInfos\\SpecMapTable]",
                 f"Map0=0;{(nx - 1) * 1e-7};0;{(ny - 1) * 1e-7};{nx};{ny};0;1"]
    path.write_bytes("\r\n".join(head + body).encode("latin-1") + b"\r\n#!" + blocks)
    return path
