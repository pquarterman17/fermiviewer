"""Shared pieces for scanning-probe (AFM/SPM) readers.

Every SPM reader returns ALL channels of a file as separate images
(``load_<fmt>_all``) and picks the topography one for a plain open
(``primary_channel``), so the AFM "Open Other Channels" action works the
same way for every format. Heights and lateral sizes are normalised to nm,
the unit `io/nanoscope.py` already uses, so a levelled height map and the
ISO 25178 parameters read the same whichever instrument wrote the file.
"""

from __future__ import annotations

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

__all__ = ["length_to_nm_factor", "primary_channel", "spm_channel", "to_nm", "unique_labels"]

_TO_NM = {
    "m": 1e9, "mm": 1e6, "um": 1e3, "µm": 1e3, "μm": 1e3, "nm": 1.0,
    "a": 0.1, "å": 0.1, "ang": 0.1, "pm": 1e-3,
}

# the channel a plain open shows: topography first, in this order
_PRIMARY = ("height", "topography", "zsensor", "z sensor", "z-sensor", "z")


def length_to_nm_factor(unit: str) -> float | None:
    """Factor to nm for a length unit, None for anything else."""
    return _TO_NM.get(unit.strip().lower())


def to_nm(values: np.ndarray, unit: str) -> tuple[np.ndarray, str]:
    """Heights in nm when `unit` is a length; otherwise unchanged."""
    f = length_to_nm_factor(unit)
    if f is None:
        return values, unit
    return values * f, "nm"


def spm_channel(
    data: np.ndarray, *, parser: str, channel: str, label: str,
    value_unit: str, dy_nm: float, dx_nm: float, **extra: object,
) -> DataStruct:
    """One channel as a calibrated image (rows top to bottom), heights in
    nm. `dy_nm`/`dx_nm` are the pixel sizes; NaN or ≤ 0 leaves the axes
    uncalibrated."""
    z, unit = to_nm(np.asarray(data, dtype=np.float64), value_unit)

    def axis(step: float) -> AxisCal:
        return AxisCal(scale=step, origin=0.0, units="nm") if np.isfinite(step) and step > 0 \
            else AxisCal()

    return DataStruct(
        data=np.ascontiguousarray(z),
        kind=DataKind.IMAGE,
        axes=(axis(dy_nm), axis(dx_nm)),
        metadata={"parser": parser, "channel": channel, "channel_label": label,
                  "value_unit": unit, **extra},
    )


def primary_channel(channels: list[DataStruct]) -> DataStruct:
    """The topography channel (trace before retrace), else the first."""
    if not channels:
        raise ValueError("the file holds no image channels")
    names = [str(ds.metadata.get("channel", "")).strip().lower() for ds in channels]
    for exact in (True, False):              # "Height" beats "Height (measured)"
        for key in _PRIMARY:
            for ds, name in zip(channels, names, strict=True):
                if name == key or (not exact and len(key) > 1 and name.startswith(key)):
                    return ds
    return channels[0]


def unique_labels(channels: list[DataStruct]) -> list[DataStruct]:
    """Number repeated channel labels ("Height", "Height 2") so every channel
    of a file can be told apart and opened (the AFM channel family is keyed
    by label)."""
    seen: dict[str, int] = {}
    for ds in channels:
        label = str(ds.metadata.get("channel_label", ""))
        seen[label] = seen.get(label, 0) + 1
        if seen[label] > 1:
            ds.metadata["channel_label"] = f"{label} {seen[label]}"
    return channels
