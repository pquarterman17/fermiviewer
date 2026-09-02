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

__all__ = ["SPECTRAL_KINDS", "AxisCal", "DataKind", "DataStruct"]


class DataKind(StrEnum):
    # Membership: use DataKind(x) or `is` checks, never `x in DataKind` —
    # value membership (`"image" in DataKind`) only works on CPython 3.12+;
    # on the supported 3.10/3.11 floor it raises TypeError.
    IMAGE = "image"                    # 2D [H, W]
    RGB_IMAGE = "rgb_image"            # 3D [H, W, 3] uint8 colour (ADR 0003)
    SPECTRUM = "spectrum"              # 1D [n_channels]
    SPECTRUM_IMAGE = "spectrum_image"  # 3D [Ny, Nx, n_channels]


#: Kinds with an energy axis (always the LAST dim). Spectral gates check
#: `kind not in SPECTRAL_KINDS`, so a future kind is excluded from spectral
#: math until someone deliberately adds it, never included by accident.
SPECTRAL_KINDS = frozenset({DataKind.SPECTRUM, DataKind.SPECTRUM_IMAGE})

# (data ndim, axes count) per kind. rgb_image carries SPATIAL axes only —
# a channel axis has no calibration semantics (ADR 0003 §1), so its 3D data
# pairs with 2 axes and `pixel_cal` keeps meaning the x axis.
_EXPECTED = {
    DataKind.IMAGE: (2, 2),
    DataKind.RGB_IMAGE: (3, 2),
    DataKind.SPECTRUM: (1, 1),
    DataKind.SPECTRUM_IMAGE: (3, 3),
}


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
        expected_ndim, expected_axes = _EXPECTED[self.kind]
        if self.data.ndim != expected_ndim:
            raise ValueError(
                f"{self.kind.value} requires {expected_ndim}D data, "
                f"got {self.data.ndim}D"
            )
        if len(self.axes) != expected_axes:
            raise ValueError(
                f"{self.kind.value} axes count {len(self.axes)} != "
                f"expected {expected_axes}"
            )
        if self.kind is DataKind.RGB_IMAGE:
            # Presentation-grade colour, composed client-side from scalar
            # rasters (ADR 0003 §2) — exactly 3 channels (producers drop
            # alpha at the boundary) and uint8 (there is no window/level
            # story for float colour, so the contract refuses it).
            if self.data.shape[-1] != 3:
                raise ValueError(
                    f"rgb_image requires [H, W, 3] data, got {self.data.shape}"
                )
            if self.data.dtype != np.uint8:
                raise ValueError(
                    f"rgb_image requires uint8 data, got {self.data.dtype}"
                )
        if self.data.size == 0:
            raise ValueError("empty data array")
        # Freeze the payload: a frozen dataclass can't stop in-place ndarray
        # mutation, so make the buffer itself read-only.
        self.data.setflags(write=False)

    # ── spectral conveniences ─────────────────────────────────────────
    @property
    def energy_cal(self) -> AxisCal:
        if self.kind not in SPECTRAL_KINDS:
            raise ValueError("images have no energy axis")
        return self.axes[-1]

    @property
    def energy_axis(self) -> np.ndarray:
        return self.energy_cal.axis(self.data.shape[-1])

    @property
    def n_channels(self) -> int:
        if self.kind not in SPECTRAL_KINDS:
            raise ValueError("images have no energy axis")
        return int(self.data.shape[-1])

    def sum_spectrum(self) -> np.ndarray:
        """Spatially-summed spectrum (identity for 1D spectra).

        Always a fresh, writeable copy. The frozen buffer is read-only, and
        np.asarray would return a read-only *view* for an already-float64 1D
        spectrum — so in-place callers (e.g. background subtraction) couldn't
        mutate it. np.array copies unconditionally, matching the
        SPECTRUM_IMAGE path's fresh .sum() allocation.
        """
        if self.kind is DataKind.SPECTRUM:
            return np.array(self.data, dtype=np.float64)
        if self.kind is DataKind.SPECTRUM_IMAGE:
            # Accumulate directly into a float64 output. Casting the full cube
            # first temporarily duplicates multi-gigabyte SI datasets.
            summed = np.empty(self.n_channels, dtype=np.float64)
            np.sum(self.data, axis=(0, 1), dtype=np.float64, out=summed)
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

    @property
    def pixel_area(self) -> float:
        """Area of ONE pixel in `pixel_unit` squared, or NaN.

        Deliberately not `pixel_size ** 2`. The two spatial axes carry
        independent scales and routinely differ: `io/nanoscope` sets them
        from `y_nm / ny` and `x_nm / nx`, and an AFM scan with 0.5 nm rows
        against 2.0 nm columns makes the squared form four times too
        large. Every area in the tree used to be computed that way.

        NaN unless BOTH spatial axes are calibrated and agree on their
        unit — multiplying nm by um would give a number in neither, and
        an area whose unit is a guess is worse than one that is absent
        (ADR 0004). `pixel_cal` keeps returning the second axis, because a
        LENGTH along one direction is a different question and does not
        become well defined by having two scales.

        Magnitude, not signed: a negative scale is a direction convention
        (DM writes them), and an area has no direction. The squared form
        used to absorb that by accident; this does it on purpose.
        """
        if self.kind is DataKind.SPECTRUM:
            raise ValueError("1D spectra have no spatial axes")
        rows, cols = self.axes[0], self.axes[1]
        if not (rows.calibrated and cols.calibrated):
            return float("nan")
        if rows.units != cols.units:
            return float("nan")
        return float(abs(rows.scale * cols.scale))

    @property
    def pixel_spacing(self) -> tuple[float, float]:
        """Physical extent of one pixel along (ROWS, COLUMNS) in
        `pixel_unit`, or ``(nan, nan)``.

        The per-axis companion to `pixel_area`, and the form
        `skimage.measure.regionprops(spacing=...)` wants. `pixel_area` is
        the product of these two; it stays a separate property because an
        area is well defined whenever both axes are, whereas a single
        LENGTH is not -- which is exactly why `pixel_size` cannot answer
        for both and why lengths derived from it alone (equivalent
        diameter, Feret, perimeter) were wrong on anisotropic data.

        Same refusals as `pixel_area`, for the same reasons: NaN unless
        both spatial axes are calibrated and agree on their unit, and
        magnitudes rather than signed scales, since a negative scale is a
        direction convention (DM writes them) and an extent has no
        direction.

        Returned as a plain tuple in (row, column) order to match numpy
        axis order and `regionprops`'s `spacing`, so callers never have to
        decide which way round it goes.
        """
        if self.kind is DataKind.SPECTRUM:
            raise ValueError("1D spectra have no spatial axes")
        rows, cols = self.axes[0], self.axes[1]
        if not (rows.calibrated and cols.calibrated):
            return (float("nan"), float("nan"))
        if rows.units != cols.units:
            return (float("nan"), float("nan"))
        return (float(abs(rows.scale)), float(abs(cols.scale)))
