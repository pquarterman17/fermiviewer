"""Energy-axis unit normalization for the EDS analysis path.

Every EDS energy quantity in this codebase is keV: the characteristic-line
library (``calc/eds.lines_in_range``), the ``e_lo``/``e_hi`` window on
``/api/eds/element-map``, ``bg_width``/``bg_gap``, ``e0_kev``, and the
recalibration anchors. The *axis* is whatever the source format calibrated
it in, and several EDS-capable formats use eV — ``io/ser.py`` (TIA spectra
and spectrum images) and ``io/dm.py`` both emit ``units="eV"``, while
``io/bcf.py`` emits ``units="keV"``.

Comparing a keV window against an eV axis silently selects (almost) no
channels, so an element map comes back blank rather than raising. Route
adapters call ``to_kev`` before handing the axis to a pure ``calc``
function so the window and the axis are in the same unit.

EELS is deliberately NOT routed through here: its native unit is eV and its
windows/edge onsets are specified in eV, so its axis is already consistent.
"""

from __future__ import annotations

import numpy as np

__all__ = ["kev_factor", "to_kev"]

# Multiply an axis in the keyed unit by this to obtain keV. Keys are
# lower-cased and stripped before lookup, so "eV", "ev" and " EV " all hit.
_TO_KEV: dict[str, float] = {
    "kev": 1.0,
    "ev": 1e-3,
    "mev": 1e-6,
}


def kev_factor(units: str) -> float:
    """Scale factor converting ``units`` to keV, or 1.0 when not convertible.

    An unrecognised or empty unit returns 1.0 so the axis passes through
    untouched. That covers uncalibrated axes, where ``AxisCal.axis()`` falls
    back to channel indices and ``units`` is ``""`` — scaling those would be
    meaningless.
    """
    return _TO_KEV.get(units.strip().lower(), 1.0)


def to_kev(energy: np.ndarray, units: str) -> np.ndarray:
    """Return ``energy`` expressed in keV.

    Returns the input unchanged when it is already keV (or the unit is not a
    recognised energy unit), so the common Bruker/BCF path allocates nothing.
    """
    factor = kev_factor(units)
    if factor == 1.0:
        return energy
    return np.asarray(energy, dtype=np.float64) * factor
