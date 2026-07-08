"""Minimal synthetic DM4 writer — port of fermi-viewer's writeMiniDM4.m.

Generates valid DM4 tag trees for format-contract tests without large
binary fixtures. The (real-data-verified) parser is the oracle for this
writer, as it was for the MATLAB original.

Layout: ImageList.0.ImageData.{DataType, Dimensions.K, Data,
Calibrations.Dimension.K.{Scale, Origin, Units}}. Structural fields
big-endian, payloads little-endian.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

__all__ = ["write_mini_dm4"]


def _be16(v: int) -> bytes:
    return struct.pack(">H", v)


def _be32(v: int) -> bytes:
    return struct.pack(">I", v)


def _be64(v: int) -> bytes:
    return struct.pack(">Q", v)


def _label(s: str) -> bytes:
    b = s.encode("ascii")
    return _be16(len(b)) + b


def _group(label: str, children: bytes, n: int) -> bytes:
    content = _be64(len(children) + 10) + b"\x01\x01" + _be64(n) + children
    return b"\x14" + _label(label) + content


def _data_tag(label: str, info: list[int], payload: bytes) -> bytes:
    body = b"%%%%" + _be64(len(info)) + b"".join(_be64(i) for i in info) + payload
    return b"\x15" + _label(label) + _be64(len(body)) + body


def _scalar(label: str, code: int, value: float, bo: str = "<") -> bytes:
    if code == 5:
        payload = struct.pack(f"{bo}I", int(value))
    elif code == 7:
        payload = struct.pack(f"{bo}d", float(value))
    else:
        raise ValueError(f"unsupported scalar type code {code}")
    return _data_tag(label, [code], payload)


def _string(label: str, s: str, bo: str = "<") -> bytes:
    payload = np.array([ord(c) for c in s], dtype=f"{bo}u2").tobytes()
    return _data_tag(label, [18, len(s)], payload)


def _array(label: str, elem_type: int, payload: bytes, n: int) -> bytes:
    return _data_tag(label, [20, elem_type, n], payload)


def write_mini_dm4(
    path: str | Path,
    dims: list[int],
    data: np.ndarray,
    data_type: int = 10,
    cal: list[dict] | None = None,
    little_endian: bool = True,
) -> Path:
    """Write a minimal DM4. `data` is in FILE order (dims[0] fastest).

    data_type: 10 (uint16) or 2 (float32). cal: per-dim dicts with
    scale/origin/units. `little_endian` sets the header's data byte-order
    flag and matches it in every tag payload (structural fields — type
    codes, label lengths, group sizes — are always big-endian regardless).
    """
    bo = "<" if little_endian else ">"
    flat = np.asarray(data).reshape(-1, order="F") if np.asarray(data).ndim > 1 \
        else np.asarray(data).reshape(-1)
    assert flat.size == int(np.prod(dims)), "data size != prod(dims)"

    if data_type == 10:
        payload, elem_type = flat.astype(f"{bo}u2").tobytes(), 4
    elif data_type == 2:
        payload, elem_type = flat.astype(f"{bo}f4").tobytes(), 6
    else:
        raise ValueError(f"unsupported data_type {data_type}")

    dim_tags = b"".join(_scalar(str(k), 5, d, bo) for k, d in enumerate(dims))

    cal = cal or []
    cal_dims = b""
    for k, c in enumerate(cal):
        inner = (_scalar("Scale", 7, c["scale"], bo)
                 + _scalar("Origin", 7, c["origin"], bo)
                 + _string("Units", c["units"], bo))
        cal_dims += _group(str(k), inner, 3)

    image_data_children = (
        _scalar("DataType", 5, data_type, bo)
        + _group("Dimensions", dim_tags, len(dims))
        + _group("Calibrations", _group("Dimension", cal_dims, len(cal)), 1)
        + _array("Data", elem_type, payload, flat.size)
    )
    image_list = _group("ImageList", _group("0", _group("ImageData", image_data_children, 4), 1), 1)

    byte_order_flag = _be32(1) if little_endian else _be32(0)
    root = (
        _be32(4) + _be64(len(image_list) + 10) + byte_order_flag
        + b"\x01\x01" + _be64(1) + image_list
    )

    out = Path(path)
    out.write_bytes(root)
    return out
