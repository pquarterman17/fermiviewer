"""Lispix ``.rpl`` + ``.raw`` reader (Data-Formats #7 remainder).

``.rpl`` ("Raw Parameter List") is a plain-text key/value header describing a
sibling ``.raw`` binary block — originally from David Mitchell's Lispix, and
later adopted by HyperSpy/rosettasciio as a generic array/EDS/EELS
interchange format. Reimplemented here from the public key vocabulary
(``width``/``height``/``depth``/``offset``/``data-length``/``data-type``/
``byte-order``/``record-by``, plus optional per-axis calibration keys);
cross-checked field-by-field against the rosettasciio ``ripple`` reader as a
dev-time test oracle only (rosettasciio is GPL — never copied from; see
``tests/test_oracle_rsciio.py``).

Geometry decides the ``DataKind``:

    width<=1 and height<=1   -> SPECTRUM        (``depth`` channels)
    depth<=1                 -> IMAGE           (``height`` x ``width``)
    otherwise                -> SPECTRUM_IMAGE, energy/depth axis LAST
        record-by == "image"           -> file stores (depth, height,
                                           width) planes back-to-back
                                           ("plane-ordered"); reordered to
                                           (height, width, depth) to match
                                           fermiviewer's cube convention
        record-by == "vector" (default) -> file already stores (height,
                                           width, depth) — a full spectrum
                                           contiguous per pixel
                                           ("spectrum-ordered"); no reorder
                                           needed

Optional per-axis calibration keys (``width-origin``/``-scale``/``-units``,
same for ``height``/``depth``) use "value = origin + index*scale" — the same
convention as the HDF5 offset/scale axes elsewhere in ``io/``, so they reuse
``hdf5_common.axiscal_from_offset_scale`` unmodified (verified against the
rosettasciio oracle's own axis ``offset``, which is numerically identical to
the raw ``-origin`` header value).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.hdf5_common import axiscal_from_offset_scale

__all__ = ["RplFormatError", "load_rpl"]

_DTYPE_KIND = {"signed": "i", "unsigned": "u", "float": "f"}
_BYTE_ORDER = {
    "big-endian": ">",
    "big": ">",
    "little-endian": "<",
    "little": "<",
    "dont-care": "=",
    "dont care": "=",
    "": "=",
}


class RplFormatError(ValueError):
    """Unreadable/unsupported ``.rpl`` header, or a missing sibling ``.raw``."""


def _parse_header(text: str) -> dict[str, str]:
    """Tab/space-separated ``key value`` lines; ``;``/``#`` are comments."""
    header: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        parts = line.split(None, 1)
        key = parts[0].strip().lower()
        val = parts[1].strip() if len(parts) > 1 else ""
        if key == "key" and val.lower() == "value":
            continue  # the literal "key value" column-header row
        header[key] = val
    return header


def _int_field(header: dict[str, str], key: str, default: int) -> int:
    v = header.get(key)
    if not v:
        return default
    try:
        return int(float(v))
    except ValueError:
        return default


def _float_field(header: dict[str, str], key: str) -> float:
    v = header.get(key)
    if not v:
        return float("nan")
    try:
        return float(v)
    except ValueError:
        return float("nan")


def _axis_cal(header: dict[str, str], prefix: str) -> AxisCal:
    scale = _float_field(header, f"{prefix}-scale")
    if not np.isfinite(scale):
        return AxisCal()
    origin = _float_field(header, f"{prefix}-origin")
    units = header.get(f"{prefix}-units", "").strip()
    return axiscal_from_offset_scale(origin if np.isfinite(origin) else 0.0, scale, units)


def _dtype_from_header(header: dict[str, str]) -> np.dtype:
    kind = _DTYPE_KIND.get(header.get("data-type", "signed").strip().lower())
    if kind is None:
        raise RplFormatError(f"unsupported data-type {header.get('data-type')!r}")
    bo = _BYTE_ORDER.get(header.get("byte-order", "dont-care").strip().lower())
    if bo is None:
        raise RplFormatError(f"unsupported byte-order {header.get('byte-order')!r}")
    length = _int_field(header, "data-length", 1)
    try:
        return np.dtype(f"{bo}{kind}{length}")
    except TypeError as e:
        raise RplFormatError(
            f"unsupported data-type/data-length combination: "
            f"{header.get('data-type')!r}/{length}"
        ) from e


def _find_sibling_raw(rpl_path: Path) -> Path | None:
    candidate = rpl_path.with_suffix(".raw")
    if candidate.is_file():
        return candidate
    # case-insensitive fallback (rare, but Lispix/.RAW pairs exist in the wild)
    for p in rpl_path.parent.glob(f"{rpl_path.stem}.*"):
        if p.suffix.lower() == ".raw":
            return p
    return None


def load_rpl(path: str | Path) -> DataStruct:
    """Parse a Lispix ``.rpl`` header + its sibling ``.raw`` into a ``DataStruct``."""
    path = Path(path)
    try:
        text = path.read_text(encoding="latin-1")
    except OSError as e:  # pragma: no cover - unreadable file
        raise RplFormatError(f"cannot read {path}: {e}") from None

    header = _parse_header(text)
    if not header:
        raise RplFormatError(f"{path.name}: no key/value header lines found")

    raw_path = _find_sibling_raw(path)
    if raw_path is None:
        raise RplFormatError(f"{path.name}: no sibling .raw file found")

    dt = _dtype_from_header(header)
    width = _int_field(header, "width", 1)
    height = _int_field(header, "height", 1)
    depth = _int_field(header, "depth", 1)
    byte_offset = _int_field(header, "offset", 0)
    record_by = header.get("record-by", "dont-care").strip().lower()

    if width <= 0 or height <= 0 or depth <= 0:
        raise RplFormatError(
            f"{path.name}: invalid geometry width={width} height={height} depth={depth}"
        )

    n = width * height * depth
    raw_bytes = raw_path.read_bytes()
    need = byte_offset + n * dt.itemsize
    if len(raw_bytes) < need:
        raise RplFormatError(
            f"{raw_path.name}: expected at least {need} bytes for "
            f"{width}x{height}x{depth} @ {dt.itemsize} bytes/element "
            f"(offset {byte_offset}), found {len(raw_bytes)}"
        )
    flat = np.frombuffer(raw_bytes, dtype=dt, count=n, offset=byte_offset).astype(
        np.float64
    )

    width_cal = _axis_cal(header, "width")
    height_cal = _axis_cal(header, "height")
    depth_cal = _axis_cal(header, "depth")

    metadata: dict[str, Any] = {
        "source": str(path),
        "parser": "rpl",
        "raw_source": str(raw_path),
        "record_by": record_by,
        "signal": header.get("signal", ""),
        "rpl_header": header,
    }

    if width <= 1 and height <= 1:
        return DataStruct(
            data=flat.reshape(depth),
            kind=DataKind.SPECTRUM,
            axes=(depth_cal,),
            metadata=metadata,
        )

    if depth <= 1:
        return DataStruct(
            data=flat.reshape(height, width),
            kind=DataKind.IMAGE,
            axes=(height_cal, width_cal),
            metadata=metadata,
        )

    if record_by == "image":
        # on disk: depth full (height x width) planes, back to back
        cube = np.ascontiguousarray(np.moveaxis(flat.reshape(depth, height, width), 0, -1))
    else:
        # "vector" (or an unspecified/"dont-care" 3D file, treated the same
        # way by default): on disk, a full depth-length spectrum per pixel
        cube = flat.reshape(height, width, depth)

    return DataStruct(
        data=cube,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(height_cal, width_cal, depth_cal),
        metadata=metadata,
    )
