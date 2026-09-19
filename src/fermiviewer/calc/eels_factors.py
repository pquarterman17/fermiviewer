"""Experimental EELS partial cross-sections derived from a known standard
(roadmap 5b, second box — the EELS half).

`calc.eels_quant.cross_section` is the onset-anchored hydrogenic model.
It is a MODEL: it knows nothing about this spectrometer's collection
geometry, the real edge shape, or the solid-state effects near the onset,
and its published accuracy is tens of percent for L edges. Quantifying an
unknown against it inherits all of that silently.

Deriving is the alternative, and it is the exact analogue of the EDS
k-factor derivation in `calc.eds_factors`: measure a standard whose
composition you already know, and the ratio of what you measured to what
is true IS the cross-section. Inverting `eels_quant.quantify`'s
``N_X ∝ I_X/σ_X``,

    σ_i ∝ I_i / a_i

Two things differ from the EDS case and both matter.

* **The basis is atomic, not weight.** `eels_quant` reports at%, so the
  relation above is between ATOMIC fractions, where Cliff-Lorimer's
  ``w_i ∝ k_i·I_i`` is between weight fractions. The same certificate
  therefore converts in opposite directions for the two derivations,
  which is why `calc.composition` holds both conversions in one place.
* **The scale must be asserted.** Only RATIOS of cross-sections are
  measurable this way, exactly as only ratios of k factors are. k solves
  that by definition (``k_ref ≡ 1``, dimensionless). σ cannot: it carries
  m² and `quantify` divides by it, so a derived set needs a real absolute
  anchor. That anchor is the model's σ for the reference element unless
  the caller supplies a better one — and because it is asserted rather
  than measured, the reference entry's σ is the anchor's σ alone (0 by
  default), the same "this is a definition, not a measurement" the
  k-factor reference carries.

So a derived set is honest about what it improved: the RELATIVE
sensitivities are now this instrument's, measured; the absolute scale is
still whatever the anchor was. Every entry keeps the model value it was
compared against, so the two can be reported side by side without either
replacing the other (ADR 0011).

Pure library (numpy only).

References
----------
Egerton, *EELS in the Electron Microscope*, 3rd ed., §3.6 (SIGMAK2/
SIGMAL2 accuracy); Malis, Cheng & Egerton, *J. Electron Microsc. Tech.*
**8** (1988) 193-200.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

__all__ = ["DerivedCrossSection", "derive_cross_sections"]


@dataclass(frozen=True)
class DerivedCrossSection:
    """One element's derived partial cross-section (m²) and its 1σ."""

    element: str
    value: float
    sigma: float
    #: the hydrogenic σ this was compared against, over the same window
    #: and conditions — kept so a report can show both without one
    #: silently standing in for the other
    model_value: float
    #: net edge intensity used and its 1σ, echoed so a reviewer can
    #: recompute the number without re-running the background fit
    intensity: float
    intensity_sigma: float
    #: the standard's atomic fraction for this element, after any
    #: weight→atomic conversion, and its 1σ
    atomic_fraction: float
    atomic_fraction_sigma: float

    @property
    def model_ratio(self) -> float:
        """Derived / model. 1.0 means the model was already right here."""
        return self.value / self.model_value if self.model_value > 0 else float("nan")


def _relative(value: float, sigma: float) -> float:
    """σ/|value|, or 0 for a zero σ. A zero VALUE with a non-zero σ is an
    infinite relative error and propagates as such rather than silently
    becoming zero."""
    if sigma == 0.0:
        return 0.0
    if value == 0.0:
        return float("inf")
    return abs(sigma / value)


def _checked_inputs(
    elements: Sequence[str],
    intensities: Sequence[float],
    model_sigmas: Sequence[float],
    atomic_fraction: Mapping[str, float],
    intensity_sigma: Sequence[float] | None,
) -> tuple[list[float], list[float], list[float]]:
    """``(intensities, model_sigmas, intensity_sigma)`` as floats, once
    every input has been checked to make a derivation meaningful."""
    n = len(elements)
    if n == 0:
        raise ValueError("no elements to derive from")
    if len(intensities) != n or len(model_sigmas) != n:
        raise ValueError(
            "elements, intensities and model_sigmas must have equal length"
        )
    i_sig = (
        [float(v) for v in intensity_sigma]
        if intensity_sigma is not None
        else [0.0] * n
    )
    if len(i_sig) != n:
        raise ValueError("intensity_sigma must match elements length")
    missing = [s for s in elements if s not in atomic_fraction]
    if missing:
        raise ValueError(f"the standard states no composition for {missing}")
    zero = [s for s in elements if not atomic_fraction[s] > 0]
    if zero:
        raise ValueError(f"the standard has no {zero} to measure against")
    inten = [float(v) for v in intensities]
    if any(v <= 0 for v in inten):
        bad = [s for s, v in zip(elements, inten, strict=True) if v <= 0]
        raise ValueError(f"no measurable edge intensity for {bad}; cannot derive σ")
    return inten, [float(v) for v in model_sigmas], i_sig


def _anchor(
    ref: str,
    model_ref: float,
    reference_value_m2: float | None,
    reference_value_sigma: float,
) -> tuple[float, float]:
    """``(value, relative sigma)`` for the set's absolute scale."""
    anchor = model_ref if reference_value_m2 is None else float(reference_value_m2)
    if not anchor > 0:
        raise ValueError(
            f"the reference cross-section for {ref!r} must be positive; "
            "a derived set has no absolute scale without one"
        )
    if reference_value_sigma < 0:
        raise ValueError("reference_value_sigma must be >= 0")
    return anchor, _relative(anchor, float(reference_value_sigma))


def derive_cross_sections(
    elements: Sequence[str],
    intensities: Sequence[float],
    model_sigmas: Sequence[float],
    atomic_fraction: Mapping[str, float],
    *,
    intensity_sigma: Sequence[float] | None = None,
    atomic_fraction_sigma: Mapping[str, float] | None = None,
    reference: str | None = None,
    reference_value_m2: float | None = None,
    reference_value_sigma: float = 0.0,
) -> tuple[list[DerivedCrossSection], str]:
    """Partial cross-sections from a standard, and the reference element.

    `intensities` and `model_sigmas` are what `eels_quant.quantify`
    already returns for the same edges — the derivation reuses that
    measurement rather than repeating the background fit, so a derived set
    and the quantification it came from cannot disagree about the counts.

    ``σ_i = σ_anchor · (I_i/a_i) / (I_ref/a_ref)``.

    The reference defaults to the element with the largest atomic
    fraction: it carries the smallest relative counting error, so it
    contaminates the rest of the set least. `reference_value_m2` overrides
    the anchor for a reference whose cross-section is independently known
    (a measured σ from the literature, say); without it the model's own σ
    for that edge is used and the set's absolute scale is only as good as
    the model was for that one element.
    """
    inten, model, i_sig = _checked_inputs(
        elements, intensities, model_sigmas, atomic_fraction, intensity_sigma
    )
    a_sig = dict(atomic_fraction_sigma or {})

    ref = reference
    if ref is None:
        ref = max(elements, key=lambda s: atomic_fraction[s])
    if ref not in elements:
        raise ValueError(
            f"reference element {ref!r} is not among the measured elements"
        )
    ri = elements.index(ref)
    anchor, rel_anchor = _anchor(
        ref, model[ri], reference_value_m2, reference_value_sigma
    )

    ratio_ref = inten[ri] / atomic_fraction[ref]
    rel_ref = np.hypot(
        _relative(inten[ri], i_sig[ri]),
        _relative(atomic_fraction[ref], a_sig.get(ref, 0.0)),
    )

    out: list[DerivedCrossSection] = []
    for idx, sym in enumerate(elements):
        ratio = inten[idx] / atomic_fraction[sym]
        value = anchor * ratio / ratio_ref
        if sym == ref:
            # the measured terms cancel identically; what is left is the
            # anchor, which is asserted rather than measured
            rel = float(rel_anchor)
        else:
            rel = float(
                np.sqrt(
                    _relative(inten[idx], i_sig[idx]) ** 2
                    + _relative(atomic_fraction[sym], a_sig.get(sym, 0.0)) ** 2
                    + rel_ref**2
                    + rel_anchor**2
                )
            )
        out.append(
            DerivedCrossSection(
                element=sym,
                value=float(value),
                sigma=float(value * rel),
                model_value=model[idx],
                intensity=inten[idx],
                intensity_sigma=float(i_sig[idx]),
                atomic_fraction=float(atomic_fraction[sym]),
                atomic_fraction_sigma=float(a_sig.get(sym, 0.0)),
            )
        )
    return out, ref
