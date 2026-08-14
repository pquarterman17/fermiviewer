"""Differential phase contrast (DPC) from a per-probe COM field (PLAN_4DSTEM #8).

`calc/fourd/com.py` resolves the descan reference center and produces two
scan-shaped maps, ``(com_y_shift, com_x_shift)``, in DETECTOR PIXELS. This
module turns that vector field into the standard DPC products: a calibrated
deflection-angle field, its magnitude/direction, and the divergence of the
field — proportional to projected charge density by Gauss's law. Reimplemented
directly from Müller-Caspary et al., "Measurement of atomic electric fields
and charge densities from average momentum transfers using scanning
transmission electron microscopy", Ultramicroscopy 178 (2017) — the same
primary reference `com.py`/`virtual.com_shift_maps` already cite.
py4DSTEM/pyxem (AGPL) were not consulted for this module.

Coordinates and axis order follow `calc/fourd/geometry.py`'s convention:
plain 0-based ``(ky, kx)`` == ``(row, col)`` for the detector axes, and the
COM maps are indexed ``(scan_y, scan_x)`` == ``(row, col)`` for the scan
axes. This is DELIBERATE, not a port of `calc/radial.py`'s 1-based MATLAB
convention — don't "fix" it to match that module.

Calibration: a COM shift in detector PIXELS only becomes a physical
deflection angle once multiplied by the detector's mrad-per-pixel
calibration. That calibration is NOT reliably available on every
``FourDDataset`` — a bare `.mib` with no `.hdr` sidecar is uncalibrated
(`AxisCal()` defaults, see `io/fourd/mib.py`), and even a calibrated
HyperSpy-4D file may report units other than mrad. Rather than default to
`1.0` (silently turning a physical field into a copy of the raw pixel
shift) or auto-read a possibly-wrong axis, every function here takes
``mrad_per_px`` as an EXPLICIT, required argument — `routes/fourd_com.py`
requires it as a request field for the same reason. It is assumed
ISOTROPIC (one scalar for both detector axes), matching the frontend's own
`mradConversion.ts` precedent, which only exposes a single calibrated scale
when both detector axes are calibrated and agree on unit — real 4D-STEM
detectors are square-pixel and calibrated isotropically.

No accelerating voltage or specimen-thickness constant is taken as input
(none was requested, and inventing one would fabricate physics) — see
``divergence_map``'s docstring for the resulting charge-density units.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "DpcMaps",
    "calibrated_field_mrad",
    "dpc_magnitude",
    "dpc_direction",
    "divergence_map",
    "dpc_maps",
]


def _validate_mrad_per_px(mrad_per_px: float) -> None:
    if not np.isfinite(mrad_per_px) or mrad_per_px <= 0:
        raise ValueError(f"mrad_per_px must be a finite value > 0, got {mrad_per_px}")


def calibrated_field_mrad(
    com_y_shift: np.ndarray, com_x_shift: np.ndarray, mrad_per_px: float
) -> tuple[np.ndarray, np.ndarray]:
    """Calibrate a COM shift field (detector PIXELS) into a beam-deflection
    ANGLE field, in MILLIRADIANS, by multiplying through the detector's
    isotropic mrad-per-pixel calibration.

    ``com_y_shift``/``com_x_shift`` are the ``(scan_y, scan_x)`` maps
    `calc.fourd.com.com_maps` returns. ``mrad_per_px`` must be a finite
    value > 0 — see the module docstring for why this is never defaulted.

    Returns ``(field_y_mrad, field_x_mrad)``, each ``(scan_y, scan_x)``,
    units milliradians.
    """
    _validate_mrad_per_px(mrad_per_px)
    field_y = np.asarray(com_y_shift, dtype=np.float64) * mrad_per_px
    field_x = np.asarray(com_x_shift, dtype=np.float64) * mrad_per_px
    return field_y, field_x


def dpc_magnitude(field_y: np.ndarray, field_x: np.ndarray) -> np.ndarray:
    """Per-probe DPC magnitude: ``hypot(field_y, field_x)``.

    Units match the two inputs (mrad, when fed `calibrated_field_mrad`'s
    output — the intended use — but the function itself is unit-agnostic:
    it is equally correct on the raw pixel-shift maps).
    """
    return np.hypot(
        np.asarray(field_y, dtype=np.float64), np.asarray(field_x, dtype=np.float64)
    )


def dpc_direction(field_y: np.ndarray, field_x: np.ndarray) -> np.ndarray:
    """Per-probe DPC direction, in RADIANS: ``atan2(field_y, field_x)``.

    Convention: 0 rad points along +kx (increasing column / ``field_x``
    only), +pi/2 rad along +ky (increasing row / ``field_y`` only) —
    standard ``atan2(y, x)`` applied to this module's 0-based ``(ky, kx)``
    row/col axis order (see the module docstring), i.e. the mathematical
    angle within the (col, row) INDEX plane. This is calibration-scale
    INVARIANT: multiplying both components by the same positive
    ``mrad_per_px`` (the isotropic-calibration assumption documented at
    module level) never changes the angle, so `dpc_direction` gives the
    identical result whether fed the raw pixel-shift maps or the
    mrad-calibrated field. Range: ``(-pi, pi]``, per `numpy.arctan2`.

    NOTE: this is an index-plane angle, not necessarily a physical
    real-space bearing — that additionally requires the detector's row/col
    axes to be aligned with the microscope's real-space scan x/y, which
    this module does not verify (no such check exists anywhere upstream
    either).
    """
    return np.arctan2(
        np.asarray(field_y, dtype=np.float64), np.asarray(field_x, dtype=np.float64)
    )


def divergence_map(field_y: np.ndarray, field_x: np.ndarray) -> np.ndarray:
    """Divergence of the calibrated deflection field, proportional to
    projected charge density by Gauss's law (``div E = rho / eps0``).

    Finite-difference scheme: ``numpy.gradient`` along each axis — central
    (2nd-order-accurate) differences at interior scan positions, one-sided
    (1st-order-accurate) differences at the scan-shape boundary, unit
    (single-scan-pixel) spacing. Both schemes are EXACT (zero truncation
    error) for a field that varies linearly in space, since the leading
    error term involves the second derivative — this is why a uniform
    field integrates to exactly zero divergence everywhere (see tests) and
    a linear (e.g. radial/point-charge-like) field integrates to its exact
    constant divergence at every scan position, boundary rows/columns
    included.

    ``divergence = d(field_y)/d(scan_y) + d(field_x)/d(scan_x)``.

    UNITS: the derivative is taken with respect to the scan-position PIXEL
    INDEX (unit spacing), not a physical length — this module is never
    given the scan axis's physical pixel pitch (that is a separate,
    optional calibration already carried on the registered image via its
    ``axes`` — `routes/fourd_com.py` records it there unchanged, exactly
    as `/com` does). So when ``field_y``/``field_x`` are `mrad`,
    ``divergence_map`` returns units of **mrad per scan-pixel** — a map
    PROPORTIONAL to projected charge density, not an absolute density in
    physical units (C/m^2 or similar). Converting to an absolute density
    additionally requires the specimen thickness, the accelerating
    voltage, and the physical scan pixel pitch — none of which this
    function invents; multiply by the caller's own constant using the
    scan-axis calibration already carried alongside this map.
    """
    fy = np.asarray(field_y, dtype=np.float64)
    fx = np.asarray(field_x, dtype=np.float64)
    if fy.shape != fx.shape:
        raise ValueError(f"field_y/field_x shape mismatch: {fy.shape} != {fx.shape}")
    if fy.ndim != 2 or fy.shape[0] < 2 or fy.shape[1] < 2:
        raise ValueError(
            "divergence_map requires a 2D field with at least 2 scan "
            f"positions along each axis, got shape {fy.shape}"
        )
    d_fy_dy = np.gradient(fy, axis=0)
    d_fx_dx = np.gradient(fx, axis=1)
    return d_fy_dy + d_fx_dx


@dataclass(frozen=True)
class DpcMaps:
    """The full DPC product set from one COM field, all ``(scan_y, scan_x)``.

    Units: ``field_y_mrad``/``field_x_mrad``/``magnitude_mrad`` are
    milliradians; ``direction_rad`` is radians; ``divergence`` is
    milliradians per scan-pixel (see `divergence_map`'s docstring).
    """

    field_y_mrad: np.ndarray
    field_x_mrad: np.ndarray
    magnitude_mrad: np.ndarray
    direction_rad: np.ndarray
    divergence: np.ndarray


def dpc_maps(
    com_y_shift: np.ndarray, com_x_shift: np.ndarray, mrad_per_px: float
) -> DpcMaps:
    """Compute the full DPC product set from a COM shift field in one call
    — the single entry point `routes/fourd_com.py`'s `/dpc` route uses.

    ``com_y_shift``/``com_x_shift`` are `calc.fourd.com.com_maps`'s output
    (detector pixels); ``mrad_per_px`` is the required, explicit detector
    calibration (see the module docstring). Raises ``ValueError`` for a
    non-finite/non-positive ``mrad_per_px`` or a scan shape too small for
    `divergence_map` (fewer than 2 rows or 2 columns).
    """
    field_y, field_x = calibrated_field_mrad(com_y_shift, com_x_shift, mrad_per_px)
    magnitude = dpc_magnitude(field_y, field_x)
    direction = dpc_direction(field_y, field_x)
    divergence = divergence_map(field_y, field_x)
    return DpcMaps(
        field_y_mrad=field_y,
        field_x_mrad=field_x,
        magnitude_mrad=magnitude,
        direction_rad=direction,
        divergence=divergence,
    )
