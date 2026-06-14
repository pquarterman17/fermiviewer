"""Gatan DigitalMicrograph DM3/DM4 parser.

Port of fermi-viewer's importDM3.m/importDM4.m (validated against real GMS
files 2026-06-06). Supports 2D images, 1D spectra, and 3D spectrum-image
cubes. Format contracts this parser owns:

- structural integers are big-endian (4-byte DM3 / 8-byte DM4); tag data
  payloads follow the header byte-order flag
- DM4 leaf tags carry a totalSize used to realign after every leaf, no
  matter how its payload parses (struct leaves otherwise desync the tree)
- in 3D SI cubes the energy axis is NOT a fixed dimension: real GMS files
  put energy LAST (slowest); detected from per-dimension calibration Units
  (eV/keV/meV), defaulting to last when no unit matches
- calibration convention: value = (index − origin) × scale
- ImageList.0 is usually a thumbnail (DataType 23); pick the first
  non-thumbnail, fall back to the largest pixel array
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

__all__ = ["DMFormatError", "load_dm"]

LARGE_ARRAY_THRESHOLD = 1000
MAX_DEPTH = 50
MAX_TAGS_PER_GROUP = 10_000
THUMBNAIL_DTYPE = 23
BOOLEAN_DTYPE = 8
ENERGY_UNITS = {"ev", "kev", "mev"}

# info-array element type code -> (numpy dtype char, byte size)
TYPE_CODES: dict[int, tuple[str, int]] = {
    2: ("i2", 2), 3: ("i4", 4), 4: ("u2", 2), 5: ("u4", 4), 6: ("f4", 4),
    7: ("f8", 8), 8: ("u1", 1), 9: ("i1", 1), 10: ("u1", 1), 11: ("i8", 8),
    12: ("u8", 8),
}
# DM image DataType code -> (numpy dtype char, bit depth) — different table!
IMAGE_DTYPES: dict[int, tuple[str, int]] = {
    1: ("i2", 16), 2: ("f4", 32), 6: ("u1", 8), 7: ("i4", 32),
    9: ("i1", 8), 10: ("u2", 16), 11: ("u4", 32), 12: ("f8", 64),
}


class DMFormatError(ValueError):
    """Raised for unreadable / non-DM / structurally broken files."""


@dataclass(frozen=True)
class _OffsetRec:
    """Large array recorded in pass 1, read lazily in pass 2."""

    offset: int
    n: int
    elem_type: int


class _Cursor:
    __slots__ = ("buf", "pos")

    def __init__(self, buf: bytes) -> None:
        self.buf = buf
        self.pos = 0

    def be(self, n: int) -> int:
        v = int.from_bytes(self.buf[self.pos : self.pos + n], "big")
        self.pos += n
        return v

    def raw(self, n: int) -> bytes:
        b = self.buf[self.pos : self.pos + n]
        self.pos += n
        return b

    @property
    def eof(self) -> bool:
        return self.pos >= len(self.buf)


# ════════════════════════════════════════════════════════════════════
#  Pass 1 — tag tree
# ════════════════════════════════════════════════════════════════════

def _parse_group(cur: _Cursor, path: str, depth: int, lsize: int,
                 le: bool, tags: dict[str, Any]) -> None:
    if depth > MAX_DEPTH:
        return
    if lsize == 8 and depth > 0:
        cur.be(8)  # group dir size — skip
    cur.raw(2)     # sorted, open flags
    n = cur.be(lsize)
    if n > MAX_TAGS_PER_GROUP:  # truncated/corrupt guard
        return
    for k in range(n):
        if cur.eof:
            return
        _parse_entry(cur, path, k, depth, lsize, le, tags)


def _parse_entry(cur: _Cursor, parent: str, idx: int, depth: int,
                 lsize: int, le: bool, tags: dict[str, Any]) -> None:
    if cur.eof:
        return
    type_code = cur.be(1)
    label_len = cur.be(2)
    label = cur.raw(label_len).decode("latin-1") if label_len else str(idx)
    path = f"{parent}.{label}" if parent else label

    if type_code == 20:
        _parse_group(cur, path, depth + 1, lsize, le, tags)
    elif type_code == 21:
        _parse_data(cur, path, lsize, le, tags)
    # type 0 = end-of-directory; anything else: cannot safely skip — the
    # DM4 totalSize realign in _parse_data is what keeps us aligned.


def _parse_data(cur: _Cursor, path: str, lsize: int, le: bool,
                tags: dict[str, Any]) -> None:
    end_pos = -1
    if lsize == 8:
        total = cur.be(8)
        end_pos = cur.pos + total
    try:
        if cur.raw(4) != b"%%%%":
            return
        info_len = cur.be(lsize)
        if info_len == 0:
            return
        info = [cur.be(lsize) for _ in range(info_len)]
        meta = info[0]
        bo = "<" if le else ">"

        if meta == 15:  # struct
            _parse_struct(cur, path, info, bo, tags)
        elif meta == 18:  # string (UTF-16 code units)
            count = info[1] if len(info) > 1 else 0
            if count:
                chars = np.frombuffer(cur.raw(2 * count), dtype=f"{bo}u2")
                tags[path] = "".join(map(chr, chars))
        elif meta == 20:  # array
            _parse_array(cur, path, info, bo, tags)
        else:  # simple scalar
            v = _read_scalar(cur, meta, bo)
            if v is not None:
                tags[path] = v
    finally:
        if end_pos >= 0:
            cur.pos = end_pos


def _parse_struct(cur: _Cursor, path: str, info: list[int], bo: str,
                  tags: dict[str, Any]) -> None:
    """Struct leaf: field type codes at info[4], info[6], ..."""
    n_fields = info[2] if len(info) > 2 else 0
    vals = []
    for k in range(n_fields):
        ti = 4 + 2 * k
        if ti >= len(info):
            return
        vals.append(_read_scalar(cur, info[ti], bo))
    if vals:
        tags[path] = vals


def _parse_array(cur: _Cursor, path: str, info: list[int], bo: str,
                 tags: dict[str, Any]) -> None:
    if len(info) < 2:
        return
    elem_type = info[1]
    if elem_type == 15 and len(info) > 3:
        # array of structs — array length is the LAST info element;
        # compute per-struct bytes from the type codes and skip.
        n_structs = info[-1]
        n_fields = info[3] if len(info) > 3 else 0
        per = 0
        for k in range(n_fields):
            ti = 5 + 2 * k
            if ti >= len(info):
                break
            per += TYPE_CODES.get(info[ti], ("", 0))[1]
        cur.pos += per * n_structs
        return
    n = info[2] if len(info) >= 3 else 0
    dt = TYPE_CODES.get(elem_type)
    if dt is None or n == 0:
        return
    nbytes = dt[1] * n
    if n > LARGE_ARRAY_THRESHOLD:
        tags[path] = _OffsetRec(cur.pos, n, elem_type)
        cur.pos += nbytes
    else:
        vals = np.frombuffer(cur.raw(nbytes), dtype=f"{bo}{dt[0]}")
        tags[path] = float(vals[0]) if n == 1 else vals


def _read_scalar(cur: _Cursor, code: int, bo: str) -> float | None:
    dt = TYPE_CODES.get(code)
    if dt is None:
        return None
    return float(np.frombuffer(cur.raw(dt[1]), dtype=f"{bo}{dt[0]}")[0])


# ════════════════════════════════════════════════════════════════════
#  Tag accessors
# ════════════════════════════════════════════════════════════════════

def _scalar(tags: dict[str, Any], key: str, default: float) -> float:
    v = tags.get(key)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, np.ndarray) and v.size:
        return float(v.flat[0])
    return default


def _string(tags: dict[str, Any], key: str, default: str) -> str:
    v = tags.get(key)
    if isinstance(v, str):
        return v
    if isinstance(v, np.ndarray) and v.dtype.kind == "u" and v.itemsize == 2:
        return "".join(map(chr, v))
    return default


# ════════════════════════════════════════════════════════════════════
#  Image selection + assembly
# ════════════════════════════════════════════════════════════════════

def _pick_image(tags: dict[str, Any], path: Path) -> int:
    first, extras = -1, []
    for k in range(100):
        dt = tags.get(f"ImageList.{k}.ImageData.DataType")
        if not isinstance(dt, (int, float)):
            continue
        if dt not in (THUMBNAIL_DTYPE, BOOLEAN_DTYPE):
            if first < 0:
                first = k
            else:
                extras.append(k)
    if extras:
        warnings.warn(
            f"DM file {path.name} has extra non-thumbnail images at "
            f"ImageList {extras} — using ImageList.{first}",
            stacklevel=3,
        )
    if first >= 0:
        return first
    best = _largest_image(tags)
    if best < 0:
        raise DMFormatError(f"no usable image in {path} (thumbnails only?)")
    return best


def _largest_image(tags: dict[str, Any]) -> int:
    """Fallback: ImageList entry with the largest pixel count."""
    best, best_px = -1, 0.0
    for k in range(100):
        base = f"ImageList.{k}.ImageData"
        if f"{base}.Data" not in tags:
            continue
        npx = _scalar(tags, f"{base}.Dimensions.0", 0)
        if npx <= 0:
            continue
        for d in (1, 2):
            extra = _scalar(tags, f"{base}.Dimensions.{d}", 0)
            if extra > 0:
                npx *= extra
        if npx > best_px:
            best, best_px = k, npx
    return best


def _read_pixels(buf: bytes, rec: Any, n_px: int, dtype: str, le: bool) -> np.ndarray:
    bo = "<" if le else ">"
    if isinstance(rec, _OffsetRec):
        avail = (len(buf) - rec.offset) // np.dtype(dtype).itemsize
        # guard against a desynced/truncated tag putting offset past EOF
        # (negative avail → confusing np.frombuffer error); mirrors mrc/ser
        n_read = min(n_px, rec.n, max(avail, 0))
        px = np.frombuffer(buf, dtype=f"{bo}{dtype}", count=n_read, offset=rec.offset)
    elif isinstance(rec, np.ndarray):
        px = rec.astype(dtype)
    else:
        raise DMFormatError("Image Data tag has unexpected format")
    if px.size < n_px:
        warnings.warn(
            f"expected {n_px} pixels, read {px.size} — zero-padding", stacklevel=3
        )
        px = np.concatenate([px, np.zeros(n_px - px.size, dtype=px.dtype)])
    return px[:n_px]


def _energy_dim(tags: dict[str, Any], cal_base: str) -> int:
    for d in range(3):
        u = _string(tags, f"{cal_base}.{d}.Units", "").strip().lower()
        if u in ENERGY_UNITS:
            return d
    return 2  # GMS layout default: energy last


def _axis_cal(tags: dict[str, Any], cal_base: str, d: int, default_units: str = "") -> AxisCal:
    return AxisCal(
        scale=_scalar(tags, f"{cal_base}.{d}.Scale", float("nan")),
        origin=_scalar(tags, f"{cal_base}.{d}.Origin", 0.0),
        units=_string(tags, f"{cal_base}.{d}.Units", default_units),
    )


def load_dm(path: str | Path) -> DataStruct:
    """Parse a .dm3/.dm4 file into a DataStruct."""
    path = Path(path)
    buf = path.read_bytes()
    if len(buf) < 16:
        raise DMFormatError(f"empty or truncated DM file: {path}")

    cur = _Cursor(buf)
    version = cur.be(4)
    if version not in (3, 4):
        raise DMFormatError(f"not a DM3/DM4 file (version {version}): {path}")
    lsize = 8 if version == 4 else 4
    cur.be(lsize)              # root dir size — skip
    le = cur.be(4) == 1        # data byte order flag

    tags: dict[str, Any] = {}
    _parse_group(cur, "", 0, lsize, le, tags)

    idx = _pick_image(tags, path)
    base = f"ImageList.{idx}.ImageData"
    cal_base = f"{base}.Calibrations.Dimension"

    dims = []
    for d in range(3):
        v = _scalar(tags, f"{base}.Dimensions.{d}", float("nan"))
        if np.isnan(v):
            break
        dims.append(int(v))
    if not dims:
        raise DMFormatError(f"could not read image dimensions: {path}")

    dm_dtype = int(_scalar(tags, f"{base}.DataType", 0))
    if dm_dtype not in IMAGE_DTYPES:
        raise DMFormatError(f"unsupported DM DataType {dm_dtype}: {path}")
    np_dtype, bit_depth = IMAGE_DTYPES[dm_dtype]

    n_px = int(np.prod(dims))
    px = _read_pixels(buf, tags.get(f"{base}.Data"), n_px, np_dtype, le)

    metadata: dict[str, Any] = {
        "source": str(path),
        "parser": "dm",
        "dm_version": version,
        "dm_data_type": dm_dtype,
        "bit_depth": bit_depth,
        "intensity_origin": _scalar(tags, f"{base}.Calibrations.Brightness.Origin", 0.0),
        "intensity_scale": _scalar(tags, f"{base}.Calibrations.Brightness.Scale", 1.0),
        "intensity_units": _string(tags, f"{base}.Calibrations.Brightness.Units", ""),
    }
    disp = f"ImageList.{idx}.ImageDisplayInfo"
    metadata["display_low"] = _scalar(tags, f"{disp}.LowLimit", float("nan"))
    metadata["display_high"] = _scalar(tags, f"{disp}.HighLimit", float("nan"))
    metadata["display_gamma"] = _scalar(tags, f"{disp}.Gamma", 1.0)
    metadata["display_inverted"] = bool(_scalar(tags, f"{disp}.IsInverted", 0))
    # acquisition metadata harvest (scalar/string leaves under ImageTags)
    prefix = f"ImageList.{idx}.ImageTags."
    metadata["image_tags"] = {
        k[len(prefix):]: v
        for k, v in tags.items()
        if k.startswith(prefix) and isinstance(v, (int, float, str))
    }

    if len(dims) == 1:                       # 1D spectrum
        return DataStruct(
            data=px,
            kind=DataKind.SPECTRUM,
            axes=(_axis_cal(tags, cal_base, 0, "eV"),),
            metadata=metadata,
        )

    if len(dims) == 2:                       # 2D image (row-major: [H, W])
        w, h = dims
        return DataStruct(
            data=px.reshape(h, w),
            kind=DataKind.IMAGE,
            axes=(_axis_cal(tags, cal_base, 1), _axis_cal(tags, cal_base, 0)),
            metadata=metadata,
        )

    # 3D spectrum image: file order d0 fastest → C-order reshape (d2, d1, d0)
    e_dim = _energy_dim(tags, cal_base)
    x_dim, y_dim = sorted(set(range(3)) - {e_dim})  # faster spatial dim = x
    arr = px.reshape(dims[2], dims[1], dims[0])     # axes order [d2, d1, d0]
    axis_of = [2, 1, 0]                              # dim id at each array axis
    cube = arr.transpose(axis_of.index(y_dim), axis_of.index(x_dim), axis_of.index(e_dim))
    return DataStruct(
        data=np.ascontiguousarray(cube),
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            _axis_cal(tags, cal_base, y_dim),
            _axis_cal(tags, cal_base, x_dim),
            _axis_cal(tags, cal_base, e_dim, "eV"),
        ),
        metadata=metadata,
    )
