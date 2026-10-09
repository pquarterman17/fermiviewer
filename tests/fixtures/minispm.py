"""Tiny synthetic SPM files (Gwyddion, Asylum IBW, JPK, WSxM) written to
each format's layout, so the readers are exercised in CI without the
instrument corpus."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

# ── Gwyddion ─────────────────────────────────────────────────────────


def _gwy_obj(name: str, comps: list[bytes]) -> bytes:
    body = b"".join(comps)
    return name.encode() + b"\0" + struct.pack("<I", len(body)) + body


def _gwy_comp(key: str, t: str, payload: bytes) -> bytes:
    return key.encode() + b"\0" + t.encode() + payload


def _gwy_unit(u: str) -> bytes:
    return _gwy_obj("GwySIUnit", [_gwy_comp("unitstr", "s", u.encode() + b"\0")])


def _gwy_field(data: np.ndarray, xreal: float, yreal: float, zunit: str) -> bytes:
    yres, xres = data.shape
    return _gwy_obj("GwyDataField", [
        _gwy_comp("xres", "i", struct.pack("<i", xres)),
        _gwy_comp("yres", "i", struct.pack("<i", yres)),
        _gwy_comp("xreal", "d", struct.pack("<d", xreal)),
        _gwy_comp("yreal", "d", struct.pack("<d", yreal)),
        _gwy_comp("si_unit_xy", "o", _gwy_unit("m")),
        _gwy_comp("si_unit_z", "o", _gwy_unit(zunit)),
        _gwy_comp("data", "D", struct.pack("<I", data.size) + data.astype("<f8").tobytes()),
    ])


def write_gwy(path: Path, channels: list[tuple[str, np.ndarray, str]],
              size_m: float = 1e-6) -> Path:
    """channels: (title, data in base SI units, z unit)."""
    comps = []
    for i, (title, data, zunit) in enumerate(channels):
        comps.append(_gwy_comp(f"/{i}/data", "o", _gwy_field(data, size_m, size_m, zunit)))
        comps.append(_gwy_comp(f"/{i}/data/title", "s", title.encode() + b"\0"))
    comps.append(_gwy_comp("/0/show", "b", b"\x01"))          # non-data component
    path.write_bytes(b"GWYP" + _gwy_obj("GwyContainer", comps))
    return path


# ── Asylum IBW (Igor binary wave v5) ─────────────────────────────────


def write_ibw(path: Path, layers: dict[str, np.ndarray], dx_m: float,
              note: str = "ScanRate: 1\rImagingMode: 1\r") -> Path:
    """layers: label → (lines × points) image, top row first."""
    names = list(layers)
    ny, nx = layers[names[0]].shape
    # Asylum: points fastest, lines bottom-up, then channels (Fortran order)
    cube = np.stack([np.flipud(layers[n]).T for n in names], axis=2).astype("<f4")
    data = cube.ravel(order="F").tobytes()
    note_b = note.encode("latin-1")
    labels = b"".join(n.encode().ljust(32, b"\0") for n in ["", *names])
    bin5 = struct.pack("<hhiiii4i4iiii", 5, 0, 320 + len(data), 0, len(note_b), 0,
                       0, 0, 0, 0, 0, 0, len(labels), 0, 0, 0, 0)
    wave = struct.pack(
        "<4xIIihh6xh32s4x4x4i4d4d4s16shhdd4x16x16x4x64xhhhbb4xihh4x4x",
        0, 0, cube.size, 2, 0, 1, b"scan", nx, ny, len(names), 0,
        dx_m, dx_m, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, b"",
        b"m\0\0\0m\0\0\0\0\0\0\0\0\0\0\0", 0, 0, 0.0, 0.0, 0, 0, 0, 0, 0, 0, 0, 0)
    path.write_bytes(bin5 + wave + data + note_b + labels)
    return path


# ── JPK (TIFF with private tags) ─────────────────────────────────────


def _jpk_tags(name: str, retrace: bool, mult: float, off: float, unit: str,
              size_m: float, n: int) -> list[tuple]:
    slot = 32912
    return [
        (32834, "d", 1, size_m, True), (32835, "d", 1, size_m, True),
        (32838, "i", 1, n, True), (32839, "i", 1, n, True),
        (32848, "s", 0, name, True), (32849, "i", 1, int(retrace), True),
        (32850, "s", 0, name.capitalize(), True),
        (32896, "i", 1, 2, True), (32897, "s", 0, "calibrated", True),
        (slot, "s", 0, "raw", True), (slot + 19, "s", 0, "NullScaling", True),
        (slot + 48, "s", 0, "calibrated", True), (slot + 48 + 18, "s", 0, unit, True),
        (slot + 48 + 19, "s", 0, "LinearScaling", True),
        (slot + 48 + 20, "d", 1, mult, True), (slot + 48 + 21, "d", 1, off, True),
    ]


def write_jpk(path: Path, raw: dict[tuple[str, bool], np.ndarray], mult: float,
              off: float, size_m: float) -> Path:
    """raw: (channel, retrace) → int32 lines bottom-up, as JPK stores them."""
    import tifffile

    n = next(iter(raw.values())).shape[0]
    with tifffile.TiffWriter(path) as tw:
        tw.write(np.zeros((8, 8), np.uint8),
                 extratags=_jpk_tags("thumbnail", False, 1, 0, "", size_m, n))
        for (name, retrace), arr in raw.items():
            unit = "m" if name == "height" else "V"
            tw.write(arr.astype(np.int32),
                     extratags=_jpk_tags(name, retrace, mult, off, unit, size_m, n))
    return path


# ── WSxM ─────────────────────────────────────────────────────────────


def write_wsxm(path: Path, stored: np.ndarray, kind: str, zamp: str,
               amp: str = "500 nm") -> Path:
    """`stored` is written as-is (WSxM keeps pixels last-first)."""
    rows, cols = stored.shape
    body = (
        "SxM Image file\r\nImage header size: {size:05d}\r\n\r\n[Control]\r\n\r\n"
        f"    X Amplitude: {amp}\r\n    Y Amplitude: {amp}\r\n\r\n[General Info]\r\n\r\n"
        "    Acquisition channel: Topography\r\n"
        f"    Image Data Type: {kind}\r\n    Number of columns: {cols}\r\n"
        f"    Number of rows: {rows}\r\n    X scanning direction: Backward\r\n"
        f"    Z Amplitude: {zamp}\r\n\r\n[Header end]\r\n"
    )
    head = ("WSxM file copyright UAM\r\n" + body)
    size = len(head.format(size=0).encode("latin-1"))     # fixed-width size field
    dt = {"short": "<i2", "double": "<f8"}[kind]
    path.write_bytes(head.format(size=size).encode("latin-1") + stored.astype(dt).tobytes())
    return path


# ── Gwyddion simple field / Gwyddion 1.x ─────────────────────────────


def write_gsf(path: Path, data: np.ndarray, size_m: float, title: str = "Height") -> Path:
    yres, xres = data.shape
    head = (f"Gwyddion Simple Field 1.0\nXRes = {xres}\nYRes = {yres}\nXReal = {size_m}\n"
            f"YReal = {size_m}\nXYUnits = m\nZUnits = m\nTitle = {title}\n").encode()
    pad = 4 - len(head) % 4
    path.write_bytes(head + b"\0" * pad + data.astype("<f4").tobytes())
    return path


def write_gwyo(path: Path, data: np.ndarray, size_m: float) -> Path:
    """Gwyddion 1.x: the container items carry a GType code (string 64,
    object 80); the data field inside serializes as in Gwyddion 2."""
    field = _gwy_field(data, size_m, size_m, "m")
    items = (struct.pack("<I", 64) + b"/0/base/palette\0Gray\0"
             + struct.pack("<I", 80) + b"/0/data\0" + field)
    path.write_bytes(b"GWYO" + b"GwyContainer\0" + struct.pack("<I", len(items)) + items)
    return path


# ── Nanosurf NID ─────────────────────────────────────────────────────


def write_nid(path: Path, channels: list[tuple[str, str, np.ndarray]], range_m: float,
              zmin: float, zrange: float) -> Path:
    """channels: (name, unit, int32 lines bottom-up) — all in group 0."""
    ny, nx = channels[0][2].shape
    head = ["[DataSet]", "Version=2", "GroupCount=1", "Gr0-Name=Scan forward",
            f"Gr0-Count={len(channels)}"]
    head += [f"Gr0-Ch{i}=DataSet-0:{i}" for i in range(len(channels))]
    for i, (name, unit, _) in enumerate(channels):
        head += ["", f"[DataSet-0:{i}]", f"Points={nx}", f"Lines={ny}",
                 "Dim0Unit=m", f"Dim0Range={range_m}", "Dim1Unit=m", f"Dim1Range={range_m}",
                 f"Dim2Name={name}", f"Dim2Unit={unit}", f"Dim2Min={zmin}",
                 f"Dim2Range={zrange}", "SaveBits=32", "SaveSign=Signed"]
    data = b"".join(c[2].astype("<i4").tobytes() for c in channels)
    path.write_bytes("\r\n".join(head).encode() + b"\r\n#!" + data)
    return path


# ── NT-MDT ───────────────────────────────────────────────────────────


def _mdt_frame(ftype: int, var: bytes, body: bytes) -> bytes:
    size = 22 + len(var) + len(body)
    return struct.pack("<IHH6HH", size, ftype, 0, 2024, 1, 1, 0, 0, 0, len(var)) + var + body


def _mda_cal(name: str, unit: str, bias: float, scale: float, n: int, dtype: int) -> bytes:
    nb, ub = name.encode(), unit.encode()
    body = struct.pack("<IIIQd8xddQQiI", len(nb), 0, len(ub), 0, 0.0, bias, scale, 0, n - 1,
                       dtype, 0)
    return struct.pack("<II", 8 + len(body) + len(nb) + len(ub), len(body)) + body + nb + ub


def write_mdt(path: Path, scanned: np.ndarray, mda: np.ndarray, step_nm: float) -> Path:
    """One classic scanned frame (int16, unit codes) and one MDA frame
    (int32, unit strings); both stored bottom line first."""
    ny, nx = scanned.shape
    axes = struct.pack("<ffhffhffh", 0, step_nm, -1, 0, step_nm, -1, 5.0, 0.5, -1)  # nm
    title = b"Topography"
    frame0 = _mdt_frame(0, axes, struct.pack("<4H", 0, nx, ny, 0)
                        + scanned.astype("<i2").tobytes() + struct.pack("<I", len(title)) + title)
    my, mx = mda.shape
    name = b"Phase"
    head = struct.pack("<II36x8I", 76, 0, len(name), 0, 0, 0, 0, 0, 0, 0)
    arr = struct.pack("<QIII", mx * my, 4, 2, 1)
    cals = (_mda_cal("X", "um", 0.0, step_nm / 1000, mx, -4)
            + _mda_cal("Y", "um", 0.0, step_nm / 1000, my, -4)
            + _mda_cal("Phase", "deg", 1.0, 0.25, mx * my, -4))
    rec = head + name + struct.pack("<II", 0, len(arr)) + arr + cals + mda.astype("<i4").tobytes()
    frame1 = _mdt_frame(106, b"", rec)
    frames = frame0 + frame1
    hdr = b"\x01\xb0\x93\xff" + struct.pack("<II", len(frames), 0) + struct.pack("<H", 1)
    path.write_bytes(hdr + bytes(18) + b"\0" + frames)
    return path


# ── Nanonis SXM ──────────────────────────────────────────────────────


def write_sxm(path: Path, fwd: np.ndarray, bwd: np.ndarray, range_m: float,
              direction: str = "up") -> Path:
    """One channel 'Z' (m) recorded in both directions, as stored."""
    ny, nx = fwd.shape
    head = (f":NANONIS_VERSION:\n2\n:SCAN_PIXELS:\n       {nx}       {ny}\n"
            f":SCAN_RANGE:\n           {range_m}           {range_m}\n"
            f":SCAN_DIR:\n{direction}\n:BIAS:\n0.1\n"
            ":DATA_INFO:\n\tChannel\tName\tUnit\tDirection\tCalibration\tOffset\n"
            "\t14\tZ\tm\tboth\t-1.0E-7\t0.0E+0\n\n:SCANIT_END:\n\n\n")
    path.write_bytes(head.encode() + b"\x1a\x04" + fwd.astype(">f4").tobytes()
                     + bwd.astype(">f4").tobytes())
    return path
