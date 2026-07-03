"""EDS spectral artifacts: Si-escape, sum / pile-up peaks (#8).

Detector artifacts masquerade as element lines: a **Si escape peak**
appears 1.740 keV below any sufficiently hard parent line (the detector
loses one Si-Kα photon), and **sum / pile-up peaks** appear at E_i + E_j
when two photons arrive within one pulse-shaping window. Both routinely
trigger false element IDs (the classic trap: Cu-Kα escape at 6.308 keV
sits on Fe-Kα at 6.404 keV).

Treatment is split by separability:

* Artifacts **clear of real lines** (most sum peaks — the high-energy
  region is usually empty) are *measured*: free-amplitude Gaussians at
  the predicted positions, fixed Fano widths, fitted jointly. A pile-up
  event deposits both photons' charge in one shaping window, so charge
  statistics scale with E_i+E_j while electronic noise enters once —
  the Fano width at the summed energy is the right width.
* Artifacts **on top of a real line** cannot be fitted (the optimiser
  would steal real counts) — escape peaks there are *modeled* as
  ``escape_fraction × parent area``; overlapping sum peaks are skipped
  and flagged.

Pure library (numpy + spectral_fit); no fastapi/pydantic/route imports.

References
----------
Goldstein et al., *SEM and X-ray Microanalysis*, 4th ed., ch. 7
(escape and sum peaks); Statham, *J. Res. NIST* **107** (2002) 531
(pile-up correction).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.eds_calib import fano_sigma_kev
from fermiviewer.calc.spectral_fit import (
    Component,
    FitResult,
    fit_spectrum,
    linear_background,
)

__all__ = [
    "DEFAULT_ESCAPE_FRACTION",
    "SI_ESCAPE_KEV",
    "SI_K_EDGE_KEV",
    "ArtifactPeak",
    "ArtifactRemoval",
    "artifact_curve",
    "measure_artifacts",
    "partition_artifacts",
    "predict_artifacts",
    "remove_artifacts",
]

SI_ESCAPE_KEV = 1.740      # Si-Kα carried away by the escaping photon
SI_K_EDGE_KEV = 1.839      # parent must ionise Si-K for escape to occur

# Typical Si-detector escape probability for mid-energy K lines (~0.1-2 %,
# falling with parent energy). One knob, route-tunable; rigorous work
# measures it from a pure standard.
DEFAULT_ESCAPE_FRACTION = 0.01

_SQRT_2PI = math.sqrt(2.0 * math.pi)


@dataclass(frozen=True)
class ArtifactPeak:
    """One predicted artifact line.

    ``name`` is the component-safe identifier (``esc_Cu``, ``sum_Fe_Cu``);
    ``label`` is the display form (``Cu esc``, ``Fe+Cu``); ``parents``
    are the element symbols whose line(s) generate it.
    """

    name: str
    label: str
    kind: str                  # "escape" | "sum"
    energy_kev: float
    parents: tuple[str, ...]


def predict_artifacts(
    line_energies: Mapping[str, float],
    *,
    e_min_kev: float = 0.2,
    e_max_kev: float | None = None,
    include_escape: bool = True,
    include_sum: bool = True,
) -> list[ArtifactPeak]:
    """Predict escape/sum peak positions from the elements' line energies.

    Parameters
    ----------
    line_energies : element symbol → principal line energy (keV); NaN
        entries are ignored.
    e_min_kev, e_max_kev : keep only artifacts inside this range (pass
        the spectrum's axis limits so off-range sums are dropped).
    include_escape, include_sum : toggle each artifact family.

    Returns
    -------
    Artifacts sorted by energy. Escape peaks exist only for parents
    above the Si K edge (1.839 keV); sum peaks are all unordered pairs
    including self-sums (2·E_i, the same-line pile-up peak).
    """
    lines = [
        (sym, float(e)) for sym, e in line_energies.items() if np.isfinite(e)
    ]
    out: list[ArtifactPeak] = []
    if include_escape:
        for sym, e in lines:
            if e <= SI_K_EDGE_KEV:
                continue
            esc = e - SI_ESCAPE_KEV
            out.append(ArtifactPeak(
                name=f"esc_{sym}", label=f"{sym} esc", kind="escape",
                energy_kev=esc, parents=(sym,),
            ))
    if include_sum:
        for i, (si, ei) in enumerate(lines):
            for sj, ej in lines[i:]:
                out.append(ArtifactPeak(
                    name=f"sum_{si}_{sj}", label=f"{si}+{sj}", kind="sum",
                    energy_kev=ei + ej, parents=(si, sj),
                ))
    lo = e_min_kev
    hi = e_max_kev if e_max_kev is not None else math.inf
    out = [a for a in out if lo <= a.energy_kev <= hi]
    out.sort(key=lambda a: a.energy_kev)
    return out


def partition_artifacts(
    artifacts: Sequence[ArtifactPeak],
    line_energies: Mapping[str, float],
    *,
    clearance_sigmas: float = 2.0,
) -> tuple[list[ArtifactPeak], list[ArtifactPeak]]:
    """Split artifacts into (free, blocked) by proximity to real lines.

    An artifact is *blocked* when it lies within
    ``clearance_sigmas · (σ_artifact + σ_line)`` of any analysed
    element's line — too close for a free-amplitude fit to separate.
    """
    free: list[ArtifactPeak] = []
    blocked: list[ArtifactPeak] = []
    lines = [float(e) for e in line_energies.values() if np.isfinite(e)]
    for a in artifacts:
        sig_a = float(fano_sigma_kev(a.energy_kev))
        near = any(
            abs(a.energy_kev - e) <
            clearance_sigmas * (sig_a + float(fano_sigma_kev(e)))
            for e in lines
        )
        (blocked if near else free).append(a)
    return free, blocked


def artifact_curve(
    energy: np.ndarray, area: float, center_kev: float
) -> np.ndarray:
    """Area-parametrised Gaussian at the detector (Fano) width."""
    sigma = max(float(fano_sigma_kev(center_kev)), 1e-9)
    amp = area / (sigma * _SQRT_2PI)
    return np.asarray(
        amp * np.exp(-0.5 * ((np.asarray(energy, dtype=np.float64) - center_kev)
                             / sigma) ** 2),
        dtype=np.float64,
    )


@dataclass(frozen=True)
class ArtifactMeasurement:
    """Freely-fitted artifact areas (over a residual or raw spectrum)."""

    areas: dict[str, float]            # by ArtifactPeak.name
    area_errors: dict[str, float]
    curves: dict[str, np.ndarray]
    fit: FitResult


def measure_artifacts(
    energy: np.ndarray,
    counts: np.ndarray,
    artifacts: Sequence[ArtifactPeak],
    *,
    weights: np.ndarray | str | None = None,
) -> ArtifactMeasurement:
    """Fit free-amplitude Gaussians at the predicted artifact positions.

    Centers and Fano widths are fixed; only amplitudes (≥ 0) are free,
    fitted jointly with a linear background. Feed a **residual**
    (spectrum − characteristic-peak model) so real peaks cannot leak in;
    the default uniform weights suit a residual, which can dip negative.
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    counts = np.asarray(counts, dtype=np.float64).ravel()
    if energy.shape != counts.shape:
        raise ValueError("energy and counts must have equal length")
    if not artifacts:
        raise ValueError("no artifacts to measure")

    components: list[Component] = [linear_background("bg")]
    sigmas: dict[str, float] = {}
    for a in artifacts:
        sigma = max(float(fano_sigma_kev(a.energy_kev)), 1e-9)
        sigmas[a.name] = sigma
        center = a.energy_kev

        def gauss(e: np.ndarray, p: np.ndarray, c: float = center,
                  s: float = sigma) -> np.ndarray:
            (amp,) = p
            return np.asarray(
                amp * np.exp(-0.5 * ((e - c) / s) ** 2), dtype=np.float64
            )

        sel = np.abs(energy - center) <= 2 * sigma
        amp0 = max(float(counts[sel].max()), 1.0) if sel.any() else 1.0
        components.append(
            Component(a.name, ("amp",), gauss, (amp0,), (0.0,), (np.inf,))
        )

    result = fit_spectrum(energy, counts, components, weights=weights)

    areas: dict[str, float] = {}
    errors: dict[str, float] = {}
    curves: dict[str, np.ndarray] = {}
    for a in artifacts:
        scale = sigmas[a.name] * _SQRT_2PI
        areas[a.name] = result.params[f"{a.name}_amp"] * scale
        errors[a.name] = result.errors[f"{a.name}_amp"] * scale
        curves[a.name] = result.component_curves[a.name]
    return ArtifactMeasurement(areas, errors, curves, result)


@dataclass(frozen=True)
class ArtifactRemoval:
    """Outcome of :func:`remove_artifacts`.

    ``measured`` holds freely-fitted areas (artifacts clear of lines);
    ``modeled`` holds blocked escapes estimated as fraction × parent;
    ``skipped`` lists blocked sum peaks left untouched (flag them in the
    UI). ``corrected`` is the input spectrum minus all measured and
    modeled artifact curves (backgrounds untouched).
    """

    artifacts: list[ArtifactPeak]
    measured: dict[str, float]
    measured_errors: dict[str, float]
    modeled: dict[str, float]
    skipped: list[str]
    corrected: np.ndarray


def remove_artifacts(
    energy: np.ndarray,
    counts: np.ndarray,
    line_energies: Mapping[str, float],
    *,
    residual: np.ndarray | None = None,
    parent_areas: Mapping[str, float] | None = None,
    escape_fraction: float = DEFAULT_ESCAPE_FRACTION,
    clearance_sigmas: float = 2.0,
    include_escape: bool = True,
    include_sum: bool = True,
) -> ArtifactRemoval:
    """Predict, measure/model, and subtract escape + sum peaks.

    The pre-pass for artifact-aware quantification: free artifacts are
    measured on ``residual`` (pass spectrum − fitted characteristic
    model; falls back to ``counts``); blocked escapes are modeled as
    ``escape_fraction × parent_areas[parent]``; blocked sums are
    skipped and reported. Re-fit characteristic peaks on ``corrected``.

    Parameters
    ----------
    energy, counts : the raw summed spectrum (keV axis).
    line_energies : analysed element → principal line energy (keV).
    residual : counts with the characteristic-peak model already
        subtracted — the safe surface for free artifact fitting.
    parent_areas : element → net area, needed to model blocked escapes.
    escape_fraction : Si escape probability for modeled escapes.
    clearance_sigmas : see :func:`partition_artifacts`.
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    counts = np.asarray(counts, dtype=np.float64).ravel()
    if energy.shape != counts.shape:
        raise ValueError("energy and counts must have equal length")
    if not 0.0 <= escape_fraction < 1.0:
        raise ValueError("escape_fraction must be in [0, 1)")

    artifacts = predict_artifacts(
        line_energies,
        e_min_kev=float(energy[0]), e_max_kev=float(energy[-1]),
        include_escape=include_escape, include_sum=include_sum,
    )
    free, blocked = partition_artifacts(
        artifacts, line_energies, clearance_sigmas=clearance_sigmas
    )

    corrected = counts.copy()
    measured: dict[str, float] = {}
    measured_err: dict[str, float] = {}
    if free:
        surface = counts if residual is None else np.asarray(
            residual, dtype=np.float64
        ).ravel()
        m = measure_artifacts(energy, surface, free)
        measured, measured_err = m.areas, m.area_errors
        for a in free:
            corrected -= m.curves[a.name]

    modeled: dict[str, float] = {}
    skipped: list[str] = []
    for a in blocked:
        if a.kind == "escape" and parent_areas is not None:
            parent = a.parents[0]
            area = escape_fraction * max(float(parent_areas.get(parent, 0.0)), 0.0)
            if area > 0.0:
                modeled[a.name] = area
                corrected -= artifact_curve(energy, area, a.energy_kev)
                continue
        skipped.append(a.name)

    return ArtifactRemoval(
        artifacts=artifacts,
        measured=measured,
        measured_errors=measured_err,
        modeled=modeled,
        skipped=skipped,
        corrected=corrected,
    )
