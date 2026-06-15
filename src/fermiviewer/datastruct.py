"""DataStruct — the canonical data contract for all parsers and analysis.

Port of fermi-viewer's unified struct (`parser.createDataStruct`), redesigned
for Python: instead of the MATLAB time/values/labels/units flattening with a
`parserSpecific` escape hatch, the array IS the payload and per-axis
calibration is first-class.

Pure-library module: numpy only (layering guard applies).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:  # py<3.11 shim — delete when 3.10 support is dropped
    from enum import Enum

    class StrEnum(str, Enum):
        """Minimal backport of 3.11's enum.StrEnum: str-valued members whose
        str()/format() yield the value (e.g. "image", not "DataKind.IMAGE")."""

        __str__ = str.__str__
        __format__ = str.__format__

__all__ = ["AxisCal", "DataKind", "DataStruct"]


class DataKind(StrEnum):
    IMAGE = "image"                    # 2D [H, W]
    SPECTRUM = "spectrum"              # 1D [n_channels]
    SPECTRUM_IMAGE = "spectrum_image"  # 3D [Ny, Nx, n_channels]


_EXPECTED_NDIM = {DataKind.IMAGE: 2, DataKind.SPECTRUM: 1, DataKind.SPECTRUM_IMAGE: 3}


@dataclass(frozen=True)
class AxisCal:
    """Per-axis calibration. DM convention: value = (index − origin) × scale.

    origin is in index units (channels/pixels), not calibrated units.
    scale == 0 or NaN means uncalibrated (axis() falls back to indices).
    """

    scale: float = 1.0
    origin: float = 0.0
    units: str = ""

    @property
    def calibrated(self) -> bool:
        return bool(np.isfinite(self.scale)) and self.scale != 0 and self.units != ""

    def axis(self, n: int) -> np.ndarray:
        """Calibrated axis values for n samples (indices if uncalibrated)."""
        idx = np.arange(n, dtype=np.float64)
        if not np.isfinite(self.scale) or self.scale == 0:
            return idx
        return (idx - self.origin) * self.scale


@dataclass(frozen=True)
class DataStruct:
    """Immutable parsed dataset: array + per-axis calibration + metadata.

    Axis order matches array dims:
        image          — axes = (y, x)
        spectrum       — axes = (energy,)
        spectrum_image — axes = (y, x, energy)

    The energy axis is always LAST for spectral kinds (the cube layout every
    consumer assumes — parsers do whatever permutation the file needs).
    """

    data: np.ndarray
    kind: DataKind
    axes: tuple[AxisCal, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        expected = _EXPECTED_NDIM[self.kind]
        if self.data.ndim != expected:
            raise ValueError(
                f"{self.kind.value} requires {expected}D data, got {self.data.ndim}D"
            )
        if len(self.axes) != self.data.ndim:
            raise ValueError(
                f"axes count {len(self.axes)} != data ndim {self.data.ndim}"
            )
        if self.data.size == 0:
            raise ValueError("empty data array")
        # Freeze the payload: a frozen dataclass can't stop in-place ndarray
        # mutation, so make the buffer itself read-only.
        self.data.setflags(write=False)

    # ── spectral conveniences ─────────────────────────────────────────
    @property
    def energy_cal(self) -> AxisCal:
        if self.kind is DataKind.IMAGE:
            raise ValueError("images have no energy axis")
        return self.axes[-1]

    @property
    def energy_axis(self) -> np.ndarray:
        return self.energy_cal.axis(self.data.shape[-1])

    @property
    def n_channels(self) -> int:
        if self.kind is DataKind.IMAGE:
            raise ValueError("images have no energy axis")
        return int(self.data.shape[-1])

    def sum_spectrum(self) -> np.ndarray:
        """Spatially-summed spectrum (identity for 1D spectra)."""
        if self.kind is DataKind.SPECTRUM:
            return np.asarray(self.data, dtype=np.float64)
        if self.kind is DataKind.SPECTRUM_IMAGE:
            summed: np.ndarray = np.asarray(self.data, dtype=np.float64).sum(axis=(0, 1))
            return summed
        raise ValueError("images have no spectrum")

    # ── spatial conveniences ──────────────────────────────────────────
    @property
    def pixel_cal(self) -> AxisCal:
        """Calibration of the first spatial axis (x and y assumed equal)."""
        if self.kind is DataKind.SPECTRUM:
            raise ValueError("1D spectra have no spatial axes")
        return self.axes[1] if self.kind is DataKind.SPECTRUM_IMAGE else self.axes[1]

    @property
    def pixel_size(self) -> float:
        return self.pixel_cal.scale if self.pixel_cal.calibrated else float("nan")

    @property
    def pixel_unit(self) -> str:
        return self.pixel_cal.units if self.pixel_cal.calibrated else ""
