"""Turning pixel-space geometry into physical lengths and angles.

One pixel has two independent extents -- `s_row` along ROWS and `s_col`
along COLUMNS -- and they routinely differ (`io/nanoscope` sets them from
``y_nm / ny`` and ``x_nm / nx``; an AFM scan with 0.5 nm rows against
2.0 nm columns is ordinary). `DataStruct.pixel_size` answers with the
COLUMN scale alone, because `pixel_cal` returns ``axes[1]``.

That single number is enough for a quantity measured purely along
columns and wrong for everything else. The failure is quiet: a diagonal
line, a vertical test line, or an angle comes back as a plausible number
in the right unit, just not the length or angle of the thing measured.

`physical_length` and `physical_angle_rad` exist so that a caller with a
pixel-space displacement never has to decide which scale goes with which
component -- the row step takes `s_row` and the column step takes `s_col`,
here, once.

Note the pairing is a property of the QUANTITY, not a constant to copy
between call sites. A test line running left-to-right traverses columns,
so its length is ``n_cols * s_col``. But the edge shared by two
horizontally-adjacent pixels is vertical, so *its* length is ``s_row``
(`calc/grains.py` measures exactly that). Same axis, opposite scale, both
right.
"""

from __future__ import annotations

import math

__all__ = [
    "calibrated_spacing",
    "growth_axis_scales",
    "physical_angle_rad",
    "physical_length",
    "resolve_spacing",
    "spacing_at_column_scale",
    "usable_spacing",
]


def usable_spacing(
    spacing: tuple[float, float] | None,
) -> tuple[float, float] | None:
    """The spacing if it can carry a physical length, else None.

    One definition of "calibrated enough to measure with", shared by
    every caller, so a length and the area beside it can never disagree
    about whether the image had a usable scale.
    """
    if spacing is None:
        return None
    s_r, s_c = float(spacing[0]), float(spacing[1])
    if not (math.isfinite(s_r) and math.isfinite(s_c)) or s_r <= 0 or s_c <= 0:
        return None
    return (s_r, s_c)


def resolve_spacing(
    spacing: tuple[float, float] | None, pixel_size: float
) -> tuple[float, float]:
    """Per-axis extents, falling back to an isotropic `pixel_size`.

    The precedence settled in #202: anything that can describe both axes
    beats a single length, and a `pixel_size` that is zero, negative or
    non-finite is not a calibration either -- it falls through to 1,
    which reads the result in pixels rather than dividing by it or
    multiplying a length by nonsense.
    """
    return (
        usable_spacing(spacing)
        or usable_spacing((pixel_size, pixel_size))
        or (1.0, 1.0)
    )


def calibrated_spacing(
    spacing: tuple[float, float] | None, pixel_size: float
) -> tuple[float, float] | None:
    """Per-axis extents when the image is calibrated, else None.

    The uncalibrated sibling of `resolve_spacing`: where that falls
    through to 1 for calcs that must return a number, this returns None
    so a caller can report pixels (or null) instead. A finite
    `pixel_size` is read as isotropic -- zero and negative included,
    because that is what the measurement paths multiplied by before
    `spacing` existed, and a correction that changes their answer on
    square pixels is not one.
    """
    sp = usable_spacing(spacing)
    if sp is not None:
        return sp
    if math.isfinite(pixel_size):
        return (float(pixel_size), float(pixel_size))
    return None


def spacing_at_column_scale(
    pixel_size: float, spacing: tuple[float, float] | None
) -> tuple[float, float] | None:
    """``(row, column)`` extents that keep `pixel_size` as the COLUMN scale.

    A caller that lets the user type one pixel size -- Å/px for a CTF
    fit, unit/px for a lattice measurement, mm/px for spot indexing -- is
    being given the column scale, because that is what `pixel_size` has
    meant everywhere (`pixel_cal` returns ``axes[1]``). The image's own
    `spacing` may be in another unit, or be exactly what the user is
    overriding, but its row-to-column RATIO is unit-free and is the only
    thing that knows the pixels are not square. Returns `spacing` itself
    when `pixel_size` is its column extent (bit for bit), the ratio
    applied to `pixel_size` otherwise, and None when either input cannot
    carry a length -- the caller then has one scale and reads it as
    isotropic, exactly as before.
    """
    sp = usable_spacing(spacing)
    if sp is None or not (math.isfinite(pixel_size) and pixel_size > 0):
        return None
    s_row, s_col = sp
    if pixel_size == s_col:
        return sp
    return (float(pixel_size) * (s_row / s_col), float(pixel_size))


def growth_axis_scales(
    axis: str, pixel_size: float, spacing: tuple[float, float] | None
) -> tuple[float, float]:
    """``(depth, lateral)`` pixel extents for a stack grown along `axis`.

    ``axis="y"`` means horizontal layers: depth runs down ROWS, so a
    layer's thickness is rows times the ROW extent, and the lateral
    coordinate an interface trace is sampled along is columns times the
    COLUMN extent. ``axis="x"`` is the transpose. Without a usable
    `spacing` both are `pixel_size`, the column scale read as isotropic --
    exactly what every thickness used to be multiplied by whatever the
    growth axis turned out to be.
    """
    sp = usable_spacing(spacing)
    if sp is None:
        return float(pixel_size), float(pixel_size)
    s_row, s_col = sp
    return (s_row, s_col) if axis == "y" else (s_col, s_row)


def physical_length(
    d_col: float, d_row: float, spacing: tuple[float, float]
) -> float:
    """Length of a pixel-space displacement, in physical units.

    `d_col` is the displacement along COLUMNS (the "x" of a 1-based
    ``(x, y)`` measurement point) and `d_row` along ROWS.

    The scaling has to happen BEFORE the Pythagorean sum, not after it:
    ``hypot(d_col, d_row) * s`` is the length of the wrong triangle
    whenever the two extents differ. On 1:3 pixels a diagonal of 10
    columns and 10 rows is 31.6 physical units, not 14.1.
    """
    s_row, s_col = spacing
    return float(math.hypot(d_col * s_col, d_row * s_row))


def physical_angle_rad(
    d_col: float, d_row: float, spacing: tuple[float, float]
) -> float:
    """Direction of a pixel-space displacement, in PHYSICAL space.

    An angle is not spared by being dimensionless: ``atan2`` of raw pixel
    components measures the angle of the sampled grid, not of the object.
    A 45-degree line drawn on 1:3 pixels really rises at 71.6 degrees.
    """
    s_row, s_col = spacing
    return math.atan2(d_row * s_row, d_col * s_col)
