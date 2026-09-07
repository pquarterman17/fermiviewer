"""Quantification quality checks reported beside a composition
(roadmap 5b, fourth box).

A composition is a number with a confidence interval, and the interval is
not the whole story: an element measured on 40 counts, a line sitting
under a neighbour's, a k-factor table quoted at 200 kV and used at 80, a
takeoff angle that fell back to a placeholder — each of these produces a
perfectly well-formed answer that a reader has no way to distrust from
the answer alone.

So the checks return FINDINGS rather than raising. The number is still
computed and still reported; what changes is that its caveats travel with
it. A check that would refuse instead of warn belongs in the calculation,
not here.

Each finding names a code (stable, for a UI to key on), a severity, a
sentence a scientist can act on, and the numbers behind it so nobody has
to take the sentence on faith.

Pure library (numpy only).

References
----------
Currie, *Anal. Chem.* **40** (1968) 586-593 (detection limits);
Goldstein et al., *SEM and X-ray Microanalysis*, 4th ed., ch. 19.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from fermiviewer.calc.eds import line_energy
from fermiviewer.calc.eds_calib import fano_sigma_kev

__all__ = [
    "QcFinding",
    "check_absorption",
    "check_counting_statistics",
    "check_detection_limit",
    "check_fit_quality",
    "check_factor_conditions",
    "check_peak_interference",
    "check_resolved_parameters",
    "findings_to_json",
]

#: Relative counting error above which a composition is worth a caveat,
#: and above which it is barely a measurement. 10% and 33% correspond to
#: roughly 100 and 9 net counts under Poisson statistics.
_REL_WARN = 0.10
_REL_ERROR = 1.0 / 3.0

#: Currie's detection criterion: a net signal below 3σ of the background
#: it sits on is not distinguishable from that background.
_DETECTION_SIGMA = 3.0

#: Two lines closer than this many combined σ are not independently
#: resolvable by a detector of the stated resolution, so their fitted
#: areas trade against each other.
_INTERFERENCE_SIGMA = 1.5

#: An absorption correction this large means the thin-film assumption is
#: carrying more than it comfortably can.
_ABSORPTION_WARN = 1.10
_ABSORPTION_ERROR = 1.50

#: A factor set used this far from the voltage it was derived at is an
#: extrapolation worth saying out loud (relative difference).
_KV_TOLERANCE = 0.05


@dataclass(frozen=True)
class QcFinding:
    """One caveat on a reported composition."""

    #: stable identifier a UI can key on
    code: str
    #: "info" | "warn" | "error" -- "error" never means the number is
    #: absent, only that it should not be published as it stands
    severity: str
    message: str
    #: the elements the finding is about, when it is about some of them
    elements: tuple[str, ...] = ()
    #: the numbers behind the sentence
    detail: dict[str, Any] = field(default_factory=dict)


def findings_to_json(findings: Sequence[QcFinding]) -> list[dict[str, Any]]:
    """Findings as a response block, most severe first so a truncated UI
    shows the ones that matter."""
    order = {"error": 0, "warn": 1, "info": 2}
    ranked = sorted(findings, key=lambda f: (order.get(f.severity, 3), f.code))
    return [
        {
            "code": f.code,
            "severity": f.severity,
            "message": f.message,
            "elements": list(f.elements),
            "detail": dict(f.detail),
        }
        for f in ranked
    ]


def check_counting_statistics(
    elements: Sequence[str],
    net: Sequence[float],
    net_sigma: Sequence[float],
) -> list[QcFinding]:
    """Poor counting statistics, per element.

    Reported on the INTENSITY rather than on the final percentage,
    because Cliff-Lorimer normalises: an element measured on nine counts
    can still come back as a confident-looking 4.1 at% once every
    element's share is forced to sum to 100.
    """
    out: list[QcFinding] = []
    weak: list[str] = []
    unusable: list[str] = []
    detail: dict[str, Any] = {}
    for sym, i, s in zip(elements, net, net_sigma, strict=True):
        if not np.isfinite(i) or i <= 0:
            unusable.append(sym)
            detail[sym] = {"net": float(i) if np.isfinite(i) else None, "relative": None}
            continue
        rel = float(s / i) if np.isfinite(s) and i > 0 else float("nan")
        detail[sym] = {"net": float(i), "sigma": float(s), "relative": rel}
        if not np.isfinite(rel):
            continue
        if rel >= _REL_ERROR:
            unusable.append(sym)
        elif rel >= _REL_WARN:
            weak.append(sym)
    if unusable:
        out.append(
            QcFinding(
                code="counts_too_low",
                severity="error",
                message=(
                    f"{', '.join(unusable)} has a counting error of 33% or worse; the "
                    "reported percentage is dominated by noise, not composition"
                ),
                elements=tuple(unusable),
                detail={k: detail[k] for k in unusable},
            )
        )
    if weak:
        out.append(
            QcFinding(
                code="counts_low",
                severity="warn",
                message=(
                    f"{', '.join(weak)} carries a counting error above 10%; collect "
                    "longer before treating the difference between runs as real"
                ),
                elements=tuple(weak),
                detail={k: detail[k] for k in weak},
            )
        )
    return out


def check_detection_limit(
    elements: Sequence[str],
    net: Sequence[float],
    background: Sequence[float],
) -> list[QcFinding]:
    """Currie's criterion: a net signal under 3·sqrt(background) is not
    distinguishable from the background it sits on, whatever the fit
    reports for its area."""
    below: list[str] = []
    detail: dict[str, Any] = {}
    for sym, i, b in zip(elements, net, background, strict=True):
        if not np.isfinite(i) or not np.isfinite(b) or b < 0:
            continue
        limit = _DETECTION_SIGMA * float(np.sqrt(b))
        detail[sym] = {"net": float(i), "background": float(b), "limit": limit}
        if i < limit:
            below.append(sym)
    if not below:
        return []
    return [
        QcFinding(
            code="below_detection_limit",
            severity="error",
            message=(
                f"{', '.join(below)} is below the 3σ detection limit of its own "
                "background; report it as not detected rather than as a percentage"
            ),
            elements=tuple(below),
            detail={k: detail[k] for k in below},
        )
    ]


def check_peak_interference(
    elements: Sequence[str], *, beam_kv: float = float("inf")
) -> list[QcFinding]:
    """Lines too close to be resolved independently.

    Their fitted areas trade against each other, so the two compositions
    are correlated in a way the per-element σ does not express: a fit can
    move counts from one to the other and barely change its residual.

    PRINCIPAL lines only. `line_energy` returns one line per element, so a
    Kβ/Kα clash — Ti Kβ 4.93 under V Kα 4.95, to name the standing
    example — is NOT caught here. Silence from this check is therefore
    weaker than "no interference"; it means "no interference between the
    lines the quantification is actually integrating", which is the
    question a caller can act on, and the limit is stated so the silence
    is not read as the stronger claim.
    """
    lines: list[tuple[str, float]] = []
    for sym in elements:
        try:
            energy, _ = line_energy(sym, beam_kv=beam_kv)
        except (KeyError, ValueError):
            continue
        if np.isfinite(energy) and energy > 0:
            lines.append((sym, float(energy)))
    clashes: list[dict[str, Any]] = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            (sa, ea), (sb, eb) = lines[i], lines[j]
            combined = float(np.hypot(fano_sigma_kev(ea), fano_sigma_kev(eb)))
            gap = abs(ea - eb)
            if combined > 0 and gap < _INTERFERENCE_SIGMA * combined:
                clashes.append(
                    {
                        "elements": [sa, sb],
                        "energies_kev": [ea, eb],
                        "separation_kev": gap,
                        "combined_sigma_kev": combined,
                    }
                )
    if not clashes:
        return []
    involved = sorted({s for c in clashes for s in c["elements"]})
    pairs = ", ".join(f"{c['elements'][0]}/{c['elements'][1]}" for c in clashes)
    return [
        QcFinding(
            code="peak_interference",
            severity="warn",
            message=(
                f"overlapping lines ({pairs}) are closer than the detector can "
                "resolve; their fitted areas trade against each other, so treat "
                "their split as uncertain beyond the quoted σ"
            ),
            elements=tuple(involved),
            detail={"pairs": clashes},
        )
    ]


def check_fit_quality(
    *, reduced_chi2: float | None = None, r_squared: float | None = None
) -> list[QcFinding]:
    """A model that does not describe the spectrum.

    A reduced χ² far above 1 means the residual carries structure the
    model does not account for — an unfitted element, a wrong background,
    an artifact peak — and every net area is then biased by whatever that
    structure is.
    """
    out: list[QcFinding] = []
    if reduced_chi2 is not None and np.isfinite(reduced_chi2):
        if reduced_chi2 >= 5.0:
            out.append(
                QcFinding(
                    code="fit_residual_structured",
                    severity="error",
                    message=(
                        f"reduced χ² is {reduced_chi2:.1f}; the model leaves structure "
                        "in the residual, so the net areas are biased by whatever it is"
                    ),
                    detail={"reduced_chi2": float(reduced_chi2)},
                )
            )
        elif reduced_chi2 >= 2.0:
            out.append(
                QcFinding(
                    code="fit_residual_high",
                    severity="warn",
                    message=(
                        f"reduced χ² is {reduced_chi2:.1f}; check for an unfitted "
                        "element or the wrong background before trusting the split"
                    ),
                    detail={"reduced_chi2": float(reduced_chi2)},
                )
            )
    if r_squared is not None and np.isfinite(r_squared) and r_squared < 0.9:
        out.append(
            QcFinding(
                code="fit_poor",
                severity="warn",
                message=f"the model explains only {r_squared * 100:.0f}% of the spectrum",
                detail={"r_squared": float(r_squared)},
            )
        )
    return out


def check_absorption(
    elements: Sequence[str], absorption_factors: Sequence[float]
) -> list[QcFinding]:
    """A large self-absorption correction means the thin-film assumption
    is doing more work than it should. The correction is applied either
    way; what this says is how much of the answer is correction."""
    heavy: list[str] = []
    severe: list[str] = []
    detail: dict[str, Any] = {}
    for sym, a in zip(elements, absorption_factors, strict=True):
        if not np.isfinite(a):
            continue
        detail[sym] = {"absorption_factor": float(a)}
        if a >= _ABSORPTION_ERROR:
            severe.append(sym)
        elif a >= _ABSORPTION_WARN:
            heavy.append(sym)
    out: list[QcFinding] = []
    if severe:
        out.append(
            QcFinding(
                code="absorption_severe",
                severity="error",
                message=(
                    f"{', '.join(severe)} needs a self-absorption correction above 50%; "
                    "the specimen is too thick for a thin-film treatment and the "
                    "correction now carries the answer"
                ),
                elements=tuple(severe),
                detail={k: detail[k] for k in severe},
            )
        )
    if heavy:
        out.append(
            QcFinding(
                code="absorption_significant",
                severity="warn",
                message=(
                    f"{', '.join(heavy)} needs a self-absorption correction above 10%; "
                    "the result depends on the assumed thickness and density"
                ),
                elements=tuple(heavy),
                detail={k: detail[k] for k in heavy},
            )
        )
    return out


def check_factor_conditions(
    *,
    beam_kv: float,
    factor_kv: float | None,
    source: str,
) -> list[QcFinding]:
    """Using a factor set away from the conditions it is a factor for.

    The built-in table is the standing example: `K_FACTORS_200KV` records
    no voltage anywhere it is used, so applying it at 80 kV is an
    extrapolation of tens of percent that is invisible in the answer. A
    derived set carries its kV precisely so this check can be made.
    """
    if factor_kv is None:
        return [
            QcFinding(
                code="factors_unstated_conditions",
                severity="warn",
                message=(
                    f"the {source} factors record no beam voltage, so whether they "
                    f"apply at {beam_kv:g} kV cannot be checked"
                ),
                detail={"beam_kv": float(beam_kv), "source": source},
            )
        ]
    if factor_kv <= 0 or not np.isfinite(factor_kv):
        return []
    rel = abs(beam_kv - factor_kv) / factor_kv
    if rel <= _KV_TOLERANCE:
        return []
    return [
        QcFinding(
            code="factors_extrapolated",
            severity="warn" if rel < 0.5 else "error",
            message=(
                f"the {source} factors were derived at {factor_kv:g} kV and are being "
                f"used at {beam_kv:g} kV; k and ζ both vary with overvoltage, so this "
                "is an extrapolation, not a correction"
            ),
            detail={
                "beam_kv": float(beam_kv),
                "factor_kv": float(factor_kv),
                "relative_difference": float(rel),
                "source": source,
            },
        )
    ]


def check_resolved_parameters(calibration: Mapping[str, Any]) -> list[QcFinding]:
    """Acquisition parameters that fell back to a built-in placeholder.

    Reads the `calibration` block ADR 0010 attaches to every quantitative
    response. A parameter with origin "default" is one nobody stated: the
    number is a plausible stand-in, and a composition computed on a
    stand-in takeoff angle should say so rather than look measured.
    """
    defaulted = sorted(
        name
        for name, entry in calibration.items()
        if isinstance(entry, Mapping) and entry.get("origin") == "default"
    )
    if not defaulted:
        return []
    return [
        QcFinding(
            code="parameters_defaulted",
            severity="warn",
            message=(
                f"{', '.join(defaulted)} came from a built-in placeholder, not from "
                "your data or a calibration profile; apply a profile or state them "
                "before publishing this composition"
            ),
            detail={
                name: dict(calibration[name])
                for name in defaulted
                if isinstance(calibration[name], Mapping)
            },
        )
    ]
