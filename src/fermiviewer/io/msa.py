"""EMSA/MAS ``.msa`` single-spectrum reader — Data-Formats #7.

The lingua-franca ASCII spectrum interchange format (EDS/EELS/WDS). A header
of ``#KEY : value`` lines precedes a ``#SPECTRUM`` data block of either
Y-only or X,Y rows, terminated by ``#ENDOFDATA``. Calibration comes from
``#XPERCHAN`` (eV/channel) + ``#OFFSET`` (x at channel 0); for ``DATATYPE XY``
with no ``#XPERCHAN`` the spacing is derived from the X column.

Returns a 1D ``SPECTRUM`` ``DataStruct``. Pure ``io/`` layer (stdlib/numpy).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.io.hdf5_common import axiscal_from_offset_scale

__all__ = ["MSAFormatError", "load_msa"]


class MSAFormatError(ValueError):
    """Raised for unreadable / non-EMSA ``.msa`` files."""


def _parse_header_and_data(
    text: str,
) -> tuple[dict[str, str], list[float], list[float]]:
    """Split an EMSA file into its header dict and the X / Y data columns."""
    header: dict[str, str] = {}
    xs: list[float] = []
    ys: list[float] = []
    in_data = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            key, _, val = line[1:].partition(":")
            key = key.strip().upper()
            val = val.strip()
            if key == "SPECTRUM":
                in_data = True
                continue
            if key == "ENDOFDATA":
                break
            header[key] = val
            continue
        if in_data:
            nums = [
                float(tok)
                for tok in line.replace(",", " ").split()
                if _is_number(tok)
            ]
            # DATATYPE XY → (x, y) pairs; Y (default) → every value is a count
            # (EMSA Y rows are often column-wrapped, several counts per line)
            if header.get("DATATYPE", "Y").strip().upper() == "XY":
                for i in range(0, len(nums) - 1, 2):
                    xs.append(nums[i])
                    ys.append(nums[i + 1])
            else:
                ys.extend(nums)
    return header, xs, ys


def _is_number(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _header_float(header: dict[str, str], key: str) -> float:
    try:
        return float(header[key])
    except (KeyError, ValueError):
        return float("nan")


def load_msa(path: str | Path) -> DataStruct:
    """Parse an EMSA/MAS ``.msa`` spectrum into a ``DataStruct``."""
    path = Path(path)
    try:
        text = path.read_text(encoding="latin-1")
    except OSError as e:  # pragma: no cover - unreadable file
        raise MSAFormatError(f"cannot read {path}: {e}") from None
    if "#" not in text:
        raise MSAFormatError(f"{path.name}: no EMSA header lines")

    header, xs, ys = _parse_header_and_data(text)
    if not ys:
        raise MSAFormatError(f"{path.name}: no spectrum data found")

    counts = np.asarray(ys, dtype=np.float64)
    datatype = header.get("DATATYPE", "Y").strip().upper()

    xperchan = _header_float(header, "XPERCHAN")
    offset = _header_float(header, "OFFSET")
    # XY data with no explicit per-channel: derive from the X column
    if (not np.isfinite(xperchan)) and datatype == "XY" and len(xs) >= 2:
        xperchan = float(xs[1] - xs[0])
        offset = float(xs[0])
    if not np.isfinite(xperchan) or xperchan == 0:
        xperchan = 1.0
    if not np.isfinite(offset):
        offset = 0.0

    units = header.get("XUNITS", "eV").strip() or "eV"
    cal = axiscal_from_offset_scale(offset, xperchan, units)

    metadata: dict[str, Any] = {
        "source": str(path),
        "parser": "msa",
        "msa_title": header.get("TITLE", ""),
        "y_units": header.get("YUNITS", ""),
        "msa_header": header,
    }
    return DataStruct(
        data=counts, kind=DataKind.SPECTRUM, axes=(cal,), metadata=metadata
    )
