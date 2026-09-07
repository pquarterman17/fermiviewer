"""Experimental Cliff-Lorimer and ζ factors derived from a known standard
(roadmap 5b, second box).

The built-in `K_FACTORS_200KV` table is one instrument's numbers at one
voltage. Using it on another microscope, or at another kV, is an
extrapolation the user cannot see in the answer. A factor derived from a
standard is the alternative: measure something whose composition you
already know, and the ratio of what you measured to what is true IS the
factor.

Both derivations invert the quantification this repo already ships, so
the conventions are taken from those functions rather than from a
textbook that might spell them differently:

* `calc.eds.cliff_lorimer` uses ``w_i ∝ k_i·I_i``, so ``k_i ∝ w_i/I_i``.
  Only ratios are defined, so a derived set is normalised to a reference
  element (Si where present, matching the built-in table's ``Si: 1.00``).
* `calc.eds_zeta` uses ``C_i·ρt = ζ_i·I_i/D_e``, so
  ``ζ_i = C_i·ρt·D_e/I_i``. ζ is absolute and carries kg·m⁻².

Both take WEIGHT fractions. A standard certified in atomic percent is
converted here (`weight_fractions`) rather than at the call site, because
doing it in two places is how the two spellings drift.

Pure library (numpy only).

References
----------
Cliff & Lorimer, *J. Microsc.* **103** (1975) 203-207; Watanabe &
Williams, *J. Microsc.* **221** (2006) 89-109 (§ζ from standards).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.elements import ELEMENTS, atomic_mass

__all__ = [
    "DerivedFactor",
    "derive_k_factors",
    "derive_zeta_factors",
    "transfer_zeta",
    "weight_fractions",
]


@dataclass(frozen=True)
class DerivedFactor:
    """One element's derived factor with its 1σ and what it came from."""

    element: str
    value: float
    sigma: float
    #: net intensity used (counts) and its 1σ, echoed so a reviewer can
    #: recompute the factor without re-running the fit
    intensity: float
    intensity_sigma: float
    #: the standard's weight fraction for this element, after any
    #: atomic→weight conversion, and its 1σ
    weight_fraction: float
    weight_fraction_sigma: float


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

    A ``"at"`` composition is converted by ``w_i ∝ a_i·M_i``. Treating an
    atomic percent as a weight percent is a silent error of tens of
    percent for any pair with dissimilar masses, which is precisely the
    size of the effect a standard is being used to pin down.
    """
    if basis not in ("wt", "at"):
        raise ValueError(f"composition basis must be 'wt' or 'at', got {basis!r}")
    if not composition_pct:
        raise ValueError("composition is empty")
    sig = dict(sigma_pct or {})
    if basis == "at":
        weights = {
            sym: pct * (atomic_mass(sym) if sym in ELEMENTS else 1.0)
            for sym, pct in composition_pct.items()
        }
        # the 1σ scales with the same factor before renormalisation
        sig = {
            sym: s * (atomic_mass(sym) if sym in ELEMENTS else 1.0)
            for sym, s in sig.items()
        }
    else:
        weights = dict(composition_pct)
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("composition sums to zero")
    fractions = {sym: v / total for sym, v in weights.items()}
    sigmas = {sym: sig.get(sym, 0.0) / total for sym in fractions}
    return fractions, sigmas


def _relative(value: float, sigma: float) -> float:
    """σ/|value|, or 0 for a zero σ. A zero VALUE with a non-zero σ is an
    infinite relative error and propagates as such rather than silently
    becoming zero."""
    if sigma == 0.0:
        return 0.0
    if value == 0.0:
        return float("inf")
    return abs(sigma / value)


def derive_k_factors(
    elements: Sequence[str],
    intensities: Sequence[float],
    weight_fraction: Mapping[str, float],
    *,
    intensity_sigma: Sequence[float] | None = None,
    weight_fraction_sigma: Mapping[str, float] | None = None,
    reference: str | None = None,
) -> tuple[list[DerivedFactor], str]:
    """Cliff-Lorimer k factors from a standard, and the reference element.

    ``k_i = (w_i/I_i) / (w_ref/I_ref)``, so ``k_ref`` is exactly 1 and the
    set is defined only up to that choice — the same freedom the built-in
    table exercises by quoting everything relative to Si.

    The reference defaults to Si when the standard contains it (so a
    derived set is directly comparable with the built-in table), else the
    element with the largest weight fraction, which carries the smallest
    relative counting error and so contaminates the other factors least.

    Uncertainty is the quadrature sum of four relative terms — this
    element's counts and certified fraction, and the reference's — which
    is why `k_ref` comes back with a σ of exactly 0: it is a definition,
    not a measurement.
    """
    n = len(elements)
    if len(intensities) != n:
        raise ValueError("elements and intensities must have equal length")
    i_sig = list(intensity_sigma) if intensity_sigma is not None else [0.0] * n
    if len(i_sig) != n:
        raise ValueError("intensity_sigma must match elements length")
    w_sig = dict(weight_fraction_sigma or {})
    missing = [s for s in elements if s not in weight_fraction]
    if missing:
        raise ValueError(f"the standard states no composition for {missing}")
    inten = [float(v) for v in intensities]
    if any(v <= 0 for v in inten):
        bad = [s for s, v in zip(elements, inten, strict=True) if v <= 0]
        raise ValueError(f"no measurable intensity for {bad}; cannot derive a factor")

    ref = reference
    if ref is None:
        ref = "Si" if "Si" in elements else max(elements, key=lambda s: weight_fraction[s])
    if ref not in elements:
        raise ValueError(f"reference element {ref!r} is not among the measured elements")
    ri = elements.index(ref)
    ratio_ref = weight_fraction[ref] / inten[ri]
    rel_ref = np.hypot(
        _relative(weight_fraction[ref], w_sig.get(ref, 0.0)),
        _relative(inten[ri], i_sig[ri]),
    )

    out: list[DerivedFactor] = []
    for idx, sym in enumerate(elements):
        ratio = weight_fraction[sym] / inten[idx]
        k = ratio / ratio_ref
        if sym == ref:
            rel = 0.0  # a definition, not a measurement
        else:
            rel = float(
                np.sqrt(
                    _relative(weight_fraction[sym], w_sig.get(sym, 0.0)) ** 2
                    + _relative(inten[idx], i_sig[idx]) ** 2
                    + rel_ref**2
                )
            )
        out.append(
            DerivedFactor(
                element=sym,
                value=float(k),
                sigma=float(abs(k) * rel),
                intensity=inten[idx],
                intensity_sigma=float(i_sig[idx]),
                weight_fraction=float(weight_fraction[sym]),
                weight_fraction_sigma=float(w_sig.get(sym, 0.0)),
            )
        )
    return out, ref


def derive_zeta_factors(
    elements: Sequence[str],
    intensities: Sequence[float],
    weight_fraction: Mapping[str, float],
    *,
    mass_thickness_kg_m2: float,
    dose_electrons: float,
    intensity_sigma: Sequence[float] | None = None,
    weight_fraction_sigma: Mapping[str, float] | None = None,
    mass_thickness_sigma: float = 0.0,
    dose_sigma: float = 0.0,
) -> list[DerivedFactor]:
    """ζ factors from a standard of KNOWN mass-thickness.

    ``ζ_i = C_i·ρt·D_e/I_i``, the inversion of `eds_zeta.zeta_quantify`.

    Unlike k, ζ is absolute: it needs the standard's mass-thickness and
    the electron dose that produced these counts, and it is specific to
    the detector geometry that collected them (see `transfer_zeta`). A
    standard with no certified mass-thickness cannot yield ζ at all, which
    is a refusal rather than a fallback — there is no way to guess ρt that
    does not simply invent the answer.
    """
    n = len(elements)
    if len(intensities) != n:
        raise ValueError("elements and intensities must have equal length")
    if not mass_thickness_kg_m2 > 0:
        raise ValueError("the standard needs a positive certified mass-thickness for ζ")
    if not dose_electrons > 0:
        raise ValueError("dose must be positive")
    i_sig = list(intensity_sigma) if intensity_sigma is not None else [0.0] * n
    if len(i_sig) != n:
        raise ValueError("intensity_sigma must match elements length")
    w_sig = dict(weight_fraction_sigma or {})
    missing = [s for s in elements if s not in weight_fraction]
    if missing:
        raise ValueError(f"the standard states no composition for {missing}")
    inten = [float(v) for v in intensities]
    if any(v <= 0 for v in inten):
        bad = [s for s, v in zip(elements, inten, strict=True) if v <= 0]
        raise ValueError(f"no measurable intensity for {bad}; cannot derive a factor")

    rel_common = np.hypot(
        _relative(mass_thickness_kg_m2, mass_thickness_sigma),
        _relative(dose_electrons, dose_sigma),
    )
    out: list[DerivedFactor] = []
    for idx, sym in enumerate(elements):
        zeta = weight_fraction[sym] * mass_thickness_kg_m2 * dose_electrons / inten[idx]
        rel = float(
            np.sqrt(
                _relative(weight_fraction[sym], w_sig.get(sym, 0.0)) ** 2
                + _relative(inten[idx], i_sig[idx]) ** 2
                + rel_common**2
            )
        )
        out.append(
            DerivedFactor(
                element=sym,
                value=float(zeta),
                sigma=float(zeta * rel),
                intensity=inten[idx],
                intensity_sigma=float(i_sig[idx]),
                weight_fraction=float(weight_fraction[sym]),
                weight_fraction_sigma=float(w_sig.get(sym, 0.0)),
            )
        )
    return out


def transfer_zeta(
    factors: Sequence[DerivedFactor],
    *,
    from_solid_angle_sr: float,
    to_solid_angle_sr: float,
    from_efficiency: float = 1.0,
    to_efficiency: float = 1.0,
) -> list[DerivedFactor]:
    """Rescale a ζ set measured on one detector geometry for another.

    ζ counts photons per electron per unit mass-thickness, so it is
    inversely proportional to how much of the emitted signal the detector
    actually collects: ``ζ ∝ 1/(Ω·ε)``. Moving a set between geometries
    is therefore

        ζ_to = ζ_from · (Ω_from·ε_from) / (Ω_to·ε_to)

    which is the one calculation that reads `detector.solid_angle` and
    `detector.efficiency`. Note what this does NOT do: the efficiency
    ratio is applied as a single scalar per set, so it is only right when
    the two detectors' efficiency CURVES have the same shape over the
    lines used. Two detectors with different windows do not, and a
    transferred set is then wrong in an energy-dependent way that no
    single number can express — which is why the σ is widened rather than
    carried across unchanged.
    """
    for name, value in (
        ("from_solid_angle_sr", from_solid_angle_sr),
        ("to_solid_angle_sr", to_solid_angle_sr),
        ("from_efficiency", from_efficiency),
        ("to_efficiency", to_efficiency),
    ):
        if not value > 0:
            raise ValueError(f"{name} must be positive")
    scale = (from_solid_angle_sr * from_efficiency) / (to_solid_angle_sr * to_efficiency)
    return [
        DerivedFactor(
            element=f.element,
            value=f.value * scale,
            # the geometry ratio is exact by construction; the widening is
            # for the flat-efficiency-ratio assumption above, and is
            # deliberately visible rather than folded away
            sigma=float(np.hypot(f.sigma * scale, 0.05 * f.value * scale)),
            intensity=f.intensity,
            intensity_sigma=f.intensity_sigma,
            weight_fraction=f.weight_fraction,
            weight_fraction_sigma=f.weight_fraction_sigma,
        )
        for f in factors
    ]
