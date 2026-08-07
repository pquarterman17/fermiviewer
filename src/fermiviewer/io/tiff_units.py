"""Scalar coercion and length-unit conversion shared by the TIFF readers.

Split out of `io.tiff_meta` so the vendor private-tag readers
(`io.tiff_vendor`) and the baseline/ImageJ reader can share one unit table
without importing each other. Nothing here touches a file — pure arithmetic
over values another module already pulled out of a tag.

Every accessor answers "absent" with NaN rather than 0 or None: an SEM tag
routinely holds an empty string for a parameter the column did not report,
and a 0 there would read as a measurement of zero.
"""

from __future__ import annotations

import math
from typing import Any

from fermiviewer.datastruct import AxisCal

__all__ = [
    "TO_NM",
    "axes_nm",
    "length_to_nm",
    "positive",
    "put",
    "tilt_deg_from_radians",
    "to_float",
]

TO_NM: dict[str, float] = {
    "pm": 1e-3,
    "a": 0.1, "å": 0.1, "ang": 0.1, "angstrom": 0.1,
    "nm": 1.0,
    "um": 1e3, "µm": 1e3, "μm": 1e3, "micron": 1e3, "microns": 1e3, "micrometer": 1e3,
    "mm": 1e6,
    "cm": 1e7,
    "m": 1e9,
    "inch": 2.54e7, "in": 2.54e7,
}

# Above this, express the axis in µm instead of nm (SEM/FIB overviews).
_UM_THRESHOLD_NM = 1e3


def to_float(value: Any) -> float:
    """Best-effort float; NaN for anything non-numeric. FEI/Zeiss INI values
    arrive already coerced by tifffile, but empty keys stay as ``''``."""
    if isinstance(value, bool):
        return float("nan")
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out if math.isfinite(out) else float("nan")


def positive(value: Any) -> float:
    """`to_float`, but a non-positive length is as useless as a missing one."""
    out = to_float(value)
    return out if out > 0 else float("nan")


def length_to_nm(value: Any, unit: str) -> float:
    """`value` expressed in nm, or NaN if `unit` is not a known length."""
    factor = TO_NM.get(unit.strip().lower().replace("μ", "µ"))
    if factor is None:
        return float("nan")
    return positive(value) * factor


def axes_nm(y_nm: float, x_nm: float) -> tuple[AxisCal, AxisCal]:
    """(y, x) AxisCals from per-pixel sizes in nm, in a readable unit.

    Both axes share one unit even when the pixels are non-square, because
    `DataStruct.pixel_unit` reports a single label for the pair. A source
    that states only one of the two gets square pixels rather than a
    half-calibrated image: `DataStruct.pixel_cal` reads the x axis alone, so
    a lone PixelHeight would otherwise be thrown away entirely.
    """
    finite = [v for v in (y_nm, x_nm) if math.isfinite(v) and v > 0]
    if not finite:
        return AxisCal(), AxisCal()
    unit, divisor = ("um", 1e3) if max(finite) >= _UM_THRESHOLD_NM else ("nm", 1.0)

    def cal(v: float) -> AxisCal:
        if not (math.isfinite(v) and v > 0):
            v = finite[0]
        return AxisCal(scale=v / divisor, origin=0.0, units=unit)

    return cal(y_nm), cal(x_nm)


def tilt_deg_from_radians(value: Any) -> float:
    """FEI stage angles are radians. Values beyond ±π cannot be — no stage
    tilts past 180° — so those are taken as degrees already, the same
    salvage `io.metadata.get_stage_tilt` applies to unlabelled FEI keys."""
    raw = to_float(value)
    if not math.isfinite(raw):
        return float("nan")
    return math.degrees(raw) if abs(raw) <= math.pi else raw


def put(meta: dict[str, Any], key: str, value: float) -> None:
    """Record `value` only when it is a real number — a metadata dict full
    of NaN placeholders reads as "the instrument said 0", not "absent"."""
    if isinstance(value, float) and math.isfinite(value):
        meta[key] = value
