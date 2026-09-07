"""Unit conversion for calibration-profile quantities (ADR 0010).

A profile field carries a magnitude AND a unit (`profiles_model.Quantity`),
and a consumer wants a number in the unit its own signature names --
`dose_electrons` takes nanoamps, the store keeps picoamps. Reading `.value`
and ignoring `.unit` is how a profile silently feeds a consumer a number
1000x wrong, which is the whole failure class profiles exist to prevent.

So conversion is explicit and DIMENSIONAL: each unit belongs to one
dimension and carries a factor to that dimension's base. Converting within
a dimension scales; converting across dimensions raises. There is no
"unrecognised unit passes through unchanged" fallback here -- that is the
right call for a display axis (`calc/energy_units.kev_factor`) where the
worst case is a mislabelled tick, and the wrong one for a quantity feeding
a published number.

Deliberately NOT in this table: the kV <-> keV equivalence. An accelerating
voltage and a beam energy are different dimensions that happen to agree
numerically for a singly-charged electron. Putting them in one dimension
would let the equivalence leak into every other conversion; consumers that
rely on it name it at the mapping site instead.

Pure stdlib, no numpy -- this sits under `io/`, which the repo keeps free
of the server stack.
"""

from __future__ import annotations

import math

__all__ = ["UnitError", "convert", "dimension_of", "same_dimension"]


class UnitError(ValueError):
    """A conversion this table cannot make."""


#: dimension -> {unit: factor to that dimension's base unit}. Keys are
#: matched case-sensitively against the spellings `FIELD_UNITS` uses, plus
#: the spellings a route signature uses, plus the obvious synonyms a
#: hand-edited store might carry.
_DIMENSIONS: dict[str, dict[str, float]] = {
    # base: steradian
    "solid_angle": {"sr": 1.0, "msr": 1e-3},
    # base: degree. Radians are here because a calc signature may want
    # them even though every profile field is stated in degrees.
    "angle": {"deg": 1.0, "degree": 1.0, "degrees": 1.0, "rad": 57.29577951308232},
    # base: second
    "time": {"s": 1.0, "sec": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9},
    # base: ampere
    "current": {"A": 1.0, "mA": 1e-3, "uA": 1e-6, "µA": 1e-6, "nA": 1e-9, "pA": 1e-12},
    # base: electronvolt
    "energy": {"eV": 1.0, "keV": 1e3, "MeV": 1e6},
    # base: volt
    "voltage": {"V": 1.0, "kV": 1e3, "MV": 1e6},
    # base: metre
    "length": {
        "m": 1.0,
        "mm": 1e-3,
        "um": 1e-6,
        "µm": 1e-6,
        "nm": 1e-9,
        "A": 1e-10,
        "Å": 1e-10,
        "angstrom": 1e-10,
        "pm": 1e-12,
    },
    # base: fraction. A percentage is a dimensionless ratio in disguise and
    # dead_time is stated in one, so the pair converts.
    "fraction": {"": 1.0, "fraction": 1.0, "%": 1e-2, "percent": 1e-2},
}

#: "A" is ampere in `current` and angstrom in `length`. Nothing in the
#: profile vocabulary states a current in bare amps, and `mm2`-style area
#: units are not convertible here at all, so the ambiguity is resolved in
#: favour of length only when the OTHER unit of the pair is a length.
_AMBIGUOUS = {"A"}


def dimension_of(unit: str, *, hint: str | None = None) -> str | None:
    """The dimension `unit` belongs to, or None if this table has no such
    unit. `hint` disambiguates a spelling two dimensions share (see
    `_AMBIGUOUS`) by naming the dimension to prefer."""
    if unit in _AMBIGUOUS and hint is not None and unit in _DIMENSIONS.get(hint, {}):
        return hint
    for dim, units in _DIMENSIONS.items():
        if unit in units:
            return dim
    return None


def same_dimension(a: str, b: str) -> bool:
    """True iff `a` and `b` are convertible into one another."""
    da = dimension_of(a, hint=dimension_of(b))
    return da is not None and da == dimension_of(b, hint=da)


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """`value` restated from `from_unit` into `to_unit`.

    Raises `UnitError` when either unit is unknown to this table or the two
    are different dimensions -- never a best-effort passthrough, because
    the caller is about to feed the number to a calculation that cannot
    tell a wrong magnitude from a right one.

    >>> convert(500.0, "pA", "nA")
    0.5
    >>> convert(20.0, "keV", "eV")
    20000.0
    """
    if from_unit == to_unit:
        return float(value)
    dim = dimension_of(from_unit, hint=dimension_of(to_unit))
    if dim is None:
        raise UnitError(f"unknown unit {from_unit!r}")
    target = dimension_of(to_unit, hint=dim)
    if target is None:
        raise UnitError(f"unknown unit {to_unit!r}")
    if target != dim:
        raise UnitError(
            f"cannot convert {from_unit!r} ({dim}) to {to_unit!r} ({target})"
        )
    units = _DIMENSIONS[dim]
    return float(value) * _ratio(units[from_unit], units[to_unit])


def _ratio(a: float, b: float) -> float:
    """`a / b`, computed exactly when both are powers of ten.

    Every metric prefix in this table is one, and the naive quotient is
    not exact for them: ``1e-6 / 1e-9`` is 1999.9999999999998 for a 2 um
    spacing, which then prints as a spurious 13th significant figure in a
    result. Exponent arithmetic gives 1000.0.
    """
    ea, eb = math.log10(a), math.log10(b)
    ra, rb = round(ea), round(eb)
    if math.isclose(ea, ra, abs_tol=1e-12) and math.isclose(eb, rb, abs_tol=1e-12):
        return 10.0 ** (ra - rb)
    return a / b
