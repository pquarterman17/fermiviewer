"""Composition on a stated basis, and conversion between the two
(roadmap 5b).

A certificate quotes 61.5%, and whether that means 61.5 grams per hundred
or 61.5 atoms per hundred changes every number derived from it. The two
are related only through the atomic weights, so a basis is carried with
the numbers and converted here — in ONE place, because the EDS and EELS
derivations need opposite bases and two spellings of the same conversion
is how they drift apart:

* Cliff-Lorimer and ζ are relations between WEIGHT fractions
  (`calc.eds.cliff_lorimer`'s ``w_i ∝ k_i·I_i``).
* EELS quantification is a relation between ATOMIC fractions
  (`calc.eels_quant.quantify`'s ``N_X ∝ I_X/σ_X``, reported as at%).

So the same standard feeds the two derivations through different
conversions, and getting that backwards is an error of tens of percent
for any pair with dissimilar masses — exactly the size of effect a
standard is brought in to pin down.

Pure library (numpy only).
"""

from __future__ import annotations

from collections.abc import Mapping

from fermiviewer.calc.elements import ELEMENTS, atomic_mass

__all__ = ["atomic_fractions", "weight_fractions"]


def _mass(symbol: str) -> float:
    """Atomic mass, or 1.0 for a symbol this build does not know.

    1.0 rather than raising: an unknown symbol then behaves as if weight
    and atomic fractions coincide for it, which is wrong but bounded and
    visible, where refusing would make one exotic label block a whole
    derivation. `validate_fields`-style rejection belongs at the point the
    composition is entered, not here.
    """
    return atomic_mass(symbol) if symbol in ELEMENTS else 1.0


def _normalise(
    weights: Mapping[str, float], sigmas: Mapping[str, float]
) -> tuple[dict[str, float], dict[str, float]]:
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("composition sums to zero")
    return (
        {sym: v / total for sym, v in weights.items()},
        {sym: sigmas.get(sym, 0.0) / total for sym in weights},
    )


def weight_fractions(
    composition_pct: Mapping[str, float],
    basis: str,
    *,
    sigma_pct: Mapping[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """``(fractions, sigmas)`` as WEIGHT fractions summing to 1.

    A ``"wt"`` composition is only renormalised — a certificate that lists
    the major elements need not reach 100%, and the ratios a derivation
    uses must not depend on whether the balance was quoted.

    An ``"at"`` composition is converted by ``w_i ∝ a_i·M_i``.
    """
    if basis not in ("wt", "at"):
        raise ValueError(f"composition basis must be 'wt' or 'at', got {basis!r}")
    if not composition_pct:
        raise ValueError("composition is empty")
    sig = dict(sigma_pct or {})
    if basis == "at":
        weights = {sym: pct * _mass(sym) for sym, pct in composition_pct.items()}
        sig = {sym: s * _mass(sym) for sym, s in sig.items()}
    else:
        weights = dict(composition_pct)
    return _normalise(weights, sig)


def atomic_fractions(
    composition_pct: Mapping[str, float],
    basis: str,
    *,
    sigma_pct: Mapping[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """``(fractions, sigmas)`` as ATOMIC fractions summing to 1.

    The mirror of `weight_fractions`: a ``"wt"`` composition is converted
    by ``a_i ∝ w_i/M_i``, and an ``"at"`` one is only renormalised.
    """
    if basis not in ("wt", "at"):
        raise ValueError(f"composition basis must be 'wt' or 'at', got {basis!r}")
    if not composition_pct:
        raise ValueError("composition is empty")
    sig = dict(sigma_pct or {})
    if basis == "wt":
        atoms = {sym: pct / _mass(sym) for sym, pct in composition_pct.items()}
        sig = {sym: s / _mass(sym) for sym, s in sig.items()}
    else:
        atoms = dict(composition_pct)
    return _normalise(atoms, sig)
