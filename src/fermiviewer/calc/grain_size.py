"""ASTM E112 grain-size numbers, kept apart from the segmentation.

Split out of `calc/grains.py` when that module crossed the repo's
500-line ceiling — the `calc/layers.py` precedent. The seam is a real
one rather than a line count: everything here is a UNIT CONVERSION and a
published relation, with no idea what a grain is or how one was found.

The relation itself is ASTM E112-13's planimetric method,
``G = 3.321928·log10(N_A) − 2.954`` for N_A grains per square millimetre,
and every function below is derived from that one line so the constants
can be checked instead of trusted.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "astm_grain_size_from_density",
    "astm_grain_size_number",
    "mm2_per_pixel",
]

# physical-length → millimetres (for the ASTM E112 grain-size number)
_MM_PER_UNIT: dict[str, float] = {
    "m": 1e3, "cm": 10.0, "mm": 1.0, "um": 1e-3, "µm": 1e-3,
    "nm": 1e-6, "a": 1e-7, "å": 1e-7, "angstrom": 1e-7, "pm": 1e-9,
}

#: ASTM E112-13's planimetric constant: G = 3.321928·log10(N_A) − 2.954,
#: with N_A the number of grains per SQUARE MILLIMETRE. Everything below
#: is derived from this one published relation rather than transcribed,
#: so the constants can be checked instead of trusted.
_E112_SLOPE = 3.321928
_E112_OFFSET = -2.954


def astm_grain_size_from_density(grains_per_mm2: float) -> float:
    """ASTM E112-13's planimetric relation, unadorned:
    ``G = 3.321928·log10(N_A) − 2.954`` for N_A grains per mm².

    This is the primitive because it is what the standard actually
    defines. `N_A` is COUNTABLE — grains divided by the area they cover —
    so a caller holding a segmentation can reach G with no assumption
    about grain shape or size spread at all.
    """
    if not np.isfinite(grains_per_mm2) or grains_per_mm2 <= 0:
        return float("nan")
    return float(_E112_SLOPE * np.log10(grains_per_mm2) + _E112_OFFSET)


def mm2_per_pixel(pixel_area: float, unit: str) -> float:
    """One pixel's area in mm², or NaN for an unknown unit."""
    factor = _MM_PER_UNIT.get((unit or "").strip().lower())
    if factor is None or not np.isfinite(pixel_area) or pixel_area <= 0:
        return float("nan")
    return float(pixel_area * factor * factor)


def astm_grain_size_number(mean_diameter: float, unit: str) -> float:
    """ASTM E112-13 grain-size number G from the mean equivalent grain
    diameter, in the image's calibrated `unit`. NaN for an unknown unit
    or a diameter ≤ 0.

    Derived, not transcribed. E112's planimetric relation is
    ``G = 3.321928·log10(N_A) − 2.954`` for N_A grains per mm². An
    equivalent circular diameter D covers ``π·D²/4``, so
    ``N_A = 4/(π·D²)`` and

        G = 3.321928·log10(4/(π·D²)) − 2.954
          = −6.643856·log10(D_mm) + 3.321928·log10(4/π) − 2.954
          = −6.643856·log10(D_mm) − 2.6055

    **This was wrong until 2026-09-01** and the error is worth naming,
    because the shape of it recurs: the slope ``6.643856`` is exactly
    ``2/log10(2)``, a coefficient CONSTRUCTED for log10, and it was being
    applied to ``log2``. That makes the slope steeper by 1/log10(2) =
    3.3219, so 10 µm grains reported G = 40.8 where E112 gives 10.7 —
    and real grain-size numbers only run from about 00 to 14, so every
    value the function returned for an ordinary micrograph was outside
    the scale it claims to be on.

    Its test could not catch it: the test recomputed the implementation's
    own expression and asserted the two matched, which is true of any
    formula whatsoever. The replacement checks published G/diameter pairs
    from E112's own table.

    **Prefer `astm_grain_size_from_density` where a count and an area are
    available.** Going through a mean DIAMETER assumes every grain is the
    same size: ``N_A = 4/(π·D̄²)`` uses the mean of the diameters, while
    the true density is ``1/mean(area)``, and by Jensen's inequality the
    first is the larger whenever grains vary. It biases G upward — the
    microstructure is reported finer than it is — by +0.06 at a
    coefficient of variation of 0.2, +0.22 at 0.4 and +0.44 at 0.6, on a
    scale quoted to a tenth. `grain_report` counts instead.
    """
    factor = _MM_PER_UNIT.get((unit or "").strip().lower())
    if factor is None or not np.isfinite(mean_diameter) or mean_diameter <= 0:
        return float("nan")
    d_mm = mean_diameter * factor
    return astm_grain_size_from_density(4.0 / (np.pi * d_mm * d_mm))
